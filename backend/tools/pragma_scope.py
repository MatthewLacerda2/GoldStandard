"""The pragma check: a ``# pragma: no mutate`` a PR adds or grows in sensitive
code hides the one mutant its reason explains, and no other.

mutmut reads a pragma where a statement starts and hides **every** mutant that
starts on its line (a ``start``/``end`` or ``block`` pragma, every one in its
region). The hidden ones are never generated, so neither the mutation gate nor
a reviewer sees them, and one pragma can swallow a dozen. For each pragma in a
sensitive ``.py`` file (``backend/mutation-sensitive.txt``) the PR changes,
this asks mutmut which mutants the source makes without that pragma and not
with it, and refuses the pragma when it

- hides more than one mutant;
- hides none (a pragma that suppresses nothing only misleads);
- carries no reason on its line (a region's ``end`` borrows its ``start``'s).

**Which pragmas are judged.** A pragma is keyed by its line's text and the
code of the mutants it hides (not their position). Keys the base's copy of the
file holds as often are not judged; every extra one is: a new pragma, a copy,
a pragma whose line or region now holds other code. A pragma moved unchanged
keeps its key.

CI runs the base branch's copy inside the mutation gate check, on the head
read as git objects (``--rev``); without ``--rev`` it reads the working tree.
Needs mutmut (``tools/mutmut_view.py``).
"""

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import libcst as cst
from mutmut.mutation.pragma_handling import PragmaParseError

from tools import mutation_gate as gate
from tools import mutation_source as source
from tools.mutmut_view import Mutant, Pragma, mutants, pragmas, region_end, switched_off

_WORD = re.compile(r"[^\W\d_]{2,}")
_UNREADABLE = (PragmaParseError, cst.ParserSyntaxError)
FIXES = (
    "a pragma hides every mutant that starts on its line, so it may stand over one"
    " unobservable mutant only: split the statement so the pragma'd one holds that"
    " mutant alone, or drop the pragma and kill the mutants with a test (or write"
    " their decision in the `## Mutation` block)"
)


@dataclass
class Scan:
    """One version of one file: its pragmas and its mutants."""

    code: str
    every: list[Pragma]
    kept: set[tuple[int, int, tuple[int, int], str]]
    seen: dict[int, list[Mutant]] = field(default_factory=dict)  # hidden, by pragma line

    @classmethod
    def of(cls, code: str) -> Scan:
        return cls(code, pragmas(code), {m.key for m in mutants(code)})

    def hidden(self, pragma: Pragma) -> list[Mutant]:
        """The mutants mutmut would make were this pragma (and its region's
        ``end``) not there."""
        if pragma.line not in self.seen:
            bare = switched_off(self.code, [pragma, *region_end(pragma, self.every)])
            self.seen[pragma.line] = [m for m in mutants(bare) if m.key not in self.kept]
        return self.seen[pragma.line]

    def keys(self) -> list[tuple[Pragma, tuple]]:
        """Each pragma with its key: its line's text and the code of the
        mutants it hides. An ``end`` is judged with its ``start``."""
        return [
            (p, (p.text, tuple(sorted((m.before, m.after) for m in self.hidden(p)))))
            for p in self.every
            if p.kind != "end"
        ]


def judge(path: str, scan: Scan, pragma: Pragma) -> list[str]:
    """Why this pragma may not stand; empty when it may."""
    where = f"{path}:{pragma.line}"
    found = []
    if not _WORD.search(pragma.reason):
        found.append(
            f"{where}: `# pragma: no mutate` with no reason on its line: say why its"
            " mutant is unobservable (equivalent, unreachable, or text nobody parses)"
        )
    gone = scan.hidden(pragma)
    if not gone:
        found.append(
            f"{where}: the pragma hides no mutant (mutmut reads it only where a"
            " statement starts): drop it"
        )
    elif len(gone) > 1:
        listed = "".join(f"\n    {m}" for m in gone)
        found.append(f"{where}: the pragma hides {len(gone)} mutants, not one:{listed}\n  {FIXES}")
    return found


def judged(head: Scan, base: Scan | None, touched: set[int]) -> list[Pragma]:
    """The head's pragmas whose key the base holds fewer times; within a key,
    those on touched lines first."""
    left = Counter(key for _, key in base.keys()) if base else Counter()
    found = []
    pairs = sorted(head.keys(), key=lambda pk: (pk[0].line in touched, pk[0].line))
    for pragma, key in pairs:
        if left[key]:
            left[key] -= 1
        else:
            found.append(pragma)
    return sorted(found, key=lambda p: p.line)


def _read(root: Path, path: str, rev: str | None) -> str:
    """``path`` as ``rev`` has it, or as the working tree does when None."""
    if rev is not None:
        return gate.show(root, rev, path)
    file = root / path
    return file.read_text() if file.is_file() else ""


def changed_files(root: Path, base_ref: str, base: str, rev: str | None) -> list[str]:
    """Sensitive ``.py`` files ``rev`` (the working tree, untracked files
    included, when None) changes from ``base`` and still has."""
    entries = gate.sensitive_entries(root, base_ref, rev or "HEAD", base)
    head = [rev] if rev is not None else []
    paths = set(gate.git(root, "diff", "--name-only", "--no-renames", base, *head, "--").split())
    if rev is None:
        paths |= set(gate.git(root, "ls-files", "--others", "--exclude-standard").split())
    return sorted(
        p
        for p in paths
        if p.endswith(".py") and gate.is_sensitive(p, entries) and _read(root, p, rev)
    )


def _file_problems(path: str, code: str, before: str, touched: set[int]) -> list[str]:
    try:
        scan = Scan.of(code)
    except _UNREADABLE as exc:
        return [f"{path}: mutmut cannot read the file, so its pragmas go unjudged: {exc}"]
    try:
        base_scan = Scan.of(before) if before else None
    except _UNREADABLE as exc:
        # Judging every pragma as new would refuse what the PR did not add.
        return [f"{path}: mutmut cannot read the base's copy, so new pragmas are unknown: {exc}"]
    try:
        return [p for pragma in judged(scan, base_scan, touched) for p in judge(path, scan, pragma)]
    except _UNREADABLE as exc:
        return [f"{path}: mutmut cannot read the file with a pragma switched off: {exc}"]


def problems(root: Path, base_ref: str, rev: str | None = None) -> list[str]:
    """Why the pragmas ``rev`` (the working tree when None) adds or grows since
    its merge base with ``base_ref`` may not stand; empty when they may."""
    base = gate.merge_base(root, base_ref, rev or "HEAD")
    paths = changed_files(root, base_ref, base, rev)
    if not paths:
        return []
    head = [rev] if rev is not None else []
    lines = source.diff_lines(gate.git(root, *gate.DIFF, "-U0", base, *head, "--", *paths))
    found = []
    for path in paths:
        code = _read(root, path, rev)
        touched = lines[path].new if path in lines else set(range(1, code.count("\n") + 2))
        found += _file_problems(path, code, gate.show(root, base, path), touched)
    return found


def main(argv: list[str]) -> int:
    rev = gate.option(argv, "--rev")
    found = problems(gate.REPO_ROOT, gate.option(argv, "--base") or gate.BASE_REF, rev)
    for problem in found:
        print(problem)
        print(f"::error title=pragma scope::{problem.splitlines()[0]}")
    if not found:
        print("[pragma scope] every pragma the PR adds or grows in sensitive code hides one mutant")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
