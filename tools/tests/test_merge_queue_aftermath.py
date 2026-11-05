"""`tools/merge_queue/aftermath.py`'s guards that need no repository: the
branch goes only after GitHub says merged, and never a fork's."""

from __future__ import annotations

import unittest
from unittest import mock

from tools.merge_queue import aftermath, talk
from tools.tests.queue_world import FakeHub
from tools.tests.queue_world import pull_request as pr


class Hub(FakeHub):
    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []

    def delete_branch(self, branch):
        self.deleted.append(branch)
        if branch == "refused":
            raise talk.AuthFailed("HTTP 403: Resource not accessible by integration")
        return f"remote branch `{branch}` deleted."


class Cleanup(unittest.TestCase):
    def setUp(self) -> None:
        self.hub = Hub()
        self.after = aftermath.Aftermath(self.hub, "/nowhere", dry=False)
        self.after.worktrees = lambda pull: []
        self.enterContext(mock.patch.object(aftermath.time, "sleep"))

    def test_nothing_is_deleted_until_github_says_merged(self) -> None:
        settled, lines = self.after.run(pr(1))
        self.assertFalse(settled)
        self.assertEqual(self.hub.deleted, [])
        self.hub.merges.append(1)
        self.assertTrue(self.after.run(pr(1))[0])
        self.assertEqual(self.hub.deleted, ["feat/x1"])

    def test_a_forks_branch_is_never_deleted(self) -> None:
        self.hub.merges.append(1)
        _, lines = self.after.run(pr(1, head_repo="someone/r"))
        self.assertEqual(self.hub.deleted, [])
        self.assertIn("fork", lines[0])

    def test_a_refused_deletion_is_said_and_stops_nothing(self) -> None:
        self.hub.merges.append(1)
        settled, lines = self.after.run(pr(1, branch="refused"))
        self.assertTrue(settled)
        self.assertIn("left undone", lines[0])


if __name__ == "__main__":
    unittest.main()
