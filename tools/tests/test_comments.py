"""`tools/comments.py`: the `//` reader finds comments and skips strings.

The `#` reader is held by `test_markers.py`; Python's is the tokenizer's own.
"""

from __future__ import annotations

import unittest

from tools.comments import comments


def slash(text: str) -> dict[int, list[str]]:
    return comments("slash", text)


class SlashComments(unittest.TestCase):
    def test_line_and_block_comments_are_read_by_line(self) -> None:
        text = "const a = 1; // one\n/* two\n * three */\nb(); /* four */ c();\n"
        expected = {1: [" one"], 2: [" two"], 3: [" * three "], 4: [" four "]}
        self.assertEqual(slash(text), expected)

    def test_strings_and_template_literals_are_not_comments(self) -> None:
        text = "a('// no'); b(\"/* no */\"); c(`\n// no\n`);\nd(); // yes\n"
        self.assertEqual(slash(text), {4: [" yes"]})

    def test_an_escaped_quote_does_not_end_a_string(self) -> None:
        self.assertEqual(slash("a('it\\'s // no'); // yes\n"), {1: [" yes"]})

    def test_a_stray_quote_costs_only_the_rest_of_its_line(self) -> None:
        self.assertEqual(slash("const r = /'/; // lost\n// read\n"), {2: [" read"]})

    def test_an_unclosed_block_runs_to_the_end(self) -> None:
        self.assertEqual(slash("x(); /* open\nstill"), {1: [" open"], 2: ["still"]})


if __name__ == "__main__":
    unittest.main()
