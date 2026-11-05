"""`skill-frontmatter`: a skill's `SKILL.md` carries what it needs to load.

`SKILL.md` opens with a `---` block holding a `name` and a `description`. A
skill outside the limits below does not load, or loads unmatched, and nothing
says so at the time; this says so at the gate. The limits are the portable
ones, so a skill made here also loads when uploaded to claude.ai or the API:

- Agent Skills specification: https://agentskills.io/specification
  (`name`: 1-64 characters, lower-case letters, digits and single hyphens, not
  at either end, equal to its folder's name; `description`: 1-1024 characters)
- Anthropic's Agent Skills overview, "Skill structure":
  https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
  (neither field holds an XML tag; `name` holds neither `anthropic` nor
  `claude`)
- Claude Code's own skill docs: https://code.claude.com/docs/en/skills (looser:
  it truncates a listing's description past 1,536 characters)

The frontmatter is read without a YAML library (the standard library has
none), so this is not a YAML parser: it reads the shapes a skill's frontmatter
takes. A top-level `key: value`, its value going on over any indented lines
that follow (folded with spaces); a plain value ends at a ` #` comment, and a
quoted one is what its quotes hold. A `|` or `>` block scalar (with an optional
`-` or `+`). Any other shape (a nested mapping, a list) is skipped. One mistake
YAML rejects is caught, since it leaves the skill with no metadata: a plain
value holding `: `, which must be quoted.
"""

from __future__ import annotations

import re

from tools.docs_lint.core import Doc, Violation, violation

RULE = "skill-frontmatter"
NAME_LIMIT = 64
DESCRIPTION_LIMIT = 1024
RESERVED_WORDS = ("anthropic", "claude")

_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_XML_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
_KEY_LINE = re.compile(r"([A-Za-z0-9_-]+):(?:\s+(.*))?")
_BLOCK_SCALARS = frozenset({"|", ">", "|-", ">-", "|+", ">+"})


def _plain(value: str) -> tuple[str, str | None]:
    """A one-line or folded value as YAML reads it, and what YAML would reject
    in it, if anything."""
    if value[:1] in "\"'":
        close = value.find(value[0], 1)
        return (value[1:close], None) if close > 0 else (value[1:], "an unclosed quote")
    value = re.split(r"\s#", value, maxsplit=1)[0].strip()
    if ": " in value or value.endswith(":"):
        return value, "a `: ` in an unquoted value, which YAML rejects: quote the value"
    return value, None


def fields(text: str) -> tuple[dict[str, str], list[str]] | None:
    """The frontmatter's top-level scalar keys and the mistakes found reading
    them, or `None` when the text does not open with a closed `---` block."""
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != "---":
        return None
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip() == "---"), None)
    if end is None:
        return None
    found: dict[str, str] = {}
    mistakes: list[str] = []
    at = 1
    while at < end:
        match = _KEY_LINE.fullmatch(lines[at].rstrip())
        at += 1
        if not match:
            continue
        key, first = match.group(1), (match.group(2) or "").strip()
        start = at
        while at < end and (not lines[at].strip() or lines[at][:1].isspace()):
            at += 1
        more = [line.strip() for line in lines[start:at]]
        if first in _BLOCK_SCALARS:
            joiner = "\n" if first[0] == "|" else " "
            found[key] = joiner.join(line for line in more if line).strip()
            continue
        if not first and more and more[0] and (_KEY_LINE.fullmatch(more[0]) or more[0][0] == "-"):
            continue  # a nested mapping or a list
        value, mistake = _plain(" ".join(part for part in [first, *more] if part))
        found[key] = value
        if mistake:
            mistakes.append(f"`{key}` has {mistake}")
    return found, mistakes


def _name_problems(name: str, folder: str) -> list[str]:
    if not name:
        return [f"no `name`: add `name: {folder}`"]
    wrong = []
    if len(name) > NAME_LIMIT:
        wrong.append(f"a `name` of {len(name)} characters, over {NAME_LIMIT}")
    if not _NAME.fullmatch(name):
        wrong.append(
            f"`name: {name}` may hold only lower-case letters, digits and single hyphens, "
            "with no hyphen at either end"
        )
    if name != folder:
        wrong.append(f"`name: {name}` differs from its folder, `{folder}`: rename one")
    wrong.extend(f"`name` holds the reserved word `{w}`" for w in RESERVED_WORDS if w in name)
    return wrong


def _description_problems(description: str) -> list[str]:
    if not description:
        return ["no `description`: say what the skill does and when to use it"]
    wrong = []
    if len(description) > DESCRIPTION_LIMIT:
        wrong.append(
            f"a `description` of {len(description)} characters, over {DESCRIPTION_LIMIT}: "
            "say when to use the skill and leave how to the body"
        )
    if _XML_TAG.search(description):
        wrong.append("the `description` holds an XML tag: write `[name]` for a placeholder")
    return wrong


def check(doc: Doc) -> list[Violation]:
    folder = doc.skill
    if folder is None or not doc.is_skill_entry:
        return []
    if doc.text.startswith("\ufeff"):
        return [violation(doc, RULE, "opens with a byte-order mark: save it without one")]
    read = fields(doc.text)
    if read is None:
        message = "no frontmatter: open with a `---` block holding `name` and `description`"
        return [violation(doc, RULE, message)]
    found, problems = read
    problems += _name_problems(found.get("name", ""), folder)
    problems += _description_problems(found.get("description", ""))
    return [violation(doc, RULE, problem) for problem in problems]
