"""`tools/regression_names.py`: which tests a change adds or changes, by name."""

from __future__ import annotations

import unittest

from tools.regression_names import Chosen, changed_tests, vitest_tests
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

class TestBuilt:
    def __init__(self):
        pass

    def test_not_collected_either(self):
        pass
"""
UNITTEST = """import unittest

class FakeRemote:
    def test_connection(self):
        return True

class Base(unittest.TestCase):
    def test_inherited(self):
        pass

class Mixin:
    def test_mixed(self):
        pass

class Case(Mixin, Base):
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
      render(<p>Don't (stop) <Icon name={x} />, see https://x.y (here)</p>);
    });
  });
  test.skip(`plain`, () => {
    expect(pattern.test("it(")).toBe(true);
  });
  it.each([1, 2])("case %i", (n) => {
    expect(n).toBeTruthy();
  });
});
it("works", () => {});
"""
WHOLE = "no test the change adds or changes is found, only code around them"


def edit(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, old
    return text.replace(old, new)


class PythonTests(unittest.TestCase):
    def test_pytest_names_node_ids_one_per_parametrized_test(self) -> None:
        head = edit(edit(PYTEST, "[1, 2]", "[1, 2, 3]"), "assert True", "assert 1")
        self.assertEqual(
            changed_tests("pytest", "tests/t.py", head, PYTEST),
            Chosen(("tests/t.py::TestGroup::TestInner::test_two", "tests/t.py::test_cases"), ""),
        )

    def test_a_changed_helper_beside_a_changed_test_is_not_judged(self) -> None:
        head = edit(edit(PYTEST, "return 1", "return 2"), "assert helper()", "assert helper() == 2")
        self.assertEqual(
            changed_tests("pytest", "t.py", head, PYTEST).tests, ("t.py::TestGroup::test_one",)
        )

    def test_dropping_a_decorator_changes_its_test(self) -> None:
        base = edit(
            PYTEST, "    def test_one", "    @pytest.mark.xfail(reason='bug')\n    def test_one"
        )
        self.assertEqual(
            changed_tests("pytest", "t.py", PYTEST, base).tests, ("t.py::TestGroup::test_one",)
        )

    def test_renaming_or_reindenting_a_class_changes_none_of_its_tests(self) -> None:
        head = PYTEST.replace("class TestGroup:", "class TestRenamed:")
        head = head.replace(
            "    class TestInner:\n        def test_two(self):\n            assert True",
            "class TestInner:\n    def test_two(self):\n        assert True",
        )
        self.assertEqual(changed_tests("pytest", "t.py", head, PYTEST), Chosen((), WHOLE))

    def test_only_a_helper_changed_judges_the_whole_file(self) -> None:
        # Classes pytest does not collect (no `Test*`, or an `__init__`) are helpers too.
        head = PYTEST.replace("pass", "return").replace("return 1", "return 2")
        self.assertEqual(changed_tests("pytest", "t.py", head, PYTEST), Chosen((), WHOLE))

    def test_a_new_file_changes_every_test(self) -> None:
        self.assertEqual(len(changed_tests("pytest", "t.py", PYTEST, None).tests), 3)

    def test_unittest_names_methods_by_qualified_name(self) -> None:
        names = changed_tests("unittest", "t.py", UNITTEST, None).tests
        self.assertEqual(names, ("Base.test_inherited", "Case.test_own", "Mixin.test_mixed"))

    def test_a_class_nothing_runs_holds_no_unittest_test(self) -> None:
        head = edit(UNITTEST, "return True", "return False")
        self.assertEqual(changed_tests("unittest", "t.py", head, UNITTEST), Chosen((), WHOLE))

    def test_a_file_that_does_not_parse_is_judged_whole(self) -> None:
        why = changed_tests("unittest", "t.py", "def test_(:\n", UNITTEST).why
        self.assertEqual(why, "the head's version of the file cannot be read for its tests")
        self.assertIn("base's version", changed_tests("unittest", "t.py", UNITTEST, "(").why)


class VitestTests(unittest.TestCase):
    def test_nested_describes_name_the_full_name(self) -> None:
        head = edit(edit(VITEST, "(stop)", "(go)"), "toBe(true)", "toBe(false)")
        self.assertEqual(
            changed_tests("vitest", "x.test.tsx", head, VITEST),
            Chosen(("outer (a) > inner > renders", "outer (a) > plain"), ""),
        )

    def test_comments_strings_regexes_and_jsx_hold_no_call(self) -> None:
        found = vitest_tests(VITEST) or []
        spans = [(t.first, t.last) for t in found]
        self.assertEqual(spans, [(8, 10), (12, 14), (15, 17), (19, 19)])

    def test_a_test_with_no_fixed_name_is_not_judged_beside_one_with(self) -> None:
        head = edit(edit(VITEST, "toBeTruthy()", "toBe(1)"), "toBe(true)", "toBe(false)")
        chosen = changed_tests("vitest", "x.test.tsx", head, VITEST)
        self.assertEqual(chosen.tests, ("outer (a) > plain",))
        self.assertIn("not judged: the changed tests at lines 15-17 have no name", chosen.why)

    def test_only_tests_with_no_name_of_their_own_judge_the_whole_file(self) -> None:
        # The second `works` would run the older one too.
        head = edit(VITEST, "toBeTruthy()", "toBe(1)") + 'it("works", () => expect(1).toBe(2));\n'
        chosen = changed_tests("vitest", "x.test.tsx", head, VITEST)
        self.assertEqual(chosen.tests, ())
        self.assertIn("lines 15-17, lines 20-20 have no name of their own", chosen.why)

    def test_wrapping_tests_in_a_new_describe_changes_none(self) -> None:
        head = VITEST.replace(
            'it("works", () => {});', 'describe("new", () => {\n  it("works", () => {});\n});'
        )
        self.assertEqual(changed_tests("vitest", "x.test.ts", head, VITEST), Chosen((), WHOLE))

    def test_names_that_join_alike_are_shared(self) -> None:
        # `-t` matches the joined name: `a > b` at the top is `b` inside `a`.
        base = 'describe("a", () => {\n  it("b", () => {});\n});\n'
        head = base + 'it("a > b", () => {});\n'
        self.assertEqual(changed_tests("vitest", "x.test.ts", head, base).tests, ())

    def test_a_change_in_a_hook_judges_the_whole_file(self) -> None:
        head = edit(VITEST, "setUp(", "setUpAgain(")
        self.assertEqual(changed_tests("vitest", "x.test.ts", head, VITEST), Chosen((), WHOLE))

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
