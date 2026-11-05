"""``make back-mutate`` (``tools/mutate.py``) refuses a bare run and native
Windows before doing any work, hands mutmut the names that keep its clean pass
small, gives every test process its own database, and says why mutmut failed."""

import importlib
import json
import os
import subprocess

import asyncpg
import pytest

from tests.tools.gate_repo import CHECKOUT
from tools import mutate, mutation_db

SECURITY = "utils.security.x_verify_password__mutmut_*"


@pytest.fixture
def no_work(monkeypatch):
    """Fail the test if the driver gets as far as Postgres or mutmut."""

    def refuse(*args, **kwargs):
        raise AssertionError("a refused run must do no work")

    monkeypatch.setattr(mutate, "_sweep", refuse)
    monkeypatch.setattr(mutate.subprocess, "call", refuse)


def test_a_bare_run_is_refused_before_any_work(no_work, capsys):
    assert mutate.main([]) == 2
    assert "ALL=1" in capsys.readouterr().err


def test_native_windows_is_sent_to_wsl_before_any_work(no_work, monkeypatch, capsys):
    monkeypatch.setattr(mutate.platform, "system", lambda: "Windows")
    assert mutate.main([SECURITY]) == 2
    err = capsys.readouterr().err
    assert "WSL" in err and "/mnt/c" in err and "Skipping is not" in err


def test_all_cannot_be_mixed_with_names(no_work):
    assert mutate.main(["--all", SECURITY]) == 2


@pytest.mark.parametrize(("argv", "names"), [([SECURITY], [SECURITY]), (["--all"], [])])
def test_names_or_all_are_handed_to_mutmut(argv, names):
    assert mutate._names(argv) == names


def test_one_functions_glob_gets_its_first_mutant_beside_it():
    first = "utils.security.x_verify_password__mutmut_1"
    assert mutate.with_clean_pass_names([SECURITY]) == [SECURITY, first]


@pytest.mark.parametrize(
    "name",
    [
        "utils.security*",  # already matches its functions' keys
        "utils.security.x_*__mutmut_*",  # many functions: no one first mutant
        "utils.security.x_verify_password__mutmut_3",  # exact already
    ],
)
def test_a_name_that_is_not_one_functions_mutants_is_passed_as_it_is(name):
    assert mutate.with_clean_pass_names([name]) == [name]


def test_main_runs_mutmut_with_the_databases_named_and_swept(monkeypatch):
    calls, swept = [], []
    monkeypatch.setattr(mutate, "_sweep", swept.append)
    monkeypatch.setattr(mutate.subprocess, "call", lambda argv, **kw: calls.append(kw) or 0)
    assert mutate.main([SECURITY]) == 0
    [kwargs] = calls
    base = kwargs["env"][mutation_db.ENV]
    assert base == mutation_db.base_name(str(mutate.REPO_ROOT)) and kwargs["cwd"] == mutate.BACKEND
    assert swept == [base, base]  # before and after


def test_every_preload_line_imports_and_none_is_ours():
    # mutmut skips a preload line that fails to import without a word.
    preload = CHECKOUT / "backend" / "tools" / "mutation_preload.txt"
    modules = [
        line.strip()
        for line in preload.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    ours = {"api", "core", "models", "repositories", "schemas", "services", "tools", "utils"}
    assert not {m.split(".")[0] for m in modules} & ours
    for name in modules:
        importlib.import_module(name)


def test_make_hands_each_glob_to_the_driver_unexpanded(tmp_path):
    # In backend/, an unquoted `utils*` is the directory `utils` to the shell.
    argv = tmp_path / "argv"
    argv.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    argv.chmod(0o755)
    out = subprocess.run(
        ["make", "-s", "back-mutate", f"PYTHON={argv}", "ONLY=utils* core.x*"],
        cwd=CHECKOUT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert out == ["-m", "tools.mutate", "utils*", "core.x*"]


def _meta(mutants, keys: list[str]) -> None:
    (mutants / "utils").mkdir(parents=True)
    (mutants / "utils" / "security.py.meta").write_text(
        json.dumps({"exit_code_by_key": dict.fromkeys(keys, None)})
    )


def test_a_name_no_mutant_matches_is_named_instead_of_a_failing_test(tmp_path, monkeypatch, capsys):
    _meta(tmp_path / "mutants", ["utils.security.x_verify_password__mutmut_1"])
    assert mutate.unmatched(tmp_path / "mutants", ["utils*", "utils", SECURITY]) == ["utils"]
    monkeypatch.setattr(mutate, "BACKEND", tmp_path)
    monkeypatch.setattr(mutate, "_sweep", lambda base: None)
    monkeypatch.setattr(mutate.subprocess, "call", lambda argv, **kw: 1)
    monkeypatch.setattr(mutate, "explain_failed_run", pytest.fail)
    assert mutate.main(["utils"]) == 1
    assert "no mutant matches utils" in capsys.readouterr().err


def test_a_database_that_refuses_the_sweep_keeps_mutmuts_exit_code(monkeypatch, capsys):
    async def refuse(admin_args, base):
        raise asyncpg.InvalidPasswordError("password authentication failed")

    explained = []
    monkeypatch.setattr(mutate.mutation_db, "sweep", refuse)
    monkeypatch.setattr(mutate.subprocess, "call", lambda argv, **kw: 3)
    monkeypatch.setattr(mutate, "explain_failed_run", lambda *args: explained.append(args))
    monkeypatch.setattr(mutate, "unmatched", lambda mutants, names: [])
    assert mutate.main([SECURITY]) == 3
    assert explained and "InvalidPasswordError" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("url", "error"),
    [
        ("not a url", "ArgumentError"),
        ("postgresql+psycopg://u:p@db/app", "ValueError"),
        # Refused when the URL is normalized: a key asyncpg does not take, a timeout of none.
        ("postgresql+asyncpg://u:p@db/app?keepalives=1", "ValueError"),
        ("postgresql+asyncpg://u:p@db/app?timeout=0", "ValueError"),
    ],
)
def test_a_url_asyncpg_cannot_take_skips_the_sweep_without_raising(url, error, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", url)
    mutate._sweep("test_gs_mut_x")
    assert f"could not drop the test databases: {error}" in capsys.readouterr().out


def _mutants_tree(root, conftest: str):
    """A ``backend/`` at ``root`` and its ``mutants/``: one conftest and one
    test in both."""
    for tree in (root, root / "mutants"):
        (tree / "tests").mkdir(parents=True)
        (tree / "pytest.ini").write_text("[pytest]\n")
        (tree / "tests" / "conftest.py").write_text(conftest)
        (tree / "tests" / "test_one.py").write_text("def test_one():\n    pass\n")
    return root / "mutants"


def test_a_suite_that_cannot_import_in_mutants_shows_pytests_error(tmp_path, capsys):
    # The one real collection: mutmut's fork server would have swallowed this.
    mutants = _mutants_tree(tmp_path, "import a_module_missing_from_also_copy\n")
    mutate.explain_failed_run(mutants, dict(os.environ), tmp_path)
    err = capsys.readouterr().err
    assert "does not import inside mutants/" in err
    assert "a_module_missing_from_also_copy" in err


def test_a_suite_that_imports_points_at_a_failing_test_instead(tmp_path, monkeypatch, capsys):
    mutants = _mutants_tree(tmp_path, "")
    collected = subprocess.CompletedProcess([], 0, "1 test collected", "")
    monkeypatch.setattr(mutate.subprocess, "run", lambda *args, **kw: collected)
    mutate.explain_failed_run(mutants, dict(os.environ), tmp_path)
    err = capsys.readouterr().err
    assert "a test failed on the unmutated code" in err and "does not import" not in err


def test_a_test_the_checkout_deleted_still_in_mutants_is_stale(tmp_path):
    mutants = _mutants_tree(tmp_path, "")
    (tmp_path / "tests" / "test_one.py").unlink()
    (mutants / "__pycache__").mkdir()
    (mutants / "__pycache__" / "cached.py").write_text("")  # mutmut's own, not a copy
    assert mutate.stale_copies(mutants, tmp_path) == ["tests/test_one.py"]


def test_a_truncated_meta_file_says_nothing_matches_nothing(tmp_path, capsys):
    (tmp_path / "utils").mkdir()
    (tmp_path / "utils" / "security.py.meta").write_text('{"exit_code_by_key": {"utils.sec')
    assert mutate.unmatched(tmp_path, ["utils"]) == []
    assert "unreadable" in capsys.readouterr().err
