"""`tools/human_checks.py`: the human checks merged pull requests left, and only those.

The fixture is hand-written in the shape GitHub's REST API answers: closed pull
requests, newest update first, and the open issues carrying both stage labels.
Nothing here talks to `gh` or `git`.
"""

from __future__ import annotations

import json
import subprocess
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
        kind = url.path.removeprefix(f"repos/{REPO}/")
        assert kind in ("pulls", "issues"), path
        size, page = int(query["per_page"]), int(query["page"])
        return FIXTURE[kind][(page - 1) * size : page * size]


def checks(heading: str, items: str = "- [ ] look\n") -> list[str]:
    return hc.human_checks(f"{heading}\n{items}")


class Sections(unittest.TestCase):
    def test_only_unticked_items_under_a_human_heading_count(self) -> None:
        # A test plan and a gate list are left out, as are a ticked item and
        # the placeholder; a wrapped item reads as one line.
        self.assertEqual(
            hc.human_checks(PULLS[14]["body"]),
            [
                "Open the settings page in a real browser and flip the toggle;"
                " the page should not flash white.",
                "Do it again with the system theme set to dark.",
                "Nothing overlaps on a 320px-wide phone.",
            ],
        )
        self.assertEqual(hc.unclaimed(PULLS[14]["body"]), 2)

    def test_any_level_and_case_and_fences_and_comments_are_examples(self) -> None:
        self.assertEqual(
            hc.human_checks(PULLS[12]["body"]),
            [
                "Read the Portuguese empty state aloud; does it sound natural?",
                "Check the Spanish one too.",
            ],
        )
        self.assertEqual(hc.unclaimed(PULLS[12]["body"]), 0)

    def test_close_and_decorated_spellings_open_a_section(self) -> None:
        for heading in (
            "## For a human",
            "## For the human",
            "## For humans",
            "## Left for the human",
            "## Human checks",
            "## Human checklist",
            "## Needs a human",
            "## **For a human**",
            "## 🧑‍💻 For a human",
            "For a human\n---",
            "For a human\n===",
        ):
            with self.subTest(heading=heading):
                self.assertEqual(checks(heading), ["look"])

    def test_other_headings_do_not(self) -> None:
        for heading in ("## Test plan", "## For the maintainer", "## Humane URLs", "---"):
            with self.subTest(heading=heading):
                self.assertEqual(checks(heading), [])

    def test_only_a_whole_placeholder_is_dropped(self) -> None:
        for placeholder in ("Nothing here needs a person.", "Nothing else.", "None", "N/A"):
            with self.subTest(placeholder=placeholder):
                self.assertEqual(checks("## For a human", f"- [ ] {placeholder}\n"), [])
        for real in ("Nothing overlaps at 320px.", "None of the buttons wrap."):
            with self.subTest(real=real):
                self.assertEqual(checks("## For a human", f"- [ ] {real}\n"), [real])

    def test_numbered_and_loose_items_are_read(self) -> None:
        items = "1. [ ] look\n2. [x] done\n3) [ ] wrap\n\n   on after a blank line\n"
        self.assertEqual(checks("## For a human", items), ["look", "wrap on after a blank line"])

    def test_a_fence_closes_only_on_its_own_kind(self) -> None:
        inline = "Run ```make check``` first.\n- [ ] a\n"
        items = inline + "````\n```\n- [ ] fenced\n```\n````\n- [ ] b\n"
        self.assertEqual(checks("## For a human", items), ["a", "b"])

    def test_a_section_holds_its_sub_headings_and_ends_at_its_level(self) -> None:
        body = "## For a human\n### Frontend\n- [ ] in\n## Test plan\n- [ ] out\n"
        self.assertEqual(hc.human_checks(body), ["in"])
        self.assertEqual(hc.unclaimed(body), 1)

    def test_no_section_or_no_body_has_none(self) -> None:
        self.assertEqual(hc.human_checks(PULLS[11]["body"]), [])
        self.assertEqual(hc.human_checks(None), [])
        self.assertEqual(hc.human_checks("#4 is not a heading\n- [ ] x"), [])


class Fetching(unittest.TestCase):
    def merged(self, since: str, api: hc.Api) -> list[int]:
        with mock.patch.object(hc, "PAGE", 2):
            pulls = hc.merged_since(REPO, hc.moment(since), api)
        return [pull["number"] for pull in pulls]

    def test_merged_pulls_since_are_kept_and_closed_or_older_ones_are_not(self) -> None:
        replay = Replay()
        self.assertEqual(self.merged("2026-03-01", replay), [11, 12, 14])
        self.assertIn("state=closed&sort=updated&direction=desc", replay.asked[0])
        self.assertEqual(len(replay.asked), 3)

    def test_paging_stops_at_the_first_pull_updated_before_since(self) -> None:
        replay = Replay()
        self.assertEqual(self.merged("2026-03-01T12:30:00Z", replay), [14])
        self.assertEqual(len(replay.asked), 2)

    def test_a_pull_that_moved_pages_is_listed_once(self) -> None:
        pages = [[PULLS[14], PULLS[12]], [PULLS[12]]]
        self.assertEqual(self.merged("2026-03-01", lambda path: pages.pop(0)), [12, 14])

    def test_issues_with_both_stages_are_paged_and_leave_pull_requests_out(self) -> None:
        replay = Replay()
        with mock.patch.object(hc, "PAGE", 1):
            self.assertEqual([i["number"] for i in hc.both_stages(REPO, replay)], [8])
        self.assertIn("labels=planning,human&state=open", replay.asked[0])
        self.assertEqual(len(replay.asked), 3)

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


class Failing(unittest.TestCase):
    def test_a_failed_gh_says_why(self) -> None:
        failed = subprocess.CompletedProcess([], 1, stdout="", stderr="HTTP 404: Not Found")
        with mock.patch.object(subprocess, "run", return_value=failed):
            with self.assertRaisesRegex(hc.NoAnswer, "HTTP 404"):
                hc.gh_api("repos/x/y/pulls")

    def test_a_missing_gh_or_git_says_so(self) -> None:
        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError("gh")):
            with self.assertRaisesRegex(hc.NoAnswer, "cannot run gh"):
                hc.gh_api("repos/x/y/pulls")
            with self.assertRaisesRegex(hc.NoAnswer, "cannot run git"):
                hc.origin_repo()

    def test_an_outage_fails_and_never_prints_an_empty_list(self) -> None:
        with (
            mock.patch.object(hc, "origin_repo", return_value=REPO),
            mock.patch.object(hc, "merged_since", side_effect=hc.NoAnswer("network down")),
            mock.patch("builtins.print") as printed,
        ):
            self.assertEqual(hc.main(["--since", "2026-03-01"]), 1)
        self.assertEqual(printed.call_count, 1)
        self.assertIn("network down", printed.call_args.args[0])


class Report(unittest.TestCase):
    def test_a_heading_per_pull_with_checks_then_totals_then_the_question(self) -> None:
        replay = Replay()
        pulls = hc.merged_since(REPO, hc.moment("2026-03-01"), replay)
        text = hc.report(pulls, hc.both_stages(REPO, replay), "2026-03-01")
        self.assertIn(f"### [#14]({PULLS[14]['html_url']}): Add a dark-mode toggle", text)
        self.assertIn("- [ ] Check the Spanish one too.", text)
        self.assertNotIn("#11", text)
        self.assertIn(
            "\n5 unticked human check(s) in 2 of the 3 pull request(s) merged since 2026-03-01.\n"
            "2 more unticked item(s) sit under other headings (#14): ",
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
