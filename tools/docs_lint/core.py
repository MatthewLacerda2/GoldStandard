"""What every rule shares: the file being read, a violation, and the allow."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

SKILLS_DIR = PurePosixPath(".claude/skills")
DOCS_DIR = PurePosixPath("docs")
CODE_SUFFIXES = frozenset({".py", ".sh", ".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs"})

# One-line HTML comments, and the comment openers of the code a skill can hold.
_HTML_COMMENT = re.compile(r"<!--(.*?)-->")
_CODE_COMMENT = ("#", "//", "/*", "*")


@dataclass(frozen=True)
class Doc:
    """One tracked file, as a rule reads it."""

    path: PurePosixPath
    text: str
    # Every tracked path, for a rule that checks what a doc names.
    tracked: frozenset[str] = field(default=frozenset(), repr=False)

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    @property
    def is_markdown(self) -> bool:
        return self.path.suffix == ".md"

    @property
    def is_claude_md(self) -> bool:
        return self.path.name == "CLAUDE.md"

    @property
    def skill(self) -> str | None:
        """The skill folder this file is in (`.claude/skills/<name>/...`), if any."""
        if not self.path.is_relative_to(SKILLS_DIR):
            return None
        parts = self.path.relative_to(SKILLS_DIR).parts
        return parts[0] if len(parts) > 1 else None

    @property
    def is_skill_entry(self) -> bool:
        """A skill's `SKILL.md`, the file Claude loads."""
        return self.skill is not None and self.path == SKILLS_DIR / self.skill / "SKILL.md"


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


def _is_html_comment(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("<!--") and stripped.endswith("-->")


def allowed_line(doc: Doc, index: int, rule: str) -> bool:
    """Whether line `index` (0-based) is excused from `rule`: an allow comment is
    on it, or in the unbroken run of one-line HTML comments directly above."""
    lines = doc.lines
    if any(grants(m.group(1), rule) for m in _HTML_COMMENT.finditer(lines[index])):
        return True
    for above in reversed(lines[:index]):
        if not _is_html_comment(above):
            return False
        if grants(above, rule):
            return True
    return False


def allowed_file(doc: Doc, rule: str) -> bool:
    """Whether a whole-file rule is excused: an allow comment anywhere in it."""
    for line in doc.lines:
        if _is_html_comment(line) and grants(line, rule):
            return True
        if not doc.is_markdown and line.lstrip().startswith(_CODE_COMMENT):
            if grants(line, rule):
                return True
    return False
