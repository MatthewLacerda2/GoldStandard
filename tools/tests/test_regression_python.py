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
from importlib import metadata
from pathlib import Path
from unittest import mock

from tools import regression
from tools.tests.test_regression_run import ScratchRepository

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / "backend" / "tools" / "pins.py"


def dry_run(*args: str) -> str:
    """What `make regression` would run, with no PYTHON of the caller's."""
    unset = ("MAKEFLAGS", "MAKELEVEL", "MFLAGS", "PYTHON")
    env = {k: v for k, v in os.environ.items() if k not in unset}
    cmd = ["make", "-n", "--no-print-directory", "regression", "BASE=x", *args]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True).stdout


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

    def test_the_default_is_the_venv_when_there_is_one(self) -> None:
        self.assertEqual(regression.interpreter(self.head, None), regression.DEFAULT_PYTHON)
        venv = self.head / regression.VENV
        venv.parent.mkdir(parents=True)
        venv.touch()
        self.assertEqual(regression.interpreter(self.head, None), str(venv))

    def test_the_makefile_passes_python_only_when_it_is_set(self) -> None:
        self.assertNotIn("--python", dry_run())
        self.assertIn("--python .venv/bin/python ", dry_run("PYTHON=.venv/bin/python"))


class Unready(ScratchRepository):
    """A backend test, and an interpreter checked against the head's pins."""

    def setUp(self) -> None:
        super().setUp()
        self.write("backend/tools/pins.py", PINS.read_text(encoding="utf-8"))
        self.commit("backend/tests/test_items.py", "def test_x():\n    assert False\n")

    def pin(self, line: str) -> None:
        for name in ("requirements.txt", "requirements-dev.txt"):
            self.write(f"backend/{name}", line + "\n")

    def run_with(self, python: str) -> tuple[int, str, mock.Mock]:
        out = io.StringIO()
        with (
            redirect_stdout(out),
            mock.patch.object(regression, "run_target", return_value="failed") as ran,
            mock.patch.object(regression, "drop_database"),
        ):
            code = regression.run(self.root, self.base, python, "bun")
        return code, out.getvalue(), ran

    def test_an_interpreter_off_the_pins_is_named_not_the_test(self) -> None:
        self.pin("pytest==0.0.1")
        code, out, ran = self.run_with(sys.executable)
        self.assertEqual(code, 1)
        self.assertIn(f"cannot run with {sys.executable}", out)
        self.assertIn("pytest", out)
        self.assertIn("make back-install", out)
        self.assertNotIn("cannot be judged", out)
        ran.assert_not_called()
        # Nothing ran on the base, so it has no worktree and no database left.
        self.assertEqual(self.worktrees().count("\n"), 0, self.worktrees())

    def test_a_missing_interpreter_is_named(self) -> None:
        self.pin("pytest==0.0.1")
        code, out, ran = self.run_with(str(self.root / "backend/.venv/bin/python"))
        self.assertEqual(code, 1)
        self.assertIn(f"no interpreter at {self.root}/backend/.venv/bin/python", out)
        ran.assert_not_called()

    def test_an_interpreter_on_the_pins_runs_the_tests(self) -> None:
        installed = next(iter(metadata.distributions()), None)
        if installed is None:
            self.skipTest("this interpreter has no package to pin")
        self.pin(f"{installed.metadata['Name']}=={installed.version}")
        code, out, ran = self.run_with(sys.executable)
        self.assertEqual(code, 0, out)
        ran.assert_called_once()


if __name__ == "__main__":
    unittest.main()
