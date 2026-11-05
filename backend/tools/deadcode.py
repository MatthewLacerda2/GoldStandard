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
   by ``getattr``, is in ``IGNORE_NAMES``. Each entry carries its reason.
3. **Code only the tests use is dead too.** The scan runs twice: with
   ``tests/`` read as a use, which finds dead code anywhere (the tests' own
   helpers included), and without it, which finds application code only the
   tests keep alive: a path nothing runs, whose test proves nothing about the
   app.
4. **What stays on purpose says so where it is**: ``# lint: allow(deadcode)
   <why>`` on the reported line or the line directly above it. The reason is
   required, and an allow that excuses nothing is reported, so they only
   shrink.

Usage (from ``backend/``)::

    python -m tools.deadcode   # every finding as path:line: message; any exits 1
"""

import os
import re
import tokenize
from dataclasses import dataclass
from pathlib import Path

from vulture import Vulture

BACKEND = Path(__file__).resolve().parents[1]
TESTS = "tests"
MIN_CONFIDENCE = 60
EXCLUDE = ["*/.venv/*"]
GATED = frozenset({"attribute", "class", "function", "method", "property", "unreachable_code"})

# fnmatch patterns against a decorator's source text: what it decorates is
# called by a framework, never by name in our code.
IGNORE_DECORATORS: dict[str, str] = {
    "@*router.*": "FastAPI route handlers: @router.get(...) registers them",
    "@app.*": "app-level routes and hooks: @app.get(...), @app.middleware(...)",
    "@pytest.fixture": "pytest fixtures, requested by parameter name or autouse",
    "@pytest_asyncio.fixture": "async pytest fixtures, likewise",
    "@field_validator": "Pydantic runs its validators on (de)serialization",
    "@model_validator": "likewise",
}

# fnmatch patterns against a name: called by convention or read by getattr.
IGNORE_NAMES: dict[str, str] = {
    "dispatch": "BaseHTTPMiddleware's override, called by Starlette",
    "pytest_*": "pytest hooks in a conftest, called by pytest by name",
}

ALLOW = re.compile(r"lint: allow\(deadcode\)(?P<why>.*)")
FIX = (
    "Delete the code, and any test that is its only use. If a framework calls it by"
    " convention, add its decorator to IGNORE_DECORATORS or its name to IGNORE_NAMES"
    " in backend/tools/deadcode.py, with the reason. If it stays on purpose, write"
    " `# lint: allow(deadcode) <why>` on the reported line or the line above it."
)


@dataclass(frozen=True)
class Allow:
    """An allow comment: where it is, and whether it gives its reason."""

    path: Path
    line: int
    has_reason: bool


def scan(root: Path, exclude: list[str]) -> list[tuple[Path, int, str]]:
    """Gated vulture findings under ``root`` as (path, line, message)."""
    vulture = Vulture(ignore_names=[*IGNORE_NAMES], ignore_decorators=[*IGNORE_DECORATORS])
    vulture.scavenge([str(root)], exclude=[*EXCLUDE, *exclude])
    found = vulture.get_unused_code(min_confidence=MIN_CONFIDENCE)
    return [
        (Path(item.filename).resolve(), item.first_lineno, item.message)
        for item in found
        if item.typ in GATED
    ]


def allows(root: Path) -> list[Allow]:
    """Every ``lint: allow(deadcode)`` comment in the Python under ``root``."""
    found = []
    for path in sorted(root.rglob("*.py")):
        if ".venv" in path.relative_to(root).parts:
            continue
        with path.open("rb") as source:
            for token in tokenize.tokenize(source.readline):
                if token.type == tokenize.COMMENT and (match := ALLOW.search(token.string)):
                    has_reason = bool(re.search(r"\w", match["why"]))
                    found.append(Allow(path.resolve(), token.start[0], has_reason))
    return found


def check(root: Path = BACKEND, tests: str = TESTS) -> list[str]:
    """Every finding under ``root``, as ``path:line: message`` (policy 1-4)."""
    dead = scan(root, [])
    only_tests = [f for f in scan(root, [f"{root.resolve() / tests}/*"]) if f not in dead]
    findings = [*dead, *((p, n, f"{m}, used only by tests") for p, n, m in only_tests)]
    every = allows(root)
    excusing = {(a.path, a.line) for a in every if a.has_reason}
    used: set[tuple[Path, int]] = set()
    report = []
    for path, line, message in findings:
        hit = {(path, line), (path, line - 1)} & excusing
        used |= hit
        if not hit:
            report.append(f"{os.path.relpath(path)}:{line}: {message}")
    for allow in every:
        where = f"{os.path.relpath(allow.path)}:{allow.line}"
        if not allow.has_reason:
            report.append(f"{where}: allow(deadcode) without a reason")
        elif (allow.path, allow.line) not in used:
            report.append(f"{where}: allow(deadcode) excuses nothing")
    return report


def main() -> int:
    report = check()
    for line in report:
        print(line)
    if report:
        print(f"\n{len(report)} dead-code finding(s). {FIX}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
