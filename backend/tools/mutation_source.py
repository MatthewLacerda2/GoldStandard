"""What a diff changed in a Python file, in mutmut's terms.

The pure half of the mutation gate (``tools/mutation_gate.py``) and of
``make back-mutate-diff`` (``tools/mutate_diff.py``):

- ``diff_lines``: the new-side and old-side line numbers of ``git diff -U0``;
- ``changed_functions``: the functions mutmut mutates whose lines changed;
- ``module_change``: what changed outside them (a constant, an import, a
  function deleted whole), as one named line that needs a decision, because
  mutmut never mutates it.

Standard library only: CI runs it without installing the backend.
"""

import ast
import hashlib
import re
from dataclasses import dataclass, field

_FILE = re.compile(r"^(---|\+\+\+) (?:[ab]/(.*)|/dev/null)$")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class Lines:
    new: set[int] = field(default_factory=set)  # touched, new side
    old: set[int] = field(default_factory=set)  # removed or rewritten, old side


def diff_lines(diff: str) -> dict[str, Lines]:
    """Each file's touched lines, from ``git diff -U0`` with ``a/`` and ``b/``
    prefixes, keyed by its new path (its old one when it was deleted).

    A pure deletion (``+N,0``) touches the new lines on both sides of the cut,
    so a line removed from inside a function counts as a change to it.
    """
    files: dict[str, Lines] = {}
    old_path: str | None = None
    current: Lines | None = None
    header = True  # a removed line can itself read `--- a/x`; only headers name files
    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            header, current, old_path = True, None, None
        elif header and (match := _FILE.match(line)):
            if match[1] == "---":
                old_path = match[2]
            else:
                path = match[2] or old_path
                current = files.setdefault(path, Lines()) if path else None
        elif current is not None and (hunk := _HUNK.match(line)):
            header = False
            old_start, old_count = int(hunk[1]), int(hunk[2] if hunk[2] is not None else 1)
            start, count = int(hunk[3]), int(hunk[4] if hunk[4] is not None else 1)
            current.old.update(range(old_start, old_start + old_count))
            current.new.update(range(start, start + count) if count else {start, start + 1})
    return files


@dataclass(frozen=True)
class Span:
    """A function as mutmut names it (``x_name``, or ``xǁClassǁmethod``)."""

    name: str
    first: int
    last: int


def _span(node: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> Span:
    first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    return Span(name, first, node.end_lineno or node.lineno)


def function_spans(source: str) -> list[Span]:
    """The functions mutmut mutates one by one: the module's own functions and
    the methods of its top-level classes. A nested function is mutated as part
    of the one that holds it, so its lines are that one's."""
    spans: list[Span] = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            spans.append(_span(node, f"x_{node.name}"))
        elif isinstance(node, ast.ClassDef):
            spans.extend(
                _span(item, f"xǁ{node.name}ǁ{item.name}")
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            )
    return spans


def module_name(path: str) -> str:
    """The module part of a mutant's name, as mutmut derives it from where it
    runs (``backend/``): ``backend/api/v1/auth.py`` is ``api.v1.auth``."""
    name = path.removeprefix("backend/").removesuffix(".py").replace("/", ".")
    return name.removesuffix(".__init__")


def changed_functions(source: str, lines: set[int]) -> list[str]:
    return [s.name for s in function_spans(source) if any(s.first <= n <= s.last for n in lines)]


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:8]


def function_sources(source: str) -> dict[str, str]:
    """Each function's own text, hashed: a decision about it holds only while
    this does not change."""
    lines = source.split("\n")
    return {
        s.name: source_hash("\n".join(lines[s.first - 1 : s.last])) for s in function_spans(source)
    }


def _docstring_lines(tree: ast.Module) -> set[int]:
    first = tree.body[0] if tree.body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
        return set(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return set()


def _ranges(lines: list[int]) -> str:
    ranges, start = [], lines[0]
    for prev, n in zip(lines, [*lines[1:], None], strict=True):
        if n != prev + 1:
            ranges.append(f"{start}-{prev}" if prev != start else str(start))
            start = n
    return ",".join(ranges)


def _significant(text: list[str], lines: set[int], skip: set[int]) -> list[int]:
    """The lines that hold code: not skipped, not blank, not a comment."""
    return sorted(
        n
        for n in lines
        if 0 < n <= len(text)
        and n not in skip
        and text[n - 1].strip()
        and not text[n - 1].strip().startswith("#")
    )


def module_change(path: str, old: str, new: str, lines: Lines) -> str | None:
    """What changed outside the functions mutmut runs, named
    ``<path>:<new lines> -<old lines> #<hash of their text>``, or None.

    New side: lines outside every function. Old side: removed lines that were
    outside every function, or inside one the new module no longer has (a
    guard deleted whole). The module's docstring aside, everything counts, an
    import included: mutmut mutates none of it, so a decision says which test
    covers it.
    """
    new_spans, old_spans = function_spans(new), function_spans(old) if old else []
    kept = {s.name for s in new_spans}
    new_skip = {n for s in new_spans for n in range(s.first, s.last + 1)}
    old_skip = {n for s in old_spans if s.name in kept for n in range(s.first, s.last + 1)}
    new_skip |= _docstring_lines(ast.parse(new))
    old_skip |= _docstring_lines(ast.parse(old)) if old else set()
    new_text, old_text = new.split("\n"), old.split("\n")
    added = _significant(new_text, lines.new, new_skip)
    removed = _significant(old_text, lines.old, old_skip) if old else []
    if not added and not removed:
        return None
    text = [f"+{new_text[n - 1]}" for n in added] + [f"-{old_text[n - 1]}" for n in removed]
    where = _ranges(added) if added else "-"
    gone = f" -{_ranges(removed)}" if removed else ""
    return f"{path}:{where}{gone} #{source_hash(chr(10).join(text))}"
