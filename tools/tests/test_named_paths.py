"""`named-path`: what a doc or a comment names must exist, read where it is meant."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


def named(files: dict[str, str]) -> list[str]:
    """The name each `named-path` finding among these files reports."""
    files = {REAL: "", "Makefile": MAKEFILE, **files}
    return [v.message.split("`")[1] for v in lint(files, files.get) if v.rule == "named-path"]


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
        ".githooks/pre-push": "#!/bin/sh\n# see {}\n",
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
    def test_wrapping_punctuation_and_suffixes_are_trimmed_until_stable(self) -> None:
        for text in (
            f"See **{GONE}**.",
            f"*{GONE}*.",
            f"<{GONE}>.",
            f"_{GONE}_.",
            f"`{GONE}:12`",
            f"`{GONE}::main`",
            f"{GONE}...",
            f"{GONE}…",
            f"{GONE}?plain=1",
            f"[x]({GONE})",
            f"./{GONE}",
            f"Is it {GONE}?",
        ):
            with self.subTest(text=text):
                self.assertEqual(named({"CLAUDE.md": text + "\n"}), [GONE])
        self.assertEqual(named({"CLAUDE.md": "**backend/gone/**.\n"}), ["backend/gone/"])

    def test_a_pattern_or_a_parent_is_skipped(self) -> None:
        for token in (
            "backend/<name>.py",
            "backend/*.py",
            "backend/{x}.py",
            "backend/x?.py",
            "backend/…/x.py",
            "backend/$X.py",
            "backend/%.py",
            "backend/~x.py",
            "backend/\\x.py",
            "backend/../gone.py",
        ):
            with self.subTest(token=token):
                self.assertEqual(found({"CLAUDE.md": token + "\n"}), [])

    def test_a_path_needs_a_root_and_an_extension_or_slash(self) -> None:
        text = "backend/gone, lib/gone.py, /backend/gone.py, backend/gone/, https://x.io/backend/a.py\n"
        self.assertEqual(named({"CLAUDE.md": text}), ["backend/gone/"])


class InsideALayer(unittest.TestCase):
    def test_a_backend_path_is_read_from_backend_too(self) -> None:
        files = {"backend/tools/lint.py": "", "backend/CLAUDE.md": "`tools/lint.py`\n"}
        self.assertEqual(found(files), [])
        files["backend/CLAUDE.md"] = "`tools/gone.py`\n"
        self.assertEqual(named(files), ["tools/gone.py"])

    def test_a_layer_folder_that_is_gone_still_fails(self) -> None:
        files = {"backend/CLAUDE.md": "`repositories/items.py`\n"}
        self.assertEqual(named(files), ["repositories/items.py"])
        files = {"frontend/CLAUDE.md": "`lib/api/client.ts`, `src/main.tsx`\n"}
        self.assertEqual(named(files), ["lib/api/client.ts", "src/main.tsx"])

    def test_frontend_paths_are_read_from_src_too(self) -> None:
        files = {"frontend/src/lib/a.ts": "", "frontend/scripts/b.ts": ""}
        files["frontend/CLAUDE.md"] = "`lib/a.ts`, `src/lib/a.ts`, `scripts/b.ts`\n"
        self.assertEqual(found(files), [])

    def test_a_folder_added_later_is_read_while_it_exists(self) -> None:
        files = {"backend/workers/a.py": "", "backend/CLAUDE.md": "`workers/a.py`\n"}
        self.assertEqual(found(files), [])
        files["backend/CLAUDE.md"] = "`workers/gone.py`\n"
        self.assertEqual(named(files), ["workers/gone.py"])

    def test_outside_a_layer_only_the_root_reading_counts(self) -> None:
        self.assertEqual(found({"CLAUDE.md": "`repositories/gone.py`\n"}), [])


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
        self.assertEqual(named({"CLAUDE.md": "Run `make gone`.\n"}), ["make gone"])
        self.assertEqual(named({"tools/x.py": "# run `make gone`\n"}), ["make gone"])

    def test_flags_variables_and_every_target_are_read(self) -> None:
        for command in ("make -s gone", "make -C dir gone", "make PYTHON=x gone", "make check gone",
                        "make -j 4 gone", "make gone; ls"):  # fmt: skip
            with self.subTest(command=command):
                self.assertEqual(named({"CLAUDE.md": f"`{command}`\n"}), ["make gone"])

    def test_a_command_line_in_a_fence_is_read_and_its_paths_are_not(self) -> None:
        text = f"```sh\nmake check   # all\n$ make gone\ncat {GONE}\necho make gone\n```\n"
        self.assertEqual(found({"docs/guide.md": text}), [("docs/guide.md", 3)])

    def test_the_verb_in_prose_is_not_a_target(self) -> None:
        text = "make sure; `make PYTHON=x`; `cmake gone`; `make <target>`\n"
        self.assertEqual(found({"CLAUDE.md": text}), [])

    def test_targets_are_read_from_rules_not_assignments(self) -> None:
        text = "a b: c\nd:: e\nX := 1\nY ?= 2\nZ ::= 3\nW :::= 4\n\tf: g\n"
        self.assertEqual(makefile_targets(text), {"a", "b", "d"})


class Allows(unittest.TestCase):
    def test_markdown_allows_on_the_line_or_in_the_comments_above(self) -> None:
        allow = "<!-- lint: allow(named-path) a command creates it -->"
        for text in (f"{GONE} {allow}\n", f"{allow}\n<!-- x -->\n{GONE}\n"):
            self.assertEqual(found({"CLAUDE.md": text}), [])
        self.assertEqual(found({"CLAUDE.md": f"{allow}\nprose\n{GONE}\n"}), [("CLAUDE.md", 3)])

    def test_code_allows_on_the_line_or_a_comment_line_above(self) -> None:
        for path, mark in (("tools/x.py", "#"), ("frontend/src/a.ts", "//")):
            allow = f"{mark} lint: allow(named-path) a command creates it"
            with self.subTest(path=path):
                self.assertEqual(found({path: f"{allow}\n{mark} {GONE}\n"}), [])
                self.assertEqual(found({path: f"x = 1 {mark} {GONE} {allow[len(mark) :]}\n"}), [])
                self.assertEqual(found({path: f"{allow}\nx = 1\n{mark} {GONE}\n"}), [(path, 3)])

    def test_an_allow_after_code_excuses_only_its_own_line(self) -> None:
        text = f"x = 1  # lint: allow(named-path) why\n# {GONE}\n"
        self.assertEqual(found({"tools/x.py": text}), [("tools/x.py", 2)])

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

    def test_untracked_counts_and_deleted_or_ignored_files_are_not_files(self) -> None:
        clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, clean, clear=True):
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            for name, text in {
                "a.md": "",
                "d.md": "",
                ".gitignore": "c.env\n",
                "Makefile": "x:\n",
            }.items():
                (repo / name).write_text(text)
            subprocess.run(["git", "add", "a.md", "d.md", ".gitignore"], cwd=repo, check=True)
            (repo / "d.md").unlink()
            (repo / "b.md").write_text("")
            (repo / "c.env").write_text("")
            tree = tree_of(repo)
            self.assertEqual(tree.files, {"a.md", ".gitignore", "Makefile", "b.md"})
            self.assertEqual(tree.targets, {"x"})
            self.assertTrue(tree.ignored("c.env"))  # asked of git, while the repo is there
            self.assertFalse(tree.ignored("b.md"))


if __name__ == "__main__":
    unittest.main()
