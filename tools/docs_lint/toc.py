"""`reference-toc`: a long reference page says what it holds near its top.

A reference page (a `.md` under a `.claude/skills/` folder other than a
`SKILL.md`, or one under `docs/`) is opened when a task needs part of it. A
`Contents` heading near the top lets a reader that previews the file see its
scope and jump, instead of reading it whole.
"""

from __future__ import annotations

import re

from tools.docs_lint.core import DOCS_DIR, Doc, Violation, allowed_file, violation

RULE = "reference-toc"
MIN_LINES = 100  # a page this long or shorter is read whole anyway
WINDOW = 20  # how near the top the heading must be
TITLES = frozenset({"contents", "table of contents"})

_ATX = re.compile(r" {0,3}#{1,6}\s+(.*?)(?:\s+#+)?\s*")
_SETEXT_UNDERLINE = re.compile(r" {0,3}(?:=+|-+)\s*")


def is_reference(doc: Doc) -> bool:
    if not doc.is_markdown:
        return False
    if doc.in_skills:
        return not doc.is_skill_entry
    return doc.path.is_relative_to(DOCS_DIR)


def _is_title(text: str) -> bool:
    return text.strip().rstrip(":").strip().lower() in TITLES


def has_toc(doc: Doc) -> bool:
    """A `Contents` or `Table of contents` heading (`#` style, or text over a
    `===` / `---` underline) in the first `WINDOW` lines, outside a code fence."""
    lines = doc.lines[:WINDOW]
    for index, line in enumerate(lines):
        if index in doc.fenced:
            continue
        atx = _ATX.fullmatch(line)
        if atx and _is_title(atx.group(1)):
            return True
        underline = index + 1 < len(lines) and _SETEXT_UNDERLINE.fullmatch(lines[index + 1])
        if underline and index + 1 not in doc.fenced and _is_title(line):
            return True
    return False


def check(doc: Doc) -> list[Violation]:
    if not is_reference(doc):
        return []
    count = len(doc.lines)
    if count <= MIN_LINES or has_toc(doc) or allowed_file(doc, RULE):
        return []
    message = (
        f"{count} lines with no `Contents` heading in its first {WINDOW}: "
        "add one that lists its sections"
    )
    return [violation(doc, RULE, message)]
