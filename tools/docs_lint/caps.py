"""Length caps: `claude-md`, `skill-doc` and `skill-code`.

A `CLAUDE.md` is loaded whole into every session under its folder, and a skill
whole into every session that uses it, so their length is a cost paid each
time. A script in a skill is not loaded but read when it breaks; the number of
files is not limited, so a long one splits into modules.
"""

from __future__ import annotations

from tools.docs_lint.core import CODE_SUFFIXES, Doc, Violation, allowed_file, violation

CLAUDE_MD_LIMIT = 300
SKILL_DOC_LIMIT = 500
SKILL_CODE_LIMIT = 400

_ADVICE = {
    "claude-md": (
        "keep what every session needs; move what one folder needs to that folder's "
        "CLAUDE.md and a procedure to a skill; delete what a gate already enforces"
    ),
    "skill-doc": "move a section into a reference file beside it, which SKILL.md names",
    "skill-code": "split it into modules; the number of files is not limited",
}


def _cap(doc: Doc) -> tuple[str, int] | None:
    """The cap rule that holds this file and its limit, if one does."""
    if doc.is_claude_md:
        return "claude-md", CLAUDE_MD_LIMIT
    if doc.skill is None:
        return None
    if doc.is_markdown:
        return "skill-doc", SKILL_DOC_LIMIT
    if doc.path.suffix in CODE_SUFFIXES:
        return "skill-code", SKILL_CODE_LIMIT
    return None


def check(doc: Doc) -> list[Violation]:
    cap = _cap(doc)
    if cap is None:
        return []
    rule, limit = cap
    count = len(doc.lines)
    if count <= limit or allowed_file(doc, rule):
        return []
    message = f"{count} lines, over the {limit}-line cap: {_ADVICE[rule]}"
    return [violation(doc, rule, message)]
