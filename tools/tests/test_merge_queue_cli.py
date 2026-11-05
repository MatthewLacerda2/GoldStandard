"""`tools/merge_queue/__main__.py`: what the command line accepts, and the line
that resumes a run."""

from __future__ import annotations

import contextlib
import io
import unittest

from tools.merge_queue import __main__ as cli
from tools.tests.queue_world import FakeClone, FakeHub, make_queue


def refused(*argv: str) -> bool:
    with contextlib.redirect_stderr(io.StringIO()), contextlib.suppress(SystemExit):
        cli.parse(list(argv))
        return False
    return True


class Parse(unittest.TestCase):
    def test_names_or_a_watch_never_both_nor_neither(self) -> None:
        self.assertFalse(refused("12", "14"))
        self.assertFalse(refused("--watch"))
        self.assertTrue(refused())
        self.assertTrue(refused("12", "--watch"))

    def test_mergeable_is_one_pull_request_and_read_only(self) -> None:
        self.assertTrue(cli.parse(["--mergeable", "12"]).dry_run)
        self.assertTrue(refused("--mergeable", "12", "14"))

    def test_a_watch_is_bounded(self) -> None:
        self.assertTrue(refused("--watch", "--for", str(cli.CAP_MINUTES + 1)))
        self.assertTrue(refused("--watch", "--for", "0"))


class Resume(unittest.TestCase):
    def test_a_named_run_resumes_every_name_whose_turn_is_not_over(self) -> None:
        opts = cli.parse(["12", "14", "16"])
        queue = make_queue(FakeHub(), FakeClone())
        queue.ended = {14}
        self.assertEqual(cli.resume(opts, queue), 'queue: resume: make queue PRS="12 16"')
        queue.ended = {12, 14, 16}
        self.assertEqual(cli.resume(opts, queue), "")

    def test_a_watch_resumes_as_a_watch(self) -> None:
        opts = cli.parse(["--watch", "--for", "30"])
        queue = make_queue(FakeHub(), FakeClone())
        self.assertEqual(
            cli.resume(opts, queue), 'watch: resume: make queue ARGS="--watch --for 30"'
        )


if __name__ == "__main__":
    unittest.main()
