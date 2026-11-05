"""`make claude-usage` over a small hand-written transcript fixture.

The fixture (`fixtures/claude_usage/projects/`) is a made-up repository
checked out at `/work/shop`: one main session that started a coder, a coder
whose first message only points at a brief, a reviewer, the reviewer's own
`code-review` agent, and an Explore agent; a session in a worktree on branch
`feat/x`; and a sibling repository, `/work/shopfront`, that must not be read.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tools.claude_prs import PullRequest, Resolver, merged_since
from tools.claude_transcripts import collect, project_folders, transcript_files
from tools.claude_usage import main, render

PROJECTS = Path(__file__).resolve().parent / "fixtures" / "claude_usage" / "projects"
REPO = Path("/work/shop")
SINCE = "2026-03-01"


def calls():
    return collect(transcript_files(project_folders(PROJECTS, REPO), SINCE), SINCE)


def by_model(model: str):
    return [c for c in calls() if c.model == model]


def pulls() -> list[PullRequest]:
    raw = [
        {"number": 11, "merged_at": "2026-03-04T00:00:00Z", "head": {"ref": "feat/x"}},
        {"number": 10, "merged_at": "2026-03-03T00:00:00Z", "body": "Fixes #8"},
        {"number": 9, "merged_at": "2026-03-02T00:00:00Z", "body": "Closes #7\n\nMore."},
        {"number": 6, "merged_at": None, "body": "Closes #8"},  # closed unmerged
        {"number": 5, "merged_at": "2026-02-01T00:00:00Z", "head": {"ref": "feat/y"}},
    ]
    for pr in raw:
        pr["updated_at"] = pr["merged_at"] or "2026-03-05T00:00:00Z"
    return merged_since(SINCE, fetch=lambda page: raw if page == 1 else [])


class ReadingTheTranscripts(unittest.TestCase):
    def test_reads_the_checkout_and_its_worktrees_but_not_a_sibling_repo(self) -> None:
        names = [d.name for d in project_folders(PROJECTS, REPO)]
        self.assertEqual(names, ["-work-shop", "-work-shop--claude-worktrees-feat-x"])

    def test_counts_each_call_once_inside_the_window(self) -> None:
        main_calls = [c for c in calls() if c.scope == "main" and c.branch == "main"]
        # m0 is before the window, m2 is synthetic, m3 is a half-written line,
        # and m1 also appears in the coder's transcript: it stays the main session's.
        self.assertEqual(len(main_calls), 1)
        self.assertEqual((main_calls[0].context, main_calls[0].output), (1000, 40))

    def test_finds_each_subagents_role(self) -> None:
        roles = {c.role for c in by_model("model-b")}
        self.assertEqual(roles, {"coder"})  # one by its opening, one by its brief
        self.assertEqual({c.role for c in by_model("model-c")}, {"explore"})
        reviewers = [c for c in calls() if c.role == "reviewer"]
        self.assertEqual(sorted(c.context for c in reviewers), [400, 500])

    def test_an_agent_without_a_number_inherits_its_parents(self) -> None:
        review_agent = next(c for c in calls() if c.context == 500)
        self.assertEqual(review_agent.refs, (9,))


class TyingCallsToPullRequests(unittest.TestCase):
    def test_keeps_only_what_merged_in_the_window(self) -> None:
        self.assertEqual([pr.number for pr in pulls()], [11, 10, 9])
        self.assertEqual(pulls()[2].closes, frozenset({7}))

    def test_by_number_by_closed_issue_then_by_branch(self) -> None:
        resolver = Resolver(pulls())
        owners = {
            c.context: getattr(resolver.owner(c.refs, c.branch), "number", None) for c in calls()
        }
        expected = {1000: None, 2000: 9, 300: 10, 400: 9, 500: 9, 600: None, 700: 11}
        self.assertEqual(owners, expected)

    def test_stops_paging_once_a_page_reaches_before_the_window(self) -> None:
        asked: list[int] = []

        def fetch(page: int) -> list[dict]:
            asked.append(page)
            return [{"number": page, "merged_at": "2026-02-01", "updated_at": "2026-02-01"}] * 100

        self.assertEqual(merged_since(SINCE, fetch=fetch), [])
        self.assertEqual(asked, [1])


class TheReport(unittest.TestCase):
    def test_reports_scopes_roles_models_and_each_merged_pr(self) -> None:
        report = render(calls(), SINCE, pulls())
        self.assertIn("this machine's local transcripts only", report)
        self.assertRegex(report, r"subagent\s+coder\s+model-b\s+2\s+2\.3k")
        self.assertRegex(report, r"#9\s+3\s+2\.9k")
        self.assertRegex(report, r"\(none\)\s+2\s+1\.6k")
        self.assertIn("Average: 1.8k per merged PR (5.5k over 3).", report)
        self.assertIn("Not seen: cloud sessions, other machines", report)

    def test_says_why_when_github_cannot_answer(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            main(["--since", SINCE, "--projects", str(PROJECTS), "--repo", str(REPO), "--no-prs"])
        self.assertIn(
            "Context per merged pull request: unknown (skipped by --no-prs)", out.getvalue()
        )


if __name__ == "__main__":
    unittest.main()
