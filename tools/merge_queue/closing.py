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

Which issues a pull request closes is read by the rule GitHub applies
([`closes`]): a keyword, then `#N`, `owner/name#N` or the issue's URL, the
last two only for this repository. It is read from the description, from
**the merge commit's own message** (what the repository's merge commit
settings put there, [`merge_text`]: this repository's default is the pull
request's title) **and from the branch's commit messages**: the queue merges
with a merge commit, which keeps them, and a `fixes #N` in any of them closes
#N when it lands on `main`. REST has
no other way to ask, so an issue linked only in the sidebar is not seen. A
description is an edit away from passing (no push, no new CI run); a commit
message needs the branch rewritten.
"""

from __future__ import annotations

import re

# The labels that mean *do not start*.
STAGES = ("planning", "human")

CLOSING_VERBS = r"close[sd]?|fix(?:e[sd])?|resolve[sd]?"


def keyword(verbs: str) -> re.Pattern[str]:
    """`verbs`, then an issue: `#N`, `owner/name#N`, or
    `https://github.com/owner/name/issues/N`; the repository is captured, empty
    for `#N`."""
    return re.compile(
        rf"\b(?:{verbs})\b:?\s+"
        r"(?:https://github\.com/([\w.-]+/[\w.-]+)/issues/|([\w.-]+/[\w.-]+)?#)(\d+)\b",
        re.IGNORECASE,
    )


# GitHub matches its closing keywords anywhere in a text, quoted or negated
# alike, so this does too: a pull request meaning to leave an issue open
# writes `refs #N`, which [`NAMING`] alone accepts.
KEYWORD = keyword(CLOSING_VERBS)
NAMING = keyword(rf"{CLOSING_VERBS}|refs?")
# A branch named for an issue: its leading number, after an optional prefix.
BRANCH = re.compile(r"^(?:[\w.-]+/)?(\d+)-")


def numbers(pattern: re.Pattern[str], text: str, repo: str) -> list[int]:
    """Every issue of `repo` that `pattern` names in `text`, once each.

    A reference naming its repository counts only when it names `repo`: another
    repository's issue is not this one's number.
    """
    return sorted(
        {
            int(number)
            for url, named, number in pattern.findall(text or "")
            if not (url or named) or (url or named).lower() == repo.lower()
        }
    )


def closes(text: str, repo: str) -> list[int]:
    """Every issue of `repo` the closing keywords in `text` name."""
    return numbers(KEYWORD, text, repo)


def labels(item: dict) -> list[str]:
    """A REST issue's label names."""
    return [label.get("name") or "" for label in item.get("labels") or []]


def refusal(closed: dict[int, dict], in_commits: frozenset[int] = frozenset()) -> list[str]:
    """Why this pull request may not close what it closes; empty when it may.

    `closed` maps each number from [`closes`] to GitHub's REST answer for it;
    `in_commits` are the ones only a commit message closes. The first line is
    the reason, as every hand-back's is.
    """
    wrong, staged = [], []
    for number, item in sorted(closed.items()):
        it = (
            f"a commit message closes #{number}" if number in in_commits else f"it closes #{number}"
        )
        if "pull_request" in item:
            wrong.append(f"{it}, which is a pull request, not an issue.")
        elif item.get("state") == "closed":
            wrong.append(f"{it}, which is already closed.")
        staged += [
            f"{it}, which is labelled `{stage}`." for stage in STAGES if stage in labels(item)
        ]
    lines = staged + wrong
    if staged:
        lines.append(
            "`planning` and `human` mean do not start (CLAUDE.md, *Issues*). Only the"
            " user removes the label; the queue takes it on the next pass once they have."
        )
    if wrong:
        lines.append("Fix the number, or write `refs #N` for an issue left open.")
    if in_commits & set(closed) and lines:
        lines.append("A commit message is fixed by rewording the commit and pushing the branch.")
    return lines


def merge_text(pull: dict, title: str, message: str) -> str:
    """The message GitHub writes on the merge commit, by the repository's
    `merge_commit_title` (`MERGE_MESSAGE`, the default, or `PR_TITLE`) and
    `merge_commit_message` (`PR_TITLE`, the default, `PR_BODY` or `BLANK`)."""
    head = pull.get("head_repo", "").split("/")[0]
    first = (
        pull["title"]
        if title == "PR_TITLE"
        else (f"Merge pull request #{pull['number']} from {head}/{pull['branch']}")
    )
    rest = {"PR_BODY": pull["body"], "BLANK": ""}.get(message, pull["title"])
    return f"{first}\n\n{rest}"


def issue_of(branch: str) -> int | None:
    """The issue a head branch is named for, or `None`."""
    found = BRANCH.match(branch or "")
    return int(found.group(1)) if found else None


def names(body: str, issue: int, repo: str) -> bool:
    """Whether `body` closes, or deliberately refers to, issue `issue`, in any
    spelling [`closes`] reads."""
    return issue in numbers(NAMING, body, repo)


def unnamed(branch: str, body: str, repo: str) -> list[str]:
    """Why the description does not name the branch's issue; empty when it does."""
    issue = issue_of(branch)
    if issue is None or names(body, issue, repo):
        return []
    return [
        f"the branch is `{branch}`, but the description neither closes nor refers to #{issue}.",
        f"Write `Closes #{issue}` (or `refs #{issue}` if the issue is deliberately left"
        " open); editing the description needs no push and no new run.",
    ]
