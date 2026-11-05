"""`tools/human_checks.py`: the human checks merged pull requests left, and only those.

The fixture is hand-written in the shape GitHub's REST API answers: a page of
closed pull requests, newest update first, and the open issues carrying both
stage labels. Nothing here talks to `gh`.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from tools import human_checks as hc

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "human_checks.json").read_text())
REPO = FIXTURE["repo"]
PULLS = {pull["number"]: pull for pull in FIXTURE["pulls"]}


class Replay:
    """GitHub's answers from the fixture, paged as the API pages them."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def __call__(self, path: str) -> list[dict]:
        self.asked.append(path)
        url = urlsplit(path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        if url.path == f"repos/{REPO}/issues":
            return FIXTURE["issues"]
        assert url.path == f"repos/{REPO}/pulls", path
        size, page = int(query["per_page"]), int(query["page"])
        return FIXTURE["pulls"][(page - 1) * size : page * size]


class Sections(unittest.TestCase):
    def test_only_unticked_items_under_a_human_heading_count(self) -> None:
        # A test plan and a gate list are left out, as are a ticked item and
        # one saying there is nothing; a wrapped item reads as one line.
        self.assertEqual(
            hc.human_checks(PULLS[14]["body"]),
            [
                "Open the settings page in a real browser and flip the toggle;"
                " the page should not flash white.",
                "Do it again with the system theme set to dark.",
            ],
        )

    def test_any_level_and_case_and_a_fence_is_an_example(self) -> None:
        self.assertEqual(
            hc.human_checks(PULLS[12]["body"]),
            [
                "Read the Portuguese empty state aloud; does it sound natural?",
                "Check the Spanish one too.",
            ],
        )

    def test_close_spellings_open_a_section(self) -> None:
        for heading in ("For a human", "For the human", "Human checks", "Needs a human"):
            with self.subTest(heading=heading):
                self.assertEqual(hc.human_checks(f"## {heading}\n- [ ] look\n"), ["look"])

    def test_no_section_or_no_body_has_none(self) -> None:
        self.assertEqual(hc.human_checks(PULLS[11]["body"]), [])
        self.assertEqual(hc.human_checks("## Checklist\n- [ ] run it\n"), [])
        self.assertEqual(hc.human_checks(None), [])
        self.assertEqual(hc.human_checks("#4 is not a heading\n- [ ] x"), [])

    def test_a_section_ends_at_a_heading_of_its_level(self) -> None:
        body = "### For a human\n- [ ] in\n## Later\n- [ ] out\n"
        self.assertEqual(hc.human_checks(body), ["in"])


class Fetching(unittest.TestCase):
    def merged(self, since: str, replay: Replay) -> list[int]:
        with mock.patch.object(hc, "PAGE", 2):
            pulls = hc.merged_since(REPO, hc.moment(since), replay)
        return [pull["number"] for pull in pulls]

    def test_merged_pulls_since_are_kept_and_closed_ones_are_not(self) -> None:
        replay = Replay()
        self.assertEqual(self.merged("2026-03-01", replay), [11, 12, 14])
        self.assertIn("state=closed&sort=updated&direction=desc", replay.asked[0])
        self.assertEqual(len(replay.asked), 3)

    def test_paging_stops_at_the_first_pull_updated_before_since(self) -> None:
        replay = Replay()
        self.assertEqual(self.merged("2026-03-01T11:30:00Z", replay), [12, 14])
        self.assertEqual(len(replay.asked), 2)

    def test_issues_with_both_stages_leave_pull_requests_out(self) -> None:
        replay = Replay()
        self.assertEqual([i["number"] for i in hc.both_stages(REPO, replay)], [8])
        self.assertIn("labels=planning,human&state=open", replay.asked[0])

    def test_a_bare_date_is_midnight_utc(self) -> None:
        self.assertEqual(hc.moment("2026-03-01"), datetime(2026, 3, 1, tzinfo=UTC))
        self.assertEqual(
            hc.moment("2026-03-01T09:00:00-03:00"), datetime(2026, 3, 1, 12, tzinfo=UTC)
        )

    def test_owner_and_repo_come_from_the_remote(self) -> None:
        for url in (
            "https://github.com/example-owner/example-repo.git",
            "git@github.com:example-owner/example-repo.git",
            "http://proxy@127.0.0.1:1234/git/example-owner/example-repo\n",
        ):
            with self.subTest(url=url):
                self.assertEqual(hc.repository(url), REPO)


class Report(unittest.TestCase):
    def test_a_heading_per_pull_with_checks_then_a_total_then_the_question(self) -> None:
        replay = Replay()
        pulls = hc.merged_since(REPO, hc.moment("2026-03-01"), replay)
        text = hc.report(pulls, hc.both_stages(REPO, replay), "2026-03-01")
        self.assertIn(f"### [#14]({PULLS[14]['html_url']}): Add a dark-mode toggle", text)
        self.assertIn("- [ ] Check the Spanish one too.", text)
        self.assertNotIn("#11", text)
        self.assertIn(
            "\n4 unticked human check(s) in 2 of the 3 pull request(s) merged since 2026-03-01.\n",
            text,
        )
        self.assertIn("Which one should each keep?", text)
        issue = FIXTURE["issues"][0]
        self.assertTrue(text.endswith(f"- [#8]({issue['html_url']}): Pick a charting library"))

    def test_nothing_found_is_one_line(self) -> None:
        self.assertEqual(
            hc.report([PULLS[11]], [], "2026-03-01"),
            "0 unticked human check(s) in 0 of the 1 pull request(s) merged since 2026-03-01.",
        )

    def test_an_outage_fails_and_never_prints_an_empty_list(self) -> None:
        outage = hc.Unreachable("network down")
        with (
            mock.patch.object(hc, "merged_since", side_effect=outage),
            mock.patch("builtins.print") as printed,
        ):
            self.assertEqual(hc.main(["--since", "2026-03-01"]), 1)
        self.assertEqual(printed.call_count, 1)
        self.assertIn("network down", printed.call_args.args[0])
