"""The pull requests merged in a window, and which of them an API call served.

GitHub is asked through its REST API (``gh api``), never GraphQL. A call is
tied to a merged pull request by, in order:

1. **The `#N` its agent was started for.** A subagent's description (the short
   label it was started with, kept in its ``.meta.json``) names its issue or its
   pull request, as a batch's coders and reviewers do; an agent started by
   another agent inherits its parent's. ``#N`` resolves to pull request N when N
   merged in the window, else to the merged pull request whose description
   closes issue N (``Closes #N``, ``Fixes #N``, ``Resolves #N``).
2. **The branch it ran on.** A session working in a branch's worktree records
   that branch, and the merged pull request with that head branch owns it.

What neither ties is **not tied to one pull request**: a main session on
`main` running a batch or a conversation, an agent whose description names no
number, work on a pull request still open. Every call is counted in the window
by its own time, so a pull request whose work began before the window shows
only the part inside it.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
PAGE_SIZE = 100
MAX_PAGES = 20


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    branch: str
    closes: frozenset[int]


class GitHubUnavailable(Exception):
    """`gh` could not answer; the message says why and what to do."""


def _gh_page(page: int) -> list[dict]:
    path = (
        "repos/{owner}/{repo}/pulls?state=closed&sort=updated&direction=desc"
        f"&per_page={PAGE_SIZE}&page={page}"
    )
    try:
        run = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise GitHubUnavailable(
            "gh is not installed (https://cli.github.com); pass --no-prs to skip"
        ) from None
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitHubUnavailable(f"gh did not run ({exc})") from None
    if run.returncode != 0:
        first = (run.stderr.strip().splitlines() or ["no message"])[0]
        raise GitHubUnavailable(f"gh failed: {first} (signed in? try `gh auth status`)")
    pulls = json.loads(run.stdout or "[]")
    return pulls if isinstance(pulls, list) else []


def merged_since(since: str, fetch=_gh_page) -> list[PullRequest]:
    """The pull requests merged from `since` (YYYY-MM-DD, UTC) on, newest first.

    Pages run newest-updated first and stop at the first page that reaches
    before the window: a merge is never later than the pull request's last update.
    """
    found: list[PullRequest] = []
    for page in range(1, MAX_PAGES + 1):
        pulls = fetch(page)
        for pr in pulls:
            if (pr.get("merged_at") or "") >= since:
                found.append(
                    PullRequest(
                        int(pr["number"]),
                        str(pr.get("title") or ""),
                        str((pr.get("head") or {}).get("ref") or ""),
                        frozenset(int(n) for n in CLOSES.findall(pr.get("body") or "")),
                    )
                )
        if len(pulls) < PAGE_SIZE or (pulls[-1].get("updated_at") or "") < since:
            break
    return found


@dataclass
class Resolver:
    """Ties a call's refs and branch to one of `prs`, or to none."""

    prs: list[PullRequest]

    def __post_init__(self) -> None:
        self.by_number = {pr.number: pr for pr in self.prs}
        self.by_issue = {n: pr for pr in reversed(self.prs) for n in pr.closes}
        self.by_branch = {pr.branch: pr for pr in reversed(self.prs) if pr.branch}

    def owner(self, refs: tuple[int, ...], branch: str) -> PullRequest | None:
        for n in refs:
            if pr := self.by_number.get(n) or self.by_issue.get(n):
                return pr
        return self.by_branch.get(branch)
