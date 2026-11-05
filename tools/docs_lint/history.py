"""`history`: a `CLAUDE.md` or a skill states the rule, never its history.

These pages are loaded into every session that reads them, so a story, a date
or an issue number there is paid for by every reader and used by none: the
rule is what an agent acts on, and the issue and pull request that made it are
where its reasons are kept. Three shapes are found, in code spans and fences
too:

- an issue or pull-request reference, `#123` or `owner/repo#123`;
- a GitHub link to one, `.../issues/123` or `.../pull/123`;
- a date, `2026-01-31`.

Not a reference: a colour such as `#33ccff` (its digits run into letters), an
HTML entity (`&#123;`), an anchor in a link target (`[see](#2-install)`, an
anchor's slug going on with a hyphen), and a `#` glued to a word that is not an
`owner/repo` (`C#12`, `page.html#3`). A colour of digits only, or a ranking
(`the #1 rule`), cannot be told from a reference, and takes an allow.
"""

from __future__ import annotations

import re

from tools.docs_lint.core import Doc, Violation, allowed_line, violation

RULE = "history"

# A Markdown link's target, `](...)`: what it points at is checked by the link
# shape, and an anchor in it is not a reference.
_LINK_TARGET = re.compile(r"\]\([^)]*\)")
# `#123` after the start of the line, a space or punctuation that can open a
# reference; or `owner/repo#123`. The number ends the word, and does not go on
# into an anchor's slug (`#2-install`).
_REFERENCE = re.compile(
    r"(?:(?<![^\s(\[{`\"'*_,;:])|[\w.-]+/[\w.-]+)#\d+(?![\w-])",
    re.ASCII,
)
_LINK = re.compile(r"/(?:issues|pull)/\d+")
_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")


def cites(line: str) -> str | None:
    """What, if anything, on `line` cites history: the message for it."""
    if _REFERENCE.search(_LINK_TARGET.sub("]()", line)):
        return "an issue or pull-request number: state the rule; its issue keeps why"
    if _LINK.search(line):
        return "a link to an issue or pull request: state the rule; its issue keeps why"
    if _DATE.search(line):
        return "a date: state the rule as it stands now"
    return None


def check(doc: Doc) -> list[Violation]:
    if not doc.is_markdown or not (doc.is_claude_md or doc.in_skills):
        return []
    found = []
    for index, line in enumerate(doc.lines):
        message = cites(line)
        if message and not allowed_line(doc, index, RULE):
            found.append(violation(doc, RULE, message, line=index + 1))
    return found
