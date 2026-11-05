"""``make back-mutate`` (``tools/mutate.py``) refuses a bare run and native
Windows before doing any work, hands mutmut the names that keep its clean pass
small, gives every test process its own database, and says why mutmut failed."""

import os
import subprocess
import sys

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


def test_each_process_names_its_own_database():
    base = mutation_db.base_name("/some/worktree")
    assert mutation_db.process_name(base) == f"{base}_{os.getpid()}"
    assert len(mutation_db.process_name(base)) + 8 <= 63  # any pid fits Postgres' limit
    assert base != mutation_db.base_name("/another/worktree")


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
    probe = f"import importlib\nfor name in {modules!r}: importlib.import_module(name)\n"
    subprocess.run([sys.executable, "-c", probe], check=True)


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
    mutants = _mutants_tree(tmp_path, "import a_module_missing_from_also_copy\n")
    mutate.explain_failed_run(mutants, dict(os.environ), tmp_path)
    err = capsys.readouterr().err
    assert "does not import inside mutants/" in err
    assert "a_module_missing_from_also_copy" in err


def test_a_suite_that_imports_points_at_a_failing_test_instead(tmp_path, capsys):
    mutants = _mutants_tree(tmp_path, "")
    mutate.explain_failed_run(mutants, dict(os.environ), tmp_path)
    err = capsys.readouterr().err
    assert "a test failed on the unmutated code" in err and "does not import" not in err


def test_a_test_the_checkout_deleted_still_in_mutants_says_to_delete_it(tmp_path, capsys):
    mutants = _mutants_tree(tmp_path, "")
    (tmp_path / "tests" / "test_one.py").unlink()
    (mutants / "__pycache__").mkdir()
    (mutants / "__pycache__" / "cached.py").write_text("")  # mutmut's own, not a copy
    mutate.explain_failed_run(mutants, dict(os.environ), tmp_path)
    err = capsys.readouterr().err
    assert "mutants/ is stale: 1 file(s)" in err and "tests/test_one.py" in err
