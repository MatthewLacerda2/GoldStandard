"""Every human check left unrun on a pull request merged since a moment, in one list.

A check only a person can do (the page in a real browser, how it looks) never
keeps a pull request a draft: it goes in the description as a checklist under
`## For a human`, and the pull request merges. That keeps merging fast and
scatters the checks across every description that merged. This gathers them,
as Markdown ready to paste into a report: a heading per pull request with its
unticked items, then a one-line total.

Only two things in a description are read:

- **The human-check sections**, found by their heading at any level and in any
  case: `For a human` and the close spellings in `HUMAN_HEADING`, with bold,
  code marks or a leading emoji ignored. A section is its heading and
  everything under it, sub-headings included, up to the next heading at its
  level or above. A checklist under any other heading (a test plan, a gate
  list) is somebody else's and is left out, but counted in a footer, so a
  human check under a spelling this does not know is never silently lost.
- **Unticked items** (`- [ ]` or `1. [ ]`) inside them. A ticked one is done,
  which is why nothing here keeps state: an item ticked on GitHub drops out of
  the next run. Code fences and HTML comments are examples, not checks.

After the list come the open issues carrying both stage labels, `planning` and
`human`. `CLAUDE.md` allows at most one, and which stays is the user's call, so
the report puts it to them as a question.

**REST only.** `gh pr`, `gh issue` and the search API go through GraphQL or a
global index, which cloud sessions are refused, and a cloud session is exactly
who writes a batch report. `repos/{owner}/{repo}/pulls` is answered everywhere.
It lists by last update, newest first, and a pull request merged at or after
SINCE was updated at or after it too, so paging stops at the first one updated
before SINCE.

    make checks SINCE=2026-01-31T18:00:00Z
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime

# A Markdown ATX heading: its level, and its text without a closing run of `#`.
HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$")

# A setext heading's underline: `===` makes the line above a level 1, `---` a 2.
SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")

# The heading texts that open a human-check section, matched at the start of
# the text in any case, so "Human checks (not a merge hold)" is in. The
# canonical one is `For a human`; the rest are spellings it drifts into.
HUMAN_HEADING = re.compile(
    r"^((for|left for|needs?) ((a|the) )?humans?\b|humans? check)", re.IGNORECASE
)

# What a heading's text is stripped of before it is matched: inline marks, and
# anything before its first word (an emoji, a bullet).
DECORATION = re.compile(r"[*_`~]|^\W+")

# An item that only says there is nothing to check, which is not a check. It
# matches the whole item, so "Nothing overlaps on a phone" is still a check.
PLACEHOLDER = re.compile(
    r"^(none|n/a|nothing((\s+(else|here|to check|for a (person|human)"
    r"|needs (a )?(person|human)( check)?))*))[\s.!]*$",
    re.IGNORECASE,
)

# An unticked task-list item, bulleted or numbered, and its text.
UNTICKED = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+\[ \]\s+(.*\S)\s*$")

# Any list item, ticked or not: what ends the continuation of the one before.
LIST_ITEM = re.compile(r"^\s*([-*+]|\d{1,9}[.)])(\s|$)")

# A code fence's opening run and its info string, and the run that closes it.
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
FENCE_END = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")

# The owner and repository at the end of a remote URL, https or ssh.
REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")

# How many results one page asks for: the API's maximum.
PAGE = 100

Api = Callable[[str], list[dict]]


class NoAnswer(Exception):
    """`gh` or `git` could not answer, so any list would be a lie by omission."""


def _lines(body: str | None) -> list[str]:
    """`body`'s lines outside code fences and HTML comments, setext headings as ATX.

    A skipped block leaves one blank line behind, so nothing joins across it.
    """
    kept: list[str] = []
    fence = ""  # the run that opened the fence we are inside, if any
    comment = False
    for line in (body or "").splitlines():
        if fence:
            end = FENCE_END.match(line)
            if end and end.group(1)[0] == fence[0] and len(end.group(1)) >= len(fence):
                fence = ""
        elif comment:
            comment = "-->" not in line
        elif (opened := FENCE.match(line)) and not (
            opened.group(1)[0] == "`" and "`" in opened.group(2)
        ):
            fence = opened.group(1)
            kept.append("")
        elif line.lstrip().startswith("<!--"):
            comment = "-->" not in line.split("<!--", 1)[1]
            kept.append("")
        elif SETEXT.match(line) and kept and _paragraph(kept[-1]):
            kept[-1] = f"{'#' if '=' in line else '##'} {kept[-1].strip()}"
        else:
            kept.append(line)
    return kept


def _paragraph(line: str) -> bool:
    """Whether `line` is plain text a setext underline would make a heading."""
    return bool(line.strip()) and not (
        HEADING.match(line) or LIST_ITEM.match(line) or line.startswith("    ")
    )


def _scan(body: str | None) -> tuple[list[str], int]:
    """The unticked items inside `body`'s human sections, and how many sit outside."""
    items: list[str] = []
    outside = 0
    inside: int | None = None  # the level of the open human section, if any
    current: tuple[int, list[str]] | None = None  # indent and text of the open item

    def close() -> None:
        nonlocal current
        if current is not None:
            text = " ".join(current[1])
            if not PLACEHOLDER.match(text):
                items.append(text)
            current = None

    for line in _lines(body):
        if heading := HEADING.match(line):
            close()
            level = len(heading.group(1))
            if inside is not None and level <= inside:
                inside = None
            if inside is None and HUMAN_HEADING.match(DECORATION.sub("", heading.group(2))):
                inside = level
            continue
        unticked = UNTICKED.match(line)
        if inside is None:
            outside += bool(unticked)
        elif unticked:
            close()
            current = (len(unticked.group(1)), [unticked.group(3)])
        elif current is not None and _continues(line, current[0]):
            current[1].append(line.strip())
        elif line.strip():
            close()
    close()
    return items, outside


def _continues(line: str, indent: int) -> bool:
    """Whether `line` carries on the item opened at `indent`; a blank line may sit between."""
    deeper = len(line) - len(line.lstrip()) > indent
    return bool(line.strip()) and not LIST_ITEM.match(line) and deeper


def human_checks(body: str | None) -> list[str]:
    """The unticked items in `body`'s human-check sections, one string each.

    An item wrapping onto indented lines below it is joined into one line, so
    each check reads whole. A nested item stays an item of its own.
    """
    return _scan(body)[0]


def unclaimed(body: str | None) -> int:
    """How many unticked items in `body` sit under no human-check heading."""
    return _scan(body)[1]


def moment(text: str) -> datetime:
    """An ISO 8601 date or time as an aware UTC datetime.

    A bare date is its midnight in UTC, and a time with no offset is read as
    UTC, which is what GitHub's own timestamps are.
    """
    parsed = datetime.fromisoformat(text.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _run(command: list[str]) -> str:
    """`command`'s output, or `NoAnswer` saying why there is none."""
    try:
        done = subprocess.run(command, capture_output=True, text=True)
    except OSError as missing:
        raise NoAnswer(f"cannot run {command[0]}: {missing}") from missing
    if done.returncode != 0:
        raise NoAnswer(done.stderr.strip() or f"{' '.join(command)} failed")
    return done.stdout


def repository(remote_url: str) -> str:
    """`owner/repo` from a git remote URL."""
    found = REMOTE.search(remote_url.strip())
    if not found:
        raise ValueError(f"cannot read owner/repo from remote {remote_url!r}")
    return f"{found.group(1)}/{found.group(2)}"


def origin_repo() -> str:
    """`owner/repo` of this checkout's `origin` remote."""
    return repository(_run(["git", "remote", "get-url", "origin"]))


def gh_api(path: str) -> list[dict]:
    """GET `path` from GitHub's REST API through `gh api`."""
    return json.loads(_run(["gh", "api", path]))


def merged_since(repo: str, since: datetime, api: Api = gh_api) -> list[dict]:
    """Every pull request merged at or after `since`, lowest number first.

    One updated while the pages are read can move onto the next page and be
    listed twice, so they are kept by number.
    """
    merged: dict[int, dict] = {}
    page = 1
    while True:
        pulls = api(
            f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc"
            f"&per_page={PAGE}&page={page}"
        )
        for pull in pulls:
            if pull["merged_at"] and moment(pull["merged_at"]) >= since:
                merged[pull["number"]] = pull
        if len(pulls) < PAGE or moment(pulls[-1]["updated_at"]) < since:
            break
        page += 1
    return sorted(merged.values(), key=lambda pull: pull["number"])


def both_stages(repo: str, api: Api = gh_api) -> list[dict]:
    """The open issues labelled both `planning` and `human` (`labels=` is an AND).

    The issues endpoint lists pull requests too; those are left out.
    """
    found: list[dict] = []
    page = 1
    while True:
        batch = api(
            f"repos/{repo}/issues?labels=planning,human&state=open&per_page={PAGE}&page={page}"
        )
        found += [issue for issue in batch if "pull_request" not in issue]
        if len(batch) < PAGE:
            return found
        page += 1


def _link(item: dict) -> str:
    return f"[#{item['number']}]({item['html_url']}): {item['title']}"


def report(pulls: list[dict], issues: list[dict], since: str) -> str:
    """The Markdown: a heading per pull request with checks, a total, the issues."""
    lines: list[str] = []
    total = with_checks = 0
    strays: dict[int, int] = {}
    for pull in pulls:
        checks, outside = _scan(pull.get("body"))
        if outside:
            strays[pull["number"]] = outside
        if checks:
            with_checks += 1
            total += len(checks)
            lines += [f"### {_link(pull)}", "", *(f"- [ ] {c}" for c in checks), ""]
    lines.append(
        f"{total} unticked human check(s) in {with_checks} of the"
        f" {len(pulls)} pull request(s) merged since {since}."
    )
    if strays:
        where = ", ".join(f"#{number}" for number in strays)
        lines.append(
            f"{sum(strays.values())} more unticked item(s) sit under other headings"
            f" ({where}): usually a test plan, but a human check under a heading"
            " spelled some other way would be among them."
        )
    if issues:
        lines += [
            "",
            "These open issues carry both `planning` and `human`, and at most"
            " one may stay. Which one should each keep?",
            "",
            *(f"- {_link(issue)}" for issue in issues),
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, help="ISO 8601 UTC, e.g. 2026-01-31T18:00:00Z")
    args = parser.parse_args(argv)
    try:
        since = moment(args.since)
    except ValueError:
        parser.error(f"--since {args.since!r} is not an ISO 8601 date or time")
    try:
        repo = origin_repo()
        print(report(merged_since(repo, since), both_stages(repo), args.since))
    except (NoAnswer, ValueError) as failure:
        print(f"human-checks: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
