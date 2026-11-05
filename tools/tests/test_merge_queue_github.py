"""`tools/merge_queue/github.py` and `talk.py`: the REST mapping, how a failure
is read, and that the queue reaches GitHub through `gh api` alone."""

from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from tools.merge_queue import github, talk

PACKAGE = Path(__file__).resolve().parents[1] / "merge_queue"


class Mapping(unittest.TestCase):
    def test_a_rest_pull_request_flattened(self) -> None:
        rest = {
            "number": 4,
            "state": "closed",
            "merged": True,
            "draft": False,
            "head": {"sha": "a" * 40, "ref": "feat/x", "repo": {"full_name": "o/r"}},
            "base": {"ref": "main", "repo": {"full_name": "o/r"}},
            "user": {"login": "dev"},
            "assignees": [{"login": "me"}],
            "labels": [{"name": "queue"}],
            "mergeable": None,
        }
        pull = github.from_rest(rest)
        self.assertEqual(
            (pull["state"], pull["branch"], pull["base"]), ("merged", "feat/x", "main")
        )
        self.assertEqual((pull["assignees"], pull["labels"], pull["body"]), (["me"], ["queue"], ""))
        self.assertIsNone(pull["mergeable"])

    def test_the_repository_from_any_remote_spelling(self) -> None:
        for url in ("https://github.com/o/r.git", "git@github.com:o/r.git", "http://proxy/git/o/r"):
            self.assertEqual(github.owner_and_name(url), "o/r")

    def test_a_check_runs_workflow_run(self) -> None:
        url = "https://github.com/o/r/actions/runs/42/job/7"
        self.assertEqual(github.run_id({"details_url": url}), 42)
        self.assertIsNone(github.run_id({"details_url": "https://ci.example/7"}))

    def test_pages_are_joined(self) -> None:
        self.assertEqual(github.joined([[1, 2], [3]]), [1, 2, 3])
        self.assertEqual(
            github.joined([{"check_runs": [1]}, {"check_runs": [2]}], "check_runs"), [1, 2]
        )


class Failures(unittest.TestCase):
    def test_in_transit_is_retried_and_an_answer_is_not(self) -> None:
        self.assertTrue(talk.transport("HTTP 502: Bad Gateway"))
        self.assertTrue(talk.transport("dial tcp: i/o timeout"))
        self.assertFalse(talk.transport("HTTP 404: Not Found"))
        self.assertFalse(talk.transport("HTTP 422: Validation Failed"))

    def test_refused_credentials_are_not_transit(self) -> None:
        self.assertTrue(talk.auth("HTTP 401: Bad credentials"))
        self.assertFalse(
            talk.transport("fatal: unable to access: The requested URL returned error: 403")
        )
        self.assertFalse(talk.auth("HTTP 403: API rate limit exceeded"))

    def test_a_rate_limit_is_put_off_not_refused(self) -> None:
        for said in ("HTTP 403: API rate limit exceeded", "HTTP 429: secondary rate limit"):
            self.assertTrue(talk.transport(said), said)
            self.assertTrue(talk.rate_limited(said), said)

    def test_a_get_reads_every_page(self) -> None:
        command = talk.api_command("repos/o/r/pulls")
        self.assertEqual(command[:2], ["gh", "api"])
        self.assertIn("--paginate", command)
        self.assertNotIn("--paginate", talk.api_command("x", method="PUT", fields={"a": "b"}))


def answered(code: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, "", stderr)


class TheMerge(unittest.TestCase):
    def setUp(self) -> None:
        self.hub = github.GitHub("o/r")
        self.enterContext(mock.patch.object(github.time, "sleep"))

    def merge(self, *answers: subprocess.CompletedProcess) -> tuple[bool | None, str, list]:
        with mock.patch.object(talk, "once", side_effect=list(answers)) as sent:
            ok, why = self.hub.merge(4, "a" * 40)
        return ok, why, [call.args[0] for call in sent.call_args_list]

    def test_it_is_a_merge_commit_pinned_to_the_judged_head(self) -> None:
        ok, _, sent = self.merge(answered())
        self.assertTrue(ok)
        self.assertIn("sha=" + "a" * 40, sent[0])
        self.assertIn("merge_method=merge", sent[0])
        self.assertEqual(sent[0][:4], ["gh", "api", "--method", "PUT"])

    def test_a_failure_in_transit_is_asked_about_never_taken_as_merged(self) -> None:
        with mock.patch.object(self.hub, "merged", return_value=False) as asked:
            ok, why, _ = self.merge(answered(1, "HTTP 502: Bad Gateway"))
        self.assertFalse(ok)
        self.assertIn("in transit", why)
        self.assertEqual(asked.call_count, github.MERGE_SETTLE_TRIES)
        with mock.patch.object(self.hub, "merged", return_value=True):
            self.assertTrue(self.merge(answered(1, "HTTP 502: Bad Gateway"))[0])

    def test_a_moved_base_is_asked_again_and_a_refusal_is_final(self) -> None:
        moved = "HTTP 405: Base branch was modified. Review and try the merge again."
        self.assertIsNone(self.merge(answered(1, moved))[0])
        self.assertIs(self.merge(answered(1, "HTTP 405: Pull Request is not mergeable"))[0], False)


class RestOnly(unittest.TestCase):
    def test_every_gh_command_is_gh_api(self) -> None:
        """`gh pr` and `gh issue` are GraphQL underneath: no module may build one."""
        for path in sorted(PACKAGE.glob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.List) and node.elts:
                    first, *rest = node.elts
                    if isinstance(first, ast.Constant) and first.value == "gh":
                        second = rest[0] if rest else None
                        value = second.value if isinstance(second, ast.Constant) else None
                        self.assertEqual(value, "api", f"{path.name}:{node.lineno}")
            self.assertNotIn("graphql", path.read_text().replace("GraphQL", ""), path.name)


if __name__ == "__main__":
    unittest.main()
