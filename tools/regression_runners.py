"""How `tools/regression.py` runs one target on the base, and judges it.

A target is one test file a runner runs by name: a pytest file of `backend/`,
a vitest file of `frontend/`, a unittest file of `tools/`. It runs only the
tests the change adds or changes (`tools/regression_names.py` finds them, and
says when there are none to find: then the whole file runs). Each run ends in
one of three outcomes:

    failed   a test failed: the bug shows on the base, which is the point
    passed   every test passed: the test does not reproduce the bug
    broken   nothing could be judged: the file does not import or compile,
             no test ran, or every failure is a name the base lacks

A name the base lacks is what a test calling only the fix's new API fails
with on any base, so it proves nothing:

    Python      `ImportError`, `NameError`, `AttributeError` (but not on
                `None`, which is how a bug usually shows), and a `TypeError`
                for a signature the base lacks: an unexpected keyword
                argument, too many positional ones, or a missing one
    JavaScript  `ReferenceError: … is not defined`, `TypeError: … is not a
                function` / `constructor`, and React's `Element type is
                invalid … got: undefined` (a component the module lacks)

What a pattern cannot see still counts as a failure: a test of a route the
fix adds gets the base's 404, and a new constant reads as `undefined`. Only
the tests that run are judged, so an older test of the same file failing on
the base counts only when the file runs whole.

Only a test body's failure counts: pytest's setup errors (no database) are
broken, not failed. A run past `TIMEOUT` has failed: a hung test is the bug
showing, and its whole process group is killed.

Pure but for `call`, `install`, `run_target` and `drop_database`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import NamedTuple

PASSED, FAILED, BROKEN = "passed", "failed", "broken"
TIMEOUT = 600  # seconds per target, and per dependency install

_PY_MISSING = re.compile(
    r"^(?:\w+\.)*(?:ImportError|ModuleNotFoundError|NameError|AttributeError)\b"
)
_PY_NONE = re.compile(r"^AttributeError: 'NoneType' object")
_PY_SIGNATURE = re.compile(
    r"^TypeError: .*(?:got an unexpected keyword argument"
    r"|takes .* positional arguments? but \d+ (?:was|were) given"
    r"|missing \d+ required (?:positional|keyword-only) arguments?)"
)
_JS_MISSING = re.compile(
    r"^(?:ReferenceError: .* is not defined"
    r"|TypeError: .* is not a (?:function|constructor)"
    r"|(?:\w*Error: )?Element type is invalid.* but got: undefined)"
)


class Target(NamedTuple):
    """One test file: `layer` is the directory its runner runs from, `path`
    the file relative to it, `tests` what of it runs (every test, if none):
    pytest node ids, vitest full names, unittest qualified names."""

    runner: str
    layer: str
    path: str
    tests: tuple[str, ...] = ()

    def __str__(self) -> str:
        return f"{self.runner} {PurePosixPath(self.layer, self.path)}"


def py_missing(failure: str) -> bool:
    if _PY_SIGNATURE.match(failure):
        return True
    return bool(_PY_MISSING.match(failure)) and not _PY_NONE.match(failure)


def js_missing(failure: str) -> bool:
    return bool(_JS_MISSING.match(failure))


def judged(failures: list[str], missing: Callable[[str], bool]) -> str:
    """A run that exited non-zero: failed, unless no test failed or each
    failure is only a name the base lacks."""
    if not failures or all(missing(f) for f in failures):
        return BROKEN
    return FAILED


def pytest_outcome(code: int, junit: str) -> str:
    """From pytest's exit code and JUnit XML report. A test body's failure is
    a `<failure>`; a setup or collection one is an `<error>`, and an exit code
    past 1 means the file did not import or ran nothing. A pass needs a test
    that ran, not one skipped."""
    try:
        report = ElementTree.fromstring(junit)
    except ElementTree.ParseError:  # none, or cut short by a kill
        return BROKEN
    if code == 0:
        ran = any(case.find("skipped") is None for case in report.iter("testcase"))
        return PASSED if ran else BROKEN
    if code != 1:
        return BROKEN
    return judged([f.get("message") or "" for f in report.iter("failure")], py_missing)


def vitest_outcome(code: int, report: str) -> str:
    """From vitest's exit code and JSON report. A file that does not load
    reports no failing test; a `-t` that matches nothing skips every test and
    exits 0, so a pass needs a test that passed."""
    try:
        files = json.loads(report).get("testResults") or []
    except ValueError:
        return BROKEN
    tests = [test for file in files for test in file.get("assertionResults") or []]
    if code == 0:
        return PASSED if any(test.get("status") == "passed" for test in tests) else BROKEN
    failures = [
        (test.get("failureMessages") or [""])[0] for test in tests if test.get("status") == "failed"
    ]
    return judged(failures, js_missing)


def unittest_outcome(code: int, report: str) -> str:
    """From `UNITTEST`'s exit code and report. A pass needs a test that ran,
    and every named test found: one a decorator hid never ran, so a pass
    proves nothing for it (a failure of another still counts)."""
    try:
        done = json.loads(report)
    except ValueError:
        return BROKEN
    if not done.get("loaded"):
        return BROKEN
    if code == 0:
        return PASSED if done.get("ran") and not done.get("unmatched") else BROKEN
    return judged(done["failures"], py_missing)


# One unittest file, run in a fresh interpreter from the base worktree so
# nothing of the head is imported: the tests named after it, if any, by the
# qualified name of the method each runs (the whole file when none matches).
# It reports each failure as `Type: message`, and how many tests ran and were
# not skipped, for `unittest_outcome` to judge the way pytest's are.
UNITTEST = """
import json, sys, unittest
from pathlib import Path
file, report, names = Path(sys.argv[1]).resolve(), sys.argv[2], set(sys.argv[3:])
failures = []
class Result(unittest.TextTestResult):
    def note(self, err):
        failures.append(f"{err[0].__name__}: {err[1]}")
    def addError(self, test, err):
        self.note(err); super().addError(test, err)
    def addFailure(self, test, err):
        self.note(err); super().addFailure(test, err)
    def addSubTest(self, test, subtest, err):
        if err is not None:
            self.note(err)
        super().addSubTest(test, subtest, err)
top = file.parent
while (top / "__init__.py").exists():
    top = top.parent
loader = unittest.TestLoader()
suite = loader.discover(str(file.parent), pattern=file.name, top_level_dir=str(top))
def cases(suite):
    for test in suite:
        yield from cases(test) if isinstance(test, unittest.TestSuite) else [test]
def qualname(test):
    return getattr(getattr(type(test), test._testMethodName, None), "__qualname__", "")
chosen = [t for t in cases(suite) if qualname(t) in names]
unmatched = sorted(names - {qualname(t) for t in chosen}) if chosen else []
if chosen:
    suite = unittest.TestSuite(chosen)
elif names:
    print("no test here is one of those named: running the whole file")
if unmatched:
    print("named, but no test here runs it:", *unmatched)
loaded = not loader.errors and suite.countTestCases() > 0
print("\\n".join(loader.errors))
run = loaded and unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite)
ran = run.testsRun - len(run.skipped) if run else 0
done = {"loaded": loaded, "ran": ran, "unmatched": unmatched, "failures": failures}
Path(report).write_text(json.dumps(done))
sys.exit(0 if run and run.wasSuccessful() else 1)
"""

OUTCOMES = {"pytest": pytest_outcome, "vitest": vitest_outcome, "unittest": unittest_outcome}


def command(t: Target, report: Path, python: str, bun: str) -> list[str]:
    """The command that runs `t`, writing its report to `report`."""
    if t.runner == "pytest":
        selected = t.tests or (t.path,)
        return [python, "-m", "pytest", *selected, "-p", "no:cacheprovider", f"--junitxml={report}"]
    if t.runner == "vitest":
        named = ["-t", f"^(?:{'|'.join(map(js_escape, t.tests))})$"] if t.tests else []
        return [
            bun,
            "run",
            "vitest",
            "run",
            t.path,
            *named,
            "--reporter=default",
            "--reporter=json",
            f"--outputFile.json={report}",
        ]
    return [sys.executable, "-c", UNITTEST, t.path, str(report), *t.tests]


def js_escape(name: str) -> str:
    """`name` as a JavaScript regular expression that matches only itself."""
    return re.sub(r"[\\^$.*+?()[\]{}|/]", r"\\\g<0>", name)


def call(argv: list[str], cwd: Path, env: dict[str, str]) -> int | None:
    """Run `argv`, then print its output; `None` when it timed out. It runs in
    a session of its own, so a timeout kills what it started too (vitest's
    workers under bun, say), not just the process itself."""
    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        print(out, f"timed out after {TIMEOUT}s", sep="\n", flush=True)
        return None
    print(out, flush=True)
    return proc.returncode


def install(base: Path, bun: str) -> bool:
    """The base's own frontend dependencies, from its lockfile. `HUSKY=0`
    keeps the install from pointing the shared git config at the base's hooks."""
    env = {**os.environ, "HUSKY": "0"}
    print(f"$ cd {base / 'frontend'} && {bun} install --frozen-lockfile", flush=True)
    return call([bun, "install", "--frozen-lockfile"], base / "frontend", env) == 0


def run_target(t: Target, base: Path, scratch: Path, python: str, bun: str) -> str:
    """Run `t` inside the base worktree `base`; its report goes in `scratch`."""
    report = scratch / hashlib.sha1(str(t).encode()).hexdigest()
    print(f"$ {t}", flush=True)
    code = call(command(t, report, python, bun), base / t.layer, dict(os.environ))
    if code is None:
        return FAILED
    text = report.read_text(encoding="utf-8") if report.is_file() else ""
    return OUTCOMES[t.runner](code, text)


# Drops the test database the base's own conftest made for the base worktree,
# by the conftest's own naming and connection, so neither the name nor the
# server's address is rebuilt here. Run from the worktree's backend/ while it
# exists.
DROP_DATABASE = """
import asyncio
from tests.conftest import _drop_database, _test_db_name
asyncio.run(_drop_database(_test_db_name()))
print("dropped", _test_db_name())
"""


def drop_database(base: Path, python: str) -> None:
    """Drop the base worktree's test database. Each run's worktree has a path
    of its own, so a database is never shared with another base; failing to
    drop it only leaves it behind, so it warns and goes on."""
    if call([python, "-c", DROP_DATABASE], base / "backend", dict(os.environ)) != 0:
        print("warning: the base's test database was not dropped.", flush=True)
