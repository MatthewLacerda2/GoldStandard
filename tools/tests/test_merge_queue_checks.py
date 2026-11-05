"""`tools/merge_queue/checks.py`: what counts as CI, and when it passed, on a
head and on `main`."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tools.merge_queue import checks
from tools.merge_queue.checks import Required
from tools.tests.queue_world import CI_OK, check_run

RULESET = Path(__file__).resolve().parents[2] / ".github" / "rulesets" / "main.json"
LATE = float("inf")


def ruleset(*contexts: dict) -> str:
    rule = {"type": "required_status_checks", "parameters": {"required_status_checks": contexts}}
    return json.dumps({"rules": [{"type": "deletion"}, rule]})


class WhatCountsAsCI(unittest.TestCase):
    def test_the_repository_ruleset_requires_ci_ok_and_the_mutation_gate(self) -> None:
        gate = Required("mutation gate", 15368)
        self.assertEqual(checks.required(RULESET.read_text()), [CI_OK, gate])

    def test_a_second_required_check_is_read_too(self) -> None:
        text = ruleset({"context": "CI ok", "integration_id": 15368}, {"context": "gate"})
        self.assertEqual(checks.required(text), [CI_OK, Required("gate", None)])

    def test_a_ruleset_requiring_nothing_is_an_error_not_an_empty_list(self) -> None:
        with self.assertRaises(ValueError):
            checks.required(ruleset())

    def test_another_apps_check_of_the_same_name_does_not_stand_in(self) -> None:
        impostor = check_run(app=1)
        self.assertEqual(checks.head([CI_OK], [impostor], LATE).state, checks.NO_RUN)
        self.assertEqual(checks.head([Required("CI ok")], [impostor], LATE).state, checks.GREEN)


class OnAHead(unittest.TestCase):
    def state(self, *runs: dict, waited: float = LATE, required=(CI_OK,)) -> str:
        return checks.head(list(required), list(runs), waited).state

    def test_success_is_green_and_failure_red(self) -> None:
        self.assertEqual(self.state(check_run()), checks.GREEN)
        self.assertEqual(self.state(check_run("failure")), checks.RED)
        self.assertEqual(self.state(check_run("cancelled")), checks.RED)

    def test_a_skipped_run_is_not_a_run(self) -> None:
        self.assertEqual(self.state(check_run("skipped")), checks.NO_RUN)

    def test_no_run_is_pending_within_the_grace_then_an_answer(self) -> None:
        self.assertEqual(self.state(waited=10), checks.PENDING)
        self.assertEqual(self.state(), checks.NO_RUN)

    def test_no_ci_ok_while_its_jobs_still_run_is_pending(self) -> None:
        # `CI ok` gets a check run only once every job it needs has finished.
        backend = check_run(status="in_progress", name="backend")
        self.assertEqual(self.state(backend, check_run(name="tools")), checks.PENDING)
        self.assertEqual(self.state(check_run(name="backend")), checks.NO_RUN)

    def test_the_newest_run_decides(self) -> None:
        draft, ready = check_run("skipped", run_id=1), check_run(run_id=2)
        self.assertEqual(self.state(ready, draft), checks.GREEN)
        rerun = check_run(status="in_progress", run_id=3)
        self.assertEqual(self.state(ready, rerun), checks.PENDING)

    def test_a_failure_with_a_newer_run_going_waits_for_it(self) -> None:
        # Re-running the failed jobs (or reopening) starts new runs while the
        # newest `CI ok` is still the old failure.
        failed, again = (
            check_run("failure", run_id=1),
            check_run(status="queued", name="backend", run_id=2),
        )
        self.assertEqual(self.state(failed, again), checks.PENDING)
        older = check_run(status="in_progress", name="backend", run_id=0)
        self.assertEqual(self.state(failed, older), checks.RED)

    def test_a_job_that_just_finished_may_still_be_followed_by_ci_ok(self) -> None:
        now = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
        backend = {**check_run(name="backend"), "completed_at": "2026-11-05T11:59:57Z"}
        self.assertEqual(checks.head([CI_OK], [backend], LATE, now).state, checks.PENDING)
        settled = {**backend, "completed_at": "2026-11-05T11:50:00Z"}
        self.assertEqual(checks.head([CI_OK], [settled], LATE, now).state, checks.NO_RUN)

    def test_red_is_an_answer_while_another_check_still_runs(self) -> None:
        both = (CI_OK, Required("gate"))
        # The gate's run is newer than the red `CI ok`, but it is another
        # required check's, so it never makes this one wait.
        red, running = check_run("failure"), check_run(status="queued", name="gate", run_id=2)
        self.assertEqual(self.state(red, running, required=both), checks.RED)
        self.assertEqual(self.state(check_run(), required=both), checks.NO_RUN)


class OnMain(unittest.TestCase):
    def red(self, *commits: list[dict]) -> checks.Red | None:
        return checks.main_red(CI_OK, [(str(i) * 40, runs) for i, runs in enumerate(commits)])

    def test_a_green_newest_commit_is_not_red(self) -> None:
        self.assertIsNone(self.red([check_run()], [check_run("failure")]))

    def test_the_streak_names_the_commit_that_broke_it(self) -> None:
        red = self.red([check_run("failure")], [check_run("failure")], [check_run()])
        assert red is not None
        self.assertEqual((red.newest, red.first), ("0" * 40, "1" * 40))

    def test_a_commit_still_running_defers_to_the_one_before(self) -> None:
        self.assertIsNone(self.red([check_run(status="in_progress")], [check_run()]))
        red = self.red([check_run(status="in_progress")], [check_run("failure")])
        self.assertEqual(red and red.first, "1" * 40)

    def test_a_red_being_re_run_is_still_red(self) -> None:
        rerun = [check_run("failure", run_id=1), check_run(status="in_progress", run_id=2)]
        red = self.red(rerun, [check_run()])
        assert red is not None
        self.assertTrue(red.rerunning and red.reran)

    def test_no_run_at_all_is_not_red(self) -> None:
        self.assertIsNone(self.red([], [check_run("skipped")]))


def job(name: str, conclusion: str = "success", suite: int = 1, run_id: int = 1) -> dict:
    return check_run(conclusion, name=name, suite=suite, run_id=run_id)


class PerJobOnMain(unittest.TestCase):
    """A push run skips the layers it did not touch, so `CI ok` alone can be green
    on a `main` whose backend is red."""

    def commits(self) -> list[tuple[str, list[dict]]]:
        docs = [job("CI ok", suite=2), job("backend", "skipped", suite=2), job("other", suite=9)]
        broke = [job("CI ok", "failure"), job("backend", "failure")]
        return [("d" * 40, docs), ("b" * 40, broke), ("g" * 40, [job("CI ok"), job("backend")])]

    def test_the_jobs_are_the_required_ones_and_their_suite_siblings(self) -> None:
        names = [each.context for each in checks.jobs([CI_OK], self.commits())]
        self.assertEqual(names, ["CI ok", "backend"])  # `other` is another workflow's

    def test_a_job_the_newest_run_no_longer_has_is_not_judged(self) -> None:
        # `backend` was renamed away: the newest push run has no such job, so
        # its old red holds nothing.
        renamed = [job("CI ok", suite=3), job("server", suite=3)]
        commits = [("n" * 40, renamed), *self.commits()]
        self.assertEqual([j.context for j in checks.jobs([CI_OK], commits)], ["CI ok", "server"])

    def test_a_docs_only_green_merge_does_not_turn_a_red_job_green(self) -> None:
        commits = self.commits()
        found = {
            each.context: checks.main_red(each, commits) for each in checks.jobs([CI_OK], commits)
        }
        self.assertIsNone(found["CI ok"])
        backend = found["backend"]
        assert backend is not None
        self.assertEqual(backend.first, "b" * 40)

    def test_only_a_run_that_ran_the_job_proves_it_fixed(self) -> None:
        red = checks.main_red(Required("backend", 15368), self.commits()[1:])
        assert red is not None
        self.assertFalse(checks.proves_fixed(red, [job("CI ok"), job("backend", "skipped")]))
        self.assertTrue(checks.proves_fixed(red, [job("CI ok"), job("backend")]))
        # A head whose workflow no longer has the job (renamed or removed) clears it.
        self.assertTrue(checks.proves_fixed(red, [job("CI ok"), job("server")]))


if __name__ == "__main__":
    unittest.main()
