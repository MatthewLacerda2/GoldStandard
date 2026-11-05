"""`layer-read`: a file a layer's code reads is one that layer's CI job counts.

`tools/ci_paths.py` runs a layer's job only when the change touches a path
that layer counts. A test that reads a file from outside its layer, say a
backend test reading a file under `frontend/`, is then skipped by a change to
only that file: the change merges green and the next branch in that layer
finds `main` red. This check reads every tracked code file of each layer
(`READERS`) for the tracked files it names, and fails on one the layer does
not count (`COUNTED`), naming the reader, the file and the layer to add it to.

- **What is read**: the code a layer's gates run, its tests and the code they
  call alike, since a gate reading a file is the same as a test reading it
  (the backend build reads `frontend/openapi.json` from `backend/tools/`).
  The `tools` job runs on every change, so it counts every path and nothing
  of its own is ever found; its files are read so that a filter put on that
  job later is held at once, by changing its entry in `COUNTED`.
- **What names a file** (`named`): a string literal, alone, or the run of
  literals that joins onto one path: Python's `ROOT / "frontend" / "x.json"`,
  any call's consecutive literal arguments (`join(ROOT, "tools", "x.py")`,
  `Path("a", "b")`), and the literal tail of a formatted string
  (`f"{ROOT}/tools/x.py"`, `` `${ROOT}/tools/x.py` ``). Python is parsed with
  `ast` and docstrings are skipped; TypeScript and JavaScript are scanned,
  comments skipped, the way `tools/comments.py` reads them.
- **Where it points** (`readings`): the literal read from the reader's own
  folder and from each folder above it, up to the root, so a constant for the
  root or for the layer's folder needs no evaluating. Only tracked files
  count, never a directory. A reading the layer counts wins, so a name that
  is also a file inside the layer is never a finding.
- **Out of reach**: a path built at run time (from a variable, a loop, a
  `.parent` chain with no literal after it, a glob), a whole directory read or
  copied, and a module imported by name. Recording the files a suite opens
  would catch those; this check is the cheap half, and the rest is still a
  reviewer's.

A literal that names a tracked file but is not read (a fixture written into a
temporary repository, say) is excused where it is, with the reason:
`lint: allow(layer-read) <why>` in a comment on the line or the one directly
above it, read as the docs lint reads its allows.

    python3.14 -m tools.layer_reads   # from the root; exit 1 on a finding
"""

from __future__ import annotations

import ast
import posixpath
import re
import sys
from collections.abc import Iterator, Mapping
from pathlib import PurePosixPath

from tools.ci_paths import LAYERS, counts
from tools.docs_lint.core import Doc, allowed_line
from tools.markers import ROOT, tracked

RULE = "layer-read"

# The code each CI job runs, read for the files it names.
READERS = {
    "backend": ("backend/**/*.py",),
    "frontend": tuple(f"frontend/**/*.{ext}" for ext in ("ts", "tsx", "js", "mjs")),
    "tools": ("tools/**/*.py",),
}

# What change runs each job: a layer's own patterns, and every path for
# `tools`, which `ci.yml` runs on every change.
COUNTED: dict[str, tuple[str, ...]] = {**LAYERS, "tools": ("**",)}

_GLOB = frozenset("*?[]{}<>$")

Named = list[tuple[int, str]]


def _joined(parts: list[str]) -> str:
    return "/".join(part.strip("/") for part in parts if part.strip("/"))


def _runs(nodes: list[ast.expr]) -> Iterator[tuple[int, str]]:
    """Each maximal run of string constants among `nodes`, joined as a path."""
    run: list[ast.Constant] = []
    for node in [*nodes, None]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            run.append(node)
            continue
        if len(run) > 1:
            yield run[0].lineno, _joined([c.value for c in run])
        run = []


def _divided(node: ast.BinOp) -> list[ast.expr]:
    """The operands of a chain of `/`, left to right."""
    left = node.left
    head = (
        _divided(left) if isinstance(left, ast.BinOp) and isinstance(left.op, ast.Div) else [left]
    )
    return [*head, node.right]


def _python(text: str) -> Named:
    tree = ast.parse(text)
    nodes = list(ast.walk(tree))
    # A docstring, or any bare string statement, is prose; an f-string's parts
    # are read as its tail only.
    skipped = {id(n.value) for n in nodes if isinstance(n, ast.Expr)}
    skipped |= {id(v) for n in nodes if isinstance(n, ast.JoinedStr) for v in n.values}
    found: Named = []
    for node in nodes:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in skipped:
                found.append((node.lineno, node.value))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            found.extend(_runs(_divided(node)))
        elif isinstance(node, ast.Call):
            found.extend(_runs(node.args))
        elif isinstance(node, ast.JoinedStr) and isinstance(node.values[-1], ast.Constant):
            found.append((node.lineno, str(node.values[-1].value).lstrip("/")))
    return found


def _end(text: str, what: str, start: int) -> int:
    """Where `what` is in `text` from `start`, or the end of the text."""
    found = text.find(what, start)
    return len(text) if found < 0 else found


def _literals(text: str) -> Iterator[tuple[int, int, str]]:
    """Each string literal of a TypeScript or JavaScript file outside its
    comments, as `(start, end, value)`; a template literal's value is its text
    after its last `${}`. A quote ends at its line's end, as in
    `tools/comments.py`, so a quote inside a regular expression costs at most
    the rest of that line."""
    at = 0
    while at < len(text):
        if text.startswith("//", at):
            at = _end(text, "\n", at)
        elif text.startswith("/*", at):
            at = _end(text, "*/", at + 2) + 2
        elif text[at] in "'\"`":
            quote, end = text[at], at + 1
            while end < len(text) and text[end] != quote and (quote == "`" or text[end] != "\n"):
                end += 2 if text[end] == "\\" else 1
            body = text[at + 1 : end]
            yield at, end + 1, body.rpartition("}")[2].lstrip("/") if quote == "`" else body
            at = end + 1
        else:
            at += 1


def _script(text: str) -> Named:
    found: Named = []
    run: list[tuple[int, int, str]] = []
    for literal in [*_literals(text), None]:
        if literal:
            found.append((text.count("\n", 0, literal[0]) + 1, literal[2]))
            if run and re.fullmatch(r"\s*,\s*", text[run[-1][1] : literal[0]]):
                run.append(literal)
                continue
        if len(run) > 1:
            line = text.count("\n", 0, run[0][0]) + 1
            found.append((line, _joined([value for *_, value in run])))
        run = [literal] if literal else []
    return found


def named(path: str, text: str) -> Named:
    """`(line, literal)` for each string, or run of strings, `path` may name a file with."""
    return _python(text) if path.endswith(".py") else _script(text)


def readings(reader: str, literal: str, files: frozenset[str]) -> list[str]:
    """The tracked files `literal`, written in `reader`, may point at: read
    from the reader's folder and from each folder above it."""
    literal = literal.strip()
    if not literal or literal.startswith("/") or _GLOB.intersection(literal):
        return []
    found = []
    for base in [*PurePosixPath(reader).parents]:
        at = posixpath.normpath(posixpath.join(str(base), literal))
        if not at.startswith("..") and at in files and at not in found:
            found.append(at)
    return found


def layer_of(path: str) -> str | None:
    return next((layer for layer, globs in READERS.items() if _matches(path, globs)), None)


def _matches(path: str, globs: tuple[str, ...]) -> bool:
    return any(PurePosixPath(path).full_match(glob) for glob in globs)


def check(
    reader: str,
    text: str,
    files: frozenset[str],
    counted: Mapping[str, tuple[str, ...]] = COUNTED,
) -> list[str]:
    """A finding per file `reader` names that its layer's job does not count."""
    layer = layer_of(reader)
    if layer is None:
        return []
    try:
        found = named(reader, text)
    except SyntaxError as exc:
        return [f"{reader}: {RULE}: could not parse it: {exc}"]
    doc = Doc(PurePosixPath(reader), text)
    findings: list[str] = []
    for line, literal in sorted(set(found)):
        points = readings(reader, literal, files)
        if not points or any(counts(counted[layer], p) for p in points):
            continue
        if allowed_line(doc, line - 1, RULE):
            continue
        findings.append(
            f"{reader}:{line}: {RULE}: reads `{' or '.join(points)}`, which `tools/ci_paths.py` "
            f"does not count for {layer}, so a change to only that file skips the "
            f"{layer} job: add it to LAYERS[{layer!r}] (or allow the line, saying "
            "why it is not read)"
        )
    return findings


def scan(counted: Mapping[str, tuple[str, ...]] = COUNTED) -> list[str]:
    """The findings in every tracked reader."""
    files = frozenset(tracked())
    findings = []
    for reader in sorted(filter(layer_of, files)):
        file = ROOT / reader
        if file.is_file():  # a file deleted locally has nothing to read
            findings += check(reader, file.read_text(encoding="utf-8"), files, counted)
    return findings


def main() -> int:
    """Check every tracked reader; print each finding."""
    findings = scan()
    print("\n".join(findings) or "layer-reads: clean")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
