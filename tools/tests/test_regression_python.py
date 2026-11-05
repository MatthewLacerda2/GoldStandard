"""Which interpreter `make regression` runs the backend's tests with, and the
refusal when it cannot: the Makefile's `PYTHON` as the backend gates take it
(relative to backend/), or, left unset, backend/'s venv."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tools import regression
from tools.tests.test_back_pins import dry_run as back_pins
from tools.tests.test_regression_run import ScratchRepository

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "backend" / "tools" / "pins.py"
REQUIREMENTS = ["requirements.txt", "requirements-dev.txt"]
# A distribution only this test installs: on PYTHONPATH, pins.py finds it.
FIXTURE = "regression-fixture-dist"


def dry_run(*args: str, **env: str) -> str:
    """What `make regression` would run, with no PYTHON but `env`'s."""
    unset = ("MAKEFLAGS", "MAKELEVEL", "MFLAGS", "PYTHON")
    env = {**{k: v for k, v in os.environ.items() if k not in unset}, **env}
    cmd = ["make", "-n", "--no-print-directory", "regression", "BASE=x", *args]
    done = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return done.stdout


class Interpreter(unittest.TestCase):
    def setUp(self) -> None:
        self.head = Path(tempfile.mkdtemp(prefix="regression-python-"))
        self.addCleanup(shutil.rmtree, self.head)

    def test_a_relative_path_is_backends(self) -> None:
        found = regression.interpreter(self.head, ".venv/bin/python")
        self.assertEqual(found, str(self.head / "backend/.venv/bin/python"))

    def test_a_name_or_an_absolute_path_is_kept(self) -> None:
        for python in ("python", "/usr/bin/python3"):
            self.assertEqual(regression.interpreter(self.head, python), python)
        self.assertEqual(regression.interpreter(self.head, "~/py"), str(Path.home() / "py"))

    def test_the_default_is_the_venv_when_there_is_one(self) -> None:
        self.assertEqual(regression.interpreter(self.head, None), regression.DEFAULT_PYTHON)
        venv = self.head / regression.VENV
        venv.parent.mkdir(parents=True)
        venv.touch()
        self.assertEqual(regression.interpreter(self.head, None), str(venv))
        self.assertEqual(regression.interpreter(self.head, ""), str(venv))


class Makefile(unittest.TestCase):
    def test_python_is_passed_only_when_it_is_set(self) -> None:
        self.assertNotIn("--python", dry_run())
        self.assertNotIn("--python", dry_run("PYTHON="))
        self.assertIn("--python .venv/bin/python ", dry_run("PYTHON=.venv/bin/python"))
        self.assertIn("--python .venv/bin/python ", dry_run(PYTHON=".venv/bin/python"))

    def test_the_requirement_files_are_back_pins(self) -> None:
        checked = back_pins("back-pins")[0].split("tools/pins.py ")[1].split()
        passed = dry_run().split("--requirement ")[1:]
        self.assertEqual([p.split()[0] for p in passed], checked)


class Unready(ScratchRepository):
    """A backend test, and an interpreter checked against the head's pins."""

    def setUp(self) -> None:
        super().setUp()
        self.write("backend/tools/pins.py", PINS.read_text(encoding="utf-8"))
        self.commit("backend/tests/test_items.py", "def test_x():\n    assert False\n")

    def pin(self, version: str) -> None:
        for name in REQUIREMENTS:
            self.write(f"backend/{name}", f"{FIXTURE}=={version}\n")
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", "pins")

    def run_with(self, python: str, requirements: list[str] = REQUIREMENTS) -> tuple[int, str]:
        site = self.root / "site"
        info = site / f"{FIXTURE.replace('-', '_')}-1.0.dist-info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {FIXTURE}\nVersion: 1.0\n")
        out = io.StringIO()
        with (
            redirect_stdout(out),
            mock.patch.dict(os.environ, {"PYTHONPATH": str(site)}),
            mock.patch.object(regression, "base_worktree") as self.worktree,
            mock.patch.object(regression, "on_base", return_value={}) as self.ran,
            mock.patch.object(regression, "drop_database") as self.dropped,
        ):
            code = regression.run(self.root, self.base, python, "bun", requirements)
        return code, out.getvalue()

    def assert_refused_up_front(self, code: int) -> None:
        self.assertEqual(code, 1)
        self.ran.assert_not_called()
        self.worktree.assert_not_called()
        self.dropped.assert_not_called()

    def test_an_interpreter_off_the_pins_is_named_not_the_test(self) -> None:
        self.pin("2.0")
        code, out = self.run_with(sys.executable)
        self.assert_refused_up_front(code)
        self.assertIn(f"cannot run with {sys.executable}", out)
        self.assertIn(f"{FIXTURE} is 1.0, the pin is 2.0", out)
        self.assertIn("make back-install", out)
        self.assertNotIn("cannot be judged", out)

    def test_a_missing_or_unrunnable_interpreter_is_named(self) -> None:
        self.pin("1.0")
        missing = str(self.root / "backend/.venv/bin/python")
        self.assertIn(f"no interpreter at {missing}", self.run_with(missing)[1])
        plain = self.root / "plain"
        plain.write_text("")
        code, out = self.run_with(str(plain))
        self.assert_refused_up_front(code)
        self.assertIn(f"{plain} is not executable", out)

    def test_no_requirement_file_refuses(self) -> None:
        self.pin("1.0")
        code, out = self.run_with(sys.executable, [])
        self.assert_refused_up_front(code)
        self.assertIn("no requirement file", out)

    def test_the_pins_are_the_head_commits(self) -> None:
        # Committed off the pins, and on them in the working tree: judged by the commit.
        self.pin("2.0")
        for name in REQUIREMENTS:
            self.write(f"backend/{name}", f"{FIXTURE}==1.0\n")
        self.assert_refused_up_front(self.run_with(sys.executable)[0])

    def test_an_interpreter_on_the_pins_runs_the_tests(self) -> None:
        self.pin("1.0")
        code, out = self.run_with(sys.executable)
        self.ran.assert_called_once()
        self.assertNotIn("cannot run with", out)


if __name__ == "__main__":
    unittest.main()
