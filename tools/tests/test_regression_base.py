"""`run`'s worktree of the base: one per run, given the head's settings, and
removed with its test database however the run ends."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest import mock

from tools import regression, regression_runners
from tools.tests.test_regression_run import FIXED, ScratchRepository

CONFTEST = Path(__file__).resolve().parents[2] / "backend" / "tests" / "conftest.py"
# Hangs on the base, after starting a process of its own that would outlive it.
HANGS = """import subprocess, time, unittest
from pathlib import Path
from tools import thing
class T(unittest.TestCase):
    def test_double(self):
        if thing.double(3) != 6:
            child = subprocess.Popen(["sleep", "60"])
            Path({pidfile!r}).write_text(str(child.pid))
            time.sleep(60)
"""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class BaseWorktree(ScratchRepository):
    def backend_fix(self) -> None:
        self.commit("backend/tests/test_items.py", "def test_x():\n    assert False\n")
        # The scratch repository has no pins to check the interpreter against:
        # test_regression_python checks that step.
        self.enterContext(mock.patch.object(regression, "backend_ready", return_value=[]))

    def test_each_run_has_a_worktree_of_its_own(self) -> None:
        # Two runs at once must not share a worktree, or its test database.
        with (
            regression.base_worktree(self.root, self.base) as one,
            regression.base_worktree(self.root, self.base) as other,
        ):
            self.assertNotEqual(one, other)
            self.assertTrue((one / "tools/thing.py").is_file())
            self.assertTrue((other / "tools/thing.py").is_file())
        self.assertFalse(one.exists() or other.exists())
        self.assertEqual(self.worktrees().count("\n"), 0, self.worktrees())

    def test_the_heads_settings_reach_the_base(self) -> None:
        # backend/.env is untracked, so a worktree has none of its own.
        self.backend_fix()
        self.write("backend/.env", "DATABASE_URL=postgresql+asyncpg://u:p@elsewhere:1/app\n")
        seen: list[str] = []

        def runs(t, tree, *_):
            seen.append((tree / "backend" / ".env").read_text(encoding="utf-8"))
            return regression_runners.FAILED

        with (
            mock.patch.object(regression, "run_target", runs),
            mock.patch.object(regression, "drop_database"),
        ):
            self.assertEqual(self.run_step()[0], 0)
        self.assertIn("elsewhere:1", seen[0])

    def test_the_base_database_is_dropped_when_a_run_fails(self) -> None:
        self.backend_fix()
        with (
            mock.patch.object(regression, "run_target", side_effect=RuntimeError("boom")),
            mock.patch.object(regression, "drop_database") as drop,
        ):
            with self.assertRaises(RuntimeError):
                self.run_step()
        drop.assert_called_once()
        self.assertFalse(drop.call_args.args[0].exists(), "the worktree outlived the run")

    def test_no_database_is_dropped_without_a_backend_test(self) -> None:
        self.fix()
        with mock.patch.object(regression, "drop_database") as drop:
            self.assertEqual(self.run_step()[0], 0)
        drop.assert_not_called()

    def test_the_drop_uses_names_the_conftest_defines(self) -> None:
        # The database's name and connection are the conftest's, never rebuilt here.
        conftest = CONFTEST.read_text(encoding="utf-8")
        for name in ("_drop_database", "_test_db_name"):
            self.assertIn(name, regression_runners.DROP_DATABASE)
            self.assertIn(f"def {name}(", conftest)

    def test_a_timeout_fails_and_kills_what_the_test_started(self) -> None:
        pidfile = self.root / "child.pid"
        self.write("tools/thing.py", FIXED)
        self.commit("tools/tests/test_thing.py", HANGS.format(pidfile=str(pidfile)))
        with mock.patch.object(regression_runners, "TIMEOUT", 2):
            self.assertEqual(self.run_step()[0], 0)
        pid = int(pidfile.read_text())
        deadline = time.monotonic() + 5
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertFalse(alive(pid), "the test's own child outlived the timeout")
