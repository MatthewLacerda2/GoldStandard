"""`tools/merge_queue/review.py`: the `Independent review` record, and the head
it vouches for."""

from __future__ import annotations

import unittest

from tools.merge_queue import review

HEAD, OLD = "a" * 40, "b" * 40
CODERS = {"dev"}


def named(*bodies: str, login: str = "dev") -> list[str]:
    return review.records([(login, body) for body in bodies], CODERS)


class TheRecord(unittest.TestCase):
    def test_the_heading_alone_then_the_reviewed_head(self) -> None:
        for heading in ("## Independent review", "**Independent review**", "Independent review:"):
            self.assertEqual(named(f"{heading}\n\nReviewed head: {HEAD}\n- fixed"), [HEAD])
        self.assertEqual(
            named(f"## Independent review\n**Reviewed head:** `{HEAD.upper()}`"), [HEAD]
        )

    def test_a_short_note_after_the_heading_is_fine(self) -> None:
        for heading in ("## Independent review (second round)", "**Independent review (round 3)**"):
            self.assertEqual(named(f"{heading}\nReviewed head: {HEAD}"), [HEAD], heading)

    def test_a_sentence_starting_with_the_words_is_no_record(self) -> None:
        self.assertEqual(named(f"Independent review is pending\nReviewed head: {HEAD}"), [])

    def test_a_record_without_the_line_names_no_head(self) -> None:
        self.assertEqual(named("## Independent review\nNo findings."), [""])
        self.assertEqual(named(f"## Independent review\nReviewed head: {HEAD[:7]}"), [""])
        self.assertEqual(named(f"## Independent review\nFindings\nReviewed head: {HEAD}"), [""])

    def test_only_the_author_or_an_assignee_writes_one(self) -> None:
        self.assertEqual(named(f"## Independent review\nReviewed head: {HEAD}", login="x"), [])


class DoesItCoverTheHead(unittest.TestCase):
    def test_a_record_naming_the_head_covers_it(self) -> None:
        self.assertEqual(review.verdict([OLD, HEAD], HEAD, lambda sha: False), (True, []))

    def test_no_record_is_the_missing_line(self) -> None:
        self.assertEqual(review.verdict([], HEAD, lambda sha: True), (False, [review.MISSING]))

    def test_an_older_head_covers_it_only_for_the_same_change(self) -> None:
        self.assertTrue(review.verdict([OLD], HEAD, lambda sha: sha == OLD)[0])
        ok, why = review.verdict([OLD], HEAD, lambda sha: False)
        self.assertFalse(ok)
        self.assertIn(OLD, why[0])

    def test_a_record_naming_no_head_never_covers_it(self) -> None:
        ok, why = review.verdict([""], HEAD, lambda sha: True)
        self.assertFalse(ok)
        self.assertIn("names no head", why[0])


if __name__ == "__main__":
    unittest.main()
