"""What every rule shares: the file being read, a violation, and the allow."""

from __future__ import annotations

import re
import tokenize
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import PurePosixPath

from tools.comments import comments as read_comments

SKILLS_DIR = (".claude", "skills")
DOCS_DIR = PurePosixPath("docs")
CODE_SUFFIXES = frozenset({".py", ".sh", ".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs"})
# The files whose comments open with `//` (`tools/comments.py`); any other
# code file but Python's takes `#`.
_SLASH_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"})

_HTML_COMMENT = re.compile(r"<!--((?:(?!-->).)*)-->")
# A fence opens with three or more backticks or tildes, indented at most three
# spaces, and closes with a run of the same character at least as long.
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")


def fenced_lines(lines: list[str]) -> frozenset[int]:
    """The 0-based indices of the lines in a fenced code block, fences included."""
    inside: set[int] = set()
    opener: str | None = None
    for index, line in enumerate(lines):
        match = _FENCE.fullmatch(line.rstrip())
        if opener is None:
            if match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
                opener = match.group(1)
                inside.add(index)
            continue
        inside.add(index)
        if match and match.group(1)[0] == opener[0] and len(match.group(1)) >= len(opener):
            if not match.group(2).strip():
                opener = None
    return frozenset(inside)


def _nothing_ignored(path: str) -> bool:
    return False


@dataclass(frozen=True)
class Tree:
    """What exists in the repository, for a rule that checks what a doc names."""

    # Every file git tracks or would track (untracked, not ignored), on disk.
    files: frozenset[str] = frozenset()
    # The root `Makefile`'s targets.
    targets: frozenset[str] = frozenset()
    # Whether git ignores a path (`.env`, `backend/.venv/`): made on a machine
    # and never committed, so it is named on purpose.
    ignored: Callable[[str], bool] = _nothing_ignored

    @cached_property
    def dirs(self) -> frozenset[str]:
        """Every directory holding one of the files."""
        return frozenset(str(d) for f in self.files for d in PurePosixPath(f).parents) - {"."}

    def has(self, path: str) -> bool:
        """Whether `path` (a file, or a directory when it ends in `/`) exists, or
        is ignored by git in a directory that does. An ignored directory may be
        named without its `/` (`backend/.venv`)."""
        bare = path.rstrip("/")
        if bare in self.dirs or (bare == path and bare in self.files):
            return True
        parent = str(PurePosixPath(bare).parent)
        placed = parent == "." or parent in self.dirs
        return placed and (self.ignored(path) or self.ignored(f"{bare}/"))


@dataclass(frozen=True)
class Doc:
    """One tracked file, as a rule reads it."""

    path: PurePosixPath
    text: str
    tree: Tree = field(default=Tree(), repr=False)

    @cached_property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    @cached_property
    def fenced(self) -> frozenset[int]:
        """Lines inside a code fence (Markdown only): an example, not the page's own."""
        return fenced_lines(self.lines) if self.is_markdown else frozenset()

    @property
    def is_markdown(self) -> bool:
        return self.path.suffix == ".md"

    @property
    def is_claude_md(self) -> bool:
        return self.path.name == "CLAUDE.md"

    @cached_property
    def _in_skills(self) -> tuple[str, ...] | None:
        """The parts of the path below a `.claude/skills/` folder, at any depth."""
        parts = self.path.parts
        for at in range(len(parts) - 2):
            if parts[at : at + 2] == SKILLS_DIR:
                return parts[at + 2 :]
        return None

    @property
    def in_skills(self) -> bool:
        return self._in_skills is not None

    @property
    def skill(self) -> str | None:
        """The skill folder this file is in (`.claude/skills/<name>/...`), if any."""
        below = self._in_skills
        return below[0] if below and len(below) > 1 else None

    @property
    def is_skill_entry(self) -> bool:
        """A skill's `SKILL.md`, the file Claude loads."""
        return (
            self._in_skills is not None
            and len(self._in_skills) == 2
            and self.path.name == "SKILL.md"
        )

    @cached_property
    def comments(self) -> dict[int, list[str]]:
        """The text of each comment, by 0-based line: one-line HTML comments in
        Markdown outside a fence, and the comments of a code file."""
        if self.is_markdown:
            found = {
                i: [m.group(1) for m in _HTML_COMMENT.finditer(line)]
                for i, line in enumerate(self.lines)
                if i not in self.fenced
            }
            return {i: texts for i, texts in found.items() if texts}
        suffix = self.path.suffix
        syntax = "python" if suffix == ".py" else "slash" if suffix in _SLASH_SUFFIXES else "hash"
        try:
            found = read_comments(syntax, self.text)
        except tokenize.TokenError, SyntaxError:
            found = read_comments("hash", self.text)  # not valid Python: read it by line
        return {line - 1: texts for line, texts in found.items()}


@dataclass(frozen=True)
class Violation:
    path: str
    line: int
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


def violation(doc: Doc, rule: str, message: str, line: int = 1) -> Violation:
    return Violation(str(doc.path), line, rule, message)


def grants(comment: str, rule: str) -> bool:
    """Whether a comment's text allows `rule` and gives a reason for it."""
    return re.search(rf"lint: allow\({re.escape(rule)}\)[\s:—-]*\w", comment) is not None


def _is_html_comment(doc: Doc, index: int) -> bool:
    """Whether line `index` is nothing but one HTML comment, outside a fence."""
    line = doc.lines[index].strip()
    return index not in doc.fenced and _HTML_COMMENT.fullmatch(line) is not None


def allowed_line(doc: Doc, index: int, rule: str) -> bool:
    """Whether line `index` (0-based) is excused from `rule`. In a Markdown
    page, an HTML comment on it allows it, or one in the unbroken run of
    one-line HTML comments directly above it does; an allow inside a fence
    excuses only its own line. In a code file, a comment on it or on the line
    directly above does."""
    if not doc.is_markdown:
        near = (*doc.comments.get(index - 1, []), *doc.comments.get(index, []))
        return any(grants(comment, rule) for comment in near)
    on_line = (m.group(1) for m in _HTML_COMMENT.finditer(doc.lines[index]))
    if any(grants(comment, rule) for comment in on_line):
        return True
    above = index - 1
    while above >= 0 and _is_html_comment(doc, above):
        if any(grants(comment, rule) for comment in doc.comments.get(above, [])):
            return True
        above -= 1
    return False


def allowed_file(doc: Doc, rule: str) -> bool:
    """Whether a whole-file rule is excused: a comment anywhere in the file
    allows it (in Markdown, an HTML comment outside a code fence)."""
    return any(grants(text, rule) for texts in doc.comments.values() for text in texts)
