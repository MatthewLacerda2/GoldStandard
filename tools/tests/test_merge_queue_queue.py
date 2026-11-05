"""One pass of the merge queue (`tools/merge_queue/queue.py`) over pull requests
GitHub and git answer for in memory (`queue_world.py`): the first green one
merges, a green one waits for a conflicting one ahead of it, everything that
needs somebody is handed back, and a red `main` holds all but its fix."""

from __future__ import annotations

import contextlib
import io
import unittest

from tools.merge_queue.state import Memory
from tools.tests.queue_world import FakeClone, FakeHub, check_run, long_ago, make_queue
from tools.tests.queue_world import pull_request as pr

REVIEW = "## Independent review\nReviewed head: {}\n\nNo findings."


class Pass(unittest.TestCase):
    def setUp(self) -> None:
        self.hub, self.clone = FakeHub(), FakeClone()
        self.out = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.out))

    def sweep(self, *pulls, **options) -> bool:
        return make_queue(self.hub, self.clone, **options).sweep(list(pulls))


class Order(Pass):
    def test_the_first_green_one_merges_and_the_pass_ends(self) -> None:
        one, two = pr(1, "2026-10-01"), pr(2, "2026-10-02")
        self.hub.green(one, two)
        queue = make_queue(self.hub, self.clone)
        self.assertTrue(queue.sweep([one, two]))
        self.assertEqual(self.hub.merges, [1])
        self.assertEqual(queue.memory.passes, {"2": 1})

    def test_a_green_one_waits_for_a_conflicting_one_ahead_but_not_for_others(self) -> None:
        one, two, three = pr(1, "2026-10-01"), pr(2, "2026-10-02"), pr(3, "2026-10-03")
        self.hub.runs[one["head"]] = [check_run(status="in_progress")]
        self.hub.green(two, three)
        self.clone.clashes = {frozenset((one["head"], two["head"]))}
        # #3 conflicts with nobody, so it goes before the pair; #2 waits for #1.
        self.assertTrue(self.sweep(one, two, three))
        self.assertEqual(self.hub.merges, [3])

    def test_priority_labels_go_first_among_equals(self) -> None:
        feat, infra = pr(1, "2026-10-01", labels=["feat"]), pr(2, "2026-10-02")
        self.hub.green(feat, infra)
        infra["body"] = "Closes #9"
        self.hub.issues[9] = {"number": 9, "state": "open", "labels": [{"name": "infrastructure"}]}
        self.assertTrue(self.sweep(feat, infra))
        self.assertEqual(self.hub.merges, [2])

    def test_a_pending_one_is_kept_in_line_not_handed_back(self) -> None:
        one = pr(1)
        self.hub.runs[one["head"]] = [check_run(status="queued")]
        queue = make_queue(self.hub, self.clone)
        self.assertFalse(queue.sweep([one]))
        self.assertIn(1, queue.in_line)
        self.assertEqual(queue.handed, {})


class CI(Pass):
    def test_a_red_pr_is_handed_back_once_in_a_watch(self) -> None:
        red = pr(1)
        self.hub.runs[red["head"]] = [check_run("failure")]
        memory = Memory(None)
        for _ in range(2):
            make_queue(self.hub, self.clone, watch=True, memory=memory).sweep([red])
        self.assertEqual(self.out.getvalue().count("HANDED BACK #1"), 1)
        self.assertEqual(self.hub.merges, [])

    def test_no_run_waits_for_the_grace_then_is_handed_back(self) -> None:
        bare = pr(1)
        memory = Memory(None)
        self.assertFalse(make_queue(self.hub, self.clone, memory=memory).sweep([bare]))
        self.assertNotIn("HANDED BACK", self.out.getvalue())
        long_ago(memory, 1, bare["head"])
        make_queue(self.hub, self.clone, memory=memory).sweep([bare])
        self.assertIn("HANDED BACK #1: `CI ok` has no run", self.out.getvalue())

    def test_a_skipped_ci_ok_is_not_green(self) -> None:
        drafted = pr(1)
        self.hub.runs[drafted["head"]] = [check_run("skipped")]
        memory = Memory(None)
        long_ago(memory, 1, drafted["head"])
        make_queue(self.hub, self.clone, memory=memory).sweep([drafted])
        self.assertEqual(self.hub.merges, [])
        self.assertIn("HANDED BACK #1: `CI ok` was skipped", self.out.getvalue())

    def test_a_refused_merge_is_handed_back(self) -> None:
        one = pr(1)
        self.hub.green(one)
        self.hub.refusing.add(1)
        queue = make_queue(self.hub, self.clone)
        self.assertFalse(queue.sweep([one]))
        self.assertIn(1, queue.handed)


class ReviewLane(Pass):
    def ci_change(self, pull) -> None:
        self.hub.green(pull)
        self.clone.paths[pull["head"]] = [".github/workflows/ci.yml"]

    def test_a_triggered_pr_without_a_record_is_handed_back(self) -> None:
        one = pr(1)
        self.ci_change(one)
        self.assertFalse(self.sweep(one))
        self.assertIn(
            "HANDED BACK #1: it hits an `independent-review` trigger", self.out.getvalue()
        )
        self.assertIn("trigger: CI and the gates: .github/workflows/ci.yml", self.out.getvalue())

    def test_a_record_for_the_head_merges_it(self) -> None:
        one = pr(1)
        self.ci_change(one)
        self.hub.notes[1] = [("dev", REVIEW.format(one["head"]))]
        self.assertTrue(self.sweep(one))

    def test_a_record_by_someone_else_does_not_count(self) -> None:
        one = pr(1)
        self.ci_change(one)
        self.hub.notes[1] = [("passer-by", REVIEW.format(one["head"]))]
        self.assertFalse(self.sweep(one))

    def test_a_record_for_an_older_head_counts_only_for_the_same_change(self) -> None:
        one, old = pr(1), "b" * 40
        self.ci_change(one)
        self.hub.notes[1] = [("dev", REVIEW.format(old))]
        self.assertFalse(self.sweep(one))
        self.assertIn("names " + old, self.out.getvalue())
        self.clone.same.add(frozenset((old, one["head"])))
        self.assertTrue(self.sweep(one))


class Closing(Pass):
    def test_a_pr_closing_a_planning_issue_is_handed_back(self) -> None:
        one = pr(1, body="Closes #5")
        self.hub.green(one)
        self.hub.issues[5] = {"number": 5, "state": "open", "labels": [{"name": "planning"}]}
        self.assertFalse(self.sweep(one))
        self.assertIn("it closes #5, which is labelled `planning`", self.out.getvalue())
        self.hub.issues[5]["labels"] = []  # the user greenlit it
        self.assertTrue(self.sweep(one))

    def test_a_branch_named_for_an_issue_must_name_it(self) -> None:
        one = pr(1, branch="feat/47-merge-queue", body="Closes #46")
        self.hub.green(one)
        self.assertFalse(self.sweep(one))
        self.assertIn("neither closes nor refers to #47", self.out.getvalue())


class Rebase(Pass):
    def test_a_conflict_is_rebased_and_pushed_then_waits_for_ci(self) -> None:
        one = pr(1)
        self.hub.green(one)
        self.clone.clashes = {frozenset((self.clone.main, one["head"]))}
        self.clone.rebases[one["head"]] = "c" * 40
        queue = make_queue(self.hub, self.clone)
        self.assertFalse(queue.sweep([one]))
        self.assertEqual(self.clone.pushed, ["feat/x1"])
        self.assertIn(1, queue.in_line)

    def test_a_rebase_that_conflicts_is_handed_back_with_the_paths(self) -> None:
        one = pr(1)
        self.hub.green(one)
        self.clone.clashes = {frozenset((self.clone.main, one["head"]))}
        self.assertFalse(self.sweep(one))
        self.assertIn(
            "HANDED BACK #1: it conflicts with `main` in `backend/x.py`", self.out.getvalue()
        )

    def test_a_dry_run_pushes_nothing(self) -> None:
        one = pr(1)
        self.clone.clashes = {frozenset((self.clone.main, one["head"]))}
        self.clone.rebases[one["head"]] = "c" * 40
        self.sweep(one, dry_run=True)
        self.assertEqual(self.clone.pushed, [])
        self.assertIn("would rebase it cleanly", self.out.getvalue())


class RedMain(Pass):
    def red_main(self) -> str:
        broke = self.clone.main
        self.hub.runs[broke] = [check_run("failure", run_id=77)]
        return broke

    def test_a_red_main_holds_a_green_pr_and_is_re_run_once(self) -> None:
        self.red_main()
        one = pr(1)
        self.hub.green(one)
        memory = Memory(None)
        for _ in range(2):
            self.assertFalse(make_queue(self.hub, self.clone, memory=memory).sweep([one]))
        self.assertEqual(self.hub.merges, [])
        self.assertEqual(self.hub.reran, [77])
        self.assertIn("`main` is red", self.out.getvalue())

    def test_a_branch_containing_the_red_commit_carries_the_fix(self) -> None:
        broke = self.red_main()
        stuck, fix = pr(1, "2026-10-01"), pr(2, "2026-10-02")
        self.hub.green(stuck, fix)
        self.clone.holds.add((fix["head"], broke))
        self.assertTrue(self.sweep(stuck, fix))
        self.assertEqual(self.hub.merges, [2])

    def test_a_streak_names_its_oldest_commit(self) -> None:
        newest, oldest, green = "1" * 40, "2" * 40, "3" * 40
        self.clone.history = [newest, oldest, green]
        self.hub.runs = {
            newest: [check_run("failure", run_id=3)],
            oldest: [check_run("failure", run_id=2)],
            green: [check_run(run_id=1)],
        }
        fix = pr(1)
        self.hub.green(fix)
        self.clone.holds.add((fix["head"], oldest))
        self.assertTrue(self.sweep(fix))


if __name__ == "__main__":
    unittest.main()
