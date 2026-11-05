"""The ``## Mutation`` block of a PR body: what ``make back-mutate-diff``
writes and the mutation gate (``tools/mutation_gate.py``) reads.

An example, for a change to ``verify_password`` and a constant::

    ## Mutation

    <!-- written by `make back-mutate-diff`; ... -->
    format: 1
    content: `sha256:<hash of the touched files as committed>`
    files: `backend/utils/security.py`
    functions mutated (mutants, source): `utils.security.x_verify_password` (27, #1a2b3c4d)
    result: 25 killed · 2 survived

    Each line below needs a decision ...:
    - survived `utils.security.x_verify_password__mutmut_5`: <decision>
    - survived `utils.security.x_verify_password__mutmut_8`: <decision>
    - module-level `backend/utils/security.py:14 #5e6f7a8b`: <decision>
    <!-- end of the Mutation block -->

A line the tool writes starts undecided (``UNDECIDED``); the text after its
colon is the only part a person edits. The gate checks the survivor lines
against the counts, the counts against the mutants run, and recomputes the
``DIFF_LINES`` and the changed functions from the diff, so a line deleted by
hand is caught.

``format:`` versions the block. CI judges a PR with the base branch's gate,
so a PR that changes the format (or anything the block's text depends on) is
judged by ``main``'s copy, in ``main``'s format, until it merges.
Standard library only.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

HEADING = "## Mutation"
# Bump it with any change to what `render` writes or `parse` reads.
FORMAT = 1
GENERATED_BY = "make back-mutate-diff"
# Ends the block, so what follows it in the body (a `Closes` line) is not read.
END = "<!-- end of the Mutation block -->"
# What a line says before anyone decides: anything starting with it is open.
UNDECIDED = "TODO"
MODULE_LEVEL = "module-level"  # a sensitive file changed outside its functions
DELETED = "deleted"  # a guarded file the PR deleted (or moved out of the list)
NO_MUTANT = "no mutant"  # a changed function mutmut makes no mutant of (decorated)
# The lines the gate computes from the diff, not from a run's verdicts.
DIFF_LINES = frozenset({MODULE_LEVEL, DELETED, NO_MUTANT})
# A mutant in any other state is listed and needs a decision.
SETTLED = frozenset({"killed", "caught by type check"})

_HEADING_RE = re.compile(r"^##\s+Mutation\s*$")
_NEXT_HEADING = re.compile(r"^#{1,2}\s")
_CONTENT = re.compile(r"^content:\s*`?sha256:([0-9a-f]{64})`?$")
_FORMAT = re.compile(r"^format:\s*(\d+)$")
_FILES = re.compile(r"^files:\s*(.*)$")
_FUNCTIONS = re.compile(r"^functions mutated \(mutants, source\):\s*(.*)$")
_FUNCTION = re.compile(r"`([^`]+)` \((\d+), #([0-9a-f]+)\)")
_RESULT = re.compile(r"^result:\s*(.*)$")
_COUNT = re.compile(r"(\d+) ([a-z][a-z ]*[a-z])")
_LINE = re.compile(r"^\s*[-*]\s+(?P<status>[a-z][a-z -]*?)\s+`(?P<name>[^`]+)`\s*:(?P<dec>.*)$")


@dataclass
class Decision:
    """A line that needs a decision: a mutant not killed, or one of ``DIFF_LINES``."""

    status: str
    name: str
    decision: str = UNDECIDED

    @property
    def decided(self) -> bool:
        text = self.decision.strip().lower()
        return bool(text) and not text.startswith(UNDECIDED.lower())


@dataclass
class Report:
    """What ``make back-mutate-diff`` ran and found."""

    content: str
    files: list[str]
    mutated: dict[str, tuple[int, str]] = field(default_factory=dict)  # fn -> (mutants, source)
    counts: dict[str, int] = field(default_factory=dict)  # status -> mutants
    lines: list[Decision] = field(default_factory=list)  # survivors, then DIFF_LINES
    format: int = FORMAT

    @property
    def undecided(self) -> list[Decision]:
        return [d for d in self.lines if not d.decided]


def render(report: Report) -> str:
    files = ", ".join(f"`{f}`" for f in report.files) or "none"
    mutated = [f"`{name}` ({n}, #{h})" for name, (n, h) in report.mutated.items()]
    counts = " · ".join(f"{n} {status}" for status, n in sorted(report.counts.items()))
    lines = [
        HEADING,
        "",
        f"<!-- written by `{GENERATED_BY}`; a decision after a line's colon"
        " is the only part to edit -->",
        f"format: {report.format}",
        f"content: `sha256:{report.content}`",
        f"files: {files}",
        f"functions mutated (mutants, source): {', '.join(mutated) or 'none'}",
        f"result: {counts or 'nothing to mutate'}",
        "",
    ]
    if not report.lines:
        return "\n".join([*lines, "Decisions needed: none.", END])
    lines.append(
        "Each line below needs a decision. A killing test, or a `# pragma: no mutate`"
        " with its reason, goes in the code and the block is written again; any other"
        " decision is written after the line's colon (a module-level or no-mutant line:"
        " which test covers the change):"
    )
    lines += [f"- {d.status} `{d.name}`: {d.decision}" for d in report.lines]
    return "\n".join([*lines, END])


def _bounds(lines: list[str]) -> tuple[int, int] | None:
    """Where the block sits: its heading, and the line past its end marker (or
    the next heading, or the body's end, when the marker was lost)."""
    start = next((i for i, line in enumerate(lines) if _HEADING_RE.match(line)), None)
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j].strip() == END:
            return start, j + 1
        if _NEXT_HEADING.match(lines[j]):
            return start, j
    return start, len(lines)


def _first(pattern: re.Pattern[str], lines: list[str]) -> re.Match[str] | None:
    return next((m for line in lines if (m := pattern.match(line.strip()))), None)


def parse(body: str) -> Report | None:
    """The block in ``body``, or None when there is none. A field the block
    should have and does not comes back empty, and fails the gate."""
    all_lines = body.splitlines()
    bounds = _bounds(all_lines)
    if bounds is None:
        return None
    lines = all_lines[bounds[0] + 1 : bounds[1]]
    content, files = _first(_CONTENT, lines), _first(_FILES, lines)
    functions, result = _first(_FUNCTIONS, lines), _first(_RESULT, lines)
    version = _first(_FORMAT, lines)
    return Report(
        content=content[1] if content else "",
        files=re.findall(r"`([^`]+)`", files[1]) if files else [],
        mutated={m[1]: (int(m[2]), m[3]) for m in _FUNCTION.finditer(functions[1])}
        if functions
        else {},
        counts={m[2]: int(m[1]) for m in _COUNT.finditer(result[1])} if result else {},
        format=int(version[1]) if version else 0,
        lines=[
            Decision(m["status"], m["name"], m["dec"].strip())
            for x in lines
            if (m := _LINE.match(x))
        ],
    )


def consistent(report: Report) -> bool:
    """Whether the survivor lines are the ones the counts call for (one per
    mutant not killed) and the counts add up to the mutants of the functions
    run. The ``DIFF_LINES`` are the gate's to recompute."""
    listed = Counter(d.status for d in report.lines if d.status not in DIFF_LINES)
    expected = {s: n for s, n in report.counts.items() if s not in SETTLED and n}
    total = sum(n for n, _ in report.mutated.values())
    return dict(listed) == expected and sum(report.counts.values()) == total


def _carried(old: Report, new: Report) -> dict[str, str]:
    """Decisions of the old block that still hold. A mutant's number is its
    position in its function, so a decision follows it only while that
    function's source is the same; a ``DIFF_LINES`` line carries in its name
    the hash of what it is about."""
    kept: dict[str, str] = {}
    for d in old.lines:
        if not d.decided:
            continue
        if d.status not in DIFF_LINES:
            function = d.name.partition("__mutmut_")[0]
            source = old.mutated.get(function, (0, None))[1]
            if source is None or source != new.mutated.get(function, (0, ""))[1]:
                continue
        kept[d.name] = d.decision
    return kept


def splice(body: str, report: Report) -> str:
    """The body with its block replaced by ``report``'s (appended when it has
    none), keeping the decisions that still hold."""
    old = parse(body)
    if old is not None:
        kept = _carried(old, report)
        for d in report.lines:
            d.decision = kept.get(d.name, d.decision)
    block = render(report)
    lines = body.splitlines()
    bounds = _bounds(lines)
    if bounds is None:
        return f"{body.rstrip()}\n\n{block}\n" if body.strip() else f"{block}\n"
    return "\n".join([*lines[: bounds[0]], block, *lines[bounds[1] :]]) + "\n"
