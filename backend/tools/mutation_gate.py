"""The mutation gate: sensitive code merges with mutation on what it touched.

A PR into ``main`` that changes a path ``backend/mutation-sensitive.txt``
lists must carry, in its body, the ``## Mutation`` block ``make
back-mutate-diff`` writes (``tools/mutate_diff.py``; the format is
``tools/mutation_block.py``). This module is the read-only half and runs no
mutant. It fails when the diff touches a guarded path and the block is

- missing;
- for other content: its ``content:`` hash is not the hash of the touched
  files as the PR's head commit has them (a commit came after the run);
- not this PR's own: its ``module-level``, ``deleted`` and ``no mutant`` lines
  or its functions are not the ones this module computes from the diff, or its
  counts do not add up (a line deleted by hand);
- in another format than this gate reads;
- holding a line with no decision yet.

It is a forcing function, not a proof: CI cannot run the mutants, so the
verdicts in the block are trusted to be the tool's output, which is why the
tool works on committed, pushed content only.

A PR that touches nothing guarded passes and asks nothing. Guarded is the list
as the base branch's tip, the merge base and the head have it, together, so a
PR cannot leave the gate by deleting its own entry; and the mutmut pin
(``PIN_FILE``), when it moves, since it decides which mutants exist. CI runs the **base
branch's** copy of this module on the PR head read as git objects (``--rev``),
so a PR cannot weaken the code that judges it
(``.github/workflows/mutation-gate.yml``). Standard library only.

Usage, from ``backend/``::

    python -m tools.mutation_gate --pr 123    # reads the body with `gh`
    PR_BODY=... python -m tools.mutation_gate --base origin/main --rev <sha>
"""

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tools import mutation_block as block
from tools import mutation_source as source

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_REF = "origin/main"
SENSITIVE_LIST = "backend/mutation-sensitive.txt"
# The mutmut pin: a PR that moves it changes which mutants exist, so it carries
# the block too. The file's other lines do not count.
PIN_FILE = "backend/requirements-dev.txt"
# An entry with this prefix is guarded (hashed and named in the block) but
# never mutated: the gate's own files.
HASH_ONLY = "hash-only "
# Pinned against a user's git config: the prefixes `mutation_source` reads,
# and the hunks (and so the names of `module-level` lines) CI computes too.
DIFF = (
    "diff",
    "--no-color",
    "--no-ext-diff",
    "--no-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
    "--inter-hunk-context=0",
    "--diff-algorithm=myers",
)


def load_sensitive(text: str) -> list[str]:
    """The list's entries: one path per line (a directory ends in ``/``;
    ``hash-only <path>`` for one never mutated), ``#`` comments, blanks."""
    lines = (" ".join(line.split("#", 1)[0].split()) for line in text.splitlines())
    return [line for line in lines if line]


def _covers(entry: str, path: str) -> bool:
    return path.startswith(entry) if entry.endswith("/") else path == entry


def is_sensitive(path: str, entries: list[str]) -> bool:
    """A path whose functions are mutated."""
    return any(_covers(e, path) for e in entries if not e.startswith(HASH_ONLY))


def guarded(path: str, entries: list[str]) -> bool:
    """A path a PR must carry the block for: sensitive, or hash-only."""
    hashed = (e.removeprefix(HASH_ONLY) for e in entries if e.startswith(HASH_ONLY))
    return is_sensitive(path, entries) or any(_covers(e, path) for e in hashed)


def git(root: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=check
    ).stdout


def show(root: Path, rev: str, path: str) -> str:
    """``path`` as ``rev`` has it; empty when it has none."""
    return git(root, "show", f"{rev}:{path}", check=False)


def read_many(root: Path, specs: list[str]) -> dict[str, str]:
    """Each ``<rev>:<path>`` in ``specs``, read in one git process (empty when
    the revision has no such path): the gate reads a dozen, and a process each
    is most of its time."""
    request = "".join(f"{spec}\n" for spec in specs).encode()
    out = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=root, input=request, capture_output=True, check=True
    ).stdout
    found, at = {}, 0
    for spec in specs:
        header_end = out.index(b"\n", at)
        header = out[at:header_end].split()
        at = header_end + 1
        if header[-1] == b"missing" or header[1] != b"blob":
            found[spec] = ""
            continue
        size = int(header[2])
        found[spec] = out[at : at + size].decode("utf-8", "replace")
        at += size + 1
    return found


def merge_base(root: Path, base_ref: str, rev: str = "HEAD") -> str:
    return git(root, "merge-base", base_ref, rev).strip()


def mutmut_pin(text: str) -> list[str]:
    """The ``mutmut`` lines of a requirements file: which mutmut runs, and so
    which mutants exist."""
    return [line.strip() for line in text.splitlines() if line.strip().lower().startswith("mutmut")]


def sensitive_entries(
    root: Path, base_ref: str, rev: str = "HEAD", base: str | None = None
) -> list[str]:
    """The list as the base's tip, the merge base and the head have it."""
    refs = (base_ref, base or merge_base(root, base_ref, rev), rev)
    texts = read_many(root, [f"{ref}:{SENSITIVE_LIST}" for ref in refs])
    return sorted({e for text in texts.values() for e in load_sensitive(text)})


def touched(root: Path, base: str, entries: list[str], rev: str = "HEAD") -> list[str]:
    """Guarded paths whose content differs between ``base`` and ``rev`` (a
    mode change alone is no change), and the requirements file when its
    mutmut pin moved."""
    raw = git(root, *DIFF, "--raw", "--no-abbrev", base, rev, "--").splitlines()
    # `:<old mode> <new mode> <old blob> <new blob> <status>\t<path>`
    rows = [line.split("\t", 1) for line in raw if line.startswith(":")]
    changed = [p for meta, p in rows if meta.split()[2] != meta.split()[3]]
    found = {p for p in changed if guarded(p, entries)}
    if PIN_FILE in changed:
        pins = read_many(root, [f"{base}:{PIN_FILE}", f"{rev}:{PIN_FILE}"])
        if mutmut_pin(pins[f"{base}:{PIN_FILE}"]) != mutmut_pin(pins[f"{rev}:{PIN_FILE}"]):
            found.add(PIN_FILE)
    return sorted(found)


def blobs(root: Path, paths: list[str], rev: str = "HEAD") -> dict[str, str]:
    """Each path's blob as ``rev`` has it; a path it lacks is left out."""
    found = {}
    if paths:
        for line in git(root, "ls-tree", rev, "--", *paths).splitlines():
            meta, path = line.split("\t", 1)
            found[path] = meta.split()[2]
    return found


def hash_of(paths: list[str], blob_of: dict[str, str]) -> str:
    """One hash for the touched files: each path and its blob (or its
    deletion). Only commits count, so the local run and CI hash the same."""
    total = hashlib.sha256()
    for path in sorted(paths):
        total.update(f"{path}\0{blob_of.get(path, 'deleted')}\n".encode())
    return total.hexdigest()


def content_hash(root: Path, paths: list[str], rev: str = "HEAD") -> str:
    return hash_of(paths, blobs(root, paths, rev))


def file_lines(
    root: Path, base: str, paths: list[str], rev: str = "HEAD"
) -> dict[str, source.Lines]:
    if not paths:
        return {}
    return source.diff_lines(git(root, *DIFF, "-U0", base, rev, "--", *paths))


@dataclass
class Expected:
    """What the diff itself says the block must hold, verdicts aside."""

    lines: list[block.Decision] = field(default_factory=list)  # deleted, module-level
    functions: dict[str, str] = field(default_factory=dict)  # `module.x_name` -> source


def expected_from(
    paths: list[str],
    present: set[str],
    texts: dict[str, tuple[str, str]],
    lines: dict[str, source.Lines],
) -> Expected:
    """One ``deleted`` line per guarded path the head no longer has (moved out
    of a listed directory counts), then, for each sensitive file in ``texts``
    (its base and head text), every changed function with the hash of its
    source and one ``module-level`` line when it changed outside them."""
    found = Expected([block.Decision(block.DELETED, p) for p in paths if p not in present])
    for path, (old, new) in texts.items():
        changed = lines.get(path, source.Lines())
        module = source.module_name(path)
        hashes = source.function_sources(new)
        for name in source.changed_functions(new, changed.new):
            found.functions[f"{module}.{name}"] = hashes[name]
        if name := source.module_change(path, old, new, changed):
            found.lines.append(block.Decision(block.MODULE_LEVEL, name))
    return found


def expected(
    root: Path,
    base: str,
    paths: list[str],
    entries: list[str],
    rev: str = "HEAD",
    blob_of: dict[str, str] | None = None,
) -> Expected:
    """``expected_from`` over what git says of ``paths``."""
    blob_of = blobs(root, paths, rev) if blob_of is None else blob_of
    python = [p for p in paths if p in blob_of and p.endswith(".py") and is_sensitive(p, entries)]
    read = read_many(root, [f"{r}:{p}" for p in python for r in (base, rev)])
    texts = {p: (read[f"{base}:{p}"], read[f"{rev}:{p}"]) for p in python}
    return expected_from(paths, set(blob_of), texts, file_lines(root, base, python, rev))


def no_mutant_name(function: str, source_hash: str) -> str:
    """A ``no mutant`` line's name: the function and the hash of its text, so
    a decision about it holds only while the function stays the same."""
    return f"{function} #{source_hash}"


def _not_own(report: block.Report, diff: Expected) -> bool:
    """Whether the block's own lines or functions are not the ones its counts
    and the diff call for (a line deleted or edited by hand)."""
    unmutated = {d.name for d in report.lines if d.status == block.NO_MUTANT}
    wanted = {(d.status, d.name) for d in diff.lines} | {
        (block.NO_MUTANT, no_mutant_name(f, h))
        for f, h in diff.functions.items()
        if f not in report.mutated
    }
    listed = {(d.status, d.name) for d in report.lines if d.status in block.DIFF_LINES}
    named = set(report.mutated) | {name.partition(" #")[0] for name in unmutated}
    sources = {f: h for f, (_, h) in report.mutated.items()}
    own = named == set(diff.functions) and sources.items() <= diff.functions.items()
    return not block.consistent(report) or listed != wanted or not own


def problems(body: str, paths: list[str], content: str, diff: Expected) -> list[str]:
    """Why the PR may not merge yet; empty when it may. ``paths`` are the
    guarded paths it touches, ``content`` their hash at its head, ``diff`` what
    its diff calls for. Pure: ``run`` reads them from git."""
    if not paths:
        return []
    report = block.parse(body)
    run = f"run `{block.GENERATED_BY} PR=<number>`, which writes the block into the PR body"
    if report is None:
        return [
            f"the PR changes guarded files ({', '.join(paths)}) with no `{block.HEADING}` block: {run}"
        ]
    if report.format != block.FORMAT:
        return [
            f"the `{block.HEADING}` block is in format {report.format}; this gate (the base"
            f" branch's) reads format {block.FORMAT}: {run}"
        ]
    found = []
    if report.content != content:
        found.append(
            f"the `{block.HEADING}` block is for other content: it covers"
            f" {', '.join(report.files) or 'nothing'}, the PR changes {', '.join(paths)}"
            f" (or a commit came after the run): {run} again"
        )
    if _not_own(report, diff):
        found.append(
            f"the `{block.HEADING}` block is not this PR's own: its lines or functions are"
            f" not the ones its counts and this diff call for: {run} again"
        )
    found += [
        f"`{d.name}` ({d.status}) has no decision: kill it with a test, pragma it with"
        " its reason, or write the decision after its colon"
        for d in report.undecided
    ]
    return found


def run(root: Path, base_ref: str, body: str, rev: str = "HEAD") -> int:
    """The check of ``rev`` against ``base_ref`` in the repository at ``root``:
    0 passes, 1 fails. ``rev`` is read as git objects, never checked out."""
    base = merge_base(root, base_ref, rev)
    entries = sensitive_entries(root, base_ref, rev, base)
    paths = touched(root, base, entries, rev)
    if not paths:
        print("[mutation gate] the PR touches no guarded path; nothing to ask")
        return 0
    print(f"[mutation gate] guarded paths touched: {', '.join(paths)}")
    blob_of = blobs(root, paths, rev)
    diff = expected(root, base, paths, entries, rev, blob_of)
    found = problems(body, paths, hash_of(paths, blob_of), diff)
    for problem in found:
        print(f"::error title=mutation gate::{problem}")
    if not found:
        print("[mutation gate] the block matches this content and every line has a decision")
    return 1 if found else 0


def option(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


def main(argv: list[str]) -> int:
    body = os.environ.get("PR_BODY")
    if body is None and (pr := option(argv, "--pr")):
        body = subprocess.run(
            ["gh", "pr", "view", pr, "--json", "body", "-q", ".body"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    base_ref = option(argv, "--base") or BASE_REF
    return run(REPO_ROOT, base_ref, body or "", option(argv, "--rev") or "HEAD")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
