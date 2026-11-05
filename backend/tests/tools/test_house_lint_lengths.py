"""The length rules on a tree that is not the backend's: ``--lengths ROOT``.

``make tools`` runs them over the root ``tools/`` folder, whose tests are
``unittest`` methods inside classes rather than module-level functions.
"""

from pathlib import Path

from tools import house_lint


def _long_test_method() -> str:
    lines = ["import unittest", "", "class T(unittest.TestCase):", "    def test_big(self):"]
    lines += [f"        a{i} = {i}" for i in range(house_lint.MAX_TEST_LINES)]
    return "\n".join(lines) + "\n"


def test_a_long_test_method_in_a_class_fails():
    violations = house_lint.check_source(Path("tests/test_x.py"), _long_test_method())
    assert any("test 'test_big'" in v for v in violations)


def test_a_test_method_at_the_limit_passes():
    source = _long_test_method().replace(f"        a{house_lint.MAX_TEST_LINES - 1} = ", "#")
    assert house_lint.check_source(Path("tests/test_x.py"), source) == []


def test_lengths_only_skips_the_backend_rules():
    source = "@router.get('/x')\ndef read() -> dict:  # TODO: a marker\n    return {}\n"
    assert house_lint.check_source(Path("app/x.py"), source) != []
    assert house_lint.check_source(Path("app/x.py"), source, lengths_only=True) == []


def test_main_scans_the_tree_it_is_given(tmp_path, capsys):
    (tmp_path / "tests").mkdir()
    test_file = tmp_path / "tests/test_x.py"
    test_file.write_text("def test_ok():\n    assert True\n")
    assert house_lint.main(["--lengths", str(tmp_path)]) == 0
    test_file.write_text(_long_test_method())
    (tmp_path / "big.py").write_text("x = 1\n" * (house_lint.MAX_FILE_LINES + 1))
    assert house_lint.main(["--lengths", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "test 'test_big'" in out
    assert f"big.py: file has {house_lint.MAX_FILE_LINES + 1} lines" in out


def test_a_tests_folder_above_the_tree_exempts_nothing(tmp_path):
    root = tmp_path / "tests/repo"
    root.mkdir(parents=True)
    (root / "big.py").write_text("x = 1\n" * (house_lint.MAX_FILE_LINES + 1))
    assert any("big.py: file has" in v for v in house_lint.scan(root, lengths_only=True))


def test_a_missing_or_empty_root_fails(tmp_path):
    for root in (tmp_path / "missing", tmp_path):
        assert house_lint.main(["--lengths", str(root)]) == 1


def test_mutmuts_working_copy_inside_the_tree_is_skipped(tmp_path):
    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "mutants").mkdir()
    (tmp_path / "mutants/big.py").write_text("x = 1\n" * (house_lint.MAX_FILE_LINES + 1))
    assert house_lint.scan(tmp_path, lengths_only=True) == []
