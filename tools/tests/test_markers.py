"""`tools/markers.py`: no `#` comment outside the layers promises work later."""

from __future__ import annotations

import unittest

from tools.markers import ADVICE, MARKERS, check, comment_of, is_checked


def found(text: str) -> list[str]:
    return check("Makefile", text)


class WhatIsAComment(unittest.TestCase):
    def test_a_hash_at_the_start_or_after_whitespace_starts_one(self) -> None:
        self.assertEqual(comment_of("# whole line"), "# whole line")
        self.assertEqual(comment_of("run: make  # trailing"), "# trailing")

    def test_quotes_and_shell_expansions_are_not_comments(self) -> None:
        for line in ['echo "a # b"', "name: 'a # b'", "echo $#", "n=${#items}", "x#y"]:
            self.assertIsNone(comment_of(line), line)


class TheRule(unittest.TestCase):
    def test_each_marker_in_a_comment_fails(self) -> None:
        for marker in MARKERS:
            self.assertEqual(
                found(f"check:  # {marker}: tidy this\n"),
                [f"Makefile:1: '{marker}' comment: {ADVICE}"],
            )

    def test_a_word_that_only_contains_a_marker_passes(self) -> None:
        self.assertEqual(found("# todos, TODO_LIST, hacker, XXXL, todo, Fixme\n"), [])

    def test_markers_outside_comments_pass(self) -> None:
        self.assertEqual(found('echo "TODO # FIXME"\nTODO=1\nname: HACK\n'), [])

    def test_an_allow_on_the_line_or_in_the_comments_above_passes(self) -> None:
        self.assertEqual(
            found("# TODO is the format  lint: allow(marker) it names it\n"), []
        )
        text = "# lint: allow(marker) quoted below\n# - XXX: ...\nx: 1  # FIXME\n"
        self.assertEqual(found(text), [])

    def test_an_allow_needs_a_reason_and_this_rule(self) -> None:
        self.assertEqual(len(found("# TODO  lint: allow(marker)\n")), 1)
        self.assertEqual(len(found("# TODO  lint: allow(marker) -- \n")), 1)
        self.assertEqual(len(found("# TODO  lint: allow(other) a reason\n")), 1)

    def test_a_line_that_is_not_a_comment_ends_an_allows_reach(self) -> None:
        [finding] = found("# lint: allow(marker) a reason\nx: 1\n# HACK\n")
        self.assertTrue(finding.startswith("Makefile:3: 'HACK'"))


class WhichFiles(unittest.TestCase):
    def test_the_hash_comment_files_outside_the_layers_are_read(self) -> None:
        for path in [
            "Makefile",
            "scripts/setup.sh",
            ".githooks/pre-commit",
            ".github/workflows/ci.yml",
            ".github/dependabot.yml",
            "backend/Dockerfile",
            "Dockerfile",
            "docker-compose.yml",
            ".env.example",
        ]:
            self.assertTrue(is_checked(path), path)

    def test_files_a_layer_lints_or_prose_are_not(self) -> None:
        for path in ["backend/main.py", "frontend/src/main.tsx", "README.md", ".env"]:
            self.assertFalse(is_checked(path), path)


if __name__ == "__main__":
    unittest.main()
