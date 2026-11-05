"""Whether a pull request's independent review happened, and for which head. Pure.

`CLAUDE.md` (*Pull Requests*) sends a change the gates cannot fully judge
through the `independent-review` skill before it merges; which changes is
`tools/review_triggers.py`. The skill's answer is one PR comment headed
`Independent review`. The queue **enforces** that rule, it does not replace
it: a pull request that hits a trigger and has no such comment for its head
is handed back, never merged.

**The record** is a comment whose first line is the heading alone
(`## Independent review`, `**Independent review**`), not a sentence that
starts with the words ("Independent review: pending"), written by the pull
request's author or an assignee: the account the findings are answered from.

**It vouches for one commit**: the next line, `Reviewed head: <full sha>`,
names the head the findings were answered on (that line only, so a quoted or
older SHA further down never stands in for it). A push after it (a fix, a
takeover's commits) makes it stale, and so does a record that names no head.
The one push it survives is a rebase that left the pull request's own change
as it was: the same diff against `main`, every changed line and its
whitespace included, only the hunks' line numbers aside
(`repo.Clone.same_change`), whoever made the rebase. A rebase that had to
resolve something changes the diff, and the review is owed again.

The record is a process guard, not a permission boundary: anyone with write
access can merge by hand. It keeps an honest pipeline from merging a review
that no longer covers the code.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection

# The first line of the comment the `independent-review` skill posts, alone.
HEADING = re.compile(r"^[#*_\s]*independent review[#*_\s.:]*$", re.IGNORECASE)
# The line under that heading naming the commit it vouches for, alone (bold
# or code marks allowed), as a full SHA: a short one names no head.
REVIEWED_HEAD = re.compile(
    r"^[*_`\s]*reviewed head[*_`\s]*:[*_`\s]*([0-9a-f]{40})[*_`\s.]*$", re.IGNORECASE
)

MISSING = (
    "it hits an `independent-review` trigger and has no `Independent review` comment"
    " by its author or an assignee: run the `independent-review` skill and answer it"
    " on the pull request; the queue takes it then."
)


def records(comments: list[tuple[str, str]], coders: Collection[str]) -> list[str]:
    """The heads the coders' `Independent review` records name, oldest first.

    `comments` are `(login, body)` pairs; `coders` the pull request's author
    and assignees. A record whose next line is not `Reviewed head: <sha>`
    names `""`, which is no head.
    """
    named = []
    for login, body in comments:
        lines = [line for line in body.splitlines() if line.strip()] + ["", ""]
        if login in coders and HEADING.match(lines[0]):
            found = REVIEWED_HEAD.match(lines[1])
            named.append(found.group(1).lower() if found else "")
    return named


def verdict(
    named: list[str], head: str, same_change: Callable[[str], bool]
) -> tuple[bool, list[str]]:
    """Whether the records cover `head`, and, when not, why and what to do.

    `same_change(sha)` says whether `sha`'s own change is `head`'s (a rebase
    that changed nothing of it). Only the newest record that names a head is
    asked about; an older one was overtaken by it.
    """
    head = head.lower()
    if head in named:
        return True, []
    if not named:
        return False, [MISSING]
    last = next((sha for sha in reversed(named) if sha), "")
    if last and same_change(last):
        return True, []
    record = "the newest `Independent review` comment"
    if not last:
        return False, [
            f"{record} names no head: its line under the heading is not"
            " `Reviewed head: <full sha>`.",
            f"The head is {head}: if nothing was pushed after the review was answered,"
            " post the record again naming it; otherwise review the new commits first.",
        ]
    return False, [
        f"{record} names {last}, but the head is {head}, and the change is not the same.",
        "Something was pushed after the review was answered: review the new commits,"
        " then post a record naming the new head (`independent-review`,"
        " *Answering the findings*).",
    ]
