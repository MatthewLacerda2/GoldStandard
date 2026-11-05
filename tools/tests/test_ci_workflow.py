"""`.github/workflows/ci.yml` keeps the promises `CI ok` rests on.

The ruleset on `main` requires `CI ok` alone, so what it vouches for is
whatever its `needs:` lists: a job missing there runs, can fail, and `main`
still takes the merge. And a required check that never reports leaves a pull
request pending forever, so the workflow must run for every ready pull
request. Read line by line (no YAML parser in the standard library), which
holds as long as the file keeps the two-space layout it has.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tools.ci_paths import decide

GITHUB = Path(__file__).resolve().parents[2] / ".github"
WORKFLOW = GITHUB / "workflows" / "ci.yml"
RULESET = GITHUB / "rulesets" / "main.json"
OK_JOB = "ok"


def jobs(text: str) -> dict[str, str]:
    """Each job's id and the text of its block, in the file's order."""
    body = text.split("\njobs:\n", 1)[1]
    parts = re.split(r"^  ([A-Za-z_][\w-]*):\n", body, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


class CiOk(unittest.TestCase):
    def setUp(self) -> None:
        self.text = WORKFLOW.read_text(encoding="utf-8")
        self.jobs = jobs(self.text)

    def test_ci_ok_needs_every_other_job(self) -> None:
        self.assertIn(OK_JOB, self.jobs, "ci.yml has no `ok` job")
        block = self.jobs[OK_JOB]
        needs = re.search(r"^    needs: \[(.*)\]$", block, flags=re.MULTILINE)
        self.assertIsNotNone(needs, "`CI ok` must list its needs as [a, b]")
        listed = {name.strip() for name in needs.group(1).split(",")}
        self.assertEqual(listed, set(self.jobs) - {OK_JOB})

    def test_the_ruleset_requires_ci_ok_by_its_name(self) -> None:
        # Renaming the job, or the context in the ruleset, unguards `main`.
        name = re.search(r"^    name: (.+)$", self.jobs[OK_JOB], flags=re.MULTILINE)
        rules = json.loads(RULESET.read_text(encoding="utf-8"))["rules"]
        contexts = [
            check["context"]
            for rule in rules
            if rule["type"] == "required_status_checks"
            for check in rule["parameters"]["required_status_checks"]
        ]
        self.assertIn(name.group(1), contexts)

    def test_ci_ok_reports_when_a_job_fails(self) -> None:
        # Without always() it is skipped after a failure, and GitHub reads a
        # skipped required check as a satisfied one.
        self.assertRegex(self.jobs[OK_JOB], r"\n    if: .*always\(\)")

    def test_every_change_prints_what_the_workflow_reads(self) -> None:
        for key in decide([]):
            self.assertIn(f"steps.diff.outputs.{key}", self.jobs["changes"], key)


class EveryReadyPullRequestGetsARun(unittest.TestCase):
    def setUp(self) -> None:
        self.triggers = WORKFLOW.read_text(encoding="utf-8").split("\njobs:\n")[0]

    def test_no_path_filter(self) -> None:
        self.assertNotRegex(self.triggers, r"(?m)^\s+paths(-ignore)?:")

    def test_marking_a_draft_ready_starts_a_run(self) -> None:
        self.assertRegex(self.triggers, r"types: \[[^\]]*\bready_for_review\b")


if __name__ == "__main__":
    unittest.main()
