"""`.githooks/` and `make pre-commit`, run in a scratch repository.

The real hook and the real Makefile run, with a stub standing in for `python`,
`bun` and `ruff`: it records its arguments and git's environment, and fails
while a `fail` file exists, bar the pin checks: it answers `--version` as the
pinned ruff, and passes the backend's `tools/pins.py` unless a `drift` file
exists.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLEARED = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
CLEARED += ("GIT_OBJECT_DIRECTORY", "GIT_PREFIX")
DROPPED = ("MAKEFLAGS", "MAKELEVEL", "MFLAGS", "PYTHON", "BUN", "RUFF")
RUFF_PIN = "9.9.9"
SCOPE = "pre-commit: {} lint would read changes that are not part of this commit"

STUB = """\
#!/bin/sh
env | grep '^GIT_' > {out}/env.txt || true
echo "$*" >> {out}/calls.txt
[ "$1" = --version ] && echo "ruff {pin}" && exit 0
if [ "$1" = tools/pins.py ]; then
    [ -f {out}/drift ] || exit 0
    echo "pins: ruff is 0.0.1, the pin is {pin}"
    echo "pins: stub does not match requirements.txt: run make back-install"
    exit 1
fi
[ -f {out}/fail ] && exit 1
exit 0
"""


def hermetic_env() -> dict[str, str]:
    """No git, make or user config leaks in: a hook may be running this test."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in DROPPED}
    hermetic = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return env | hermetic | {"TOOLS_PYTHON": sys.executable}


class Scratch(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp())
        self.out = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo)
        self.addCleanup(shutil.rmtree, self.out)
        self.stub = self.out / "stub"
        self.stub.write_text(STUB.format(out=self.out, pin=RUFF_PIN))
        self.stub.chmod(0o755)
        self.git("init", "-q")
        for key, value in [
            ("user.email", "test@example.com"),
            ("user.name", "test"),
            ("commit.gpgsign", "false"),
            ("core.hooksPath", ".githooks"),
        ]:
            self.git("config", key, value)
        for name in ("Makefile", ".gitignore", ".githooks"):
            copy = shutil.copytree if (ROOT / name).is_dir() else shutil.copy
            copy(ROOT / name, self.repo / name)
        # The docs lint, which the hook runs, is a stub: it has its own tests,
        # and the real one would judge this scratch copy against what the
        # Makefile's comments name.
        lint = self.repo / "tools/docs_lint"
        lint.mkdir(parents=True)
        (lint / "__init__.py").write_text("")
        (lint / "__main__.py").write_text('print("docs-lint: stub")\n')
        for layer in ("backend", "frontend", "tools"):
            (self.repo / layer).mkdir(exist_ok=True)
            (self.repo / layer / "a.txt").write_text("one\n")
        (self.repo / "backend/requirements-dev.txt").write_text(f"ruff=={RUFF_PIN}\n")
        (self.repo / "backend/pyproject.toml").write_text("[tool.ruff]\n")
        (self.repo / "backend/tools").mkdir()
        shutil.copy(ROOT / "backend/tools/house_lint.py", self.repo / "backend/tools")

    def run_in(self, cmd: list[str], cwd: Path | None, **env: str):
        return subprocess.run(
            cmd,
            cwd=cwd or self.repo,
            env=hermetic_env() | env,
            capture_output=True,
            text=True,
        )

    def git(self, *args: str, cwd: Path | None = None, **env: str):
        return self.run_in(["git", *args], cwd, **env)

    def make(self, *args: str):
        return self.run_in(["make", "--no-print-directory", *args], None)

    def calls(self) -> str:
        path = self.out / "calls.txt"
        return path.read_text() if path.exists() else ""

    def make_tools_fail(self) -> None:
        (self.out / "fail").write_text("")


class TheHook(Scratch):
    def setUp(self) -> None:
        super().setUp()
        eslint = self.repo / "frontend/node_modules/.bin/eslint"
        eslint.parent.mkdir(parents=True)
        eslint.write_text("")
        eslint.chmod(0o755)
        self.git("add", ".")
        self.git("commit", "-q", "--no-verify", "-m", "base")
        self.tools = {"PYTHON": str(self.stub), "BUN": str(self.stub), "RUFF": str(self.stub)}

    def commit(self, *args: str, cwd: Path | None = None):
        return self.git("commit", "-q", *args, "-m", "x", cwd=cwd, **self.tools)

    def commits(self) -> int:
        return int(self.git("rev-list", "--count", "HEAD").stdout)

    def test_clears_gits_environment_in_a_linked_worktree(self) -> None:
        tree = self.out / "tree"
        self.git("worktree", "add", "-q", str(tree))
        (tree / "backend/a.txt").write_text("two\n")
        # From a subfolder, with `-a`: a temporary index only git's env names.
        done = self.commit("-a", cwd=tree / "backend")
        self.assertEqual(done.returncode, 0, done.stderr)
        leaked = (self.out / "env.txt").read_text()
        for name in CLEARED:
            self.assertNotIn(f"{name}=", leaked)
        self.assertIn("-m ruff check .", self.calls())
        self.assertNotIn("run check", self.calls())

    def test_a_lint_failure_blocks_the_commit_and_names_the_fix(self) -> None:
        self.make_tools_fail()
        fixes = {"backend": "make back-fix PYTHON=", "frontend": "make front-fix"}
        for layer, fix in (fixes | {"tools": "make tools-fix"}).items():
            (self.repo / layer / "a.txt").write_text(f"{layer}\n")
            done = self.commit("-a")
            self.assertNotEqual(done.returncode, 0)
            self.assertIn(fix, done.stdout + done.stderr)
            self.assertIn("git commit --no-verify", done.stderr)
            self.git("checkout", "--", layer)
        self.assertEqual(self.commits(), 1)

    def test_what_the_commit_leaves_out_of_a_touched_layer_is_refused(self) -> None:
        a, b = self.repo / "backend/a.txt", self.repo / "backend/b.txt"
        cases = {
            "an unstaged edit": (lambda: a.write_text("on disk\n"), "a.txt", ()),
            "an untracked file": (lambda: b.write_text("new\n"), "b.txt", ()),
            "a staged file the path leaves out": (
                lambda: (b.write_text("new\n"), self.git("add", str(b))),
                "b.txt",
                ("backend/a.txt",),
            ),
        }
        for case, (leave_out, listed, path) in cases.items():
            with self.subTest(case):
                a.write_text("staged\n")
                self.git("add", str(a))
                leave_out()
                done = self.commit(*path)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn(SCOPE.format("backend"), done.stderr)
                self.assertIn(f"backend/{listed}", done.stderr)
                self.assertEqual(self.calls(), "")
                self.git("reset", "-q", "--hard")
                b.unlink(missing_ok=True)

    def test_the_backend_venv_is_preferred(self) -> None:
        venv = self.repo / "backend/.venv/bin/python"
        venv.parent.mkdir(parents=True)
        shutil.copy(self.stub, venv)
        (self.repo / "backend/a.txt").write_text("two\n")
        done = self.git("commit", "-q", "-a", "-m", "x")  # no PYTHON given
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("tools/pins.py requirements.txt requirements-dev.txt", self.calls())
        self.assertIn("-m ruff check .", self.calls())

    def test_a_drifted_venv_blocks_the_commit_before_lint(self) -> None:
        (self.out / "drift").write_text("")
        (self.repo / "backend/a.txt").write_text("two\n")
        done = self.commit("-a")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("pre-commit: pins: ruff is 0.0.1", done.stderr)
        self.assertIn("run make back-install", done.stderr)
        self.assertNotIn("-m ruff check", self.calls())
        self.assertEqual(self.commits(), 1)

    def test_a_commit_to_tools_runs_its_lint_and_length_limits(self) -> None:
        (self.repo / "tools/a.txt").write_text("two\n")
        done = self.commit("-a")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("check --config backend/pyproject.toml tools", self.calls())
        said = done.stdout + done.stderr  # git hands a hook's stdout to stderr
        self.assertIn("house_lint: clean", said)
        self.assertIn("backend skipped", said)

    def test_tools_is_held_to_the_same_scope_check_over_what_its_lint_reads(self) -> None:
        cases = {"untracked": "tools/b.txt", "the backend's ruff rules": "backend/pyproject.toml"}
        for case, left_out in cases.items():
            with self.subTest(case):
                (self.repo / "tools/a.txt").write_text("staged\n")
                self.git("add", "tools/a.txt")
                (self.repo / left_out).write_text("on disk only\n")
                done = self.commit()
                self.assertNotEqual(done.returncode, 0)
                self.assertIn(SCOPE.format("tools"), done.stderr)
                self.assertIn(left_out, done.stderr)
                self.assertEqual(self.calls(), "")
                self.git("reset", "-q", "--hard")
                (self.repo / "tools/b.txt").unlink(missing_ok=True)

    def test_a_change_to_what_tools_lint_reads_lints_tools(self) -> None:
        (self.repo / "backend/pyproject.toml").write_text("[tool.ruff]\nline-length = 1\n")
        done = self.commit("-a")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("check --config backend/pyproject.toml tools", self.calls())

    def test_a_merge_is_checked_too(self) -> None:
        self.git("checkout", "-q", "-b", "side")
        (self.repo / "backend/a.txt").write_text("side\n")
        self.assertEqual(self.commit("-a").returncode, 0)
        self.git("checkout", "-q", "-")
        self.make_tools_fail()
        done = self.git("merge", "-q", "--no-ff", "-m", "m", "side", **self.tools)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("backend lint failed", done.stdout + done.stderr)
        self.assertEqual(self.commits(), 1)


class TheMakeTarget(Scratch):
    """Never a silent pass over a layer it could not check."""

    def test_an_untouched_layer_is_skipped_out_loud(self) -> None:
        done = self.make("pre-commit")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("backend skipped", done.stdout)
        self.assertIn("frontend skipped", done.stdout)
        self.assertIn("tools skipped", done.stdout)

    def test_a_touched_layer_without_its_tools_fails(self) -> None:
        (self.repo / "backend/é.txt").write_text("a path git quotes\n")
        self.git("add", "backend/é.txt", "frontend")
        back = self.make("pre-commit-back", "PYTHON=/nonexistent/python")
        self.assertNotEqual(back.returncode, 0)
        self.assertIn("no interpreter at PYTHON=/nonexistent/python", back.stdout)
        self.assertIn("make back-install", back.stdout)
        front = self.make("pre-commit-front", "BUN=/nonexistent/bun")
        self.assertNotEqual(front.returncode, 0)
        self.assertIn("make front-install", front.stdout)

    def test_touched_tools_without_the_pinned_ruff_fails(self) -> None:
        self.git("add", "tools")
        for case, args in {
            "missing": ("RUFF=/nonexistent/ruff",),
            "off the pin": (f"RUFF={self.stub}", "RUFF_PIN=0.0.1"),
        }.items():
            with self.subTest(case):
                done = self.make("pre-commit-tools", *args)
                self.assertNotEqual(done.returncode, 0)
                self.assertIn("pre-commit: tools-ruff:", done.stdout)
                self.assertIn("run make back-install", done.stdout)
                self.assertNotIn("tools-fix", done.stdout)
                self.assertNotIn("check --config", self.calls())

    def test_back_fix_formats_even_when_errors_are_left(self) -> None:
        self.make_tools_fail()
        done = self.make("back-fix", f"PYTHON={self.stub}")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("-m ruff format .", self.calls())

    def test_no_fixer_runs_off_its_pin(self) -> None:
        (self.out / "drift").write_text("")
        back = self.make("back-fix", f"PYTHON={self.stub}")
        tools = self.make("tools-fix", f"RUFF={self.stub}", "RUFF_PIN=0.0.1")
        self.assertNotEqual(back.returncode, 0)
        self.assertNotEqual(tools.returncode, 0)
        self.assertNotIn("--fix", self.calls())

    def test_tools_fix_formats_even_when_errors_are_left(self) -> None:
        self.make_tools_fail()
        done = self.make("tools-fix", f"RUFF={self.stub}")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("format --config backend/pyproject.toml tools", self.calls())


if __name__ == "__main__":
    unittest.main()
