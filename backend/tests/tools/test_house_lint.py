"""Tests proving the custom house linter behaves as specified."""

import ast
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


def _code_file(code_lines: int) -> str:
    """A file of exactly ``code_lines`` lines of code, padded with non-code."""
    header = '"""Module docstring\n\nspanning lines.\n"""\n'
    body = "\n".join(f"# comment {i}\n\nx{i} = {i}" for i in range(code_lines))
    return header + body + "\n"


def test_comments_blank_lines_and_docstrings_do_not_count():
    at_cap = _code_file(house_lint.MAX_FILE_LINES)
    assert len(at_cap.splitlines()) > house_lint.MAX_FILE_LINES
    assert house_lint.check_source(Path("app/x.py"), at_cap) == []
    over = _code_file(house_lint.MAX_FILE_LINES + 1)
    assert any("file has" in v for v in house_lint.check_source(Path("app/x.py"), over))


def test_multiline_string_that_is_not_a_docstring_counts():
    body = "\n".join(f"line {i}" for i in range(house_lint.MAX_FILE_LINES + 5))
    source = f'x = 1\nTEXT = """\n{body}\n"""\n'
    violations = house_lint.check_source(Path("app/text.py"), source)
    assert any("file has" in v for v in violations)


def _handler(code_lines: int) -> str:
    """A handler of ``code_lines`` lines of code (``def`` included), plus a
    docstring, comments and blank lines."""
    lines = ["@router.get('/x')", "def handler():", '    """Doc', "", "    more doc.", '    """']
    lines += [f"    # note {i}\n\n    a{i} = {i}" for i in range(code_lines - 1)]
    return "\n".join(lines) + "\n"


def test_handler_docstring_and_comments_do_not_count():
    path = Path("api/v1/x.py")
    assert house_lint.check_source(path, _handler(house_lint.MAX_HANDLER_LINES)) == []
    over = house_lint.check_source(path, _handler(house_lint.MAX_HANDLER_LINES + 1))
    assert any("handler 'handler'" in v for v in over)


def test_one_line_def_with_docstring_counts_its_def():
    source = 'def f(): """doc"""\n'
    assert house_lint.code_lines(source, ast.parse(source)) == {1}


def test_clean_input_passes():
    source = "@router.get('/ok')\ndef ok():\n    return 1\n"
    violations = house_lint.check_source(Path("api/v1/ok.py"), source)
    assert violations == []


SCHEMA_IMPORT = "from schemas.items import ItemCreate, ItemRead\n"


def _io_violations(body: str, imports: str = SCHEMA_IMPORT) -> list[str]:
    return house_lint.check_source(Path("api/v1/x.py"), imports + body)


def test_schema_body_param_passes():
    body = "@router.post('/x')\ndef create(payload: ItemCreate) -> ItemRead:\n    return 1\n"
    assert _io_violations(body) == []


def test_non_schema_body_param_fails():
    body = "@router.post('/x')\ndef create(payload: dict) -> ItemRead:\n    return 1\n"
    assert any("parameter 'payload' is 'dict'" in v for v in _io_violations(body))


def test_scalar_path_and_query_params_pass():
    body = (
        "@router.get('/x')\ndef read(item_id: uuid.UUID, limit: int) -> ItemRead:\n    return 1\n"
    )
    assert _io_violations(body) == []


def test_injected_dependency_passes():
    body = (
        "@router.get('/x')\n"
        "def read(session: AsyncSession = Depends(get_db)) -> ItemRead:\n"
        "    return 1\n"
    )
    assert _io_violations(body) == []


def test_annotated_dependency_passes():
    body = (
        "@router.get('/x')\n"
        "def read(session: Annotated[AsyncSession, Depends(get_db)]) -> ItemRead:\n"
        "    return 1\n"
    )
    assert _io_violations(body) == []


def test_list_of_schema_return_passes():
    body = "@router.get('/x')\ndef read() -> list[ItemRead]:\n    return []\n"
    assert _io_violations(body) == []


def test_none_return_passes():
    body = "@router.delete('/x')\ndef remove(item_id: uuid.UUID) -> None:\n    return None\n"
    assert _io_violations(body) == []


def test_non_schema_return_fails():
    body = "@router.get('/x')\ndef read() -> dict:\n    return {}\n"
    assert any("returns 'dict'" in v for v in _io_violations(body))


def test_list_of_non_schema_return_fails():
    body = "@router.get('/x')\ndef read() -> list[dict]:\n    return []\n"
    assert any("returns 'list[dict]'" in v for v in _io_violations(body))


def test_schema_shaped_name_without_import_fails():
    body = "@router.post('/x')\ndef create(payload: ItemCreate) -> ItemRead:\n    return 1\n"
    violations = _io_violations(body, imports="")
    assert any("parameter 'payload' is 'ItemCreate'" in v for v in violations)
    assert any("returns 'ItemRead'" in v for v in violations)


def test_schema_module_import_passes():
    body = "@router.get('/x')\ndef read() -> schemas.items.ItemRead:\n    return 1\n"
    assert _io_violations(body, imports="import schemas.items\n") == []


def test_non_handler_function_ignored():
    body = "def helper(raw: dict) -> dict:\n    return raw\n"
    assert _io_violations(body) == []


def test_app_decorated_baseline_route_ignored():
    body = "@app.get('/health')\ndef health() -> dict[str, str]:\n    return {}\n"
    assert _io_violations(body, imports="") == []
