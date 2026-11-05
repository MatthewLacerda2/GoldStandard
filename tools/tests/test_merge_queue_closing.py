"""`tools/merge_queue/closing.py`: what a description closes, and whether it may."""

from __future__ import annotations

import unittest

from tools.merge_queue import closing

REPO = "owner/name"


def issue(state: str = "open", *labels: str, pull: bool = False) -> dict:
    found = {"state": state, "labels": [{"name": label} for label in labels]}
    return {**found, "pull_request": {}} if pull else found


class WhatItCloses(unittest.TestCase):
    def test_every_keyword_form_github_honours(self) -> None:
        body = "Closes #1, fixes #2. Resolved: #3\nclose owner/name#4 and fix https://github.com/owner/name/issues/5"
        self.assertEqual(closing.closes(body, REPO), [1, 2, 3, 4, 5])

    def test_another_repositorys_issue_is_not_this_ones(self) -> None:
        self.assertEqual(closing.closes("Closes other/repo#7, fixes #8", REPO), [8])

    def test_a_mention_is_not_a_close(self) -> None:
        self.assertEqual(closing.closes("refs #3; see #4; blocked by #5", REPO), [])


class MayItClose(unittest.TestCase):
    def test_a_startable_open_issue_may_be_closed(self) -> None:
        self.assertEqual(closing.refusal({1: issue("open", "feat")}), [])

    def test_a_stage_label_refuses(self) -> None:
        for stage in closing.STAGES:
            lines = closing.refusal({1: issue("open", stage)})
            self.assertEqual(lines[0], f"it closes #1, which is labelled `{stage}`.")

    def test_a_pull_request_or_a_closed_issue_refuses(self) -> None:
        self.assertIn("pull request", closing.refusal({2: issue(pull=True)})[0])
        self.assertIn("already closed", closing.refusal({3: issue("closed")})[0])


class ABranchNamedForAnIssue(unittest.TestCase):
    def test_its_number_is_read_with_or_without_a_prefix(self) -> None:
        self.assertEqual(closing.issue_of("47-merge-queue"), 47)
        self.assertEqual(closing.issue_of("feat/47-merge-queue"), 47)
        self.assertIsNone(closing.issue_of("feat/merge-queue"))
        self.assertIsNone(closing.issue_of("feat/v2"))

    def test_the_description_closes_or_refers_to_it(self) -> None:
        self.assertEqual(closing.unnamed("feat/47-q", "Closes #47"), [])
        self.assertEqual(closing.unnamed("feat/47-q", "Leaves it open: refs #47"), [])
        self.assertIn("#47", closing.unnamed("feat/47-q", "Closes #470")[0])
        self.assertEqual(closing.unnamed("feat/q", ""), [])


if __name__ == "__main__":
    unittest.main()
