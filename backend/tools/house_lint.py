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
  4. Every body crossing a ``@router.<method>`` boundary is a Pydantic schema
     type: a parameter is either an injected dependency (``Depends()`` and the
     rest of FastAPI's parameter markers), a path/query scalar, or a schema
     type; a return annotation is a schema type, a ``list`` of one, or ``None``.
     Only ``router`` counts here — the unversioned ``@app.get`` baseline routes
     are outside the versioned API contract. Rules 2 and 3 stay broader and
     still cover them.

Rule 4 is structural only — that a body is a declared model, not that its
fields carry the right constraints. A template cannot know what its users will
build, so value-level validation is deliberately left to them.

Being single-file and pure-AST, this linter cannot resolve a name back to a
``BaseModel`` subclass in another module. It instead reads the file's own
``schemas`` imports and treats the names they bind as schema types. Spelling is
never consulted: a ``Read``/``Create`` suffix proves nothing on its own.

Missing annotations are ruff's job (``ANN``); rule 4 only judges the
annotations that are there.

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
_SCHEMA_PACKAGE = "schemas"
_ROUTER_OBJECT = "router"

# FastAPI's parameter markers. A parameter carrying one is injected by the
# framework, so it is not a request body.
_INJECTION_MARKERS = frozenset(
    {"Body", "Cookie", "Depends", "File", "Form", "Header", "Path", "Query", "Security"}
)

# Types a path or query parameter can be spelled as.
_SCALARS = frozenset({"bool", "bytes", "float", "int", "str", "UUID", "uuid.UUID"})


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
                f"{path}:{node.lineno}: test '{node.name}' is {span} lines (max {MAX_TEST_LINES})"
            )
    return violations


def _dotted_name(node: ast.expr) -> str:
    """Source spelling of a ``Name``/``Attribute`` chain, e.g. ``uuid.UUID``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _is_none(node: ast.expr) -> bool:
    """True for the literal ``None`` annotation."""
    return isinstance(node, ast.Constant) and node.value is None


def _subscript_of(node: ast.expr, name: str) -> ast.expr | None:
    """Return the subscript of ``name[...]`` (``list``, ``Annotated``, …), else None."""
    if isinstance(node, ast.Subscript) and _dotted_name(node.value).split(".")[-1] == name:
        return node.slice
    return None


def _schema_names(tree: ast.Module) -> set[str]:
    """Names this module binds by importing from the ``schemas`` package.

    Covers ``from schemas.x import Y`` (binds ``Y``), ``from schemas import x``
    (binds ``x``) and ``import schemas.x`` (binds ``schemas``), with aliases.
    """
    names: set[str] = set()
    prefix = f"{_SCHEMA_PACKAGE}."
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == _SCHEMA_PACKAGE or module.startswith(prefix):
                names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _SCHEMA_PACKAGE or alias.name.startswith(prefix):
                    names.add(alias.asname or alias.name.split(".")[0])
    return names


def _unwrap(node: ast.expr) -> ast.expr:
    """Peel ``Annotated[X, ...]`` and the ``None`` half of an optional off ``X``."""
    annotated = _subscript_of(node, "Annotated")
    if isinstance(annotated, ast.Tuple) and annotated.elts:
        return _unwrap(annotated.elts[0])
    optional = _subscript_of(node, "Optional")
    if optional is not None:
        return _unwrap(optional)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        sides = [side for side in (node.left, node.right) if not _is_none(side)]
        if len(sides) == 1:
            return _unwrap(sides[0])
    return node


def _is_schema_type(node: ast.expr, known: set[str]) -> bool:
    """True if the annotation resolves to a name imported from ``schemas``."""
    name = _dotted_name(_unwrap(node))
    return bool(name) and name.split(".")[0] in known


def _is_injection(node: ast.expr | None) -> bool:
    """True for a call to one of FastAPI's parameter markers."""
    return (
        isinstance(node, ast.Call) and _dotted_name(node.func).split(".")[-1] in _INJECTION_MARKERS
    )


def _is_injected(annotation: ast.expr, default: ast.expr | None) -> bool:
    """True if FastAPI supplies this parameter, as a default or inside ``Annotated``."""
    if _is_injection(default):
        return True
    metadata = _subscript_of(annotation, "Annotated")
    return isinstance(metadata, ast.Tuple) and any(_is_injection(e) for e in metadata.elts[1:])


def _iter_params(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[tuple[ast.arg, ast.expr | None]]:
    """Pair each named parameter with its default, if it has one."""
    positional = [*node.args.posonlyargs, *node.args.args]
    padding: list[ast.expr | None] = [None] * (len(positional) - len(node.args.defaults))
    return [
        *zip(positional, padding + list(node.args.defaults), strict=True),
        *zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True),
    ]


def _is_api_router_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True only for ``@router.<http-method>(...)``.

    Deliberately narrower than ``_is_router_handler``, which matches the method
    name on any object. Rule 4 governs the versioned API surface, where the
    decorated object is an ``APIRouter`` named ``router``. The unversioned
    baseline routes in ``main.py`` hang off ``@app.get`` and answer with plain
    infrastructure payloads, so they stay outside it.
    """
    for dec in node.decorator_list:
        call = dec.func if isinstance(dec, ast.Call) else dec
        if not isinstance(call, ast.Attribute) or call.attr not in _HTTP_METHODS:
            continue
        if _dotted_name(call.value).split(".")[-1] == _ROUTER_OBJECT:
            return True
    return False


def _check_params(
    path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef, known: set[str]
) -> list[str]:
    """Every parameter is an injection, a path/query scalar, or a schema type."""
    violations: list[str] = []
    for param, default in _iter_params(node):
        annotation = param.annotation
        if annotation is None or _is_injected(annotation, default):
            continue
        if _dotted_name(_unwrap(annotation)) in _SCALARS or _is_schema_type(annotation, known):
            continue
        violations.append(
            f"{path}:{node.lineno}: handler '{node.name}' parameter '{param.arg}' is "
            f"'{ast.unparse(annotation)}' (request bodies must be schema types)"
        )
    return violations


def _check_return(
    path: Path, node: ast.FunctionDef | ast.AsyncFunctionDef, known: set[str]
) -> list[str]:
    """The return annotation is a schema type, a ``list`` of one, or ``None``."""
    annotation = node.returns
    if annotation is None:
        return []
    unwrapped = _unwrap(annotation)
    element = _subscript_of(unwrapped, "list")
    if element is not None:
        valid = _is_schema_type(element, known)
    else:
        valid = _is_none(unwrapped) or _is_schema_type(unwrapped, known)
    if valid:
        return []
    return [
        f"{path}:{node.lineno}: handler '{node.name}' returns "
        f"'{ast.unparse(annotation)}' (responses must be a schema type, list of one, or None)"
    ]


def check_router_io(path: Path, source: str) -> list[str]:
    """Rule 4: every body crossing a router boundary is a Pydantic schema type."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []  # Already reported by check_function_lengths.

    known = _schema_names(tree)
    violations: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not _is_api_router_handler(node):
            continue
        violations.extend(_check_params(path, node, known))
        violations.extend(_check_return(path, node, known))
    return violations


def check_source(path: Path, source: str) -> list[str]:
    """Run every rule against a single file's source text."""
    return (
        check_file_length(path, source)
        + check_function_lengths(path, source)
        + check_router_io(path, source)
    )


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
