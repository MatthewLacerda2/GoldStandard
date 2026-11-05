"""The pull requests merged in a window, and which of them an API call served.

GitHub is asked through its REST API (``gh api``), never GraphQL. A call is
tied to a merged pull request by, in order:

1. **The `#N` its agent was started for.** A subagent's description (the short
   label it was started with, kept in its ``.meta.json``) names its issue or its
   pull request, as a batch's coders and reviewers do; an agent started by
   another agent inherits its parent's. ``#N`` resolves to pull request N when N
   merged in the window, else to the merged pull request whose description
   closes issue N (``Closes #N``, ``Fixes #N``, ``Resolves #N``). A description
   naming several numbers ties only when every one of them resolves to the
   same pull request.
2. **The branch it ran on**, for an agent whose description names no number.
   A session working in a branch's worktree records that branch, and the merged
   pull request with that head branch owns the calls made before it merged.
   Only a branch of this repository counts, never its default branch (a fork's
   pull request from its own `main` owns nothing here), and a branch name more
   than one merged pull request used ties to neither.

Anything ambiguous is left untied rather than guessed, so what this reports is
a floor, never a wrong owner. What is **not tied to one pull request**: a main
session on `main` running a batch or a conversation, an agent whose description
names no number, work on a pull request still open. Every call is counted in
the window by its own time, so a pull request whose work began before the
window shows only the part inside it.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
PAGE_SIZE = 100
MAX_PAGES = 20


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    branch: str  # "" when its head is another repository's or the default branch
    closes: frozenset[int]
    merged_at: str


class GitHubUnavailable(Exception):
    """`gh` could not answer; the message says why and what to do."""


def gh_page(page: int, cwd: Path | None = None) -> list[dict]:
    """One page of the repository's closed pull requests; `gh` reads the
    repository from the git remote of `cwd`."""
    path = (
        "repos/{owner}/{repo}/pulls?state=closed&sort=updated&direction=desc"
        f"&per_page={PAGE_SIZE}&page={page}"
    )
    try:
        run = subprocess.run(
            ["gh", "api", path], cwd=cwd, capture_output=True, text=True, timeout=60
        )
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


def _own_branch(pr: dict) -> str:
    """The head branch, when it is a branch of this repository other than its default."""
    head, base = pr.get("head") or {}, pr.get("base") or {}
    head_repo, base_repo = head.get("repo") or {}, base.get("repo") or {}
    ref = str(head.get("ref") or "")
    same_repo = bool(head_repo) and head_repo.get("full_name") == base_repo.get("full_name")
    return ref if same_repo and ref != base_repo.get("default_branch") else ""


def merged_since(since: str, fetch=gh_page) -> list[PullRequest]:
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
                        _own_branch(pr),
                        frozenset(int(n) for n in CLOSES.findall(pr.get("body") or "")),
                        str(pr["merged_at"]),
                    )
                )
        if len(pulls) < PAGE_SIZE or (pulls[-1].get("updated_at") or "") < since:
            break
    return found


def _unique(pairs: Iterable[tuple[object, PullRequest]]) -> dict[object, PullRequest]:
    """Each key that names exactly one pull request, mapped to it."""
    seen: dict[object, set[int]] = {}
    prs: dict[int, PullRequest] = {}
    for key, pr in pairs:
        seen.setdefault(key, set()).add(pr.number)
        prs[pr.number] = pr
    return {key: prs[next(iter(numbers))] for key, numbers in seen.items() if len(numbers) == 1}


@dataclass
class Resolver:
    """Ties a call's refs and branch to one of `prs`, or to none."""

    prs: list[PullRequest]

    def __post_init__(self) -> None:
        self.by_number = {pr.number: pr for pr in self.prs}
        self.by_issue = _unique((n, pr) for pr in self.prs for n in pr.closes)
        self.by_branch = _unique((pr.branch, pr) for pr in self.prs if pr.branch)

    def owner(self, refs: tuple[int, ...], branch: str, time: str) -> PullRequest | None:
        if refs:
            owners = {self.by_number.get(n) or self.by_issue.get(n) for n in refs}
            return owners.pop() if len(owners) == 1 else None  # {None} stays None
        pr = self.by_branch.get(branch)
        return pr if pr and time <= pr.merged_at else None
