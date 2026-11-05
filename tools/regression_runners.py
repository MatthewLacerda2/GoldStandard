"""How `tools/regression.py` runs one target on the base, and judges it.

A target is one test file a runner runs by name: a pytest file of `backend/`,
a vitest file of `frontend/`, a unittest file of `tools/`. Each run ends in one
of three outcomes:

    failed   a test failed: the bug shows on the base, which is the point
    passed   every test passed: the test does not reproduce the bug
    broken   nothing could be judged: the file does not import or compile,
             no test ran, or every failure is a name the base lacks

A name the base lacks is Python's `ImportError`, `NameError` or
`AttributeError` (but not on `None`, which is how a bug usually shows), and
JavaScript's `ReferenceError` or `… is not a function` / `constructor`. A test
calling the fix's new function fails that way on any base, so it proves
nothing. Only a test body's failure counts: pytest's setup errors (no
database) are broken, not failed. A run past `TIMEOUT` has failed.

Pure but for `run_target` and `install`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
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
_JS_MISSING = re.compile(
    r"^(?:ReferenceError: .* is not defined|TypeError: .* is not a (?:function|constructor))"
)


class Target(NamedTuple):
    """One test file: `layer` is the directory its runner runs from, `path`
    the file relative to it."""

    runner: str
    layer: str
    path: str

    def __str__(self) -> str:
        return f"{self.runner} {PurePosixPath(self.layer, self.path)}"


def py_missing(failure: str) -> bool:
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
    past 1 means the file did not import or ran nothing."""
    if code == 0:
        return PASSED
    if code != 1 or not junit:
        return BROKEN
    failures = ElementTree.fromstring(junit).iter("failure")
    return judged([f.get("message") or "" for f in failures], py_missing)


def vitest_outcome(code: int, report: str) -> str:
    """From vitest's exit code and JSON report. A file that does not load
    reports no failing test."""
    if code == 0:
        return PASSED
    try:
        files = json.loads(report).get("testResults") or []
    except ValueError:
        return BROKEN
    failures = [
        (test.get("failureMessages") or [""])[0]
        for file in files
        for test in file.get("assertionResults") or []
        if test.get("status") == "failed"
    ]
    return judged(failures, js_missing)


def unittest_outcome(code: int, report: str) -> str:
    """From `UNITTEST`'s exit code and report."""
    if code == 0:
        return PASSED
    try:
        done = json.loads(report)
    except ValueError:
        return BROKEN
    return judged(done["failures"], py_missing) if done.get("loaded") else BROKEN


# One unittest file, run in a fresh interpreter from the base worktree so
# nothing of the head is imported. It reports each failure as `Type: message`,
# for `unittest_outcome` to judge the way pytest's are.
UNITTEST = """
import json, sys, unittest
from pathlib import Path
file, report = Path(sys.argv[1]).resolve(), sys.argv[2]
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
loaded = not loader.errors and suite.countTestCases() > 0
print("\\n".join(loader.errors))
ok = loaded and unittest.TextTestRunner(verbosity=2, resultclass=Result).run(suite).wasSuccessful()
Path(report).write_text(json.dumps({"loaded": loaded, "failures": failures}))
sys.exit(0 if ok else 1)
"""

OUTCOMES = {"pytest": pytest_outcome, "vitest": vitest_outcome, "unittest": unittest_outcome}


def command(t: Target, report: Path, python: str, bun: str) -> list[str]:
    """The command that runs `t`, writing its report to `report`."""
    if t.runner == "pytest":
        return [python, "-m", "pytest", t.path, "-p", "no:cacheprovider", f"--junitxml={report}"]
    if t.runner == "vitest":
        return [
            bun,
            "run",
            "vitest",
            "run",
            t.path,
            "--reporter=default",
            "--reporter=json",
            f"--outputFile.json={report}",
        ]
    return [sys.executable, "-c", UNITTEST, t.path, str(report)]


def call(argv: list[str], cwd: Path, env: dict[str, str]) -> int | None:
    """Run `argv`, then print its output; `None` when it timed out."""
    try:
        done = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            timeout=TIMEOUT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except subprocess.TimeoutExpired as hung:
        out = hung.output or ""
        out = out.decode(errors="replace") if isinstance(out, bytes) else out
        print(out, f"timed out after {TIMEOUT}s", sep="\n", flush=True)
        return None
    print(done.stdout, flush=True)
    return done.returncode


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
