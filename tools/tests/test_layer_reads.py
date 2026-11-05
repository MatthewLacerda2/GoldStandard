"""`tools/layer_reads.py`: a file a layer's code reads is one its CI job counts."""

from __future__ import annotations

import unittest

from tools.layer_reads import COUNTED, check, named, readings, scan

FILES = frozenset(
    {
        "Makefile",
        "README.md",
        "backend/tests/fixtures/case.json",
        "backend/tools/house_lint.py",
        "frontend/openapi.json",
        "frontend/data.json",
        "frontend/package.json",
        "tools/markers.py",
        "tools/secret.py",
    }
)


def found(reader: str, text: str, counted=COUNTED) -> list[str]:
    """What each finding names: the file it reads."""
    return [f.split("reads `")[1].split("`")[0] for f in check(reader, text, FILES, counted)]


class EachLayer(unittest.TestCase):
    def test_a_backend_read_of_a_file_the_backend_does_not_count_is_flagged(self) -> None:
        text = (
            'ROOT = Path(__file__).resolve().parents[2]\nDATA = ROOT / "frontend" / "data.json"\n'
        )
        self.assertEqual(found("backend/tests/test_x.py", text), ["frontend/data.json"])

    def test_a_backend_read_of_a_file_the_backend_counts_passes(self) -> None:
        text = 'CONTRACT = ROOT / "frontend" / "openapi.json"\nMAKE = ROOT / "Makefile"\n'
        self.assertEqual(found("backend/tools/contract.py", text), [])

    def test_a_frontend_read_of_a_file_the_frontend_does_not_count_is_flagged(self) -> None:
        text = 'const ROOT = join(import.meta.dirname, "..", "..");\nread(join(ROOT, "tools", "secret.py"));\n'
        self.assertEqual(found("frontend/scripts/x.test.ts", text), ["tools/secret.py"])

    def test_a_frontend_read_of_a_file_the_frontend_counts_passes(self) -> None:
        text = 'readFileSync(join(ROOT, "tools/markers.py"), "utf8");\nread("package.json");\n'
        self.assertEqual(found("frontend/eslint-rules/x.test.ts", text), [])

    def test_the_tools_job_runs_on_every_change_so_its_reads_all_pass(self) -> None:
        text = 'DATA = ROOT / "frontend" / "data.json"\nREADME = ROOT / "README.md"\n'
        self.assertEqual(found("tools/tests/test_x.py", text), [])

    def test_a_filter_on_the_tools_job_would_flag_its_reads_at_once(self) -> None:
        counted = {**COUNTED, "tools": ("tools/**",)}
        text = 'DATA = ROOT / "frontend" / "data.json"\n'
        self.assertEqual(found("tools/tests/test_x.py", text, counted), ["frontend/data.json"])

    def test_markdown_inside_a_layer_that_excludes_it_is_flagged(self) -> None:
        # The backend excludes `**/*.md`, so a backend test reading a page is skipped.
        self.assertEqual(found("backend/tests/test_x.py", 'ROOT / "README.md"\n'), ["README.md"])

    def test_code_outside_every_layer_is_not_read(self) -> None:
        self.assertEqual(found(".claude/skills/x/run.py", 'ROOT / "tools" / "secret.py"\n'), [])


class TheAllow(unittest.TestCase):
    def test_an_allow_with_a_reason_excuses_its_line(self) -> None:
        python = (
            '# lint: allow(layer-read) a fixture in a temporary repository\nwrite("README.md")\n'
        )
        self.assertEqual(found("backend/tests/test_x.py", python), [])
        script = 'commit({ "tools/secret.py": "x" }); // lint: allow(layer-read) a fixture\n'
        self.assertEqual(found("frontend/scripts/x.test.ts", script), [])

    def test_an_allow_without_a_reason_or_for_another_rule_excuses_nothing(self) -> None:
        for allow in ("# lint: allow(layer-read)", "# lint: allow(marker) a fixture"):
            text = f'{allow}\nwrite("README.md")\n'
            self.assertEqual(found("backend/tests/test_x.py", text), ["README.md"], allow)


class WhatNamesAFile(unittest.TestCase):
    def named(self, path: str, text: str) -> set[str]:
        return {literal for _, literal in named(path, text)}

    def test_python_joins_division_chains_call_arguments_and_f_string_tails(self) -> None:
        text = 'A = X.parents[3] / "frontend" / "openapi.json"\nB = Path("tools", "markers.py")\nC = f"{ROOT}/tools/secret.py"\n'
        self.assertLessEqual(
            {"frontend/openapi.json", "tools/markers.py", "tools/secret.py"},
            self.named("backend/x.py", text),
        )

    def test_python_skips_docstrings(self) -> None:
        text = '"""Reads frontend/data.json."""\n\ndef f():\n    "frontend/data.json"\n'
        self.assertEqual(self.named("backend/x.py", text), set())

    def test_scripts_join_call_arguments_and_template_tails_and_skip_comments(self) -> None:
        text = (
            'join(ROOT, "tools", "secret.py");\nconst t = `${ROOT}/frontend/data.json`;\n'
            '// read("README.md")\n/* "Makefile" */\n'
        )
        found = self.named("frontend/x.ts", text)
        self.assertLessEqual({"tools/secret.py", "frontend/data.json"}, found)
        self.assertFalse({"README.md", "Makefile"} & found, found)

    def test_a_literal_is_read_from_its_folder_and_each_one_above(self) -> None:
        reader = "backend/tests/test_x.py"
        self.assertEqual(
            readings(reader, "fixtures/case.json", FILES), ["backend/tests/fixtures/case.json"]
        )
        self.assertEqual(
            readings(reader, "tools/house_lint.py", FILES), ["backend/tools/house_lint.py"]
        )
        self.assertEqual(
            readings(reader, "../tools/house_lint.py", FILES), ["backend/tools/house_lint.py"]
        )

    def test_globs_absolute_paths_directories_and_escapes_name_no_file(self) -> None:
        for literal in (
            "frontend/*.json",
            "/frontend/data.json",
            "frontend",
            "../../../../Makefile",
        ):
            self.assertEqual(readings("backend/tests/test_x.py", literal, FILES), [], literal)


class TheRepository(unittest.TestCase):
    """Each cross-layer read this repository has, taken out of its layer's
    patterns, is found where the read is."""

    CASES = {
        ("backend", "frontend/openapi.json"): "backend/tools/openapi_contract.py",
        (
            "backend",
            "frontend/scripts/openapi-form.json",
        ): "backend/tests/tools/test_openapi_contract.py",
        ("frontend", "tools/markers.py"): "frontend/eslint-rules/marker-scope.test.ts",
    }

    def test_the_repository_is_clean(self) -> None:
        self.assertEqual(scan(COUNTED), [])

    def test_each_read_is_found_once_its_file_leaves_the_layer(self) -> None:
        for (layer, path), reader in self.CASES.items():
            patterns = tuple(p for p in COUNTED[layer] if p != path)
            self.assertNotEqual(patterns, COUNTED[layer], f"{path} is no longer in {layer}")
            findings = scan({**COUNTED, layer: patterns})
            self.assertTrue(
                any(f.startswith(f"{reader}:") and path in f for f in findings), findings
            )


if __name__ == "__main__":
    unittest.main()
