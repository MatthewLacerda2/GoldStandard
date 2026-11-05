"""What mutmut makes of a source file, read through mutmut itself: the half of
the pragma check (``tools/pragma_scope.py``) that needs mutmut.

- ``pragmas``: every ``# pragma: no mutate`` comment, with its kind and reason;
- ``mutants``: the mutants mutmut makes **and applies** (inside a module
  function or a method of a top-level class), with their position and code;
- ``switched_off``: the source with some pragmas no longer read as pragmas,
  every position unchanged.

Needs mutmut (and libcst): the mutation gate's workflow installs the version
``requirements-dev.txt`` pins.
"""

import io
import re
import tokenize
import warnings
from dataclasses import dataclass

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider
from mutmut.mutation.file_mutation import MutationVisitor
from mutmut.mutation.mutators import mutation_operators
from mutmut.mutation.pragma_handling import get_ignored_lines

REGION = ("block", "start", "end")
MARK, OFF = "no mutate", "no_mutate"  # same length: every position is kept
# Another tool's comment after the reason (fmt: skip, a noqa), and coverage's
# own pragma words, which are no reason.
_TOOL_COMMENT = re.compile(r"\s#\s*(fmt|noqa|type|pyright|mypy|pylint|isort|nosec)\b")
_OTHER_PRAGMA = re.compile(r"\bno (cover|branch)\b")


@dataclass(frozen=True)
class Pragma:
    line: int  # 1-based
    kind: str  # "bare", "block", "start" or "end", as mutmut reads it
    reason: str
    start: int  # column where `no mutate` starts
    text: str  # the source line, stripped


@dataclass(frozen=True)
class Mutant:
    line: int
    column: int
    end: tuple[int, int]
    before: str
    after: str

    def __str__(self) -> str:
        return f"{self.line}:{self.column} `{_short(self.before)}` → `{_short(self.after)}`"

    @property
    def key(self) -> tuple[int, int, tuple[int, int], str]:
        return (self.line, self.column, self.end, self.after)


def _short(code: str, width: int = 60) -> str:
    flat = " ".join(code.split())
    return flat if len(flat) <= width else f"{flat[: width - 1]}…"


def reason(comment: str) -> str:
    """What the comment says beside the pragma: the text after ``no mutate``
    (and its kind), up to another tool's comment, without coverage's words."""
    tail = _TOOL_COMMENT.split(comment.partition(MARK)[2], maxsplit=1)[0]
    words = _OTHER_PRAGMA.sub(" ", tail).strip(" :—–-,;()").split()
    if words and words[0] in REGION:
        words = words[1:]
    return " ".join(words).strip(" :—–-,;()")


def pragmas(code: str) -> list[Pragma]:
    """Every ``# pragma: no mutate`` comment, as mutmut recognises one."""
    found = []
    lines = code.split("\n")
    for tok in tokenize.generate_tokens(io.StringIO(code).readline):
        text = tok.string
        if tok.type != tokenize.COMMENT or "# pragma:" not in text or MARK not in text:
            continue
        first = text.partition(MARK)[2].lstrip(": ").split(",", 1)[0].split()
        kind = first[0] if first and first[0] in REGION else "bare"
        row, col = tok.start
        if kind in ("start", "end") and lines[row - 1][:col].strip():
            kind = "bare"  # after code, mutmut reads it as a plain pragma on that line
        found.append(
            Pragma(row, kind, reason(text), col + text.index(MARK), lines[row - 1].strip())
        )
    return found


def _applied(module: cst.Module) -> set[int]:
    """The functions whose mutants mutmut applies, by node id."""
    ids: set[int] = set()
    for node in module.body:
        if isinstance(node, cst.FunctionDef):
            ids.add(id(node))
        elif isinstance(node, cst.ClassDef) and isinstance(node.body, cst.IndentedBlock):
            ids.update(id(item) for item in node.body.body if isinstance(item, cst.FunctionDef))
    return ids


def mutants(code: str) -> list[Mutant]:
    """The mutants mutmut makes of ``code`` and applies."""
    wrapper = MetadataWrapper(cst.parse_module(code))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ignored = get_ignored_lines("<source>", code, wrapper)
    visitor = MutationVisitor(mutation_operators, ignored)
    wrapper.visit(visitor)
    positions = wrapper.resolve(PositionProvider)
    module = wrapper.module
    applied = _applied(module)
    found = []
    for m in visitor.mutations:
        # A class-body statement or a nested class's method has an owner too,
        # but mutmut never applies its mutants.
        if id(m.contained_by_top_level_function) not in applied:
            continue
        where = positions[m.original_node]
        found.append(
            Mutant(
                where.start.line,
                where.start.column,
                (where.end.line, where.end.column),
                module.code_for_node(m.original_node).replace(OFF, MARK),
                module.code_for_node(m.mutated_node).replace(OFF, MARK),
            )
        )
    return found


def region_end(pragma: Pragma, every: list[Pragma]) -> list[Pragma]:
    """The ``end`` that closes a ``start``, switched off with it."""
    if pragma.kind != "start":
        return []
    return [p for p in every if p.kind == "end" and p.line > pragma.line][:1]


def switched_off(code: str, off: list[Pragma]) -> str:
    """``code`` with these pragmas no longer read as pragmas: ``no mutate``
    becomes ``no_mutate``, so every position stays what it was."""
    lines = code.split("\n")
    for p in off:
        line = lines[p.line - 1]
        lines[p.line - 1] = line[: p.start] + OFF + line[p.start + len(MARK) :]
    return "\n".join(lines)
