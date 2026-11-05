"""`tools/regression.py`'s decisions: what is owed, what runs, how it is judged."""

from __future__ import annotations

import json
import unittest

from tools.regression import closes, excused, fixes, laid, owed, target, targets, verdict
from tools.regression_runners import (
    BROKEN,
    FAILED,
    PASSED,
    Target,
    pytest_outcome,
    unittest_outcome,
    vitest_outcome,
)

FIX = {"labels": [{"name": "fix"}]}
FEAT = {"labels": [{"name": "feat"}]}
REASON = "No regression test on base: the bug was only visible in a real browser."
PYTEST = Target("pytest", "backend", "tests/api/v1/test_items.py")


def junit(*messages: str) -> str:
    cases = "".join(f'<testcase name="t"><failure message="{m}"/></testcase>' for m in messages)
    return f"<testsuites><testsuite>{cases}</testsuite></testsuites>"


def vitest(*messages: str) -> str:
    tests = [{"status": "failed", "failureMessages": [m]} for m in messages]
    return json.dumps({"testResults": [{"assertionResults": tests}]})


class WhatIsOwed(unittest.TestCase):
    def test_closing_keywords_name_this_repositorys_issues(self) -> None:
        body = "Closes #59, fixes o/r#7, resolves https://github.com/x/y/issues/3, refs #9"
        self.assertEqual(closes(body, "o/r"), [7, 59])

    def test_only_an_issue_labelled_fix_owes_a_test(self) -> None:
        issues = {1: FIX, 2: FEAT, 3: {**FIX, "pull_request": {}}}
        self.assertEqual(fixes(issues), [1])

    def test_a_fix_with_no_test_file_is_refused(self) -> None:
        self.assertTrue(owed([1], "Closes #1", []))
        self.assertEqual(owed([1], "Closes #1", [PYTEST]), [])
        self.assertEqual(owed([], "Closes #1", []), [])

    def test_an_exception_line_with_its_reason_owes_nothing(self) -> None:
        self.assertEqual(owed([1], f"Closes #1\n\n{REASON}\n", []), [])
        self.assertEqual(excused(f"- **{REASON}**"), "the bug was only visible in a real browser.")

    def test_an_exception_needs_a_reason_and_a_line_of_its_own(self) -> None:
        self.assertIsNone(excused("No regression test on base: n/a"))
        self.assertIsNone(excused(f"See: {REASON}"))


class WhatRuns(unittest.TestCase):
    def test_each_layer_names_its_runner(self) -> None:
        self.assertEqual(
            target("backend/tests/core/test_config.py"),
            Target("pytest", "backend", "tests/core/test_config.py"),
        )
        self.assertEqual(
            target("frontend/src/a/b.test.tsx"), Target("vitest", "frontend", "src/a/b.test.tsx")
        )
        self.assertEqual(
            target("tools/tests/test_ci_paths.py"),
            Target("unittest", ".", "tools/tests/test_ci_paths.py"),
        )

    def test_helpers_and_other_folders_name_no_target(self) -> None:
        for path in (
            "backend/tests/conftest.py",
            "frontend/eslint-rules/tester.ts",
            "docs/test_x.py",
            "backend/test_x.ts",
            "frontend/src/a.ts",
        ):
            self.assertIsNone(target(path), path)

    def test_helpers_and_fixtures_are_laid_over_too(self) -> None:
        for path in ("backend/tests/conftest.py", "frontend/src/fixtures/reply.json"):
            self.assertTrue(laid(path), path)
        self.assertFalse(laid("backend/services/items.py"))

    def test_a_deleted_test_runs_nothing(self) -> None:
        paths = ["backend/tests/test_gone.py", "backend/tests/test_kept.py"]
        found = targets(paths, lambda p: p.endswith("kept.py"))
        self.assertEqual(found, [Target("pytest", "backend", "tests/test_kept.py")])


class HowItIsJudged(unittest.TestCase):
    def test_a_failure_on_the_base_passes_the_check(self) -> None:
        self.assertEqual(pytest_outcome(1, junit("assert 1 == 2")), FAILED)
        self.assertEqual(verdict({PYTEST: FAILED, PYTEST._replace(path="b"): PASSED}), [])

    def test_a_pass_on_the_base_is_refused(self) -> None:
        self.assertEqual(pytest_outcome(0, ""), PASSED)
        self.assertIn("passes on the base", "\n".join(verdict({PYTEST: PASSED})))

    def test_only_a_missing_name_does_not_count(self) -> None:
        missing = (
            "ImportError: x",
            "NameError: name 'f' is not defined",
            "AttributeError: module 'core' has no attribute 'f'",
        )
        self.assertEqual(pytest_outcome(1, junit(*missing)), BROKEN)
        self.assertEqual(pytest_outcome(1, junit(*missing, "assert 0")), FAILED)
        self.assertTrue(verdict({PYTEST: BROKEN}))

    def test_an_attribute_error_on_none_is_the_bug(self) -> None:
        none = "AttributeError: 'NoneType' object has no attribute 'id'"
        self.assertEqual(pytest_outcome(1, junit(none)), FAILED)

    def test_a_file_that_does_not_import_or_set_up_does_not_count(self) -> None:
        self.assertEqual(pytest_outcome(2, ""), BROKEN)
        errored = '<testsuites><testcase name="t"><error message="no db"/></testcase></testsuites>'
        self.assertEqual(pytest_outcome(1, errored), BROKEN)

    def test_vitest_names_a_missing_function_or_variable(self) -> None:
        self.assertEqual(
            vitest_outcome(1, vitest("TypeError: (0 , m.f) is not a function")), BROKEN
        )
        self.assertEqual(vitest_outcome(1, vitest("ReferenceError: f is not defined")), BROKEN)
        self.assertEqual(vitest_outcome(1, vitest("AssertionError: expected 1 to be 2")), FAILED)
        self.assertEqual(vitest_outcome(1, json.dumps({"testResults": [{}]})), BROKEN)
        self.assertEqual(vitest_outcome(0, ""), PASSED)

    def test_unittest_reports_what_failed(self) -> None:
        report = json.dumps({"loaded": True, "failures": ["AssertionError: 1 != 2"]})
        self.assertEqual(unittest_outcome(1, report), FAILED)
        self.assertEqual(unittest_outcome(1, json.dumps({"loaded": False, "failures": []})), BROKEN)

    def test_no_target_is_refused(self) -> None:
        self.assertTrue(verdict({}))


if __name__ == "__main__":
    unittest.main()
