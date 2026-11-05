"""`tools/regression.py`'s `plan` and `run`, on a scratch repository.

Each test builds a repository with a `tools/` package, commits a base and a
fix on top, and runs the steps for real: `run` makes and removes its worktree,
and the unittest target it runs is a fresh interpreter.
"""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from tools import regression, regression_runners

BUGGY = "def double(x):\n    return x + 2\n"
FIXED = "def double(x):\n    return x * 2\n"
TEST = (
    "import unittest\nfrom tools import thing\n"
    "class T(unittest.TestCase):\n"
    "    def test_double(self):\n        self.assertEqual(thing.{call}, 6)\n"
)
HANGS = (
    "import time, unittest\nfrom tools import thing\n"
    "class T(unittest.TestCase):\n"
    "    def test_double(self):\n"
    "        while thing.double(3) != 6:\n            time.sleep(0.1)\n"
)
REASON = "No regression test on base: the bug only shows on real hardware."


class ScratchRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="regression-test-")).resolve()
        self.addCleanup(subprocess.run, ("rm", "-rf", str(self.root)))
        self.git("init", "--quiet", "--initial-branch=main")
        self.write("tools/__init__.py", "")
        self.write("tools/tests/__init__.py", "")
        self.base = self.commit("tools/thing.py", BUGGY)

    def git(self, *argv: str) -> str:
        return subprocess.run(
            ("git", "-c", "user.name=t", "-c", "user.email=t@t", *argv),
            cwd=self.root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    def write(self, path: str, text: str) -> None:
        (self.root / path).parent.mkdir(parents=True, exist_ok=True)
        (self.root / path).write_text(text, encoding="utf-8")

    def commit(self, path: str, text: str) -> str:
        self.write(path, text)
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", path)
        return self.git("rev-parse", "HEAD")

    def fix(self, call: str = "double(3)") -> None:
        self.write("tools/thing.py", FIXED + "def triple(x):\n    return x * 3\n")
        self.commit("tools/tests/test_thing.py", TEST.format(call=call))

    def run_step(self) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = regression.run(self.root, self.base, "python3.14", "bun")
        return code, out.getvalue()

    def worktrees(self) -> str:
        return self.git("worktree", "list")


class Run(ScratchRepository):
    def test_a_test_failing_on_the_base_passes(self) -> None:
        self.fix()
        code, out = self.run_step()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.worktrees().count("\n"), 0, "the base worktree is left behind")

    def test_a_test_passing_on_the_base_is_refused(self) -> None:
        self.fix(call="double(2) + 2")
        code, out = self.run_step()
        self.assertEqual(code, 1)
        self.assertIn("passes on the base", out)

    def test_a_test_failing_only_on_a_missing_name_is_refused(self) -> None:
        self.fix(call="triple(2)")
        code, out = self.run_step()
        self.assertEqual(code, 1)
        self.assertIn("cannot be judged", out)

    def test_a_test_hanging_on_the_base_has_failed(self) -> None:
        self.write("tools/thing.py", FIXED)
        self.commit("tools/tests/test_thing.py", HANGS)
        with mock.patch.object(regression_runners, "TIMEOUT", 1):
            self.assertEqual(self.run_step()[0], 0)

    def test_no_changed_test_is_refused(self) -> None:
        self.commit("tools/thing.py", FIXED)
        self.assertEqual(self.run_step()[0], 1)

    def test_the_worktree_is_removed_when_a_run_fails(self) -> None:
        self.fix()
        with mock.patch.object(regression, "run_target", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.run_step()
        self.assertEqual(self.worktrees().count("\n"), 0, self.worktrees())


class Plan(ScratchRepository):
    def plan(self, body: str, labels: list[str]) -> tuple[int, list, str]:
        answers = {"repos/o/r/issues/1": {"labels": [{"name": n} for n in labels]}}
        output = self.root / "output"
        with (
            mock.patch.object(regression, "gh", answers.__getitem__),
            mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}),
            redirect_stdout(io.StringIO()),
        ):
            code, found = regression.plan(self.root, {"body": body}, "o/r", self.base)
        return code, found, output.read_text() if output.exists() else ""

    def test_a_fix_owes_its_test_and_runs_it(self) -> None:
        self.fix()
        code, found, output = self.plan("Closes #1", ["fix"])
        self.assertEqual(
            (code, [str(t) for t in found]), (0, ["unittest tools/tests/test_thing.py"])
        )
        self.assertEqual(output, "owed=true\nbackend=false\nfrontend=false\n")

    def test_a_feature_owes_nothing(self) -> None:
        self.fix()
        self.assertEqual(self.plan("Closes #1", ["feat"])[:2], (0, []))

    def test_an_exception_owes_nothing(self) -> None:
        self.commit("tools/thing.py", FIXED)
        code, found, output = self.plan(f"Closes #1\n{REASON}", ["fix"])
        self.assertEqual((code, found), (0, []))
        self.assertIn("owed=false", output)

    def test_a_fix_with_no_test_file_is_refused(self) -> None:
        self.commit("tools/thing.py", FIXED)
        self.assertEqual(self.plan("Closes #1", ["fix"])[0], 1)

    def test_plan_writes_every_output_the_job_reads(self) -> None:
        self.fix()
        output = self.plan("Closes #1", ["fix"])[2]
        self.assertEqual([line.split("=")[0] for line in output.split()], list(regression.OUTPUTS))


if __name__ == "__main__":
    unittest.main()
