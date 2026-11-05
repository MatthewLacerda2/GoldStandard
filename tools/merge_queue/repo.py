"""What the queue asks of the local clone: heads, diffs, conflicts, the rebase.

Nothing here touches a worktree somebody is working in. Conflicts are asked of
`git merge-tree --write-tree` (no checkout), and the one rebase the queue does
happens in a **detached throwaway worktree it creates and removes**: an agent
may be standing in the branch's real worktree, and rewriting it underneath them
is not the queue's to do. The worktree shares the clone's config, so a merge
driver registered there runs in the rebase too. The push carries
`--force-with-lease` against the head the pull request had when the queue
looked, so a push from anywhere else in the meantime is refused rather than
overwritten. A conflict is never resolved here: a machine that cannot say why
the code is shaped as it is does not get to pick a side.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from tools.merge_queue import github, order, talk
from tools.review_triggers import PACKAGE

BASE = "main"
UPSTREAM = f"origin/{BASE}"
RULESET = ".github/rulesets/main.json"
# How far back `main`'s first parents are read for its red streak.
MAIN_DEPTH = 20


class Clone:
    """The clone at `root`, with answers cached by the commits they are about."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.main = ""
        self._pairs: dict[frozenset[str], list[str] | None] = {}
        self._paths: dict[str, list[str]] = {}
        self._ids: dict[str, str | None] = {}

    def ask(self, *args: str) -> str:
        """A local question whose failure must not read as an empty answer."""
        done = talk.git(*args, cwd=self.root)
        if done.returncode != 0:
            raise talk.Refused(f"git {' '.join(args[:2])}: {done.stderr.strip()}")
        return done.stdout

    def common_dir(self) -> Path:
        found = self.ask("rev-parse", "--git-common-dir").strip()
        return (Path(self.root) / (found or ".git")).resolve()

    def repository(self) -> str:
        """`owner/name` from `origin`: no API call."""
        return github.owner_and_name(self.ask("remote", "get-url", "origin"))

    def has(self, sha: str) -> bool:
        return talk.git("cat-file", "-e", f"{sha}^{{commit}}", cwd=self.root).returncode == 0

    def fetch(self, heads: list[str]) -> None:
        """`main`, and any head this clone does not hold yet."""
        missing = [h for h in heads if h and not self.has(h)]
        done = talk.git_net("fetch", "--quiet", "origin", BASE, *missing, cwd=self.root)
        if done.returncode != 0:
            raise talk.Refused(f"git fetch: {done.stderr.strip()}")
        self.main = self.ask("rev-parse", UPSTREAM).strip()

    def changed(self, head: str) -> list[str]:
        """The paths the pull request changes: its head against its merge base
        with `main`, both ends of a rename."""
        key = f"{head} {self.main}"
        if key not in self._paths:
            out = self.ask("diff", "--name-only", "--no-renames", f"{UPSTREAM}...{head}")
            self._paths[key] = [line for line in out.splitlines() if line]
        return self._paths[key]

    def file(self, rev: str, path: str) -> str | None:
        """`path` as `rev` has it, or `None` where it has no such file."""
        done = talk.git("show", f"{rev}:{path}", cwd=self.root)
        return done.stdout if done.returncode == 0 else None

    def backend_diff(self, head: str) -> str:
        """The pull request's backend change outside the tests, with no context."""
        spec = f"{UPSTREAM}...{head}"
        return self.ask("diff", "-U0", "--no-color", spec, "--", "backend", ":!backend/tests")

    def package_sides(self, head: str) -> tuple[str | None, str | None]:
        """`frontend/package.json` at the merge base and at the head."""
        base = self.ask("merge-base", UPSTREAM, head).strip()
        return self.file(base, PACKAGE), self.file(head, PACKAGE)

    def patch_id(self, sha: str) -> str | None:
        """`git patch-id --stable` of `sha`'s change against its merge base with
        `main`, with no context lines (a `main` edit beside a hunk is not the
        pull request's). The diff is git's own (`--no-ext-diff --no-textconv`:
        a machine's difftastic would print nothing patch-id reads), read as
        bytes. `None` when there is no such id (a binary-only change, a commit
        that cannot be fetched): the review is then owed, never assumed."""
        key = f"{sha} {self.main}"
        if key not in self._ids:
            self._ids[key] = self._patch_id(sha)
        return self._ids[key]

    def _patch_id(self, sha: str) -> str | None:
        if not self.has(sha):
            talk.git_net("fetch", "--quiet", "origin", sha, cwd=self.root)
        options = ("--no-ext-diff", "--no-textconv", "--no-color", "-U0")
        command = ["git", "diff", *options, f"{UPSTREAM}...{sha}"]
        diff = subprocess.run(command, capture_output=True, check=False, cwd=self.root)
        if diff.returncode != 0:
            return None
        found = subprocess.run(
            ["git", "patch-id", "--stable"],
            capture_output=True,
            check=False,
            cwd=self.root,
            input=diff.stdout,
        )
        words = found.stdout.split()
        return words[0].decode() if found.returncode == 0 and words else None

    def same_change(self, one: str, other: str) -> bool:
        """Whether two heads carry the same change against `main`."""
        if one.lower() == other.lower():
            return True
        first = self.patch_id(one)
        return first is not None and first == self.patch_id(other)

    def conflicts(self, one: str, other: str) -> list[str] | None:
        """The paths two commits conflict on, or `None` (clean, or git could not say)."""
        key = frozenset((one, other))
        if key not in self._pairs:
            done = talk.git("merge-tree", "--write-tree", "--name-only", one, other, cwd=self.root)
            self._pairs[key] = order.conflict_paths(done.returncode, done.stdout)
        return self._pairs[key]

    def contains(self, head: str, sha: str) -> bool:
        """Whether `head` holds commit `sha`. A question git cannot answer is `Refused`."""
        done = talk.git("merge-base", "--is-ancestor", sha, head, cwd=self.root)
        if done.returncode not in (0, 1):
            raise talk.Refused(f"git merge-base --is-ancestor: {done.stderr.strip()}")
        return done.returncode == 0

    def main_commits(self) -> list[str]:
        """`main`'s first parents, newest first: each one a merge or a direct push."""
        out = self.ask("rev-list", "--first-parent", f"--max-count={MAIN_DEPTH}", UPSTREAM)
        return out.split()

    def ruleset(self) -> str:
        """The ruleset as `main` has it: what protects `main` is what counts."""
        text = self.file(UPSTREAM, RULESET)
        if text is None:
            raise talk.Refused(f"`main` has no {RULESET}, so nothing names the required checks.")
        return text

    def rebase(self, branch: str, head: str, push: bool) -> tuple[str | None, list[str]]:
        """Rebase `branch` onto `main` in a throwaway worktree; push it when `push`.

        Returns the new head (`head` itself when it already held `main`'s tip,
        and then nothing is pushed), or `None` and why not.
        """
        with tempfile.TemporaryDirectory(prefix="merge-queue-") as scratch:
            work = str(Path(scratch) / "wt")
            made = talk.git("worktree", "add", "--detach", work, head, cwd=self.root)
            if made.returncode != 0:
                raise talk.MachineDown(f"could not check {branch} out: {made.stderr.strip()}")
            try:
                return self._rebase_in(work, branch, head, push)
            finally:
                talk.git("worktree", "remove", "--force", work, cwd=self.root)

    def _rebase_in(
        self, work: str, branch: str, head: str, push: bool
    ) -> tuple[str | None, list[str]]:
        who = ("-c", "user.name=merge queue", "-c", "user.email=merge-queue@noreply")
        done = talk.git(*who, "rebase", UPSTREAM, cwd=work)
        if done.returncode != 0:
            listed = talk.git("diff", "--name-only", "--diff-filter=U", cwd=work).stdout.split()
            talk.git("rebase", "--abort", cwd=work)
            where = ", ".join(f"`{p}`" for p in listed) or "a path git did not name"
            return None, [
                f"it conflicts with `{BASE}` in {where}: resolve it on the branch and push."
            ]
        fresh = talk.git("rev-parse", "HEAD", cwd=work).stdout.strip()
        if push and fresh != head:
            lease = f"--force-with-lease=refs/heads/{branch}:{head}"
            pushed = talk.git_net("push", lease, "origin", f"HEAD:refs/heads/{branch}", cwd=work)
            if pushed.returncode != 0:
                return None, [f"the rebased push was refused: {pushed.stderr.strip()}"]
        return fresh, []
