"""What the queue asks of GitHub, and the few things it tells it, over REST.

[`from_rest`] flattens a pull request into the fields the pure modules read,
so none of them knows the API's nesting; it is pure, and so is
[`owner_and_name`]. [`GitHub`] is the side that asks, through `talk.api`.

REST has no "issues this pull request closes": `closing.py` reads them from the
description, by GitHub's own keyword rule. A listing of pull requests carries
no `mergeable` and no `additions`, so the queue reads each one it judges on its
own ([`GitHub.pull`]).
"""

from __future__ import annotations

import re
import time
from urllib.parse import quote

from tools.merge_queue import talk

# Owner and name at the end of any spelling of a GitHub remote: https, ssh, or
# a proxy's (`…/git/<owner>/<name>`).
REMOTE = re.compile(r"[/:]([^/:]+)/([^/]+?)(?:\.git)?/?$")
# The run a check run belongs to, from its `details_url` (Actions only).
RUN_URL = re.compile(r"/actions/runs/(\d+)(?:/|$)")
# How long a merge call that failed in transit is given to show up as merged.
MERGE_SETTLES_SECONDS = 60


def owner_and_name(url: str) -> str:
    """`owner/name` from a git remote's URL."""
    match = REMOTE.search(url.strip())
    if not match:
        raise talk.Refused(f"cannot read a GitHub repository from the remote {url!r}.")
    return f"{match.group(1)}/{match.group(2)}"


def from_rest(rest: dict) -> dict:
    """`repos/{repo}/pulls/N` (or a listing's entry) as the flat record the queue reads."""
    head, base = rest.get("head") or {}, rest.get("base") or {}
    state = "merged" if rest.get("merged") or rest.get("merged_at") else rest.get("state", "")
    return {
        "number": rest.get("number"),
        "title": rest.get("title") or "",
        "url": rest.get("html_url") or "",
        "state": state,
        "draft": bool(rest.get("draft")),
        "head": head.get("sha") or "",
        "branch": head.get("ref") or "",
        "head_repo": (head.get("repo") or {}).get("full_name") or "",
        "base": base.get("ref") or "",
        "base_repo": (base.get("repo") or {}).get("full_name") or "",
        "body": rest.get("body") or "",
        "author": (rest.get("user") or {}).get("login") or "",
        "assignees": [a.get("login") or "" for a in rest.get("assignees") or []],
        "labels": [label.get("name") or "" for label in rest.get("labels") or []],
        "created_at": rest.get("created_at") or "",
        "additions": rest.get("additions") or 0,
        # True, False, or None while GitHub is still computing it.
        "mergeable": rest.get("mergeable"),
    }


def run_id(check_run: dict) -> int | None:
    """The Actions run a check run is a job of, or `None` (another app's check)."""
    found = RUN_URL.search(check_run.get("details_url") or "")
    return int(found.group(1)) if found else None


def joined(answer: object, key: str | None = None) -> list:
    """A paginated answer's items, every page: the pages are lists, or objects
    holding the list under `key`."""
    items: list = []
    for page in answer if isinstance(answer, list) else []:
        items += (page.get(key) or []) if key else page
    return items


def single(answer: object) -> dict:
    """A paginated answer for one object: its only page."""
    if isinstance(answer, list) and answer and isinstance(answer[0], dict):
        return answer[0]
    raise talk.Refused(f"unexpected answer from GitHub: {str(answer)[:200]}")


class GitHub:
    """One repository on GitHub, as `owner/name`."""

    def __init__(self, repo: str) -> None:
        self.repo = repo

    def path(self, rest: str) -> str:
        return f"repos/{self.repo}/{rest}"

    def pull(self, number: int) -> dict:
        return from_rest(single(talk.api(self.path(f"pulls/{number}"))))

    def open_pulls(self, base: str) -> list[dict]:
        """Every open pull request into `base` (listing fields only)."""
        found = joined(talk.api(self.path(f"pulls?state=open&base={base}&per_page=100")))
        return [from_rest(rest) for rest in found]

    def issue(self, number: int) -> dict:
        """An issue as GitHub has it; a pull request's number answers with a
        `pull_request` key."""
        return single(talk.api(self.path(f"issues/{number}")))

    def comments(self, number: int) -> list[tuple[str, str]]:
        """Every comment on the pull request's conversation, as `(login, body)`."""
        found = joined(talk.api(self.path(f"issues/{number}/comments?per_page=100")))
        return [((c.get("user") or {}).get("login") or "", c.get("body") or "") for c in found]

    def check_runs(self, sha: str) -> list[dict]:
        """Every check run on commit `sha`, re-runs included."""
        found = talk.api(self.path(f"commits/{sha}/check-runs?filter=all&per_page=100"))
        return joined(found, "check_runs")

    def rerun_failed(self, run: int) -> str | None:
        """Re-run a workflow run's failed jobs (and what needs them); `None`
        when GitHub took it, else its answer."""
        try:
            talk.api(self.path(f"actions/runs/{run}/rerun-failed-jobs"), method="POST")
        except talk.Refused as answer:
            return str(answer)
        return None

    def merged(self, number: int) -> bool | None:
        """Whether GitHub's record says merged; `None` when it did not answer."""
        try:
            return self.pull(number)["state"] == "merged"
        except talk.Refused, talk.Unreachable:
            return None

    def merge(self, number: int, sha: str) -> tuple[bool, str]:
        """Merge with a merge commit, only while the head is still `sha`.

        `sha` is REST's `--match-head-commit`: GitHub refuses the merge (409)
        if the head moved after the queue judged it. The call is never retried:
        a 502 can arrive with the merge already done, so a call that failed in
        transit is followed by asking whether it merged, for
        [`MERGE_SETTLES_SECONDS`]; a refusal GitHub reasoned about is a real no.
        """
        command = talk.api_command(
            self.path(f"pulls/{number}/merge"),
            method="PUT",
            fields={"merge_method": "merge", "sha": sha},
        )
        done = talk.once(command)
        if done.returncode == 0:
            return True, ""
        failure = done.stderr.strip()
        if talk.auth(failure):
            raise talk.AuthFailed(f"the merge: {failure}")
        if not talk.transport(failure):
            return False, f"GitHub refused the merge: {failure}"
        began = time.monotonic()
        while time.monotonic() - began < MERGE_SETTLES_SECONDS:
            if self.merged(number):
                return True, ""
            time.sleep(10)
        return False, (
            f"the merge call failed in transit ({failure}) and GitHub has not said it"
            " merged: look at the pull request before merging it again."
        )

    def delete_branch(self, branch: str) -> str:
        """Delete the remote branch; one line saying what happened."""
        try:
            talk.api(self.path(f"git/refs/heads/{quote(branch)}"), method="DELETE")
        except talk.Refused as answer:
            if "Reference does not exist" in str(answer):
                return f"remote branch `{branch}` was already gone."
            return f"remote branch `{branch}` not deleted: {answer}"
        return f"remote branch `{branch}` deleted."
