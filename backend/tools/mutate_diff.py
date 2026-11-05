"""`make back-mutate-diff`: mutation on the sensitive functions a branch changed.

Finds the files of ``backend/mutation-sensitive.txt`` whose committed content
differs from the merge base with ``origin/main``, the functions in them whose
lines changed, and runs mutmut on every mutant of those functions and nothing
else, through ``make back-mutate``'s driver (``tools/mutate.py``). Then it
writes the ``## Mutation`` block the mutation gate reads
(``tools/mutation_block.py``) to ``mutants/mutation-gate.md``, prints it, and
with ``--pr N`` puts it in that PR's body, keeping the decisions that still
hold.

- A changed function mutmut makes no mutant of (it skips a decorated one, so
  every route handler) is a ``no mutant`` line; what changed outside the
  functions is a ``module-level`` line; a guarded file deleted is a
  ``deleted`` line. Each needs a decision, as a survivor does.
- ``--no-run`` writes the block from the results already in ``mutants/``, as
  they stand after rerunning one mutant alone (``make back-mutate ONLY=...``).
  It refuses results that are not for the current source of every function.
- It refuses anything uncommitted or untracked under ``backend/`` or in a
  guarded file: the block hashes the commit, and a killing test left out of
  the push would vouch for a mutant nobody else can. With ``--pr`` it also
  refuses when the PR's head on GitHub is another commit.

Exit status: mutmut's when it fails, 2 on a refusal, 1 while a line still needs
a decision, 0 otherwise. Usage, from ``backend/`` (needs Postgres up)::

    python -m tools.mutate_diff --pr 123    # run, and write the block into PR #123
    python -m tools.mutate_diff --no-run    # rewrite it from the existing results

What to do with a survivor: backend/CLAUDE.md, "Mutation testing".
"""

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from mutmut.mutation.file_mutation import mutate_file_contents
from mutmut.stats import status_by_exit_code
from mutmut.utils.format_utils import mangled_name_from_mutant_name

from tools import mutate
from tools import mutation_block as block
from tools import mutation_gate as gate
from tools import mutation_source as source

REPORT = Path("backend") / "mutants" / "mutation-gate.md"


@dataclass
class Planned:
    """One changed function mutmut mutates."""

    path: str
    function: str  # as mutmut's results key it: `x_name`
    mutants: int
    source: str  # our hash of its text, for carrying decisions
    mutmut_hash: str  # mutmut's, for telling stale results apart


@dataclass
class Plan:
    functions: dict[str, Planned] = field(default_factory=dict)  # glob -> function
    unmutated: list[block.Decision] = field(default_factory=list)


def plan_file(plan: Plan, path: str, text: str, lines: set[int]) -> None:
    """Add one file's changed functions to ``plan``.

    The mutants are mutmut's own (``mutate_file_contents``, what ``mutmut run``
    writes into ``mutants/``), so whatever mutmut skips agrees with the run."""
    changed = source.changed_functions(text, lines)
    ours = source.function_sources(text)
    mutated = mutate_file_contents(path, text)
    per_function: dict[str, int] = {}
    for mutant in mutated.mutant_names:
        function = mangled_name_from_mutant_name(mutant)
        per_function[function] = per_function.get(function, 0) + 1
    module = source.module_name(path)
    for function in changed:
        if n := per_function.get(function):
            theirs = mutated.hash_by_function_name.get(function, "")
            planned = Planned(path, function, n, ours[function], theirs)
            plan.functions[f"{module}.{function}__mutmut_*"] = planned
        else:
            name = gate.no_mutant_name(f"{module}.{function}", ours[function])
            plan.unmutated.append(block.Decision(block.NO_MUTANT, name))


def plan(root: Path, base: str, paths: list[str], entries: list[str]) -> Plan:
    """What to run over the touched sensitive ``.py`` files that still exist
    (the gate's own files are hashed, never mutated)."""
    result = Plan()
    sources = [p for p in paths if p.endswith(".py") and gate.is_sensitive(p, entries)]
    sources = [p for p in sources if (root / p).is_file()]
    lines = gate.file_lines(root, base, sources)
    for path in sources:
        plan_file(result, path, (root / path).read_text(), lines.get(path, source.Lines()).new)
    return result


def _meta(root: Path, path: str) -> dict:
    meta = root / "backend" / "mutants" / f"{path.removeprefix('backend/')}.meta"
    return json.loads(meta.read_text()) if meta.is_file() else {}


def verdicts(root: Path, work: Plan) -> tuple[dict[str, str], list[str]]:
    """Every planned mutant's verdict, and the functions whose results are
    stale: for another source than this one, or short of a verdict."""
    found: dict[str, str] = {}
    stale: list[str] = []
    for glob, planned in work.functions.items():
        meta = _meta(root, planned.path)
        prefix = glob.removesuffix("*")
        codes = {k: v for k, v in meta.get("exit_code_by_key", {}).items() if k.startswith(prefix)}
        found.update({k: status_by_exit_code[v] for k, v in codes.items()})
        fresh = meta.get("hash_by_function_name", {}).get(planned.function) == planned.mutmut_hash
        complete = len(codes) == planned.mutants and None not in codes.values()
        if not (fresh and complete):
            stale.append(glob.removesuffix("__mutmut_*"))
    return found, stale


def report(
    paths: list[str], content: str, work: Plan, found: dict[str, str], diff: gate.Expected
) -> block.Report:
    """The block for a run: ``found`` the verdicts, ``diff`` what the gate
    computes from the diff (its ``deleted`` and ``module-level`` lines)."""
    counts: dict[str, int] = {}
    for status in found.values():
        counts[status] = counts.get(status, 0) + 1
    survivors = [
        block.Decision(status, name)
        for name, status in sorted(found.items())
        if status not in block.SETTLED
    ]
    return block.Report(
        content=content,
        files=paths,
        mutated={
            g.removesuffix("__mutmut_*"): (p.mutants, p.source) for g, p in work.functions.items()
        },
        counts=counts,
        lines=survivors + work.unmutated + diff.lines,
    )


def _gh(*args: str, stdin: str | None = None) -> str:
    return subprocess.run(
        ["gh", *args], cwd=gate.REPO_ROOT, input=stdin, capture_output=True, text=True, check=True
    ).stdout


def dirty(status: str, entries: list[str]) -> list[str]:
    """Of ``git status --porcelain``, the paths under ``backend/`` or guarded
    anywhere: what the block's hash would not see."""
    paths = (line[3:].split(" -> ")[-1] for line in status.splitlines())
    return sorted(p for p in paths if p.startswith("backend/") or gate.guarded(p, entries))


def _write_report(root: Path, result: block.Report) -> None:
    (root / REPORT).parent.mkdir(parents=True, exist_ok=True)
    (root / REPORT).write_text(block.render(result) + "\n")


def _refusal(root: Path, entries: list[str], pr: str | None) -> str | None:
    status = gate.git(root, "status", "--porcelain", "--untracked-files=all")
    if found := dirty(status, entries):
        return f"commit or remove first: {', '.join(found)}"
    here = gate.git(root, "rev-parse", "HEAD").strip()
    if pr:
        there = _gh("pr", "view", pr, "--json", "headRefOid", "-q", ".headRefOid").strip()
        if there != here:
            return (
                f"PR #{pr} is at {there[:12]}, this checkout at {here[:12]}: push (or pull) first"
            )
    return None


def main(argv: list[str], root: Path = gate.REPO_ROOT) -> int:
    if mutate.native_windows():
        return 2
    pr = gate.option(argv, "--pr")
    # The gate takes its merge base and its list from `main` as GitHub has it.
    if subprocess.run(["git", "fetch", "--quiet", "origin", "main"], cwd=root).returncode:
        print("[back-mutate-diff] could not fetch origin/main; using the local copy")
    base = gate.merge_base(root, gate.BASE_REF)
    entries = gate.sensitive_entries(root, gate.BASE_REF, base=base)
    if refusal := _refusal(root, entries, pr):
        print(f"[back-mutate-diff] {refusal}", file=sys.stderr)
        return 2
    paths = gate.touched(root, base, entries)
    if not paths:
        print("[back-mutate-diff] the branch touches no guarded path; the PR needs no block")
        return 0
    work = plan(root, base, paths, entries)
    print(
        f"[back-mutate-diff] changed functions with mutants: {', '.join(work.functions) or 'none'}"
    )
    if work.functions and "--no-run" not in argv and (code := mutate.main(list(work.functions))):
        return code
    found, stale = verdicts(root, work)
    if stale:
        print(
            f"[back-mutate-diff] the results in mutants/ are not for this source: {', '.join(stale)};"
            " run without NO_RUN",
            file=sys.stderr,
        )
        return 2
    blob_of = gate.blobs(root, paths)
    diff = gate.expected(root, base, paths, entries, blob_of=blob_of)
    result = report(paths, gate.hash_of(paths, blob_of), work, found, diff)
    _write_report(root, result)  # first: a `gh` failure must not lose a long run
    if pr:
        body = block.splice(_gh("pr", "view", pr, "--json", "body", "-q", ".body"), result)
        _write_report(root, result)  # with the decisions the body carried
        _gh("pr", "edit", pr, "--body-file", "-", stdin=body)
        print(f"[back-mutate-diff] wrote the block into PR #{pr}")
    print(f"\n{block.render(result)}\n\n[back-mutate-diff] written to {REPORT}")
    return 1 if result.undecided else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
