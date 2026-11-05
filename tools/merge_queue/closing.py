"""What a pull request closes, and whether the merge may close it. Pure.

`CLAUDE.md` (*Issues*, the stage labels): `planning` and `human` both mean
**do not start**. A pull request that closes such an issue started it, so the
queue and `make mergeable` refuse one, naming the issue and the label. The
label is read as it stands **at merge time**: the user may remove it and
greenlight the work, and the pull request merges on the next pass.

`CLAUDE.md` (*Pull Requests*) also says to check the number after `Closes`,
because a wrong one closes the wrong issue silently. So a closing keyword
aimed at a pull request, or at an issue already closed, is refused too: it
closes nothing anybody is told about, and the issue that was meant stays open.

And a branch named for an issue (`N-…`, or `feat/N-…` with the prefix
`CLAUDE.md` asks for) is work on issue N: its description must close it, or
say it deliberately leaves it open (`refs #N`).

Which issues a pull request closes is read from its description by the rule
GitHub applies ([`closes`]): a keyword, then `#N`, `owner/name#N` or the
issue's URL, the last two only for this repository. REST has no other way to
ask, so an issue linked only in the sidebar is not seen. Every one of these is
a description edit away from passing: no push, no new CI run.
"""

from __future__ import annotations

import re

# The labels that mean *do not start*.
STAGES = ("planning", "human")

# GitHub's closing keywords, then an issue: `#N`, `owner/name#N`, or
# `https://github.com/owner/name/issues/N`; the repository is captured, empty
# for `#N`. GitHub matches them anywhere in a description, quoted or negated
# alike, so this does too: a pull request meaning to leave an issue open
# writes `refs #N`.
KEYWORD = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+"
    r"(?:https://github\.com/([\w.-]+/[\w.-]+)/issues/|([\w.-]+/[\w.-]+)?#)(\d+)\b",
    re.IGNORECASE,
)
# A branch named for an issue: its leading number, after an optional prefix.
BRANCH = re.compile(r"^(?:[\w.-]+/)?(\d+)-")
# What names an issue on purpose: a closing keyword, or `refs`.
NAMING = r"(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)"


def closes(body: str, repo: str) -> list[int]:
    """Every issue of `repo` the description's closing keywords name, once each.

    A reference naming its repository counts only when it names `repo`: another
    repository's issue is not this one's number.
    """
    return sorted(
        {
            int(number)
            for url, named, number in KEYWORD.findall(body or "")
            if not (url or named) or (url or named).lower() == repo.lower()
        }
    )


def labels(item: dict) -> list[str]:
    """A REST issue's label names."""
    return [label.get("name") or "" for label in item.get("labels") or []]


def refusal(closed: dict[int, dict]) -> list[str]:
    """Why this pull request may not close what it closes; empty when it may.

    `closed` maps each number from [`closes`] to GitHub's REST answer for it.
    The first line is the reason, as every hand-back's is.
    """
    wrong, staged = [], []
    for number, item in sorted(closed.items()):
        if "pull_request" in item:
            wrong.append(f"it closes #{number}, which is a pull request, not an issue.")
        elif item.get("state") == "closed":
            wrong.append(f"it closes #{number}, which is already closed.")
        staged += [
            f"it closes #{number}, which is labelled `{stage}`."
            for stage in STAGES
            if stage in labels(item)
        ]
    lines = staged + wrong
    if staged:
        lines.append(
            "`planning` and `human` mean do not start (CLAUDE.md, *Issues*). Only the"
            " user removes the label; the queue takes it on the next pass once they have."
        )
    if wrong:
        lines.append("Fix the number, or write `refs #N` for an issue left open.")
    return lines


def issue_of(branch: str) -> int | None:
    """The issue a head branch is named for, or `None`."""
    found = BRANCH.match(branch or "")
    return int(found.group(1)) if found else None


def names(body: str, issue: int) -> bool:
    """Whether `body` closes, or deliberately refers to, issue `issue`."""
    pattern = rf"\b{NAMING}\b:?\s+#{issue}\b"
    return re.search(pattern, body or "", re.IGNORECASE) is not None


def unnamed(branch: str, body: str) -> list[str]:
    """Why the description does not name the branch's issue; empty when it does."""
    issue = issue_of(branch)
    if issue is None or names(body, issue):
        return []
    return [
        f"the branch is `{branch}`, but the description neither closes nor refers to #{issue}.",
        f"Write `Closes #{issue}` (or `refs #{issue}` if the issue is deliberately left"
        " open); editing the description needs no push and no new run.",
    ]
