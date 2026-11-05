"""`.githooks/pre-commit` and `make pre-commit`, run in a scratch repository."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLEARED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
CLEARED += ("GIT_OBJECT_DIRECTORY", "GIT_PREFIX")

# Stands in for the real Makefile: records what the hook handed it, and fails
# when a `fail` file exists.
FAKE_MAKEFILE = """\
pre-commit:
\t@env | grep '^GIT_' > {out}/env.txt || true
\t@echo "$(STAGED_LAYERS)" > {out}/layers.txt
\t@test ! -f fail
"""


def clean_env() -> dict[str, str]:
    """This process's environment without git's, in case a hook is running it."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


class Scratch(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp())
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        self.addCleanup(shutil.rmtree, self.out)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", ".githooks")
        (self.repo / ".githooks").mkdir()
        shutil.copy(ROOT / ".githooks/pre-commit", self.repo / ".githooks")
        for layer in ("backend", "frontend"):
            (self.repo / layer).mkdir()
            (self.repo / layer / "a.txt").write_text("one\n")

    def git(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            env=clean_env(),
            capture_output=True,
            text=True,
        )

    def make(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["make", "--no-print-directory", *args],
            cwd=self.repo,
            env=clean_env(),
            capture_output=True,
            text=True,
        )


class TheHook(Scratch):
    def setUp(self) -> None:
        super().setUp()
        (self.repo / "Makefile").write_text(FAKE_MAKEFILE.format(out=self.out))
        self.git("add", ".")
        self.assertEqual(self.git("commit", "-q", "-m", "base").returncode, 0)

    def test_clears_gits_environment_and_runs_from_the_top(self) -> None:
        (self.repo / "backend/a.txt").write_text("two\n")
        # From a subfolder, with `-a`: a temporary index only git's env names.
        done = self.git("commit", "-q", "-a", "-m", "x", cwd=self.repo / "backend")
        self.assertEqual(done.returncode, 0, done.stderr)
        leaked = (self.out / "env.txt").read_text()
        for name in CLEARED:
            self.assertNotIn(f"{name}=", leaked)
        self.assertEqual((self.out / "layers.txt").read_text().split(), ["backend"])

    def test_a_failure_blocks_the_commit_and_says_how_to_skip(self) -> None:
        (self.repo / "fail").write_text("")
        (self.repo / "frontend/a.txt").write_text("two\n")
        done = self.git("commit", "-q", "-a", "-m", "x")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("git commit --no-verify", done.stderr)
        self.assertIn("make front-fix", done.stderr)
        self.assertEqual(self.git("rev-list", "--count", "HEAD").stdout.strip(), "1")


class TheMakeTarget(Scratch):
    """The real Makefile: never a silent pass over a layer it could not check."""

    def setUp(self) -> None:
        super().setUp()
        shutil.copy(ROOT / "Makefile", self.repo)

    def test_an_untouched_layer_is_skipped_out_loud(self) -> None:
        done = self.make("pre-commit")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("backend skipped", done.stdout)
        self.assertIn("frontend skipped", done.stdout)

    def test_a_touched_layer_without_its_tools_fails(self) -> None:
        self.git("add", "backend", "frontend")
        back = self.make("pre-commit-back", "PYTHON=/nonexistent/python")
        self.assertNotEqual(back.returncode, 0)
        self.assertIn("make back-install", back.stdout)
        front = self.make("pre-commit-front")
        self.assertNotEqual(front.returncode, 0)
        self.assertIn("make front-install", front.stdout)


if __name__ == "__main__":
    unittest.main()
