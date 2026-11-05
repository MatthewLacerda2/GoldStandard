"""Read this repository's Claude Code transcripts into API calls, each counted once.

Claude Code keeps one folder per working directory under
``~/.claude/projects/``, named after the directory's absolute path with every
character that is not a letter or a digit turned into ``-``. A worktree under
``.claude/worktrees/<name>`` is a working directory of its own, so it gets a
folder of its own: ``<repo folder>--claude-worktrees-<name>``. That folder
outlives the worktree, so a merged branch's transcripts are still read.

Inside a folder, ``<session>.jsonl`` is a main session and
``<session>/subagents/agent-<id>.jsonl`` is one subagent it started, beside an
``agent-<id>.meta.json`` holding the description it was started with (and, for
an agent another agent started, that parent's id).

How it counts:

- **One API call, once.** Claude Code writes one line per content block
  (thinking, text, tool use) of a response, each carrying the same ``usage``,
  so summing lines nearly doubles the totals. Calls are deduplicated by
  ``message.id`` across every file (a forked agent's transcript repeats its
  parent's calls), main sessions read first so a repeated call stays the
  parent's. A call's output is the largest any of its lines reports: the first
  lines are written mid-stream.
- **Context per call** = ``input_tokens + cache_creation_input_tokens +
  cache_read_input_tokens``: everything the model read on that call. Output is
  counted apart.
- **Role** is a subagent's agent type (``Explore``, ``Plan``) when it has one
  other than the general-purpose default: that type says what the agent is,
  whatever its prompt mentions. Otherwise it comes from the opening: its first
  message and, when that message only names a brief file (``….md``), the first
  tool result after it, which is the brief it read. ``ROLES`` runs in order and
  the first match wins. A main session has no role.
- **The window** is by each call's own timestamp (UTC), from ``since`` on.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

# (role, pattern) in order: the first that matches the opening wins. The
# reviewer rules are anchored to the opening's first words because a coder's
# brief talks about the independent review it will get.
ROLES: list[tuple[str, re.Pattern[str]]] = [
    # The `independent-review` prompt, and the agents the `code-review` skill starts.
    ("reviewer", re.compile(r"\A(?:Review PR #|Review target:|Review the latest changes)")),
    ("coder", re.compile(r"\bcoder\b|^You are (?:resolving|implementing|fixing)\b", re.I | re.M)),
    ("reviewer", re.compile(r"\bcode-review\b")),
]
GENERIC_AGENT_TYPES = {"", "general-purpose", "fork"}
BRIEF_FILE = re.compile(r"[\w./-]+\.md\b")
REF = re.compile(r"#(\d+)")
# A first message longer than this is a brief in itself, not a pointer to one.
POINTER_MAX = 400
REMINDER = "<system-reminder>"


@dataclass
class Call:
    """One API call: who made it, on which model, and what it read and wrote."""

    scope: str  # "main" or "subagent"
    role: str
    model: str
    context: int
    output: int
    refs: tuple[int, ...]  # the issue / PR numbers its agent was started for
    branch: str  # the git branch of the directory it ran in
    time: str  # when it was made, ISO 8601 UTC


class Usage(NamedTuple):
    """One call as a transcript records it, before it is tied to its agent."""

    model: str
    context: int
    output: int
    branch: str
    time: str


@dataclass
class Transcript:
    scope: str
    agent_id: str = ""
    opening: list[str] = field(default_factory=list)
    # message.id -> its usage, in the order first seen.
    calls: dict[str, Usage] = field(default_factory=dict)


def project_folders(projects: Path, repo: Path) -> list[Path]:
    """The transcript folders of the checkout at `repo` and of its worktrees."""
    name = re.sub(r"[^A-Za-z0-9]", "-", str(repo))
    return sorted(
        d
        for d in projects.glob(f"{name}*")
        if d.is_dir() and (d.name == name or d.name.startswith(f"{name}--claude-worktrees-"))
    )


def transcript_files(folders: Iterable[Path], since: str) -> list[Path]:
    """Every transcript that may hold a call in the window, main sessions first."""
    floor = datetime.fromisoformat(since).replace(tzinfo=UTC).timestamp()
    files = [p for d in folders for p in sorted(d.rglob("*.jsonl")) if p.stat().st_mtime >= floor]
    return sorted(files, key=lambda p: p.parent.name == "subagents")


def role_of(opening: str, agent_type: str = "") -> str:
    if agent_type not in GENERIC_AGENT_TYPES:
        return agent_type.lower()
    for role, pattern in ROLES:
        if pattern.search(opening):
            return role
    return "other"


def _text(content: object) -> str:
    """The readable text of a message's content: plain text and tool results."""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif block.get("type") == "tool_result":
            parts.append(_text(block.get("content") or ""))
    return "\n".join(parts)


def _lines(path: Path) -> Iterator[dict]:
    # `replace`: a session still writing can stop mid-character.
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:  # a session still writing its last line
                continue
            if isinstance(entry, dict):
                yield entry


def _wants_brief(opening: list[str]) -> bool:
    """Still reading the opening: the first message only named a brief file,
    whose content (the next user message) is not in yet."""
    return (
        len(opening) == 1 and bool(BRIEF_FILE.search(opening[0])) and len(opening[0]) <= POINTER_MAX
    )


def read_transcript(path: Path, since: str) -> Transcript:
    is_agent = path.parent.name == "subagents"
    agent_id = path.stem.removeprefix("agent-") if is_agent else ""
    t = Transcript("subagent" if is_agent else "main", agent_id)
    for entry in _lines(path):
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        kind = entry.get("type")
        if kind == "user" and (not t.opening or _wants_brief(t.opening)):
            # Meta messages count: the `code-review` skill's agents get their
            # prompt as one. A system reminder is no opening.
            text = _text(message.get("content")).strip()
            if text and not text.startswith(REMINDER):
                t.opening.append(text)
        if kind != "assistant" or str(entry.get("timestamp", "")) < since:
            continue
        usage, model = message.get("usage"), message.get("model")
        if not isinstance(usage, dict) or not model or model == "<synthetic>":
            continue  # no API call behind it
        context = sum(
            int(usage.get(k) or 0)
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        output = int(usage.get("output_tokens") or 0)
        key = str(message.get("id") or entry.get("uuid"))
        seen = t.calls[key].output if key in t.calls else 0
        branch = str(entry.get("gitBranch") or "")
        time = str(entry.get("timestamp"))
        t.calls[key] = Usage(str(model), context, max(seen, output), branch, time)
    return t


def read_meta(path: Path) -> dict:
    """The `.meta.json` beside a subagent transcript, or nothing."""
    try:
        meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _refs(agent_id: str, metas: dict[str, dict]) -> tuple[int, ...]:
    """The `#N` its description names, or else the nearest ancestor's."""
    seen: set[str] = set()
    while agent_id in metas and agent_id not in seen:
        seen.add(agent_id)
        meta = metas[agent_id]
        refs = tuple(int(n) for n in REF.findall(str(meta.get("description") or "")))
        if refs:
            return refs
        agent_id = str(meta.get("parentAgentId") or "")
    return ()


def collect(files: Iterable[Path], since: str) -> list[Call]:
    """Each API call once: the first file that holds an id owns it, and its
    output is the largest any file reports for it."""
    files = list(files)
    metas = {
        p.stem.removeprefix("agent-"): read_meta(p) for p in files if p.parent.name == "subagents"
    }
    owned: dict[str, Call] = {}
    for path in files:
        t = read_transcript(path, since)
        meta = metas.get(t.agent_id, {})
        role = "-"
        if t.scope == "subagent":
            role = role_of("\n".join(t.opening), str(meta.get("agentType") or ""))
        refs = _refs(t.agent_id, metas)
        for key, u in t.calls.items():
            if key in owned:
                owned[key].output = max(owned[key].output, u.output)
            else:
                owned[key] = Call(
                    t.scope, role, u.model, u.context, u.output, refs, u.branch, u.time
                )
    return list(owned.values())
