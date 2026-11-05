"""`history`: a `CLAUDE.md` or a skill states the rule, never its history.

These pages are loaded into every session that reads them, so a story, a date
or an issue number there is paid for by every reader and used by none: the
rule is what an agent acts on, and the issue and pull request that made it are
where its reasons are kept. Three shapes are found, in code spans too:

- an issue or pull-request reference, `#123` or `owner/repo#123`;
- a GitHub link to one, `.../issues/123` or `.../pull/123`;
- a date, `2026-01-31`.

A colour such as `#33ccff` is not a reference (its digits run into letters),
and neither is an HTML entity (`&#123;`). A colour of digits only cannot be
told from one, and takes an allow.
"""

from __future__ import annotations

import re

from tools.docs_lint.core import Doc, Violation, allowed_line, violation

RULE = "history"

_SHAPES = (
    (
        re.compile(r"(?<!&)#\d+(?!\w)", re.ASCII),
        "an issue or pull-request number: state the rule; its issue keeps why",
    ),
    (
        re.compile(r"/(?:issues|pull)/\d+"),
        "a link to an issue or pull request: state the rule; its issue keeps why",
    ),
    (
        re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)"),
        "a date: state the rule as it stands now",
    ),
)


def cites(line: str) -> str | None:
    """What, if anything, on `line` cites history: the message for it."""
    return next((message for shape, message in _SHAPES if shape.search(line)), None)


def check(doc: Doc) -> list[Violation]:
    if not doc.is_markdown or not (doc.is_claude_md or doc.skill is not None):
        return []
    found = []
    for index, line in enumerate(doc.lines):
        message = cites(line)
        if message and not allowed_line(doc, index, RULE):
            found.append(violation(doc, RULE, message, line=index + 1))
    return found
