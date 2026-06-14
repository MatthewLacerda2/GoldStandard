"""Custom house linter (pure stdlib, AST-based).

Rules enforced:
  1. A source file longer than ``MAX_FILE_LINES`` lines fails, unless it carries
     a ``# lint: data-file`` marker within its first 15 lines. Files under a
     ``tests/`` directory are exempt from this rule.
  2. Any function decorated with ``@router.<method>`` (get/post/put/patch/delete)
     longer than ``MAX_HANDLER_LINES`` (def line to last line, decorators
     excluded) fails.
  3. Any ``test_*`` function under a ``tests/`` directory longer than
     ``MAX_TEST_LINES`` fails.

The module is importable (rules return violation lists) and runnable as
``python tools/house_lint.py`` to scan the backend tree.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

MAX_FILE_LINES = 350
MAX_HANDLER_LINES = 50
MAX_TEST_LINES = 50
DATA_FILE_MARKER = "# lint: data-file"
_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
_MARKER_SCAN_LINES = 15


def _is_under_tests(path: Path) -> bool:
    """Return True if any path component is a ``tests`` directory."""
    return "tests" in path.parts


def _node_line_span(node: ast.AST) -> int:
    """Number of lines a function spans, excluding decorators."""
    start = node.lineno  # `def`/`async def` line, after decorators
    end = node.end_lineno or start
    return end - start + 1


def _is_router_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True if the function is decorated with ``@router.<http-method>(...)``."""
    for dec in node.decorator_list:
        call = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(call, ast.Attribute) and call.attr in _HTTP_METHODS:
            return True
    return False


def check_file_length(path: Path, source: str) -> list[str]:
    """Rule 1: enforce the maximum file length."""
    if _is_under_tests(path):
        return []
    lines = source.splitlines()
    if len(lines) <= MAX_FILE_LINES:
        return []
    header = "\n".join(lines[:_MARKER_SCAN_LINES])
    if DATA_FILE_MARKER in header:
        return []
    return [f"{path}: file has {len(lines)} lines (max {MAX_FILE_LINES})"]


def check_function_lengths(path: Path, source: str) -> list[str]:
    """Rules 2 and 3: enforce handler and test function length limits."""
    violations: list[str] = []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: syntax error: {exc}"]

    under_tests = _is_under_tests(path)
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        span = _node_line_span(node)
        if _is_router_handler(node) and span > MAX_HANDLER_LINES:
            violations.append(
                f"{path}:{node.lineno}: handler '{node.name}' is {span} lines "
                f"(max {MAX_HANDLER_LINES})"
            )
        if under_tests and node.name.startswith("test_") and span > MAX_TEST_LINES:
            violations.append(
                f"{path}:{node.lineno}: test '{node.name}' is {span} lines "
                f"(max {MAX_TEST_LINES})"
            )
    return violations


def check_source(path: Path, source: str) -> list[str]:
    """Run every rule against a single file's source text."""
    return check_file_length(path, source) + check_function_lengths(path, source)


def iter_python_files(root: Path) -> list[Path]:
    """Yield Python files under ``root``, skipping caches and virtualenvs."""
    skip = {".venv", "__pycache__", ".ruff_cache", ".pytest_cache", ".git"}
    return sorted(p for p in root.rglob("*.py") if not any(part in skip for part in p.parts))


def scan(root: Path) -> list[str]:
    """Scan the tree under ``root`` and return all violations."""
    violations: list[str] = []
    for path in iter_python_files(root):
        violations.extend(check_source(path, path.read_text(encoding="utf-8")))
    return violations


def main() -> int:
    """Entry point: scan the backend tree, print violations, set exit code."""
    root = Path(__file__).resolve().parent.parent
    violations = scan(root)
    if violations:
        for v in violations:
            print(v)
        print(f"\nhouse_lint: {len(violations)} violation(s)")
        return 1
    print("house_lint: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
