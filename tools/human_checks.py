"""Every human check left unrun on a pull request merged since a moment, in one list.

A check only a person can do (the page in a real browser, how it looks) never
keeps a pull request a draft: it goes in the description as a checklist under
`## For a human`, and the pull request merges. That keeps merging fast and
scatters the checks across every description that merged. This gathers them,
as Markdown ready to paste into a report: a heading per pull request with its
unticked items, then a one-line total.

Only two things in a description are read:

- **The human-check sections**, found by their heading at any level and in any
  case: `For a human` and the close spellings in `HUMAN_HEADING`. A section
  runs to the next heading at its level or above. A checklist under any other
  heading (a test plan, a gate list) is somebody else's and is left out.
- **Unticked items** (`- [ ]`) inside them. A ticked one is done, which is why
  nothing here keeps state: an item ticked on GitHub drops out of the next run.

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
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")

# The heading texts that open a human-check section, matched at the start of
# the text in any case, so "Human checks (not a merge hold)" is in. The
# canonical one is `For a human`; the rest are spellings it drifts into.
HUMAN_HEADING = re.compile(
    r"^(for (a|the) human|left for a human|needs? a human|human check)", re.IGNORECASE
)

# An item saying there is nothing to check is not a check.
NOTHING = re.compile(r"^nothing\b", re.IGNORECASE)

# An unticked task-list item and its text. A ticked `[x]` never matches.
UNTICKED = re.compile(r"^(\s*)[-*+]\s+\[ \]\s+(.*\S)\s*$")

# Any list item, ticked or not: what ends the continuation of the one before.
LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")

# A fenced code block's fence. A checklist inside one is an example.
FENCE = re.compile(r"^\s*(```|~~~)")

# The owner and repository at the end of a remote URL, https or ssh.
REMOTE = re.compile(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$")

# How many results one page asks for: the API's maximum.
PAGE = 100

Api = Callable[[str], list[dict]]


class Unreachable(Exception):
    """GitHub did not answer, so the list would be a lie by omission."""


def human_checks(body: str | None) -> list[str]:
    """The unticked items in `body`'s human-check sections, one string each.

    An item wrapping onto indented lines below it is joined into one line, so
    each check reads whole. A nested item stays an item of its own.
    """
    items: list[str] = []
    inside: int | None = None  # the level of the open human section, if any
    fenced = False
    current: tuple[int, list[str]] | None = None  # indent and text of the open item

    def close() -> None:
        nonlocal current
        if current is not None:
            text = " ".join(current[1])
            if not NOTHING.match(text):
                items.append(text)
            current = None

    for line in (body or "").splitlines():
        if FENCE.match(line):
            fenced = not fenced
            close()
            continue
        if fenced:
            continue
        if heading := HEADING.match(line):
            close()
            level = len(heading.group(1))
            if inside is not None and level <= inside:
                inside = None
            if inside is None and HUMAN_HEADING.match(heading.group(2)):
                inside = level
            continue
        if inside is None:
            continue
        if unticked := UNTICKED.match(line):
            close()
            current = (len(unticked.group(1)), [unticked.group(2)])
        elif current is not None and _continues(line, current[0]):
            current[1].append(line.strip())
        else:
            close()
    close()
    return items


def _continues(line: str, indent: int) -> bool:
    """Whether `line` carries on the item opened at `indent`."""
    deeper = len(line) - len(line.lstrip()) > indent
    return bool(line.strip()) and not LIST_ITEM.match(line) and deeper


def moment(text: str) -> datetime:
    """An ISO 8601 date or time as an aware UTC datetime.

    A bare date is its midnight in UTC, and a time with no offset is read as
    UTC, which is what GitHub's own timestamps are.
    """
    parsed = datetime.fromisoformat(text.strip())
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def repository(remote_url: str) -> str:
    """`owner/repo` from a git remote URL."""
    found = REMOTE.search(remote_url.strip())
    if not found:
        raise ValueError(f"cannot read owner/repo from remote {remote_url!r}")
    return f"{found.group(1)}/{found.group(2)}"


def gh_api(path: str) -> list[dict]:
    """GET `path` from GitHub's REST API through `gh api`."""
    done = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if done.returncode != 0:
        raise Unreachable(done.stderr.strip() or f"gh api {path} failed")
    return json.loads(done.stdout)


def merged_since(repo: str, since: datetime, api: Api = gh_api) -> list[dict]:
    """Every pull request merged at or after `since`, lowest number first."""
    merged: list[dict] = []
    page = 1
    while True:
        pulls = api(
            f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc"
            f"&per_page={PAGE}&page={page}"
        )
        merged += [p for p in pulls if p["merged_at"] and moment(p["merged_at"]) >= since]
        if len(pulls) < PAGE or moment(pulls[-1]["updated_at"]) < since:
            break
        page += 1
    return sorted(merged, key=lambda pull: pull["number"])


def both_stages(repo: str, api: Api = gh_api) -> list[dict]:
    """The open issues labelled both `planning` and `human` (`labels=` is an AND).

    The issues endpoint lists pull requests too; those are left out.
    """
    found = api(f"repos/{repo}/issues?labels=planning,human&state=open&per_page={PAGE}")
    return [issue for issue in found if "pull_request" not in issue]


def _link(item: dict) -> str:
    return f"[#{item['number']}]({item['html_url']}): {item['title']}"


def report(pulls: list[dict], issues: list[dict], since: str) -> str:
    """The Markdown: a heading per pull request with checks, a total, the issues."""
    lines: list[str] = []
    total = with_checks = 0
    for pull in pulls:
        if checks := human_checks(pull.get("body")):
            with_checks += 1
            total += len(checks)
            lines += [f"### {_link(pull)}", "", *(f"- [ ] {c}" for c in checks), ""]
    lines.append(
        f"{total} unticked human check(s) in {with_checks} of the"
        f" {len(pulls)} pull request(s) merged since {since}."
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
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True
        )
        repo = repository(remote.stdout)
        print(report(merged_since(repo, since), both_stages(repo), args.since))
    except (Unreachable, ValueError, subprocess.CalledProcessError) as failure:
        print(f"human-checks: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
