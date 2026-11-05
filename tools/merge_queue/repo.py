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

import tempfile
from pathlib import Path

from tools.merge_queue import github, order, talk

BASE = "main"
UPSTREAM = f"origin/{BASE}"
RULESET = ".github/rulesets/main.json"
NODE_MODULES = "frontend/node_modules"
# A diff the queue parses is git's own, whatever this machine's config says:
# no external or text-converting diff, no colour, no renames, and the `a/` and
# `b/` prefixes `review_triggers.querying` reads (`diff.noprefix` and
# `diff.mnemonicPrefix` would change them).
PLAIN_DIFF = (
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--no-renames",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)
# How far back `main`'s first parents are read for its red streak.
MAIN_DEPTH = 20


class Clone:
    """The clone at `root`, with answers cached by the commits they are about."""

    def __init__(self, root: str) -> None:
        self.root = root
        self.main = ""
        self._pairs: dict[frozenset[str], list[str] | None] = {}
        self._paths: dict[str, list[str]] = {}
        self._covers: dict[tuple[str, str, str], bool] = {}

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
            out = self.ask("diff", *PLAIN_DIFF, "--name-only", f"{UPSTREAM}...{head}")
            self._paths[key] = [line for line in out.splitlines() if line]
        return self._paths[key]

    def file(self, rev: str, path: str) -> str | None:
        """`path` as `rev` has it, or `None` where it has no such file."""
        done = talk.git("show", f"{rev}:{path}", cwd=self.root)
        return done.stdout if done.returncode == 0 else None

    def backend_diff(self, head: str) -> str:
        """The pull request's backend change outside the tests, with no context."""
        spec = f"{UPSTREAM}...{head}"
        return self.ask("diff", *PLAIN_DIFF, "-U0", spec, "--", "backend", ":!backend/tests")

    def sides(self, head: str, path: str) -> tuple[str | None, str | None]:
        """`path` at the pull request's merge base with `main`, and at its head."""
        base = self.ask("merge-base", UPSTREAM, head).strip()
        return self.file(base, path), self.file(head, path)

    def covers(self, reviewed: str, head: str) -> bool:
        """Whether `head` is `reviewed`'s change and nothing else: its tree is
        exactly what replaying `reviewed` onto `head`'s base gives.

        The replay is a three-way merge with no checkout (`git merge-tree
        --write-tree --merge-base`): `reviewed`'s change, from its own merge
        base with `main`, onto `head`'s merge base. Equal trees mean a rebase
        that resolved nothing; any line moved, re-indented or added, a binary
        file changed, or a conflict, means not. A commit that cannot be
        fetched, or a question git cannot answer, is `False`: the review is
        then owed, never assumed.
        """
        if reviewed.lower() == head.lower():
            return True
        key = (reviewed, head, self.main)
        if key not in self._covers:
            self._covers[key] = self._covers_now(reviewed, head)
        return self._covers[key]

    def _covers_now(self, reviewed: str, head: str) -> bool:
        if not self.has(reviewed):
            talk.git_net("fetch", "--quiet", "origin", reviewed, cwd=self.root)
        bases = [talk.git("merge-base", sha, UPSTREAM, cwd=self.root) for sha in (reviewed, head)]
        tree = talk.git("rev-parse", f"{head}^{{tree}}", cwd=self.root)
        if any(done.returncode != 0 for done in (*bases, tree)):
            return False
        old_base, new_base = (done.stdout.strip() for done in bases)
        replay = talk.git(
            "merge-tree",
            "--write-tree",
            f"--merge-base={old_base}",
            new_base,
            reviewed,
            cwd=self.root,
        )
        replayed = replay.stdout.split("\n", 1)[0].strip()
        return replay.returncode == 0 and replayed == tree.stdout.strip()

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
            # The route-tree merge driver runs the TanStack generator from the
            # worktree's `frontend/node_modules`: lend it this checkout's.
            modules = Path(self.root, NODE_MODULES).resolve()
            lent = Path(work, NODE_MODULES)
            if modules.is_dir() and lent.parent.is_dir() and not lent.exists():
                lent.symlink_to(modules, target_is_directory=True)
            try:
                return self._rebase_in(work, branch, head, push)
            finally:
                if lent.is_symlink():
                    lent.unlink()
                talk.git("worktree", "remove", "--force", work, cwd=self.root)

    def _rebase_in(
        self, work: str, branch: str, head: str, push: bool
    ) -> tuple[str | None, list[str]]:
        # The queue's own commits: its name, and no signing key it may not have.
        who = ("-c", "user.name=merge queue", "-c", "user.email=merge-queue@noreply")
        unsigned = ("-c", "commit.gpgSign=false")
        done = talk.git(*who, *unsigned, "rebase", UPSTREAM, cwd=work)
        if done.returncode != 0:
            listed = talk.git("diff", "--name-only", "--diff-filter=U", cwd=work).stdout.split()
            talk.git("rebase", "--abort", cwd=work)
            if not listed:
                why = (done.stderr or done.stdout).strip() or f"exit {done.returncode}"
                return None, [f"the rebase onto `{BASE}` failed without a conflict: {why}"]
            where = ", ".join(f"`{p}`" for p in listed)
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
