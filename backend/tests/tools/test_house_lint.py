"""Tests proving the custom house linter behaves as specified."""

from pathlib import Path

from tools import house_lint


def test_too_long_file_fails():
    source = "\n".join(f"x = {i}" for i in range(house_lint.MAX_FILE_LINES + 5))
    violations = house_lint.check_source(Path("app/big.py"), source)
    assert any("file has" in v for v in violations)


def test_data_file_marker_exempts():
    body = "\n".join(f"x = {i}" for i in range(house_lint.MAX_FILE_LINES + 5))
    source = f"{house_lint.DATA_FILE_MARKER}\n{body}"
    violations = house_lint.check_source(Path("app/data.py"), source)
    assert violations == []


def test_long_handler_fails():
    lines = ["@router.get('/x')", "def handler():"]
    lines += [f"    a{i} = {i}" for i in range(house_lint.MAX_HANDLER_LINES + 1)]
    source = "\n".join(lines)
    violations = house_lint.check_source(Path("api/v1/x.py"), source)
    assert any("handler 'handler'" in v for v in violations)


def test_long_test_fails():
    lines = ["def test_big():"]
    lines += [f"    a{i} = {i}" for i in range(house_lint.MAX_TEST_LINES + 1)]
    source = "\n".join(lines)
    violations = house_lint.check_source(Path("tests/test_x.py"), source)
    assert any("test 'test_big'" in v for v in violations)


def test_tests_dir_exempt_from_file_length():
    source = "\n".join(f"x = {i}" for i in range(house_lint.MAX_FILE_LINES + 5))
    violations = house_lint.check_source(Path("tests/test_huge.py"), source)
    assert all("file has" not in v for v in violations)


def test_clean_input_passes():
    source = "@router.get('/ok')\ndef ok():\n    return 1\n"
    violations = house_lint.check_source(Path("api/v1/ok.py"), source)
    assert violations == []
