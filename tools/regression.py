"""Whether a bug fix carries a test that fails without it.

A fix proves itself with a test that fails on the broken code and passes on
the fixed code. The gates check the second half; this checks the first. CI's
`regression` job and `make regression` run the same steps:

    python3.14 tools/regression.py plan --pr N --base REV   # is a test owed?
    python3.14 tools/regression.py run --base REV           # does one fail there?
    python3.14 tools/regression.py check --pr N             # both: make regression

`plan` reads the pull request's description over REST (`gh api`) for closing
keywords. A test is owed when an issue it closes is labelled `fix`, unless the
description says why none can, on a line of its own, in a few words:

    No regression test on base: the bug was only visible in a real browser.

An owed test needs a changed test file that names a target (`target`): none
is a refusal.

`run` judges the change, whatever its description says. It makes a worktree of
the base, lays every test file and fixture the change touched over it (as the
head commit has them; a deleted one is deleted) and runs each target there:
only the tests of it the change adds or changes, or the whole file when none
can be told apart (`tools/regression_names.py` has how they are found, and
`tools/regression_runners.py` how each is run and judged). It passes when at
least one target **fails** on the base. The worktree is removed when `run`
ends, however it ends.

`REV` is the base: in CI the merge commit's first parent, `HEAD^1`. `check`
without one takes where the branch left the pull request's base branch.

Pure but for `git`, `gh`, `narrowed`, `shown`, `lay_over`, `base_worktree`,
`on_base`, `plan`, `run` and `main`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

if __package__:
    from tools.regression_names import changed_tests
    from tools.regression_runners import (
        BROKEN,
        FAILED,
        PASSED,
        Target,
        drop_database,
        install,
        run_target,
    )
else:  # run as a script: its own folder is on the path
    from regression_names import changed_tests
    from regression_runners import (
        BROKEN,
        FAILED,
        PASSED,
        Target,
        drop_database,
        install,
        run_target,
    )

FIX = "fix"
EXCEPTION = re.compile(
    r"^\s*[-*]?\s*\**no regression test on base\**\s*:(.*)$", re.IGNORECASE | re.MULTILINE
)
REASON_WORDS = 3
# GitHub's closing keywords and an issue: `#N`, `owner/name#N` or its URL.
KEYWORD = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+"
    r"(?:https://github\.com/([\w.-]+/[\w.-]+)/issues/|([\w.-]+/[\w.-]+)?#)(\d+)\b",
    re.IGNORECASE,
)
TEST_NAME = re.compile(r"^test_.*\.py$|\.test\.tsx?$")
# Which runner a test file's top-level folder runs it with, and from where.
RUNNERS = {
    "backend": ("pytest", "backend"),
    "frontend": ("vitest", "frontend"),
    "tools": ("unittest", "."),
}
# What `plan` tells the job: whether to run, and which layers to set up.
OUTPUT_LAYERS = ("backend", "frontend")
OUTPUTS = ("owed", *OUTPUT_LAYERS)

HOW = (
    "Write the test that reproduces the bug before the fix (a `test_*.py` under"
    " backend/ or tools/, a `*.test.ts(x)` under frontend/), so it fails on the"
    " base and passes with the fix; `make regression PR=<n>` runs this check"
    " locally. If no test can, say why on a line of its own in the description:"
    " `No regression test on base: <why, in a few words>`. Editing the"
    " description starts no CI run: re-run this job (it reads the description"
    " afresh), push a commit, or close and reopen the pull request."
)
JUDGED = (
    "cannot be judged on the base: it does not import or compile there, runs"
    " no test, or fails only on a name the fix adds."
)


def laid(path: str) -> bool:
    """What is copied over the base: a test file (`test_*.py`, `*.test.ts(x)`,
    anything under a `tests` directory, such as a `conftest.py`) or a file
    under a `fixtures` directory, which a test reads as data."""
    parts = PurePosixPath(path).parts
    return bool(TEST_NAME.search(parts[-1])) or bool({"tests", "fixtures"} & set(parts[:-1]))


def target(path: str) -> Target | None:
    """The target a test file names, if any: a helper names none."""
    folder, _, rest = path.partition("/")
    if folder not in RUNNERS or not TEST_NAME.search(PurePosixPath(path).name):
        return None
    runner, layer = RUNNERS[folder]
    if (runner == "vitest") != path.endswith((".ts", ".tsx")):
        return None
    return Target(runner, layer, path if layer == "." else rest)


def targets(paths: list[str], exists: Callable[[str], bool]) -> list[Target]:
    """Every target the changed test files that the head still has name."""
    return sorted({t for p in paths if exists(p) and (t := target(p)) is not None})


def closes(body: str, repo: str) -> list[int]:
    """The issues of `repo` the description's closing keywords name."""
    return sorted(
        {
            int(number)
            for url, named, number in KEYWORD.findall(body or "")
            if not (url or named) or (url or named).lower() == repo.lower()
        }
    )


def excused(body: str) -> str | None:
    """The reason the description gives for owing no regression test."""
    for reason in EXCEPTION.findall(body or ""):
        if len(re.findall(r"[A-Za-z0-9]{2,}", reason)) >= REASON_WORDS:
            return reason.strip(" *")
    return None


def fixes(issues: dict[int, dict]) -> list[int]:
    """The issues labelled `fix`, from GitHub's REST answers (a pull request's
    number answers too, and is never a fix)."""
    return sorted(
        n
        for n, issue in issues.items()
        if "pull_request" not in issue
        and FIX in [label.get("name") for label in issue.get("labels") or []]
    )


def owed(fixed: list[int], body: str, found: list[Target]) -> list[str]:
    """`plan`'s refusal: a fix with no target and no exception."""
    if not fixed or excused(body) or found:
        return []
    numbers = ", ".join(f"#{n}" for n in fixed)
    return [f"it closes {numbers}, labelled `{FIX}`, and changes no test file.", HOW]


def verdict(results: dict[Target, str]) -> list[str]:
    """`run`'s refusal: no target failed on the base."""
    if any(outcome == FAILED for outcome in results.values()):
        return []
    lines = ["no changed test fails on the base, so none shows the bug."]
    if not results:
        lines = ["no changed test file names a target."]
    for t, outcome in sorted(results.items()):
        named = f"{t} ({', '.join(t.tests)})" if t.tests else str(t)
        lines.append(f"{named}: " + ("passes on the base." if outcome == PASSED else JUDGED))
    return [*lines, HOW]


def git(*argv: str, cwd: Path) -> str:
    return subprocess.run(
        ("git", *argv), cwd=cwd, check=True, text=True, stdout=subprocess.PIPE
    ).stdout


def gh(path: str) -> dict:
    """One GitHub REST answer (`gh api`, never GraphQL); `LookupError` when
    there is none, such as an issue number that does not exist."""
    done = subprocess.run(("gh", "api", path), text=True, capture_output=True)
    if done.returncode:
        raise LookupError(f"`gh api {path}`: {done.stderr.strip() or done.stdout.strip()}")
    return json.loads(done.stdout)


def changed(head: Path, base: str) -> list[str]:
    """Every path the change touches, both ends of a rename."""
    return git(
        "-c", "core.quotePath=false", "diff", "--name-only", "--no-renames", base, "HEAD", cwd=head
    ).splitlines()


def committed(head: Path) -> set[str]:
    """The head commit's files: what is laid over is the commit, not the tree."""
    return set(
        git(
            "-c", "core.quotePath=false", "ls-tree", "-r", "--name-only", "HEAD", cwd=head
        ).splitlines()
    )


def narrowed(head: Path, base: str, t: Target) -> Target:
    """`t` cut down to the tests the change adds or changes, saying which, or
    left whole, saying why."""
    path = str(PurePosixPath(t.layer, t.path))
    head_text, base_text = shown(head, "HEAD", path) or b"", shown(head, base, path)
    tests, why = changed_tests(
        t.runner,
        t.path,
        head_text.decode(errors="replace"),
        None if base_text is None else base_text.decode(errors="replace"),
    )
    lines = [f"{t}: judging the whole file: {why}."]
    if tests:
        lines = [f"{t}: judging the tests the change adds or changes:", *(f"  {n}" for n in tests)]
        lines += [f"  {why}."] if why else []
    print("\n".join(lines), flush=True)
    return t._replace(tests=tests)


def shown(head: Path, rev: str, path: str) -> bytes | None:
    """`path` as commit `rev` has it, or `None` when it has no such file."""
    done = subprocess.run(("git", "show", f"{rev}:{path}"), cwd=head, capture_output=True)
    return None if done.returncode else done.stdout


def lay_over(head: Path, worktree: Path, paths: list[str], present: set[str]) -> None:
    """Copy the head commit's version of each path over the base, deleting
    the ones the head no longer has."""
    for path in paths:
        dest = worktree / path
        if path in present:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(shown(head, "HEAD", path) or b"")
        elif dest.is_file():
            dest.unlink()


@contextmanager
def base_worktree(head: Path, base: str) -> Iterator[Path]:
    """A worktree of `base` at a path of its own, removed on the way out. Its
    own path means its own test database, and no other run's worktree."""
    git("worktree", "prune", cwd=head)  # registrations a killed run left behind
    path = Path(tempfile.mkdtemp(prefix="regression-base-"))
    try:
        git("worktree", "add", "--quiet", "--detach", str(path), base, cwd=head)
        yield path
    finally:
        subprocess.run(
            ("git", "worktree", "remove", "--force", str(path)),
            cwd=head,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        shutil.rmtree(path, ignore_errors=True)
        git("worktree", "prune", cwd=head)


def write_output(**values: bool) -> None:
    """The job's step outputs, when run in CI."""
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.writelines(f"{k}={str(v).lower()}\n" for k, v in values.items())


def plan(head: Path, pull: dict, repo: str, base: str) -> tuple[int, list[Target]]:
    """Exit code and the targets to run: none when nothing is owed."""
    body = pull.get("body") or ""
    try:
        fixed = fixes({n: gh(f"repos/{repo}/issues/{n}") for n in closes(body, repo)})
    except LookupError as unread:
        why = f"an issue it closes cannot be read ({unread}): check each closing keyword's number."
        print("\n".join(["Refused:", why, HOW]))
        return 1, []
    present = committed(head)
    found = targets(changed(head, base), present.__contains__)
    refused = owed(fixed, body, found)
    if refused:
        print("\n".join(["Refused:", *refused]))
        return 1, []
    if not fixed or excused(body):
        print(
            f"excused: {excused(body)}"
            if fixed
            else f"it closes no `{FIX}` issue: nothing is owed."
        )
        found = []
    else:
        numbers = ", ".join(f"#{n}" for n in fixed)
        print(f"it closes {numbers}, labelled `{FIX}`; runs on the base:", *found, sep="\n  ")
    layers = {t.layer for t in found}
    write_output(owed=bool(found), **{layer: layer in layers for layer in OUTPUT_LAYERS})
    return 0, found


def on_base(
    head: Path, base: str, paths: list[str], found: list[Target], python: str, bun: str
) -> dict[Target, str]:
    """Each target's outcome in a worktree of the base, the change's test
    files laid over it. The head's backend/.env goes too (it is not tracked),
    so the base's tests reach the same database the head's do."""
    results: dict[Target, str] = {}
    with base_worktree(head, base) as tree, tempfile.TemporaryDirectory() as scratch:
        lay_over(head, tree, [p for p in paths if laid(p)], committed(head))
        if (head / "backend" / ".env").is_file():
            shutil.copy2(head / "backend" / ".env", tree / "backend" / ".env")
        installed = not any(t.runner == "vitest" for t in found) or install(tree, bun)
        try:
            for t in found:
                ran = installed or t.runner != "vitest"
                results[t] = run_target(t, tree, Path(scratch), python, bun) if ran else BROKEN
                print(f"{t}: {results[t]} on the base", flush=True)
        finally:
            if any(t.runner == "pytest" for t in found):
                drop_database(tree, python)
    return results


def run(head: Path, base: str, python: str, bun: str) -> int:
    """0 when a changed test fails on the base, 1 when none does."""
    paths = changed(head, base)
    found = [narrowed(head, base, t) for t in targets(paths, committed(head).__contains__)]
    results = on_base(head, base, paths, found, python, bun) if found else {}
    refused = verdict(results)
    print("\n".join(["Refused:", *refused]) if refused else "a changed test fails on the base.")
    return 1 if refused else 0


def pull_request(head: Path, repo: str, number: int) -> dict:
    """The pull request as GitHub has it now, noting a local head that differs."""
    pull = gh(f"repos/{repo}/pulls/{number}")
    here = git("rev-parse", "HEAD", cwd=head).strip()
    if not os.environ.get("GITHUB_ACTIONS") and pull["head"]["sha"] != here:
        print(
            f"note: #{number}'s head is {pull['head']['sha'][:12]}, this checkout is at"
            f" {here[:12]}: what is judged is this checkout."
        )
    return pull


def local_base(head: Path, pull: dict) -> str:
    """Where this branch left the pull request's base branch (fetched)."""
    ref = pull["base"]["ref"]
    git("fetch", "--quiet", "origin", ref, cwd=head)
    return git("merge-base", f"origin/{ref}", "HEAD", cwd=head).strip()


def interpreter(head: Path, python: str) -> str:
    """`--python` as the Makefile's `PYTHON`: a relative path is backend/'s."""
    return (
        str(head / "backend" / python) if "/" in python and not python.startswith("/") else python
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Does a bug fix's test fail on its base?")
    parser.add_argument("step", choices=("plan", "run", "check"))
    parser.add_argument("--pr", type=int, help="the pull request (plan, check)")
    parser.add_argument("--base", help="the base commit (default for check: the merge-base)")
    parser.add_argument("--python", default="python3.14", help="Python with backend/'s deps")
    parser.add_argument("--bun", default="bun")
    args = parser.parse_args(argv)
    # A cancelled CI job is sent SIGTERM: exit through the `finally`s, so the
    # base worktree and its database go too.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    if args.step == "plan" and not (args.pr and args.base) or args.step == "run" and not args.base:
        parser.error("plan needs --pr and --base, run needs --base")
    if args.step == "check" and not (args.pr or args.base):
        parser.error("check needs --pr, --base, or both")
    head = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()).strip())
    python = interpreter(head, args.python)
    if git("status", "--porcelain", "--untracked-files=no", cwd=head).strip():
        print("note: uncommitted changes are not judged; the head commit is.")
    if args.step == "run" or not args.pr:
        return run(head, args.base, python, args.bun)
    repo = os.environ.get("GITHUB_REPOSITORY") or gh("repos/{owner}/{repo}")["full_name"]
    pull = pull_request(head, repo, args.pr)
    base = args.base or local_base(head, pull)
    code, found = plan(head, pull, repo, base)
    if args.step == "plan" or code or not found:
        return code
    return run(head, base, python, args.bun)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
