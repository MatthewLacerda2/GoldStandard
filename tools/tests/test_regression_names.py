"""`tools/regression_names.py`: which tests a change adds or changes, by name."""

from __future__ import annotations

import unittest

from tools.regression_names import changed_tests, hunks, vitest_tests
from tools.regression_runners import Target, command

PYTEST = """import pytest

def helper():
    return 1

@pytest.mark.parametrize("x", [1, 2])
def test_cases(x):
    assert x

class TestGroup:
    def test_one(self):
        assert helper()

    class TestInner:
        def test_two(self):
            assert True

class Helpers:
    def test_not_collected(self):
        pass
"""
UNITTEST = """import unittest

def test_not_a_method():
    pass

class Base(unittest.TestCase):
    def setUp(self):
        self.x = 1

    def test_inherited(self):
        pass

class Case(Base):
    def test_own(self):
        pass
"""
VITEST = """import { render } from "./x";

// it("in a comment", () => {})
const pattern = /it\\(/;
describe("outer (a)", () => {
  beforeEach(() => setUp(`it("x")`));
  describe('inner', () => {
    it("renders", () => {
      render(<p>Don't (stop)</p>);
    });
  });
  test.skip(`plain`, () => {
    expect(pattern.test("it(")).toBe(true);
  });
  it.each([1, 2])("case %i", (n) => {
    expect(n).toBeTruthy();
  });
});
"""


def lines(*spans: tuple[int, int]) -> str:
    """A `-U0` diff changing `count` head lines from `first`, per span."""
    return "\n".join(f"@@ -1,1 +{first},{count} @@" for first, count in spans)


class PythonTests(unittest.TestCase):
    def test_pytest_names_node_ids_one_per_parametrized_test(self) -> None:
        # The parametrize decorator is part of its test.
        names, why = changed_tests("pytest", "tests/t.py", PYTEST, lines((6, 1), (14, 2)))
        self.assertEqual(why, "")
        self.assertEqual(
            names, ("tests/t.py::TestGroup::TestInner::test_two", "tests/t.py::test_cases")
        )

    def test_a_changed_helper_beside_a_changed_test_is_not_judged(self) -> None:
        names, _ = changed_tests("pytest", "t.py", PYTEST, lines((3, 2), (11, 1)))
        self.assertEqual(names, ("t.py::TestGroup::test_one",))

    def test_only_a_helper_changed_judges_the_whole_file(self) -> None:
        # A class pytest does not collect is a helper too.
        names, why = changed_tests("pytest", "t.py", PYTEST, lines((1, 4), (19, 1)))
        self.assertEqual(names, ())
        self.assertIn("no test", why)

    def test_a_deletion_inside_a_test_changes_it(self) -> None:
        self.assertEqual(hunks("@@ -9,2 +8,0 @@\n@@ -1 +1 @@"), [(8, 0), (1, 1)])
        names, _ = changed_tests("pytest", "t.py", PYTEST, lines((7, 0)))
        self.assertEqual(names, ("t.py::test_cases",))
        # A deletion between two tests is in neither.
        self.assertEqual(changed_tests("pytest", "t.py", PYTEST, lines((9, 0)))[0], ())

    def test_unittest_names_methods_by_qualified_name(self) -> None:
        names, _ = changed_tests("unittest", "t.py", UNITTEST, lines((1, 15)))
        self.assertEqual(names, ("Base.test_inherited", "Case.test_own"))

    def test_a_file_that_does_not_parse_is_judged_whole(self) -> None:
        names, why = changed_tests("unittest", "t.py", "def test_(:\n", lines((1, 1)))
        self.assertEqual((names, why), ((), "the file cannot be read for its tests"))


class VitestTests(unittest.TestCase):
    def test_nested_describes_name_the_full_name(self) -> None:
        names, why = changed_tests("vitest", "x.test.tsx", VITEST, lines((9, 1), (13, 1)))
        self.assertEqual(why, "")
        self.assertEqual(names, ("outer (a) > inner > renders", "outer (a) > plain"))

    def test_comments_strings_and_regexes_hold_no_call(self) -> None:
        found = vitest_tests(VITEST) or []
        self.assertEqual([(t.first, t.last) for t in found], [(8, 10), (12, 14), (15, 17)])

    def test_a_test_with_no_fixed_name_judges_the_whole_file(self) -> None:
        names, why = changed_tests("vitest", "x.test.ts", VITEST, lines((16, 1)))
        self.assertEqual((names, why), ((), "a test the change adds or changes has no fixed name"))

    def test_a_change_in_a_hook_judges_the_whole_file(self) -> None:
        self.assertEqual(changed_tests("vitest", "x.test.ts", VITEST, lines((6, 1)))[0], ())

    def test_brackets_that_do_not_balance_judge_the_whole_file(self) -> None:
        self.assertIsNone(vitest_tests('it("a", () => {\n'))


class TheCommand(unittest.TestCase):
    def test_each_runner_runs_only_the_named_tests(self) -> None:
        pytest = Target("pytest", "backend", "tests/t.py", ("tests/t.py::test_a",))
        self.assertIn("tests/t.py::test_a", command(pytest, "r", "python", "bun"))
        self.assertNotIn("tests/t.py", command(pytest, "r", "python", "bun"))
        vitest = Target("vitest", "frontend", "x.test.ts", ("a (b) > c", "d"))
        self.assertIn(r"^(?:a \(b\) > c|d)$", command(vitest, "r", "python", "bun"))
        unit = Target("unittest", ".", "tools/tests/test_x.py", ("A.test_b",))
        self.assertEqual(command(unit, "r", "python", "bun")[-1], "A.test_b")

    def test_with_no_names_the_whole_file_runs(self) -> None:
        vitest = command(Target("vitest", "frontend", "x.test.ts"), "r", "python", "bun")
        self.assertNotIn("-t", vitest)


if __name__ == "__main__":
    unittest.main()
