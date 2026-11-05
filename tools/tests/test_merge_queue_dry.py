"""A `--dry-run` pass writes nothing anywhere: one pass over a world holding
every action the queue can take (a merge, a rebase push, a re-run of `main`'s
failed jobs, a branch and a worktree to clean, an unsettled merge, a state
file), with a real clone for the worktree and the real cleanup code."""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from tools.merge_queue import __main__ as cli
from tools.merge_queue import judge
from tools.merge_queue.queue import Queue
from tools.merge_queue.state import Memory
from tools.tests.queue_world import CI_OK, FakeClone, FakeHub, check_run
from tools.tests.queue_world import pull_request as pr

HERMETIC = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd: Path, *args: str) -> None:
    who = ("-c", "user.name=t", "-c", "user.email=t@t")
    subprocess.run(["git", *who, *args], cwd=cwd, check=True, capture_output=True)


class RecordingHub(FakeHub):
    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []

    def delete_branch(self, branch):
        self.deleted.append(branch)
        return "deleted."


def clone_with_a_merged_worktree(place: Path) -> Path:
    """A clone whose `feat/x1` is merged into `origin/main`, checked out in a worktree."""
    origin, work = place / "origin.git", place / "work"
    git(place, "init", "-q", "--bare", "-b", "main", str(origin))
    git(place, "init", "-q", "-b", "main", str(work))
    git(work, "remote", "add", "origin", str(origin))
    (work / "a.txt").write_text("a\n")
    git(work, "add", "a.txt")
    git(work, "commit", "-q", "-m", "base")
    git(work, "branch", "feat/x1")
    git(work, "push", "-q", "origin", "HEAD:main", "feat/x1")
    git(work, "fetch", "-q", "origin")
    git(work, "checkout", "-q", "--detach")
    git(work, "worktree", "add", "-q", str(place / "wt"), "feat/x1")
    return work


class DryRun(unittest.TestCase):
    def setUp(self) -> None:
        self.enterContext(mock.patch.dict(os.environ, HERMETIC))
        self.place = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.out = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.out))
        self.hub, self.clone = RecordingHub(), FakeClone()
        self.clone.root = str(clone_with_a_merged_worktree(self.place))
        self.state = self.place / "state.json"
        written = Memory(self.state)
        written.unsettled["9"] = {
            "number": 9,
            "branch": "feat/x9",
            "head_repo": "o/r",
            "base_repo": "o/r",
        }
        written.save()

    def world(self) -> list[dict]:
        broke = self.clone.main
        self.hub.runs[broke] = [check_run("failure", run_id=77)]  # `main` red: re-run owed
        fix, other, clash, red = pr(1), pr(2), pr(3), pr(4)
        self.hub.green(fix, other, clash)
        self.clone.holds |= {(fix["head"], broke), (other["head"], broke)}
        self.hub.runs[red["head"]] = [check_run("failure", run_id=5)]
        self.clone.clashes = {frozenset((self.clone.main, clash["head"]))}
        self.clone.rebases[clash["head"]] = "c" * 40
        self.hub.merges.append(9)  # the unsettled merge GitHub now confirms
        return [fix, other, clash, red]

    def test_a_dry_pass_writes_nothing_and_answers_as_a_real_pass_would(self) -> None:
        pulls, before = self.world(), self.state.read_bytes()
        memory = Memory(self.state, read_only=True)
        gate = judge.MainGate(self.hub, self.clone, [CI_OK], memory, dry=True)
        opts = Namespace(watch=False, dry_run=True, label="queue", poll=0, watch_for=1, prs=[])
        queue = Queue(opts, self.hub, self.clone, memory, judge.Judge(self.hub, self.clone, gate))
        self.assertTrue(queue.sweep(pulls))
        queue.memory.save()
        self.assertEqual((self.hub.merges, self.hub.reran, self.hub.deleted), ([9], [], []))
        self.assertEqual(self.clone.pushed, [])
        self.assertEqual(self.state.read_bytes(), before)
        self.assertTrue((self.place / "wt").is_dir())
        self.assertEqual(self.out.getvalue().count("would merge"), 1)  # one merge a pass
        self.assertEqual(queue.merged, [1])
        self.assertIn(4, queue.handed)  # so the exit status says something was handed back
        self.assertIn("would re-run", self.out.getvalue())

    def test_only_a_run_that_may_write_writes_the_memory(self) -> None:
        clone = mock.Mock(common_dir=lambda: self.place)
        self.assertTrue(cli.memory_for(clone, writes=False).read_only)
        self.assertFalse(cli.memory_for(clone, writes=True).read_only)


if __name__ == "__main__":
    unittest.main()
