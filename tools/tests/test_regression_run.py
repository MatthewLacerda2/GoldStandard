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

from tools import regression

BUGGY = "def double(x):\n    return x + 2\n"
FIXED = "def double(x):\n    return x * 2\n"
TEST = (
    "import unittest\nfrom tools import thing\n"
    "class T(unittest.TestCase):\n"
    "    def test_double(self):\n        self.assertEqual(thing.{call}, 6)\n"
)
REASON = "No regression test on base: the bug only shows on real hardware."
# A test file the base already has, whose test fails on every commit.
OLD = (
    "import unittest\nfrom tools import thing\n"
    "class {cls}:\n"
    "    def test_old(self):\n        self.fail('fails on every commit')\n"
)
CASE = "T(unittest.TestCase)"
# The imports, and a decorator that does not keep its method's name.
HIDE = "import unittest\nfrom tools import thing\ndef hide(f):\n    return lambda self: f(self)\n"
NEW = "    def test_new(self):\n        self.assertEqual(thing.{call}, 6)\n"
HIDDEN = NEW.format(call="double(2) + 2").replace("def test_new", "@hide\n    def test_hidden")


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

    def test_no_changed_test_is_refused(self) -> None:
        self.commit("tools/thing.py", FIXED)
        self.assertEqual(self.run_step()[0], 1)

    def test_the_worktree_is_removed_when_a_run_fails(self) -> None:
        self.fix()
        with mock.patch.object(regression, "run_target", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.run_step()
        self.assertEqual(self.worktrees().count("\n"), 0, self.worktrees())


class PerTest(ScratchRepository):
    """Only the tests the change adds or changes are judged."""

    def setUp(self) -> None:
        super().setUp()
        self.base = self.commit("tools/tests/test_thing.py", OLD.format(cls=CASE))

    def fix_with(self, call: str, tail: str = "") -> str:
        self.write("tools/thing.py", FIXED)
        self.commit(
            "tools/tests/test_thing.py", OLD.format(cls=CASE) + NEW.format(call=call) + tail
        )
        return self.run_step()[1]

    def test_an_older_failing_test_cannot_pass_a_new_one(self) -> None:
        out = self.fix_with(call="double(2) + 2")
        self.assertIn("judging the tests the change adds or changes:\n  T.test_new", out)
        self.assertIn("Ran 1 test", out)
        self.assertIn("test_thing.py (T.test_new): passes on the base.", out)

    def test_a_new_test_failing_on_the_base_passes(self) -> None:
        self.assertIn("a changed test fails on the base", self.fix_with(call="double(3)"))

    def test_an_inherited_test_runs_in_the_case_that_inherits_it(self) -> None:
        mixed = NEW.format(call="double(2) + 2").replace("test_new", "test_mixed")
        tail = f"class Mixin:\n{mixed}class U(Mixin, unittest.TestCase):\n    pass\n"
        out = self.fix_with(call="double(2) + 2", tail=tail)
        self.assertIn("  Mixin.test_mixed\n  T.test_new\n", out)
        self.assertIn("Ran 2 tests", out)
        self.assertIn("Refused:", out)

    def hidden_fix(self, *new: str) -> tuple[int, str]:
        """Commit the fix, and `new` tests after the older one."""
        self.write("tools/thing.py", FIXED)
        older = OLD.format(cls=CASE).split("\n", 2)[2]  # without its imports
        self.commit("tools/tests/test_thing.py", HIDE + older + "".join(new))
        return self.run_step()

    def test_a_test_a_decorator_hides_cannot_pass(self) -> None:
        # Without `functools.wraps` the method is no longer `T.test_hidden`.
        code, out = self.hidden_fix(NEW.format(call="double(2) + 2"), HIDDEN)
        self.assertIn("named, but no test here runs it: T.test_hidden", out)
        self.assertIn("cannot be judged", out)
        self.assertEqual(code, 1)

    def test_every_named_test_hidden_runs_the_whole_file(self) -> None:
        code, out = self.hidden_fix(HIDDEN)
        self.assertIn("no test here is one of those named: running the whole file", out)
        self.assertEqual(code, 0, out)  # the older failing test counts again: a documented limit

    def test_a_change_to_no_test_judges_the_whole_file(self) -> None:
        self.write("tools/thing.py", FIXED)
        self.commit("tools/tests/test_thing.py", "# helpers\n" + OLD.format(cls=CASE))
        code, out = self.run_step()
        self.assertIn("judging the whole file: no test the change adds or changes", out)
        self.assertEqual(code, 0, out)


class Plan(ScratchRepository):
    def plan(self, body: str, labels: list[str]) -> tuple[int, list, str]:
        answers = {"repos/o/r/issues/1": {"labels": [{"name": n} for n in labels]}}

        def gh(path: str) -> dict:
            if path not in answers:
                raise LookupError(f"{path}: Not Found (HTTP 404)")
            return answers[path]

        output = self.root / "output"
        with (
            mock.patch.object(regression, "gh", gh),
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

    def test_an_issue_that_cannot_be_read_is_refused(self) -> None:
        self.fix()
        self.assertEqual(self.plan("Closes #2", ["fix"])[0], 1)

    def test_plan_writes_every_output_the_job_reads(self) -> None:
        self.fix()
        output = self.plan("Closes #1", ["fix"])[2]
        self.assertEqual([line.split("=")[0] for line in output.split()], list(regression.OUTPUTS))


if __name__ == "__main__":
    unittest.main()
