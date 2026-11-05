"""`tools/docs_lint/`: each rule flags what it must and passes what it must."""

from __future__ import annotations

import unittest

from tools.docs_lint.run import ROOT, lint, read_from, tracked_files

SKILL = ".claude/skills/demo/SKILL.md"
FRONTMATTER = "---\nname: demo\ndescription: Does a demo. Use when demoing.\n---\n"


def rules(files: dict[str, str]) -> list[tuple[str, str, int]]:
    """What `lint` finds in these files, as `(path, rule, line)`."""
    return [(v.path, v.rule, v.line) for v in lint(files, files.get)]


def lines(n: int, head: str = "") -> str:
    return head + "text\n" * (n - head.count("\n"))


class Caps(unittest.TestCase):
    def test_claude_md_over_300_lines_is_flagged_anywhere(self) -> None:
        self.assertEqual(rules({"a/CLAUDE.md": lines(301)}), [("a/CLAUDE.md", "claude-md", 1)])
        self.assertEqual(rules({"CLAUDE.md": lines(300)}), [])

    def test_blank_lines_count(self) -> None:
        self.assertEqual(len(rules({"CLAUDE.md": "\n" * 301})), 1)

    def test_skill_doc_over_500_lines_is_flagged(self) -> None:
        files = {
            SKILL: lines(501, FRONTMATTER),
            ".claude/skills/demo/ref.md": lines(500, "## Contents\n"),
        }
        self.assertEqual(rules(files), [(SKILL, "skill-doc", 1)])

    def test_skill_code_over_400_lines_is_flagged(self) -> None:
        files = {".claude/skills/demo/x.py": "x = 1\n" * 401, SKILL: FRONTMATTER}
        self.assertEqual(rules(files), [(".claude/skills/demo/x.py", "skill-code", 1)])
        self.assertEqual(rules({".claude/skills/demo/x.py": "x = 1\n" * 400}), [])

    def test_an_allow_with_a_reason_anywhere_excuses_a_cap(self) -> None:
        allow = "<!-- lint: allow(claude-md) it is generated -->\n"
        self.assertEqual(rules({"CLAUDE.md": lines(301) + allow}), [])
        code = "# lint: allow(skill-code) a vendored parser\n" + "x = 1\n" * 401
        self.assertEqual(rules({".claude/skills/demo/x.py": code}), [])

    def test_an_allow_needs_a_reason_and_the_rule_it_names(self) -> None:
        for allow in ("<!-- lint: allow(claude-md) -->", "<!-- lint: allow(history) why -->"):
            self.assertEqual(len(rules({"CLAUDE.md": lines(301) + allow + "\n"})), 1)


class SkillFrontmatter(unittest.TestCase):
    def problems(self, text: str, path: str = SKILL) -> list[str]:
        return [v.message for v in lint({path: text}, {path: text}.get)]

    def test_a_valid_frontmatter_passes(self) -> None:
        self.assertEqual(self.problems(FRONTMATTER + "# Demo\n"), [])
        folded = "---\nname: demo\ndescription: >-\n  Does a demo.\n  Use when demoing.\n---\n"
        self.assertEqual(self.problems(folded), [])
        quoted = "---\nname: \"demo\"\ndescription: 'Does a demo.'\n---\n"
        self.assertEqual(self.problems(quoted), [])

    def test_a_missing_or_unclosed_block_is_flagged(self) -> None:
        self.assertEqual(len(self.problems("# Demo\n")), 1)
        self.assertEqual(len(self.problems("---\nname: demo\n")), 1)

    def test_a_missing_field_is_flagged(self) -> None:
        self.assertEqual(len(self.problems("---\nname: demo\n---\n")), 1)
        self.assertEqual(len(self.problems("---\ndescription: Does.\n---\n")), 1)

    def test_a_name_outside_the_spec_is_flagged(self) -> None:
        for name in ("Demo", "-demo", "de--mo", "other"):
            with self.subTest(name=name):
                self.assertTrue(self.problems(f"---\nname: {name}\ndescription: D.\n---\n"))
        long = "a" * 65
        text = f"---\nname: {long}\ndescription: D.\n---\n"
        self.assertTrue(self.problems(text, f".claude/skills/{long}/SKILL.md"))
        text = "---\nname: claude-demo\ndescription: D.\n---\n"
        self.assertTrue(self.problems(text, ".claude/skills/claude-demo/SKILL.md"))

    def test_a_long_description_or_one_with_a_tag_is_flagged(self) -> None:
        self.assertTrue(self.problems(f"---\nname: demo\ndescription: {'d' * 1025}\n---\n"))
        self.assertTrue(self.problems("---\nname: demo\ndescription: Use on <branch>.\n---\n"))
        self.assertEqual(self.problems(f"---\nname: demo\ndescription: {'d' * 1024}\n---\n"), [])

    def test_only_a_skills_entry_file_is_held(self) -> None:
        self.assertEqual(self.problems("# Notes\n", ".claude/skills/demo/notes/SKILL.md"), [])


class ReferenceToc(unittest.TestCase):
    def test_a_long_reference_without_contents_is_flagged(self) -> None:
        for path in (".claude/skills/demo/ref.md", "docs/guide.md"):
            with self.subTest(path=path):
                self.assertEqual(rules({path: lines(101)}), [(path, "reference-toc", 1)])

    def test_a_contents_heading_near_the_top_passes(self) -> None:
        for heading in ("## Contents\n", "# Table of contents\n"):
            self.assertEqual(rules({"docs/guide.md": lines(101, "# Guide\n" + heading)}), [])

    def test_a_heading_too_low_or_in_a_fence_does_not_count(self) -> None:
        low = lines(21) + "## Contents\n" + lines(90)
        fenced = "```\n## Contents\n```\n" + lines(100)
        for text in (low, fenced):
            self.assertEqual(len(rules({"docs/guide.md": text})), 1)

    def test_short_pages_and_other_pages_pass(self) -> None:
        files = {"docs/short.md": lines(100), "README.md": lines(200), SKILL: FRONTMATTER}
        self.assertEqual(rules(files), [])


class History(unittest.TestCase):
    def test_references_links_and_dates_are_flagged(self) -> None:
        for line in (
            "See #12.",
            "owner/repo#7 says so",
            "`#3`",
            "https://github.com/o/r/issues/4",
            "https://github.com/o/r/pull/5",
            "Decided on 2026-01-31.",
        ):
            with self.subTest(line=line):
                self.assertEqual(rules({"CLAUDE.md": line + "\n"}), [("CLAUDE.md", "history", 1)])

    def test_colours_entities_and_placeholders_pass(self) -> None:
        text = "#33ccff, &#123;, `Closes #N`, #1a, 12026-01-311, /issues/new\n"
        self.assertEqual(rules({"CLAUDE.md": text}), [])

    def test_skills_are_held_and_other_pages_are_not(self) -> None:
        files = {SKILL: FRONTMATTER + "See #12.\n", "README.md": "See #12.\n"}
        self.assertEqual(rules(files), [(SKILL, "history", 5)])

    def test_an_allow_on_the_line_or_in_the_comments_above_excuses_it(self) -> None:
        on_line = "Black is #000000. <!-- lint: allow(history) a colour -->\n"
        above = "<!-- lint: allow(history) a colour -->\n<!-- another -->\nBlack is #000000.\n"
        for text in (on_line, above):
            self.assertEqual(rules({"CLAUDE.md": text}), [])

    def test_an_allow_does_not_reach_past_other_text(self) -> None:
        text = "<!-- lint: allow(history) a colour -->\nprose\nBlack is #000000.\n"
        self.assertEqual(rules({"CLAUDE.md": text}), [("CLAUDE.md", "history", 3)])


class Allows(unittest.TestCase):
    ALLOW = "<!-- lint: allow(claude-md) it is generated -->"

    def test_a_file_allow_counts_anywhere_on_a_line_outside_a_fence(self) -> None:
        text = lines(301) + f"Generated. {self.ALLOW} Do not edit.\n"
        self.assertEqual(rules({"CLAUDE.md": text}), [])

    def test_a_file_allow_shown_in_a_fence_is_an_example(self) -> None:
        for fence in ("```", "~~~~"):
            text = lines(300) + f"{fence}md\n{self.ALLOW}\n{fence}\n"
            self.assertEqual(len(rules({"CLAUDE.md": text})), 1, fence)
        toc = "```\n<!-- lint: allow(reference-toc) why -->\n```\n" + lines(100)
        self.assertEqual(len(rules({"docs/guide.md": toc})), 1)

    def test_a_code_allow_must_be_a_comment_not_a_string(self) -> None:
        code = '"""Shows the allow:\n\n# lint: allow(skill-code) why\n"""\n' + "x = 1\n" * 400
        self.assertEqual(len(rules({".claude/skills/demo/x.py": code})), 1)

    def test_the_allow_must_be_inside_the_comment(self) -> None:
        between = "<!-- a --> lint: allow({}) a reason <!-- b -->\n"
        text = between.format("history") + "See #12.\n"
        self.assertEqual(rules({"CLAUDE.md": text}), [("CLAUDE.md", "history", 2)])
        self.assertEqual(len(rules({"CLAUDE.md": lines(301) + between.format("claude-md")})), 1)


class WhereSkillsLive(unittest.TestCase):
    def test_a_page_directly_under_skills_is_capped(self) -> None:
        path = ".claude/skills/README.md"
        self.assertIn((path, "skill-doc", 1), rules({path: lines(501, "## Contents\n")}))

    def test_a_nested_skills_folder_is_held_too(self) -> None:
        path = "frontend/.claude/skills/demo/SKILL.md"
        self.assertEqual(rules({path: FRONTMATTER + "See #12.\n"}), [(path, "history", 5)])
        self.assertEqual(rules({path: "# Demo\n"}), [(path, "skill-frontmatter", 1)])


class FrontmatterAsYamlReadsIt(unittest.TestCase):
    def problems(self, text: str) -> list[str]:
        return [v.message for v in lint({SKILL: text}, {SKILL: text}.get)]

    def test_a_comment_ends_a_plain_value(self) -> None:
        self.assertEqual(self.problems("---\nname: demo  # the folder\ndescription: D.\n---\n"), [])

    def test_an_unquoted_colon_is_flagged_and_a_quoted_one_passes(self) -> None:
        self.assertEqual(len(self.problems("---\nname: demo\ndescription: Use when: x\n---\n")), 1)
        self.assertEqual(self.problems('---\nname: demo\ndescription: "Use when: x"\n---\n'), [])

    def test_a_byte_order_mark_is_named(self) -> None:
        self.assertIn("byte-order mark", self.problems("\ufeff" + FRONTMATTER)[0])


class NotReferences(unittest.TestCase):
    def test_anchors_and_hashes_glued_to_a_word_pass(self) -> None:
        for line in ("[jump](#2-install)", "see [x](page.md#3)", "page.html#3", "C#12", "F#"):
            with self.subTest(line=line):
                self.assertEqual(rules({"CLAUDE.md": line + "\n"}), [])

    def test_a_ranking_cannot_be_told_from_a_reference(self) -> None:
        self.assertEqual(len(rules({"CLAUDE.md": "the #1 rule\n"})), 1)


class TocShapes(unittest.TestCase):
    def test_a_colon_or_an_underlined_heading_counts(self) -> None:
        for head in ("## Contents:\n", "Contents\n========\n", "Table of contents\n---\n"):
            with self.subTest(head=head):
                self.assertEqual(rules({"docs/guide.md": lines(101, head)}), [])

    def test_a_shorter_fence_inside_a_longer_one_does_not_close_it(self) -> None:
        text = "````\n```\n## Contents\n````\n" + lines(100)
        self.assertEqual(len(rules({"docs/guide.md": text})), 1)


class TheRepository(unittest.TestCase):
    def test_tracked_files_are_read_from_git(self) -> None:
        tracked = tracked_files(ROOT)
        self.assertIn("CLAUDE.md", tracked)
        self.assertIsNotNone(read_from(ROOT)("CLAUDE.md"))


if __name__ == "__main__":
    unittest.main()
