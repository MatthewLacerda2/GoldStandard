"""`make claude-usage` over a small hand-written transcript fixture.

The fixture (`fixtures/claude_usage/projects/`) is a made-up repository
checked out at `/work/shop`: one main session that started a coder, a coder
whose first message only points at a brief, a reviewer, the reviewer's own
`code-review` agent, and an Explore agent; a session in a worktree on branch
`feat/x`; and a sibling repository, `/work/shopfront`, that must not be read.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tools.claude_prs import GitHubUnavailable, PullRequest, Resolver, gh_page, merged_since
from tools.claude_transcripts import collect, project_folders, read_transcript, transcript_files
from tools.claude_usage import main, render

PROJECTS = Path(__file__).resolve().parent / "fixtures" / "claude_usage" / "projects"
REPO = Path("/work/shop")
SINCE = "2026-03-01"


def calls():
    return collect(transcript_files(project_folders(PROJECTS, REPO), SINCE), SINCE)


def by_model(model: str):
    return [c for c in calls() if c.model == model]


def raw_pr(number: int, merged_at: str | None, ref: str = "", body: str = "", **kw) -> dict:
    """A pull request as GitHub's REST API returns it, with only the fields read."""
    base = {"full_name": "me/shop", "default_branch": "main"}
    head_repo = {"full_name": kw.get("head_repo", "me/shop")}
    return {
        "number": number,
        "merged_at": merged_at,
        "updated_at": merged_at or "2026-03-05T00:00:00Z",
        "body": body,
        "head": {"ref": ref, "repo": head_repo},
        "base": {"repo": base},
    }


def pulls(*extra: dict) -> list[PullRequest]:
    raw = [
        raw_pr(11, "2026-03-04T00:00:00Z", ref="feat/x"),
        raw_pr(10, "2026-03-03T00:00:00Z", ref="feat/docs", body="Fixes #8"),
        raw_pr(9, "2026-03-02T00:00:00Z", body="Closes #7\n\nMore."),
        raw_pr(6, None, body="Closes #8"),  # closed unmerged
        raw_pr(5, "2026-02-01T00:00:00Z", ref="feat/y"),
        *extra,
    ]
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

    def test_a_line_cut_mid_character_is_skipped_not_fatal(self) -> None:
        line = b'{"type":"assistant","timestamp":"2026-03-02T00:00:00Z","message":'
        line += b'{"id":"z","model":"m","usage":{"input_tokens":5,"output_tokens":1}}}\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            path.write_bytes(line + b'{"type":"user","message":"caf\xc3')
            self.assertEqual(list(read_transcript(path, SINCE).calls), ["z"])

    def test_finds_each_subagents_role(self) -> None:
        roles = {c.role for c in by_model("model-b")}
        self.assertEqual(roles, {"coder"})  # one by its opening, one by its brief
        # Its prompt says "coder", but its agent type says what it is.
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
            c.context: getattr(resolver.owner(c.refs, c.branch, c.time), "number", None)
            for c in calls()
        }
        expected = {1000: None, 2000: 9, 300: 10, 400: 9, 500: 9, 600: None, 700: 11}
        self.assertEqual(owners, expected)

    def test_several_numbers_tie_only_when_they_agree(self) -> None:
        resolver = Resolver(pulls())
        self.assertEqual(resolver.owner((9, 7), "main", "2026-03-02").number, 9)
        self.assertIsNone(resolver.owner((9, 10), "main", "2026-03-02"))  # disagree
        self.assertIsNone(resolver.owner((60, 7), "main", "2026-03-02"))  # #60 still open

    def test_a_branch_ties_only_to_its_one_merged_pr_before_the_merge(self) -> None:
        resolver = Resolver(
            pulls(
                raw_pr(12, "2026-03-04T00:00:00Z", ref="main", head_repo="fork/shop"),
                raw_pr(13, "2026-03-04T00:00:00Z", ref="feat/again"),
                raw_pr(14, "2026-03-05T00:00:00Z", ref="feat/again"),
            )
        )
        self.assertEqual(resolver.owner((), "feat/x", "2026-03-03T00:00:00Z").number, 11)
        self.assertIsNone(resolver.owner((), "feat/x", "2026-03-05T00:00:00Z"))  # after merge
        self.assertIsNone(resolver.owner((), "main", "2026-03-03T00:00:00Z"))  # a fork's main
        self.assertIsNone(resolver.owner((), "feat/again", "2026-03-03T00:00:00Z"))  # reused

    def test_stops_paging_once_a_page_reaches_before_the_window(self) -> None:
        asked: list[int] = []

        def fetch(page: int) -> list[dict]:
            asked.append(page)
            return [raw_pr(page, "2026-02-01T00:00:00Z")] * 100

        self.assertEqual(merged_since(SINCE, fetch=fetch), [])
        self.assertEqual(asked, [1])


class AskingGitHub(unittest.TestCase):
    def test_gh_missing(self) -> None:
        missing = mock.patch("subprocess.run", side_effect=FileNotFoundError)
        with missing, self.assertRaisesRegex(GitHubUnavailable, "gh is not installed"):
            gh_page(1)

    def test_gh_failing_says_why_and_asks_it_from_the_reported_checkout(self) -> None:
        failed = subprocess.CompletedProcess([], 1, "", "gh: Bad credentials (HTTP 401)\n")
        out = io.StringIO()
        with mock.patch("subprocess.run", return_value=failed) as run, redirect_stdout(out):
            main(["--since", SINCE, "--projects", str(PROJECTS), "--repo", str(REPO)])
        self.assertEqual(run.call_args.kwargs["cwd"], REPO.resolve())
        self.assertIn("unknown (gh failed: gh: Bad credentials (HTTP 401)", out.getvalue())
        self.assertIn("gh auth status", out.getvalue())


class TheReport(unittest.TestCase):
    def test_reports_scopes_roles_models_and_each_merged_pr(self) -> None:
        report = render(calls(), SINCE, pulls())
        self.assertIn("this machine's local transcripts only", report)
        self.assertRegex(report, r"subagent\s+coder\s+model-b\s+2\s+2\.3k")
        self.assertRegex(report, r"#9\s+3\s+2\.9k")
        self.assertRegex(report, r"\(none\)\s+2\s+1\.6k")
        self.assertIn("Average: 1.8k per merged PR (5.5k over 3).", report)
        self.assertIn("Not seen: cloud sessions, other machines", report)

    def test_no_prs_skips_github(self) -> None:
        out = io.StringIO()
        with mock.patch("subprocess.run") as run, redirect_stdout(out):
            main(["--since", SINCE, "--projects", str(PROJECTS), "--repo", str(REPO), "--no-prs"])
        run.assert_not_called()
        self.assertIn("unknown (skipped by --no-prs)", out.getvalue())


if __name__ == "__main__":
    unittest.main()
