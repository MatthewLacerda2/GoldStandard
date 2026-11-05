"""`tools/markers.py`: no comment outside the layers' lints promises work later."""

from __future__ import annotations

import unittest

from tools.markers import (
    ADVICE,
    LAYER_LINTED,
    MARKERS,
    NOT_READ,
    check,
    comment_of,
    matches,
    syntax_of,
    tracked,
)


def found(text: str, syntax: str = "hash") -> list[str]:
    return check("f", text, syntax)


def lines(findings: list[str]) -> list[str]:
    return [finding.split(": '")[0] for finding in findings]


class WhatIsAComment(unittest.TestCase):
    def test_a_hash_at_the_start_or_after_whitespace_starts_one(self) -> None:
        self.assertEqual(comment_of("# whole line"), "# whole line")
        self.assertEqual(comment_of("run: make  # trailing"), "# trailing")
        self.assertEqual(comment_of('echo "a \\" b"  # after'), "# after")

    def test_quotes_escapes_and_shell_expansions_are_not_comments(self) -> None:
        for line in [
            'echo "a # b"',
            "name: 'a # b'",
            'echo "a \\"b # TODO"',
            "echo a \\# b",
            "echo $#",
            "n=${#items}",
            "x#y",
        ]:
            self.assertIsNone(comment_of(line), line)

    def test_python_css_and_html_comments_are_read(self) -> None:
        self.assertEqual(lines(found('s = "TODO"  # FIXME\n', "python")), ["f:1"])
        self.assertEqual(lines(found("a {}\n/* x\n   HACK */\n", "css")), ["f:3"])
        self.assertEqual(lines(found("<p>TODO</p>\n<!-- XXX -->\n", "html")), ["f:2"])


class TheRule(unittest.TestCase):
    def test_each_marker_in_a_comment_fails(self) -> None:
        for marker in MARKERS:
            self.assertEqual(
                found(f"check:  # {marker}: tidy this\n"),
                [f"f:1: '{marker}' comment: {ADVICE}"],
            )

    def test_a_word_that_only_contains_a_marker_passes(self) -> None:
        self.assertEqual(found("# todos, TODO_LIST, hacker, XXXL, todo, Fixme\n"), [])

    def test_markers_outside_comments_pass(self) -> None:
        self.assertEqual(found('echo "TODO # FIXME"\nTODO=1\nname: HACK\n'), [])

    def test_an_allow_on_the_line_or_directly_above_passes(self) -> None:
        self.assertEqual(found("# TODO is the format  lint: allow(marker) it is\n"), [])
        self.assertEqual(found("# lint: allow(marker) `XXX` below\n# - XXX: ...\n"), [])
        self.assertEqual(found("# TODO  lint: allow(marker) été\n"), [])

    def test_an_allow_excuses_only_the_line_below_it(self) -> None:
        text = "# lint: allow(marker) a reason\n# TODO\n# XXX\nx: 1  # FIXME\n"
        self.assertEqual(lines(found(text)), ["f:3", "f:4"])

    def test_an_allow_needs_a_reason_this_rule_and_a_comment(self) -> None:
        for text in [
            "# TODO  lint: allow(marker)\n",
            "# TODO  lint: allow(marker) -- \n",
            "# TODO  lint: allow(other) a reason\n",
            'echo "lint: allow(marker) a reason"  # FIXME\n',
        ]:
            self.assertEqual(len(found(text)), 1, text)


class WhichFiles(unittest.TestCase):
    def test_each_kind_is_read_in_its_syntax(self) -> None:
        expected = {
            "Makefile": "hash",
            ".githooks/pre-commit": "hash",
            ".github/workflows/ci.yml": "hash",
            "docker/postgres/Dockerfile": "hash",
            "backend/pyproject.toml": "hash",
            "backend/requirements-dev.txt": "hash",
            "frontend/scripts/contract/baseline.txt": "hash",
            "tools/markers.py": "python",
            "frontend/src/styles.css": "css",
            "frontend/index.html": "html",
        }
        self.assertEqual({path: syntax_of(path) for path in expected}, expected)

    def test_what_a_layer_lints_or_nothing_reads_is_skipped(self) -> None:
        for path in ["backend/main.py", "frontend/src/main.tsx", "README.md"]:
            self.assertIsNone(syntax_of(path), path)

    def test_every_tracked_file_is_read_by_one_of_the_three_checks(self) -> None:
        stray = [
            path
            for path in tracked()
            if syntax_of(path) is None and not matches(path, LAYER_LINTED + NOT_READ)
        ]
        self.assertEqual(
            stray, [], "add these to FILES or NOT_READ in tools/markers.py"
        )


if __name__ == "__main__":
    unittest.main()
