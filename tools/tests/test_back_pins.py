"""Every backend gate starts by checking the venv against its pins.

`backend/tools/pins.py` does the comparing, and the backend's own tests cover
it. These hold the Makefile to running it first, on every requirement file.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

from tools.tests.test_tools_lint import target

ROOT = Path(__file__).resolve().parents[2]


def dry_run(goal: str) -> list[str]:
    """The commands `make <goal>` would run, without running them."""
    cmd = ["make", "-n", "--no-print-directory", goal, "PYTHON=python"]
    env = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MAKELEVEL", "MFLAGS")}
    done = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return done.stdout.splitlines()


class BackendPins(unittest.TestCase):
    def test_every_requirement_file_is_checked(self) -> None:
        recipe = target((ROOT / "Makefile").read_text(encoding="utf-8"), "back-pins")
        for path in sorted((ROOT / "backend").glob("requirements*.txt")):
            self.assertIn(f" {path.name}", recipe)

    def test_each_backend_gate_checks_the_pins_first_and_once(self) -> None:
        for goal in ("backend", "back-lint", "back-build", "back-test"):
            with self.subTest(goal):
                commands = dry_run(goal)
                self.assertIn("tools/pins.py", commands[0])
                self.assertEqual(sum("tools/pins.py" in c for c in commands), 1)


if __name__ == "__main__":
    unittest.main()
