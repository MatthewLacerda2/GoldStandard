"""Which tests a change adds or changes, by the name its runner selects it by.

`tools/regression.py` judges only these on the base, so an older test of the
same file failing there, for whatever reason, proves nothing for the change.
A test is a Python test function with its decorators, or a vitest `it` /
`test` call from its name to its closing parenthesis. It is changed when the
head file has it and no test of the base's version has its source, dedented:
no diff is read, so how `git diff` is configured changes nothing, dropping a
decorator changes its test, and renaming its class or wrapping it in a new
`describe` does not. The names:

    pytest    node ids, `tests/x.py::TestA::test_b`: one names every case of
              a parametrized test
    unittest  the method's qualified name, `A.test_b`, matched against the
              class that defines it, so a test a subclass inherits counts too
    vitest    the full name, `outer > inner > test`, as `-t` matches it

A changed line outside every test (an import, a fixture, a helper, a
`beforeEach`) names no test. Beside a changed test it is that test's support,
and only the test is judged; a change of nothing but such lines (a fixture
that makes the older tests show the bug, say) judges the whole file, as the
check did before it judged by test. A changed test that cannot be selected
alone (no fixed name: `it.each`, a name built at run time; or a name another
test of the file shares) is not judged, and is said so; when no changed test
can be, the whole file is, as it is for a file that cannot be read.

Limits:
- The vitest side is a scanner, not a parser: it skips comments, strings,
  template literals and regular expressions. JSX text it misreads (a `//`
  that is not after `scheme:`, a lone `/` or quote) can unbalance brackets or
  move a test's span; unbalanced brackets judge the whole file.
- Tests made by `test.extend` (a fixture-carrying `test` of another name) are
  not found.
- A vitest test written inside a helper function that a `describe` calls is
  named without that `describe`, so `-t` selects nothing and the run cannot
  be judged.
- pytest's collection is read from names alone: a test a `Test*` class
  inherits from a base of another name, `__test__ = False`, and an inherited
  `__init__` are not seen.
- unittest matches a method by its `__qualname__`: a decorator that does not
  keep it (no `functools.wraps`) hides the test. Some named tests hidden: the
  run cannot pass (`tools/regression_runners.py`). All of them hidden: the
  whole file runs, and an older test failing in it counts again, as it did
  before tests were judged one by one.

Pure.
"""

from __future__ import annotations

import ast
import re
import textwrap
from collections import Counter
from typing import NamedTuple

# A vitest suite or test call: `describe(`, `it.skip(`, `test.each(`.
CALL = re.compile(r"(?<![\w$.])(describe|suite|it|test)((?:\s*\.\s*\w+)*)\s*\(")
SUITES = {"describe", "suite"}
# Modifiers whose call returns the function the name and body go to.
LATER = {"each", "for", "skipIf", "runIf", "extend", "scoped"}
# What a `/` after these starts is a regular expression, not a division. Not
# after `}`: in JSX it ends an attribute (`<Icon name={x} />`).
REGEX_AFTER = set("(,=:[!&|?{;+-*%~^")
REGEX_WORDS = {"return", "typeof", "case", "in", "of", "new", "delete", "void", "throw", "await"}
CLOSE = {")": "(", "]": "[", "}": "{"}
SPACE = re.compile(r"\s*")
# `//` after a URL's scheme (`https://`) is JSX text, not a comment.
SCHEME = re.compile(r"[A-Za-z]:$")


class Test(NamedTuple):
    """One test: its name's parts (`None` when it has no fixed name) and the
    lines it spans."""

    parts: tuple[str, ...] | None
    first: int
    last: int


def python_tests(text: str, runner: str) -> list[Test] | None:
    """pytest's tests: `test*` functions and the methods of the classes it
    collects (nested too). unittest's: the `test*` methods of the module's
    classes that may hold tests. `None` when the file does not parse."""
    try:
        module = ast.parse(text)
    except SyntaxError:
        return None

    # A class pytest collects: `Test*` with no `__init__`, or a `TestCase`.
    # One unittest runs tests of: a subclass, or another class's base here.
    bases = {
        ast.unparse(b) for n in ast.walk(module) if isinstance(n, ast.ClassDef) for b in n.bases
    }

    def collected(node: ast.ClassDef) -> bool:
        if runner == "unittest":
            return bool(node.bases) or node.name in bases
        if any(ast.unparse(b).endswith("TestCase") for b in node.bases):
            return True
        init = any(isinstance(n, ast.FunctionDef) and n.name == "__init__" for n in node.body)
        return node.name.startswith("Test") and not init

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
            if text.startswith("//", i) and not SCHEME.search(text, max(i - 2, 0), i):
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


class Chosen(NamedTuple):
    """What of a file runs: `tests` by selector, every test when empty; `why`
    says why it runs whole, or which changed tests are not judged."""

    tests: tuple[str, ...]
    why: str


def _found(runner: str, text: str) -> list[tuple[Test, str]] | None:
    """Each test of `text`, with its source, dedented: what is around it (its
    class or `describe`, how deep it sits) is not part of it."""
    tests = vitest_tests(text) if runner == "vitest" else python_tests(text, runner)
    lines = text.split("\n")  # as `ast` and the scanner count them
    if tests is None:
        return None
    return [(t, textwrap.dedent("\n".join(lines[t.first - 1 : t.last]))) for t in tests]


def changed_tests(runner: str, path: str, head: str, base: str | None) -> Chosen:
    """The tests of `path` the change adds or changes, from its `head` text
    and its `base` one (`None` when the base has no such file)."""
    now, before = _found(runner, head), [] if base is None else _found(runner, base)
    if now is None or before is None:
        side = "head's" if now is None else "base's"
        return Chosen((), f"the {side} version of the file cannot be read for its tests")
    old = {source for _, source in before}
    changed = [t for t, source in now if source not in old]
    if not changed:
        return Chosen((), "no test the change adds or changes is found, only code around them")
    names = {t: selector(runner, path, t.parts) for t, _ in now if t.parts}
    shared = Counter(names.values())
    alone = [t for t in changed if t in names and shared[names[t]] == 1]
    rest = ", ".join(f"lines {t.first}-{t.last}" for t in changed if t not in alone)
    why = rest and f"the changed tests at {rest} have no name of their own to be run by"
    if not alone:
        return Chosen((), why)
    tests = tuple(sorted(names[t] for t in alone))
    return Chosen(tests, why and f"not judged: {why}")
