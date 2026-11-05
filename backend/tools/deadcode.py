"""Whole-program dead-code gate: code nothing calls (``make back-deadcode``).

Ruff sees one file at a time, so it catches unused imports and locals; a
function, class or method no other module uses takes whole-program analysis,
which vulture provides. Vulture matches names and is purely static, so this
wrapper adds the policy that makes its output worth gating on:

1. **Only structural findings gate** (``GATED``): functions, classes,
   methods, properties, attributes and unreachable code. A ``variable``
   finding is dropped: at class level it is an ORM column or a Pydantic field,
   read dynamically (the database mapping, JSON serialization), an unused
   local is ruff's (F841), and an unused parameter usually matches a signature
   on purpose. Unused imports are ruff's too (F401).
2. **Framework entry points are not dead.** What a decorator hands to a
   framework (route handlers, pytest fixtures, Pydantic validators) is in
   ``IGNORE_DECORATORS``; a name a framework calls by convention, or code reads
   by ``getattr``, is in ``IGNORE_NAMES``. Each entry carries its reason, and
   an entry nothing in the backend matches is reported: an entry is added with
   the first code that needs it (``@model_validator``, ``@field_serializer``,
   ``@computed_field``, SQLAlchemy's ``@validates``, a ``pytest_*`` hook).
3. **Code only the tests use is dead too.** The scan runs twice: with
   ``tests/`` read as a use, which finds dead code anywhere (the tests' own
   helpers included), and without it, which finds application code only the
   tests keep alive: a path nothing runs, whose test proves nothing about the
   app.
4. **What stays on purpose says so where it is**: ``# lint: allow(deadcode)
   <why>`` at the end of the reported line, or alone on the line directly
   above it. Either excuses that one line, every finding on it. A decorated
   definition is reported at its first decorator, so its allow goes there.
   The reason is required (more than separators, as house_lint's marker allow
   reads it), and an allow that excuses nothing is reported, so they only
   shrink. It is the only exception we write: vulture's own ``# noqa``
   handling is switched off. Vulture's built-in ignores still apply: dunder
   methods, and ``test_*`` functions and ``*Test*`` classes in ``test*.py``
   files, which pytest collects by name.

Usage (from ``backend/``)::

    python -m tools.deadcode   # every finding as path:line: message; any exits 1
"""

import ast
import glob
import os
import re
import tokenize
from collections import defaultdict
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from vulture import Vulture
from vulture.utils import get_decorator_name

BACKEND = Path(__file__).resolve().parents[1]
TESTS = "tests"
MIN_CONFIDENCE = 60
EXCLUDE = ["*/.venv/*"]
GATED = frozenset({"attribute", "class", "function", "method", "property", "unreachable_code"})

# fnmatch patterns against a decorator's source text: what it decorates is
# called by a framework, never by name in our code.
IGNORE_DECORATORS: dict[str, str] = {
    "@*router.*": "FastAPI route handlers: @router.get(...) registers them",
    "@app.*": "app-level routes: @app.get(...) registers them",
    "@pytest.fixture": "pytest fixtures, requested by parameter name or autouse",
    "@pytest_asyncio.fixture": "async pytest fixtures, likewise",
    "@field_validator": "Pydantic runs its validators on (de)serialization",
}

# fnmatch patterns against a name: called by convention or read by getattr.
IGNORE_NAMES: dict[str, str] = {
    "dispatch": "BaseHTTPMiddleware's override, called by Starlette",
}

ALLOW = re.compile(r"lint: allow\(deadcode\)(?P<why>.*)")
# A reason is anything besides separators: house_lint's marker allow reads it so.
REASON = re.compile(r"[^\s:—#*/-]")
FIX = (
    "Delete the code, and any test that is its only use. If a framework calls it by"
    " convention, add its decorator to IGNORE_DECORATORS or its name to IGNORE_NAMES"
    " in backend/tools/deadcode.py, with the reason. If it stays on purpose, write"
    " `# lint: allow(deadcode) <why>` at the end of the reported line or alone on the"
    " line above it (a decorated definition is reported at its first decorator). An"
    " entry or an allow that excuses nothing is deleted."
)


class _Vulture(Vulture):
    """Vulture with its ``# noqa`` handling off: the allow above is the one
    exception, because it carries a reason and is reported when stale."""

    @property
    def noqa_lines(self) -> defaultdict[str, set[int]]:
        return defaultdict(set)

    @noqa_lines.setter
    def noqa_lines(self, _: object) -> None:
        pass


@dataclass(frozen=True)
class Allow:
    """An allow comment: where it is, the line it excuses, and whether it
    gives its reason."""

    path: Path
    line: int
    excuses: int
    has_reason: bool


def scan(root: Path, exclude: list[str]) -> list[tuple[Path, int, str]]:
    """Gated vulture findings under ``root`` as (path, line, message)."""
    vulture = _Vulture(ignore_names=[*IGNORE_NAMES], ignore_decorators=[*IGNORE_DECORATORS])
    vulture.scavenge([str(root)], exclude=[*EXCLUDE, *exclude])
    found = vulture.get_unused_code(min_confidence=MIN_CONFIDENCE)
    return [
        (Path(item.filename).resolve(), item.first_lineno, item.message)
        for item in found
        if item.typ in GATED
    ]


def _sources(root: Path) -> list[Path]:
    paths = sorted(root.rglob("*.py"))
    return [p for p in paths if ".venv" not in p.relative_to(root).parts]


def allows(root: Path) -> list[Allow]:
    """Every ``lint: allow(deadcode)`` comment in the Python under ``root``."""
    found = []
    for path in _sources(root):
        with path.open("rb") as source:
            for token in tokenize.tokenize(source.readline):
                if token.type == tokenize.COMMENT and (match := ALLOW.search(token.string)):
                    line = token.start[0]
                    alone = not token.line[: token.start[1]].strip()
                    has_reason = bool(REASON.search(match["why"]))
                    found.append(Allow(path.resolve(), line, line + alone, has_reason))
    return found


def check(root: Path = BACKEND, tests: str = TESTS) -> list[str]:
    """Every finding under ``root``, as ``path:line: message`` (policy 1-4)."""
    dead = scan(root, [])
    # Escaped: a `[` or `?` in the path would make the pattern miss the tests.
    without = f"{glob.escape(str(root.resolve() / tests))}/*"
    only_tests = [f for f in scan(root, [without]) if f not in dead]
    findings = [*dead, *((p, n, f"{m}, used only by tests") for p, n, m in only_tests)]
    every = allows(root)
    excusing = {(a.path, a.excuses) for a in every if a.has_reason}
    excused = {(path, line) for path, line, _ in findings} & excusing
    report = [
        f"{os.path.relpath(path)}:{line}: {message}"
        for path, line, message in findings
        if (path, line) not in excused
    ]
    for allow in every:
        where = f"{os.path.relpath(allow.path)}:{allow.line}"
        if not allow.has_reason:
            report.append(f"{where}: allow(deadcode) without a reason")
        elif (allow.path, allow.excuses) not in excused:
            report.append(f"{where}: allow(deadcode) excuses nothing")
    return report


def unmatched_entries(root: Path = BACKEND) -> list[str]:
    """The IGNORE_DECORATORS and IGNORE_NAMES patterns nothing under ``root``
    matches: a decorator vulture would read, or a name defined there (a
    function, class, attribute or variable, which vulture's ``ignore_names``
    all cover)."""
    decorators: set[str] = set()
    names: set[str] = set()
    for path in _sources(root):
        for node in ast.walk(ast.parse(path.read_bytes(), str(path))):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
                decorators.update(get_decorator_name(d) for d in node.decorator_list)
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
                names.add(node.attr)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
    return [
        f"{table} names '{pattern}', which matches nothing in the backend"
        for table, entries, seen in (
            ("IGNORE_DECORATORS", IGNORE_DECORATORS, decorators),
            ("IGNORE_NAMES", IGNORE_NAMES, names),
        )
        for pattern in entries
        if not any(fnmatchcase(name, pattern) for name in seen)
    ]


def main() -> int:
    report = [*check(), *unmatched_entries()]
    for line in report:
        print(line)
    if report:
        print(f"\n{len(report)} dead-code finding(s). {FIX}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
