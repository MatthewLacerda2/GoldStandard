"""Which tests a change adds or changes, by the name its runner selects it by.

`tools/regression.py` judges only these on the base, so an older test of the
same file failing there, for whatever reason, proves nothing for the change.
A test is changed when a line the diff adds or edits, or a deletion, falls
inside it: a Python test function with its decorators, or a vitest `it` /
`test` call from its name to its closing parenthesis. The names:

    pytest    node ids, `tests/x.py::TestA::test_b`: one names every case of
              a parametrized test
    unittest  the method's qualified name, `A.test_b`, matched against the
              class that defines it, so a test a subclass inherits counts too
    vitest    the full name, `outer > inner > test`, as `-t` matches it

A changed line outside every test (an import, a fixture, a helper, a
`beforeEach`) names no test. Beside a changed test it is that test's support,
and only the test is judged; a change of nothing but such lines (a fixture
that makes the older tests show the bug, say) judges the whole file, as the
check did before it judged by test. So does a changed test with no fixed name
(`it.each`, a name built at run time), and a file that cannot be read;
`changed_tests` says which.

The vitest side is a scanner, not a parser: it skips comments, strings,
template literals and regular expressions, and gives up (the whole file) on
brackets that do not balance.

Pure.
"""

from __future__ import annotations

import ast
import re
from typing import NamedTuple

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)
# A vitest suite or test call: `describe(`, `it.skip(`, `test.each(`.
CALL = re.compile(r"(?<![\w$.])(describe|suite|it|test)((?:\s*\.\s*\w+)*)\s*\(")
SUITES = {"describe", "suite"}
# Modifiers whose call returns the function the name and body go to.
LATER = {"each", "for", "skipIf", "runIf", "extend", "scoped"}
# What a `/` after these starts is a regular expression, not a division.
REGEX_AFTER = set("(,=:[!&|?{};+-*%~^")
REGEX_WORDS = {"return", "typeof", "case", "in", "of", "new", "delete", "void", "throw", "await"}
CLOSE = {")": "(", "]": "[", "}": "{"}
SPACE = re.compile(r"\s*")


class Test(NamedTuple):
    """One test: its name's parts (`None` when it has no fixed name) and the
    lines it spans in the head file."""

    parts: tuple[str, ...] | None
    first: int
    last: int


def hunks(diff: str) -> list[tuple[int, int]]:
    """The head side of each hunk of a `-U0` diff: (first line, line count).
    A count of 0 is a deletion, after line `first`."""
    return [(int(first), int(count or 1)) for first, count in HUNK.findall(diff)]


def touches(test: Test, hunk: tuple[int, int]) -> bool:
    first, count = hunk
    if count == 0:
        return test.first <= first < test.last
    return first <= test.last and first + count - 1 >= test.first


def python_tests(text: str, runner: str) -> list[Test] | None:
    """pytest's tests: `test*` functions and the methods of `Test*` classes
    (nested too) or of `TestCase` subclasses. unittest's: the `test*`
    methods of the module's classes. `None` when the file does not parse."""
    try:
        module = ast.parse(text)
    except SyntaxError:
        return None

    def collected(node: ast.ClassDef) -> bool:
        if runner == "unittest":
            return True
        return node.name.startswith("Test") or any(
            ast.unparse(b).endswith("TestCase") for b in node.bases
        )

    def walk(body: list[ast.stmt], prefix: tuple[str, ...]) -> list[Test]:
        found = []
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.startswith("test") and (prefix or runner == "pytest"):
                    first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                    found.append(Test((*prefix, node.name), first, node.end_lineno or first))
            elif isinstance(node, ast.ClassDef) and collected(node):
                if not prefix or runner == "pytest":
                    found += walk(node.body, (*prefix, node.name))
        return found

    return walk(module.body, ())


def _until(text: str, mark: str, i: int) -> int:
    """Where `mark` ends, searching from `i`; the text's end if it never does."""
    found = text.find(mark, i)
    return len(text) if found < 0 else found + len(mark)


def _string(text: str, i: int) -> int | None:
    """The end of the `'`/`"` string at `i`, or `None`: a quote whose line
    ends first is no string (an apostrophe in JSX text, say)."""
    j = i + 1
    while j < len(text) and text[j] != "\n":
        if text[j] == "\\":
            j += 2
        elif text[j] == text[i]:
            return j + 1
        else:
            j += 1
    return None


def _regex(text: str, i: int) -> int | None:
    """The end of the regular expression at `i`, or `None` if its line ends."""
    j, in_class = i + 1, False
    while j < len(text) and text[j] != "\n":
        c = text[j]
        if c == "\\":
            j += 1
        elif c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            return j + 1
        j += 1
    return None


class _Scan:
    """Masks a TypeScript file: comments and the text of strings, templates
    and regular expressions become spaces, so only code's brackets are left.
    `literals` maps where each string, or template without `${`, starts to
    where it ends and its text: `None` when it carries an escape this does
    not decode."""

    def __init__(self, text: str) -> None:
        self.text, self.out = text, list(text)
        self.literals: dict[int, tuple[int, str | None]] = {}
        self.code(0, inside=False)
        self.masked = "".join(self.out)

    def blank(self, start: int, end: int) -> None:
        for k in range(start, min(end, len(self.out))):
            if self.out[k] != "\n":
                self.out[k] = " "

    def regex_allowed(self, i: int) -> bool:
        k = i - 1
        while k >= 0 and self.out[k].isspace():
            k -= 1
        if k < 0 or self.out[k] in REGEX_AFTER or self.out[k - 1 : k + 1] == ["=", ">"]:
            return True
        start = k
        while start >= 0 and (self.out[start].isalnum() or self.out[start] in "_$"):
            start -= 1
        return "".join(self.out[start + 1 : k + 1]) in REGEX_WORDS

    def literal(self, start: int, end: int) -> None:
        body = self.text[start + 1 : end - 1]
        plain = not re.search(r"\\[^'\"\\`$]", body)
        self.literals[start] = (end, re.sub(r"\\(.)", r"\1", body) if plain else None)
        self.blank(start + 1, end - 1)

    def code(self, i: int, inside: bool) -> int:
        """Scan code from `i`; inside a template's `${`, up to its `}`."""
        depth, text = 0, self.text
        while i < len(text):
            c, end = text[i], None
            if text.startswith("//", i):
                end = _until(text, "\n", i)
            elif text.startswith("/*", i):
                end = _until(text, "*/", i + 2)
            elif c == "/" and self.regex_allowed(i):
                end = _regex(text, i)
            elif c in "'\"" and (end := _string(text, i)):
                self.literal(i, end)
                i = end
                continue
            elif c == "`":
                i = self.template(i)
                continue
            elif c == "{":
                depth += 1
            elif c == "}":
                if inside and depth == 0:
                    return i
                depth -= 1
            if end:
                self.blank(i, end)
                i = end
            else:
                i += 1
        return i

    def template(self, i: int) -> int:
        """Scan the template literal at `i`; where it ends."""
        text, start, j, plain = self.text, i, i + 1, True
        while j < len(text) and text[j] != "`":
            if text[j] == "\\":
                j += 2
            elif text.startswith("${", j):
                self.blank(i + 1, j)
                plain, i = False, self.code(j + 2, inside=True)
                j = i + 1
            else:
                j += 1
        if plain:
            self.literal(start, j + 1)
        self.blank(i + 1, j)
        return j + 1


def _closing(masked: str, opening: int) -> int | None:
    """Where the bracket at `opening` closes, or `None`."""
    stack = []
    for k in range(opening, len(masked)):
        c = masked[k]
        if c in "([{":
            stack.append(c)
        elif c in CLOSE:
            if not stack or stack.pop() != CLOSE[c]:
                return None
            if not stack:
                return k
    return None


def _balanced(masked: str) -> bool:
    return _closing(f"({masked})", 0) == len(masked) + 1


def vitest_tests(text: str) -> list[Test] | None:
    """Each `it`/`test` call, named after the suites around it. `None` when
    the brackets do not balance."""
    scan = _Scan(text)
    masked = scan.masked
    if not _balanced(masked):
        return None
    line = [0]
    for c in text:
        line.append(line[-1] + (c == "\n"))
    calls = []  # (start, end, is a suite, name)
    for match in CALL.finditer(masked):
        end = _closing(masked, match.end() - 1)
        later = bool(LATER & set(re.findall(r"\w+", match.group(2))))
        if later and end is not None:  # `it.each(table)(name, body)`
            follow = SPACE.match(masked, end + 1).end()
            end = _closing(masked, follow) if masked[follow : follow + 1] == "(" else end
        if end is None:
            return None
        name = None if later else _name(scan, match.end())
        calls.append((match.start(), end, match.group(1) in SUITES, name))
    tests = []
    for start, end, is_suite, name in calls:
        if not is_suite:
            around = [c[3] for c in calls if c[2] and c[0] < start and end <= c[1]]
            parts = None if None in [*around, name] else (*around, name)
            tests.append(Test(parts, line[start] + 1, line[end] + 1))
    return tests


def _name(scan: _Scan, i: int) -> str | None:
    """A call's name: its first argument, from `i`, when that is a literal."""
    first = SPACE.match(scan.masked, i).end()
    if first not in scan.literals:
        return None
    end, name = scan.literals[first]
    after = SPACE.match(scan.masked, end).end()
    return name if scan.masked[after : after + 1] in (",", ")") else None


def selector(runner: str, path: str, parts: tuple[str, ...]) -> str:
    """The name `runner` selects a test by."""
    if runner == "pytest":
        return "::".join((path, *parts))
    return " > ".join(parts) if runner == "vitest" else ".".join(parts)


def changed_tests(runner: str, path: str, text: str, diff: str) -> tuple[tuple[str, ...], str]:
    """The tests of `path` (its head `text`) the `-U0` `diff` adds or
    changes, by selector; none, with the reason, when it is judged whole."""
    tests = vitest_tests(text) if runner == "vitest" else python_tests(text, runner)
    if tests is None:
        return (), "the file cannot be read for its tests"
    changed = [t for t in tests if any(touches(t, h) for h in hunks(diff))]
    if not changed:
        return (), "no test the change adds or changes is found, only code around them"
    if any(t.parts is None for t in changed):
        return (), "a test the change adds or changes has no fixed name"
    return tuple(sorted({selector(runner, path, t.parts) for t in changed if t.parts})), ""
