"""`named-path`: what a doc or a comment names must exist, read where it is meant."""

from __future__ import annotations

import unittest

from tools.docs_lint.core import Tree
from tools.docs_lint.named_paths import makefile_targets
from tools.docs_lint.run import ROOT, lint, tree_of

REAL = "backend/main.py"
GONE = "backend/gone.py"
MAKEFILE = ".PHONY: check\ncheck: tools\ntools:\n\tpython -m x\nRUFF ?= ruff\n"


def found(files: dict[str, str], tree: Tree | None = None) -> list[tuple[str, int]]:
    """Where `named-path` fires among these files (the real file and the
    Makefile added), as `(path, line)`."""
    files = {REAL: "", "Makefile": MAKEFILE, **files}
    return [(v.path, v.line) for v in lint(files, files.get, tree) if v.rule == "named-path"]


class EachSourceKind(unittest.TestCase):
    """For each kind of file read: a missing name flags, a real one passes."""

    CASES = {
        "docs/guide.md": "See {}.\n",
        ".claude/skills/demo/ref.md": "See {}.\n",
        "CLAUDE.md": "See {}.\n",
        "frontend/README.md": "See {}.\n",
        "tools/x.py": "x = 1  # see {}\n",
        "frontend/src/a.ts": "const a = 1; // see {}\n",
        "frontend/src/b.tsx": "/**\n * see {}\n */\nexport {{}};\n",
        "tools/x.sh": 'echo "#"  # see {}\n',
        ".github/workflows/ci.yml": "on: push  # see {}\n",
        "Makefile": "x: ## see {}\n\techo\n",
    }

    def test_a_missing_path_is_flagged(self) -> None:
        for path, template in self.CASES.items():
            with self.subTest(path=path):
                line = template.count("\n", 0, template.index("{}")) + 1
                self.assertEqual(found({path: template.format(GONE)}), [(path, line)])

    def test_an_existing_path_passes(self) -> None:
        for path, template in self.CASES.items():
            with self.subTest(path=path):
                self.assertEqual(found({path: template.format(REAL)}), [])


class WhatIsNotRead(unittest.TestCase):
    def test_strings_are_never_read(self) -> None:
        files = {
            "tools/x.py": f'FIXTURE = "{GONE}"\n"""A docstring naming {GONE}."""\n',
            "frontend/src/a.ts": f"const a = '{GONE}'; const b = `// {GONE}`;\n",
            "tools/x.sh": f"echo '# {GONE}'\n",
        }
        self.assertEqual(found(files), [])

    def test_fences_and_files_outside_the_reach_are_not_read(self) -> None:
        files = {
            "docs/guide.md": f"```\n{GONE}\n```\n",
            "notes/page.md": f"{GONE}\n",
            "docker-compose.yml": f"# {GONE}\n",
            "frontend/src/styles.css": f"/* {GONE} */\n",
        }
        self.assertEqual(found(files), [])

    def test_the_makefile_recipe_is_code(self) -> None:
        self.assertEqual(found({"Makefile": f"x:\n\tcat {GONE}\n"}), [])


class WhatIsAPath(unittest.TestCase):
    def test_wrapping_punctuation_and_suffixes_are_trimmed(self) -> None:
        for text in (
            f"**{REAL}**",
            f"<{REAL}>",
            f"`{REAL}:12`",
            f"`{REAL}::main`",
            f"{REAL}.",
            f"[x]({REAL})",
            f"./{REAL}",
        ):
            with self.subTest(text=text):
                self.assertEqual(found({"CLAUDE.md": text + "\n"}), [])
        self.assertEqual(found({"CLAUDE.md": f"_{GONE}_:3.\n"}), [("CLAUDE.md", 1)])

    def test_patterns_parents_and_absolute_paths_are_skipped(self) -> None:
        for token in (
            "backend/<name>.py",
            "backend/*.py",
            "backend/{a,b}.py",
            "backend/…/x.py",
            "backend/$X.py",
            "backend/../x.py",
            "/backend/x.py",
            "~/backend/x.py",
        ):
            with self.subTest(token=token):
                self.assertEqual(found({"CLAUDE.md": token + "\n"}), [])

    def test_a_path_needs_a_root_and_an_extension_or_slash(self) -> None:
        text = "backend/gone and lib/gone.py and backend/gone/ and https://x.io/backend/a.py\n"
        self.assertEqual(found({"CLAUDE.md": text}), [("CLAUDE.md", 1)])

    def test_a_layer_doc_reads_its_own_folders_too(self) -> None:
        files = {"backend/tools/lint.py": "", "backend/CLAUDE.md": "`tools/lint.py`\n"}
        self.assertEqual(found(files), [])
        files["backend/CLAUDE.md"] = "`tools/gone.py` and `api/gone.py`\n"
        files["backend/api/x.py"] = ""
        self.assertEqual(found(files), [("backend/CLAUDE.md", 1), ("backend/CLAUDE.md", 1)])


class WhatExists(unittest.TestCase):
    def test_a_directory_holding_a_file_exists(self) -> None:
        self.assertEqual(found({"CLAUDE.md": "backend/ and backend\n"}), [])
        self.assertEqual(found({"CLAUDE.md": "frontend/\n"}), [("CLAUDE.md", 1)])

    def test_a_would_be_tracked_file_exists(self) -> None:
        tree = Tree(frozenset({REAL, GONE}), makefile_targets(MAKEFILE))
        self.assertEqual(found({"CLAUDE.md": f"{GONE}\n"}, tree), [])

    def test_an_ignored_path_exists_where_its_folder_does(self) -> None:
        def ignored(path: str) -> bool:
            return path.endswith((".env", ".venv/"))

        tree = Tree(frozenset({REAL}), frozenset(), ignored)
        text = "backend/.env, backend/.venv, backend/.venv/\n"
        self.assertEqual(found({"CLAUDE.md": text}, tree), [])
        self.assertEqual(found({"CLAUDE.md": "docker/.env\n"}, tree), [("CLAUDE.md", 1)])


class MakeTargets(unittest.TestCase):
    def test_a_target_in_a_code_span_must_be_in_the_makefile(self) -> None:
        self.assertEqual(found({"CLAUDE.md": "`make check PYTHON=x`, `cd a && make tools`\n"}), [])
        self.assertEqual(found({"CLAUDE.md": "Run `make gone`.\n"}), [("CLAUDE.md", 1)])
        self.assertEqual(found({"tools/x.py": "# run `make gone`\n"}), [("tools/x.py", 1)])

    def test_the_verb_in_prose_is_not_a_target(self) -> None:
        self.assertEqual(found({"CLAUDE.md": "make sure; `make PYTHON=x`; `cmake gone`\n"}), [])

    def test_targets_are_read_from_rules_not_assignments(self) -> None:
        text = "a b: c\nd:: e\nX := 1\nY ?= 2\n\tf: g\n"
        self.assertEqual(makefile_targets(text), {"a", "b", "d"})


class Allows(unittest.TestCase):
    def test_markdown_allows_on_the_line_or_in_the_comments_above(self) -> None:
        allow = "<!-- lint: allow(named-path) a command creates it -->"
        for text in (f"{GONE} {allow}\n", f"{allow}\n<!-- x -->\n{GONE}\n"):
            self.assertEqual(found({"CLAUDE.md": text}), [])
        self.assertEqual(found({"CLAUDE.md": f"{allow}\nprose\n{GONE}\n"}), [("CLAUDE.md", 3)])

    def test_code_allows_on_the_line_or_the_one_above(self) -> None:
        for path, mark in (("tools/x.py", "#"), ("frontend/src/a.ts", "//")):
            allow = f"{mark} lint: allow(named-path) a command creates it\n"
            with self.subTest(path=path):
                self.assertEqual(found({path: f"{allow}{mark} {GONE}\n"}), [])
                self.assertEqual(found({path: f"{allow}x = 1\n{mark} {GONE}\n"}), [(path, 3)])

    def test_an_allow_needs_its_reason(self) -> None:
        text = f"{GONE} <!-- lint: allow(named-path) -->\n"
        self.assertEqual(found({"CLAUDE.md": text}), [("CLAUDE.md", 1)])


class TheRepository(unittest.TestCase):
    def test_the_tree_is_read_from_git_and_the_makefile(self) -> None:
        tree = tree_of(ROOT)
        self.assertIn("tools/docs_lint/named_paths.py", tree.files)
        self.assertIn("docs-lint", tree.targets)
        self.assertTrue(tree.has(".env"))
        self.assertFalse(tree.has(GONE))


if __name__ == "__main__":
    unittest.main()
