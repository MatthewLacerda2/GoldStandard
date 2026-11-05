"""Ruff holds `tools/` to the backend's version and rules, locally and in CI.

The version is pinned once, in `backend/requirements-dev.txt`: locally `make
tools-lint` runs the backend venv's ruff, which that file installed, and CI's
`tools` job installs the pin it reads from the same file, and `tools-lint`
fails on a local ruff off that pin. The rules are `backend/pyproject.toml`'s,
passed with `--config`. A second pin or a second
config is how the two would drift apart, so these tests fail on one.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tools.tests.test_ci_workflow import WORKFLOW, jobs

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = "backend/requirements-dev.txt"
CONFIG = "backend/pyproject.toml"


def target(makefile: str, name: str) -> str:
    """The recipe of Makefile target `name`."""
    match = re.search(rf"^{name}:.*\n((?:\t.*\n)+)", makefile, flags=re.MULTILINE)
    assert match, f"the Makefile has no `{name}` target"
    return match.group(1)


class OneRuff(unittest.TestCase):
    def test_the_backend_pins_ruff_exactly_once(self) -> None:
        pins = re.findall(r"(?m)^ruff==\S+$", (ROOT / REQUIREMENTS).read_text(encoding="utf-8"))
        self.assertEqual(len(pins), 1, f"{REQUIREMENTS} must pin ruff with == once")

    def test_ci_installs_the_backends_pin_and_no_version_of_its_own(self) -> None:
        tools = jobs(WORKFLOW.read_text(encoding="utf-8"))["tools"]
        self.assertIn(REQUIREMENTS, tools)
        self.assertNotRegex(tools, r"ruff==\d")
        self.assertIn("RUFF=ruff", tools)

    def test_both_ruff_runs_read_the_backends_config(self) -> None:
        recipe = target((ROOT / "Makefile").read_text(encoding="utf-8"), "tools-lint")
        runs = [line for line in recipe.splitlines() if line.startswith("\t$(RUFF) ")]
        self.assertEqual(len(runs), 2, "tools-lint runs `ruff check` and `ruff format`")
        for line in runs:
            self.assertIn(f"--config {CONFIG} tools", line)

    def test_a_local_ruff_off_the_pin_fails(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertRegex(makefile, rf"(?m)^RUFF_PIN := .*{re.escape(REQUIREMENTS)}")
        self.assertIn('"ruff $(RUFF_PIN)"', target(makefile, "tools-lint"))


if __name__ == "__main__":
    unittest.main()
