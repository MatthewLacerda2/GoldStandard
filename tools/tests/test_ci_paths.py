"""`tools/ci_paths.py`: what each change runs, and that every file is classified."""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from tools.ci_paths import LAYERS, UNGATED, counts, decide, main

ROOT = Path(__file__).resolve().parents[2]


def tracked_files() -> list[str]:
    return subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()


def runs(*files: str) -> dict[str, bool]:
    return decide(list(files))


class WhatAChangeRuns(unittest.TestCase):
    def test_markdown_only_runs_nothing_heavy(self) -> None:
        answer = runs("README.md", "backend/CLAUDE.md", ".claude/skills/x/SKILL.md")
        self.assertEqual(answer, {"backend": False, "frontend": False, "code": False})

    def test_frontend_markdown_runs_the_frontend(self) -> None:
        # `make front-lint` runs Prettier over every file in frontend/.
        self.assertEqual(
            runs("frontend/CLAUDE.md"),
            {"backend": False, "frontend": True, "code": True},
        )

    def test_a_layer_runs_its_own_gates_only(self) -> None:
        self.assertEqual(
            runs("backend/api/items.py"),
            {"backend": True, "frontend": False, "code": True},
        )
        self.assertEqual(
            runs("frontend/src/main.tsx"),
            {"backend": False, "frontend": True, "code": True},
        )

    def test_the_postgres_definition_is_backend(self) -> None:
        backend_only = {"backend": True, "frontend": False, "code": True}
        for path in (
            "docker/postgres/Dockerfile",
            "docker-compose.yml",
            ".env.example",
        ):
            self.assertEqual(runs(path), backend_only, path)

    def test_the_api_contract_runs_both_layers(self) -> None:
        # The backend build checks the app against the frontend's copy.
        self.assertEqual(
            runs("frontend/openapi.json"),
            {"backend": True, "frontend": True, "code": True},
        )

    def test_the_makefile_and_the_workflow_run_both_layers(self) -> None:
        for path in ("Makefile", ".github/workflows/ci.yml"):
            answer = runs(path)
            self.assertTrue(answer["backend"] and answer["frontend"], path)

    def test_tools_run_no_layer(self) -> None:
        # The `tools` job runs on every change, so a tools-only change needs
        # nothing heavy.
        self.assertEqual(
            runs("tools/ci_paths.py"),
            {"backend": False, "frontend": False, "code": True},
        )

    def test_an_empty_diff_runs_everything(self) -> None:
        self.assertEqual(runs(), {"backend": True, "frontend": True, "code": True})

    def test_output_is_one_line_per_answer(self) -> None:
        out = main(["backend/main.py\n", "\n", "README.md\n"])
        self.assertEqual(out, "backend=true\nfrontend=false\ncode=true")


class Patterns(unittest.TestCase):
    def test_the_last_matching_pattern_decides(self) -> None:
        patterns = ("docs/**", "!**/*.md", "docs/read.md")
        self.assertTrue(counts(patterns, "docs/a/b.txt"))
        self.assertFalse(counts(patterns, "docs/skip.md"))
        self.assertTrue(counts(patterns, "docs/read.md"))

    def test_a_single_star_stops_at_a_slash(self) -> None:
        self.assertTrue(counts(("*.yml",), "docker-compose.yml"))
        self.assertFalse(counts(("*.yml",), "deep/docker-compose.yml"))


class EveryTrackedFileIsClassified(unittest.TestCase):
    """A file no layer claims and `UNGATED` does not list would change with no
    gate running for it. New folders have to be placed on purpose."""

    def test_every_tracked_file_is_claimed_or_ungated(self) -> None:
        tracked = tracked_files()
        self.assertIn("Makefile", tracked, "git ls-files found nothing it should")
        stray = [
            path
            for path in tracked
            if not counts(UNGATED, path)
            and not any(counts(p, path) for p in LAYERS.values())
        ]
        self.assertEqual(
            stray, [], "add these to a layer or to UNGATED in tools/ci_paths.py"
        )

    def test_every_ungated_pattern_still_matches_something(self) -> None:
        tracked = tracked_files()
        for pattern in UNGATED:
            self.assertTrue(
                any(counts((pattern,), path) for path in tracked),
                f"UNGATED lists {pattern}, which matches no tracked file",
            )


if __name__ == "__main__":
    unittest.main()
