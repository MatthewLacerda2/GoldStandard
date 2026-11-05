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
  its `## ` help text among them). A test's made-up fixture lives in a string,
  so it is never read.
- **What is a path** (`named_in`): a token that starts with one of the `ROOTS`
  and ends in a file extension or a `/`. What wraps it is trimmed, again and
  again until nothing more comes off: Markdown's emphasis and brackets
  (`**docs/a.md**`, `<docs/a.md>`), a sentence's closing `.`, `...` or `…`,
  and a `?query`. A `:12` or `::symbol` after it is not part of it. A token
  still holding a template or glob character (`<name>`, `*`, `{a,b}`, `…`,
  `$`, `~`, `%`) or a `..` names no one file and is skipped, and an absolute
  path starts with no root.
- **Inside a layer** (`LAYERS`): in a file under `backend/` or `frontend/`, a
  token is also read from the folders that layer's own docs and comments write
  paths from (`backend/`; `frontend/src/` and `frontend/`), when it starts
  with one of their folders (`tools/house_lint.py`, `lib/api/client.ts`). It
  passes if any reading exists.
- **What exists** (`core.Tree`): a file git tracks or would track (so a new
  file counts before `git add`, and a deleted one does not), a directory
  holding one, or a path git ignores whose directory exists (`.env`,
  `backend/.venv/`): made on a machine, never committed, so named on purpose.
- **A `make` target** is read in a code span (`` `make docs-lint` ``), where
  `make` is the command and not the verb, and on a line of a code fence that
  starts with `make` (paths in a fence stay unread: a fence holds examples).
  Each target the command names, past its flags and `VAR=value`s, must be a
  target of the root `Makefile`.

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
# own. The list is fixed, not read from the tree, so the names into a folder
# that is deleted still fail.
ROOTS = frozenset(
    {"backend", "frontend", "tools", "docs", "docker", ".github", ".claude", ".githooks"}
)

# For a file under each layer, the folders its paths may be written from, and
# the folders there a path may start with. Fixed for the same reason as ROOTS;
# a folder added later is read too, while it exists.
LAYERS = {
    "backend": {
        "backend": frozenset(
            {"api", "core", "models", "repositories", "schemas", "services", "tests"}
            | {"tools", "utils"}
        ),
    },
    "frontend": {
        "frontend/src": frozenset({"components", "i18n", "lib", "routes"}),
        "frontend": frozenset({"eslint-rules", "scripts", "src"}),
    },
}

CODE_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".sh"})
MARKDOWN_NAMES = frozenset({"CLAUDE.md", "README.md"})

# A token: what a path is made of, and the template and glob characters that
# mark one as a pattern rather than a path.
_TEMPLATE = frozenset("*?{}<>$…~%\\")
_TOKEN = re.compile(r"[\w./\-*?{}<>$…~%\\]+")
_WRAPPING = "*_?<>"
_QUERY = re.compile(r"\?[\w=]*$")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
# `make` as a command: what follows it up to the end of the command.
_MAKE = re.compile(r"(?<![\w./-])make((?:[ \t]+[^\s;&|()`#]+)*)")
_FENCED_MAKE = re.compile(r"\s*(?:\$\s+)?make\b")
_TARGET = re.compile(r"[a-z][\w.-]*")
# The flags of `make` that take the next word as their argument (`make -C dir`).
_FLAG_ARGUMENTS = frozenset({"-C", "-f", "-I", "-o", "-W", "--directory", "--file"})
# A `Makefile` rule's targets: names before a `:` or `::` that does not go on
# into an assignment (`:=`, `::=`, `:::=`).
_RULE_LINE = re.compile(r"^([\w./-]+(?:[ \t]+[\w./-]+)*)[ \t]*::?(?![:=])", re.MULTILINE)


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
    """The text the rule reads for paths in `doc`, as `(0-based line, text)`."""
    if doc.is_markdown:
        return [(i, line) for i, line in enumerate(doc.lines) if i not in doc.fenced]
    return [(i, text) for i, texts in sorted(doc.comments.items()) for text in texts]


def _trimmed(token: str) -> str:
    """`token` without what wraps it, trimmed until nothing more comes off."""
    while True:
        trimmed = _QUERY.sub("", token.strip(_WRAPPING).rstrip(".…"))
        if trimmed == token:
            return token.removeprefix("./")
        token = trimmed


def _path_of(token: str) -> str | None:
    """The path `token` names, as written, or None when it is not shaped like one."""
    token = _trimmed(token)
    if _TEMPLATE.intersection(token) or ".." in token:
        return None
    last = token.rsplit("/", 1)[-1]
    extension = last.rpartition(".")[2] if "." in last else ""
    if "/" not in token or not (token.endswith("/") or extension.isalnum()):
        return None
    return token


def _readings(path: str, doc: Doc) -> list[str]:
    """Where `path`, named in `doc`, may point, read from the root: from the
    root when it starts with a root, and from each folder of `doc`'s layer
    where it starts with a folder there."""
    first = path.split("/", 1)[0]
    found = [path] if first in ROOTS else []
    for base, folders in LAYERS.get(doc.path.parts[0], {}).items():
        if first in folders or f"{base}/{first}" in doc.tree.dirs:
            found.append(f"{base}/{path}")
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


def targets_in(command: str) -> list[str]:
    """The targets each `make` command in `command` names."""
    found = []
    for call in _MAKE.finditer(command):
        words = iter(call.group(1).split())
        for word in words:
            if word in _FLAG_ARGUMENTS:
                next(words, None)
            elif word.startswith("-") or "=" in word or word.isdigit():
                continue  # a flag, a variable, a job count
            elif _TARGET.fullmatch(word):
                found.append(word)
            else:
                break  # a placeholder or prose: the command's words end here
    return found


def _make_texts(doc: Doc) -> list[tuple[int, str]]:
    """The commands the rule reads for `make` targets: each code span in what
    it reads for paths, and each line of a Markdown fence that runs `make`."""
    spans = [
        (index, span.group(2)) for index, text in _texts(doc) for span in _CODE_SPAN.finditer(text)
    ]
    fenced = [
        (index, doc.lines[index])
        for index in sorted(doc.fenced)
        if _FENCED_MAKE.match(doc.lines[index])
    ]
    return spans + fenced


def _missing(doc: Doc) -> list[tuple[int, str]]:
    """What `doc` names that does not exist: `(0-based line, message)`."""
    wrong = [
        (
            index,
            f"names `{path}`, which does not exist: point it at where that is now, or "
            "remove it (or allow it, saying why it is named on purpose)",
        )
        for index, text in _texts(doc)
        for path, readings in named_in(text, doc)
        if not any(doc.tree.has(reading) for reading in readings)
    ]
    wrong += [
        (index, f"names `make {target}`, which is not a target in the Makefile")
        for index, command in _make_texts(doc)
        for target in targets_in(command)
        if target not in doc.tree.targets
    ]
    return wrong


def check(doc: Doc) -> list[Violation]:
    if not reads(str(doc.path)):
        return []
    return [
        violation(doc, RULE, message, line=index + 1)
        for index, message in _missing(doc)
        if not allowed_line(doc, index, RULE)
    ]
