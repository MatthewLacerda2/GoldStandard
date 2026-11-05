"""After a merge: the remote branch and the coder's worktree.

What whoever merged used to do by hand after every merge (`ci-merge`, *The
merge*: `deleteBranchOnMerge` is off):

- the remote branch is deleted **only once GitHub says merged**: deleting the
  branch of a merge that did not happen closes the pull request; and never a
  branch on a fork, which is not this repository's to delete. A merge GitHub
  has not confirmed within half a minute is kept in the queue's memory and
  asked about again on every pass (`queue.Queue.settle`);
- each worktree on the branch is removed, and then the local branch, unless
  somebody's work is still in it ([`keep_reason`]). Never the worktree the
  queue runs in, and never a **locked** one: a lock marks a session that is
  still using it, so it is left, said, for that session or a person to free.

Each step is best effort: a failure is said, never a hand-back. The merge is
done, and what is left is housekeeping.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from tools.merge_queue import github, repo, talk

SETTLE_TRIES = 6
SETTLE_SECONDS = 5


def worktrees_on(porcelain: str, branch: str) -> list[tuple[str, bool]]:
    """The worktrees `git worktree list --porcelain` shows on `branch`, each
    with whether it is locked."""
    found, path, on, locked = [], "", False, False
    for line in [*porcelain.splitlines(), ""]:
        if line.startswith("worktree "):
            path, on, locked = line.removeprefix("worktree "), False, False
        elif line == f"branch refs/heads/{branch}":
            on = True
        elif line == "locked" or line.startswith("locked "):
            locked = True
        elif not line and path:
            if on:
                found.append((path, locked))
            path = ""
    return found


def keep_reason(status_code: int, status: str, cherry: str) -> str | None:
    """Why a worktree on a merged branch must stay, or `None` when it may go.

    `status` is its `git status --porcelain`; `cherry` is `git cherry` of its
    HEAD against `main`, where a `+` is a commit with no equivalent there.
    Uncommitted changes, or a commit `main` lacks, are somebody's work in
    flight: a coder resumed to fix the pull request while the queue merged
    the head before the fix.
    """
    if status_code != 0:
        return "git could not read its state"
    if status.strip():
        return "it has uncommitted changes"
    ahead = [line for line in cherry.splitlines() if line.startswith("+")]
    if ahead:
        return f"it has {len(ahead)} commit(s) `main` has no equivalent of"
    return None


def inside(path: str, place: str) -> bool:
    here, there = Path(path).resolve(), Path(place).resolve()
    return here == there or there.is_relative_to(here)


class Aftermath:
    def __init__(self, hub: github.GitHub | None, root: str, dry: bool) -> None:
        self.hub = hub
        self.root = root
        self.dry = dry

    def run(self, pull: dict) -> tuple[bool, list[str]]:
        """Whether GitHub confirmed the merge (and so the steps ran), and their lines."""
        if not self.dry and not self.settled(pull["number"]):
            return False, ["GitHub does not say merged yet: cleaning up once it does."]
        return True, self.cleanup(pull)

    def cleanup(self, pull: dict) -> list[str]:
        """Every step, each answering with a line; one failing never stops the others."""
        lines = []
        for step in (self.branch, self.worktrees):
            try:
                lines += step(pull)
            except (talk.Unreachable, talk.MachineDown, talk.Refused, talk.AuthFailed) as failed:
                lines.append(f"a step was left undone ({failed}); settle it by hand.")
        return lines

    def settled(self, number: int) -> bool:
        """Whether GitHub's record says merged, asked for up to half a minute."""
        for _ in range(SETTLE_TRIES):
            if self.hub.merged(number):
                return True
            time.sleep(SETTLE_SECONDS)
        return False

    @staticmethod
    def fork(pull: dict) -> bool:
        """A fork's branch name says nothing about this clone's branches: a fork's
        `main` is not this `main`."""
        return pull.get("head_repo") != pull.get("base_repo")

    def branch(self, pull: dict) -> list[str]:
        name = pull["branch"]
        if self.fork(pull):
            return [f"`{name}` lives on a fork: not this repository's branch to delete."]
        if self.dry:
            return [f"would delete the remote branch `{name}`."]
        return [self.hub.delete_branch(name)]

    def worktrees(self, pull: dict) -> list[str]:
        """Free the worktrees on the branch, unless somebody's work is in one."""
        branch = pull["branch"]
        if self.fork(pull):
            return [f"`{branch}` lives on a fork: no worktree or branch here is its."]
        if not self.dry:
            talk.git_net("fetch", "--quiet", "origin", repo.BASE, cwd=self.root)
        listed = talk.git("worktree", "list", "--porcelain", cwd=self.root).stdout
        lines, kept = [], False
        for path, locked in worktrees_on(listed, branch):
            if not Path(path).is_dir():
                kept = True
                lines.append(f"worktree {path} is gone from disk: `git worktree prune` clears it.")
                continue
            why = "it is locked, by a session still using it" if locked else self.keep(path)
            if why:
                kept = True
                lines.append(f"worktree {path} kept: {why}.")
            elif self.dry:
                lines.append(f"would remove worktree {path}.")
            else:
                done = talk.git("worktree", "remove", "--force", path, cwd=self.root)
                if done.returncode != 0:
                    kept = True
                    lines.append(f"worktree {path} not removed: {done.stderr.strip()}")
                    continue
                lines.append(f"worktree {path} removed.")
        if not (self.dry or kept) and self.drop_branch(branch):
            lines.append(f"local branch `{branch}` deleted.")
        return lines

    def keep(self, path: str) -> str | None:
        if inside(path, self.root) or inside(path, os.getcwd()):
            return "the queue runs in it"
        # Every untracked file and every submodule counted, whatever
        # `status.showUntrackedFiles` says: a new file nobody committed yet is
        # work, and `worktree remove --force` would delete it.
        status = talk.git(
            "status", "--porcelain", "--untracked-files=all", "--ignore-submodules=none", cwd=path
        )
        cherry = talk.git("cherry", repo.UPSTREAM, "HEAD", cwd=path)
        if cherry.returncode != 0:
            return "its commits could not be compared with `main`"
        return keep_reason(status.returncode, status.stdout, cherry.stdout)

    def drop_branch(self, name: str) -> bool:
        """Delete a local branch only when `main` holds an equivalent of every commit."""
        ref = f"refs/heads/{name}"
        if talk.git("rev-parse", "--verify", "--quiet", ref, cwd=self.root).returncode != 0:
            return False
        cherry = talk.git("cherry", repo.UPSTREAM, ref, cwd=self.root)
        if cherry.returncode != 0 or keep_reason(0, "", cherry.stdout):
            return False
        return talk.git("branch", "-D", name, cwd=self.root).returncode == 0
