"""`named-path`: a path or a `make` target that a doc or a comment names exists.

A pointer to a file that moved, or to a target that was renamed, still reads
as true, and sends the next agent to nothing. In a template it is worse: every
project made from it moves things. So what an agent reads as description is
scanned for what it names, and each name is looked up:

- **What is read** (`reads`): every line outside a code fence of the Markdown
  under `docs/` or `.claude/` and of every `CLAUDE.md` and `README.md`; and
  only the comments, never the strings, of `.py`, `.ts`/`.tsx` and `.sh`
  files, of the `.yml` under `.github/`, of the git hooks under `.githooks/`
  (shell scripts with no extension), and of the `Makefile` (its `#` comments,
  its `## ` help text among them). A test's made-up fixture lives in
  a string, so it is never read.
- **What is a path** (`named_in`): a token that starts with one of the `ROOTS`
  and ends in a file extension or a `/`. Markdown's wrapping around it
  (`**docs/a.md**`, `<docs/a.md>`) and a sentence's closing `.` are trimmed; a
  `:12` or `::symbol` after it is not part of it. A token still holding a
  template or glob character (`<name>`, `*`, `{a,b}`, `…`, `$`), a `..`, or a
  leading `/` names no one file and is skipped. In a file inside a top-level
  folder (`backend/`, `frontend/`), a token starting with a folder of that one
  (`tools/house_lint.py`, `src/lib/`) is read from there too, the way the
  layer's own docs write it, and passes if either reading exists.
- **What exists** (`core.Tree`): a file git tracks or would track (so a new
  file counts before `git add`, and a deleted one does not), a directory
  holding one, or a path git ignores whose directory exists (`.env`,
  `backend/.venv/`): made on a machine, never committed, so named on purpose.
- **A `make` target** is read in a code span (`` `make docs-lint` ``), where
  `make` is the command and not the verb: it must be a target of the root
  `Makefile`.

A path named on purpose though absent from the tree (a file a command creates,
a path in a project made from this template) is excused where it is named, with
the reason: an HTML comment `<!-- lint: allow(named-path) <why> -->` on the
line or in the run of them just above it in Markdown, and a comment
`lint: allow(named-path) <why>` on the line or the one just above it in code.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from tools.docs_lint.core import Doc, Violation, allowed_line, violation

RULE = "named-path"

# The top-level folders a named path may start with: this template's, with
# `docs`, which its docs name before it exists. A project made from it adds its
# own.
ROOTS = frozenset(
    {"backend", "frontend", "tools", "docs", "docker", ".github", ".claude", ".githooks"}
)

CODE_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".sh"})
MARKDOWN_NAMES = frozenset({"CLAUDE.md", "README.md"})

# A token: what a path is made of, and the template and glob characters that
# mark one as a pattern rather than a path.
_TEMPLATE = frozenset("*?{}<>$…~%\\")
_TOKEN = re.compile(r"[\w./\-*?{}<>$…~%\\]+")
_WRAPPING = "*_?<>"
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_MAKE = re.compile(r"(?<![\w-])make ([a-z][\w-]*)(?![\w=-])")
# A `Makefile` rule's targets: names before a `:` that is not `:=`.
_RULE_LINE = re.compile(r"^([\w./-]+(?:[ \t]+[\w./-]+)*)[ \t]*::?(?!=)", re.MULTILINE)


def makefile_targets(makefile: str) -> frozenset[str]:
    """The targets a `Makefile`'s rules define."""
    return frozenset(t for m in _RULE_LINE.finditer(makefile) for t in m.group(1).split())


def reads(path: str) -> bool:
    """Whether this rule reads the file at `path`."""
    at = PurePosixPath(path)
    if at.suffix == ".md":
        return at.name in MARKDOWN_NAMES or at.parts[0] == "docs" or ".claude" in at.parts
    if at.suffix in (".yml", ".yaml"):
        return at.parts[0] == ".github"
    return at.suffix in CODE_SUFFIXES or path == "Makefile" or at.parts[0] == ".githooks"


def _texts(doc: Doc) -> list[tuple[int, str]]:
    """The text the rule reads in `doc`, as `(0-based line, text)`."""
    if doc.is_markdown:
        return [(i, line) for i, line in enumerate(doc.lines) if i not in doc.fenced]
    return [(i, text) for i, texts in sorted(doc.comments.items()) for text in texts]


def _path_of(token: str) -> str | None:
    """The path `token` names, as written, or None when it is not shaped like one."""
    token = token.strip(_WRAPPING)
    if _TEMPLATE.intersection(token) or ".." in token or token.startswith("/"):
        return None
    token = token.rstrip(".").removeprefix("./")
    last = token.rsplit("/", 1)[-1]
    extension = last.rpartition(".")[2] if "." in last else ""
    if "/" not in token or not (token.endswith("/") or extension.isalnum()):
        return None
    return token


def _readings(path: str, doc: Doc) -> list[str]:
    """Where `path`, named in `doc`, may point, read from the root: from the
    root when it starts with a root, and from `doc`'s top-level folder when it
    starts with a folder there."""
    first = path.split("/", 1)[0]
    found = [path] if first in ROOTS else []
    if len(doc.path.parts) > 1:
        top = doc.path.parts[0]
        if f"{top}/{first}" in doc.tree.dirs:
            found.append(f"{top}/{path}")
    return found


def named_in(text: str, doc: Doc) -> list[tuple[str, list[str]]]:
    """Each path `text` names, with where it may point."""
    found = []
    for token in _TOKEN.findall(text):
        path = _path_of(token)
        readings = _readings(path, doc) if path else []
        if path and readings:
            found.append((path, readings))
    return found


def _missing(text: str, doc: Doc) -> list[str]:
    """What `text` names that does not exist, as a message for each."""
    wrong = [
        f"names `{path}`, which does not exist: point it at where that is now, or remove "
        "it (or allow it, saying why it is named on purpose)"
        for path, readings in named_in(text, doc)
        if not any(doc.tree.has(reading) for reading in readings)
    ]
    for span in _CODE_SPAN.finditer(text):
        wrong.extend(
            f"names `make {target}`, which is not a target in the Makefile"
            for target in _MAKE.findall(span.group(2))
            if target not in doc.tree.targets
        )
    return wrong


def check(doc: Doc) -> list[Violation]:
    if not reads(str(doc.path)):
        return []
    found = []
    for index, text in _texts(doc):
        for message in _missing(text, doc):
            if not allowed_line(doc, index, RULE):
                found.append(violation(doc, RULE, message, line=index + 1))
    return found
