"""`reference-toc`: a long reference page says what it holds near its top.

A reference page (a `.md` in a skill folder other than `SKILL.md`, or one under
`docs/`) is opened when a task needs part of it. A `Contents` heading near the
top lets a reader that previews the file see its scope and jump, instead of
reading it whole.
"""

from __future__ import annotations

import re

from tools.docs_lint.core import DOCS_DIR, Doc, Violation, allowed_file, violation

RULE = "reference-toc"
MIN_LINES = 100  # a page this long or shorter is read whole anyway
WINDOW = 20  # how near the top the heading must be
TITLES = frozenset({"contents", "table of contents"})

_HEADING = re.compile(r" {0,3}#{1,6}\s+(.*?)(?:\s+#+)?\s*")
_FENCES = ("```", "~~~")


def is_reference(doc: Doc) -> bool:
    if not doc.is_markdown:
        return False
    if doc.skill is not None:
        return not doc.is_skill_entry
    return doc.path.is_relative_to(DOCS_DIR)


def has_toc(lines: list[str]) -> bool:
    """A `Contents` or `Table of contents` heading in the first `WINDOW` lines,
    outside a code fence."""
    fenced = False
    for line in lines[:WINDOW]:
        if line.lstrip().startswith(_FENCES):
            fenced = not fenced
            continue
        match = None if fenced else _HEADING.fullmatch(line)
        if match and match.group(1).strip().lower() in TITLES:
            return True
    return False


def check(doc: Doc) -> list[Violation]:
    if not is_reference(doc):
        return []
    lines = doc.lines
    if len(lines) <= MIN_LINES or has_toc(lines) or allowed_file(doc, RULE):
        return []
    message = (
        f"{len(lines)} lines with no `Contents` heading in its first {WINDOW}: "
        "add one that lists its sections"
    )
    return [violation(doc, RULE, message)]
