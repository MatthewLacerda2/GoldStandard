"""The conftest under mutation testing (``tests/conftest.py`` with
``tools/mutation_db.py``): each process names its own database, drops it when
its session ends, and refuses to run under a bare mutmut."""

import os

import pytest

from tests import conftest
from tools import mutation_db


def test_each_process_names_its_own_database(monkeypatch):
    base = mutation_db.base_name("/some/worktree")
    assert base != mutation_db.base_name("/another/worktree")
    assert len(mutation_db.process_name(base)) + 8 <= 63  # any pid fits Postgres' limit
    monkeypatch.setenv(mutation_db.ENV, base)
    assert conftest._test_db_name() == f"{base}_{os.getpid()}"


def test_outside_mutation_testing_it_is_the_worktrees_database(monkeypatch):
    monkeypatch.delenv(mutation_db.ENV, raising=False)
    monkeypatch.delenv("MUTANT_UNDER_TEST", raising=False)
    assert conftest._test_db_name() == conftest._worktree_db_name()


def test_a_bare_mutmut_run_fails_instead_of_sharing_one_database(monkeypatch):
    monkeypatch.delenv(mutation_db.ENV, raising=False)
    monkeypatch.setenv("MUTANT_UNDER_TEST", "stats")
    with pytest.raises(pytest.fail.Exception, match="make back-mutate"):
        conftest._test_db_name()


def test_the_session_drops_only_the_database_this_process_made(monkeypatch):
    dropped: list[str] = []

    async def drop(name: str) -> None:
        dropped.append(name)

    monkeypatch.setattr(conftest, "_drop_database", drop)
    monkeypatch.setenv(mutation_db.ENV, "test_gs_mut_x")
    monkeypatch.setattr(conftest, "_READY_DB", None)
    conftest.pytest_sessionfinish(None)
    assert dropped == []  # no test asked for one
    monkeypatch.setattr(conftest, "_READY_DB", conftest._test_db_name())
    conftest.pytest_sessionfinish(None)
    assert dropped == [f"test_gs_mut_x_{os.getpid()}"] and conftest._READY_DB is None


def test_the_maintenance_database_is_on_the_same_server():
    url = "postgresql+asyncpg://u:p@db:5433/app"
    assert mutation_db.admin_dsn(url) == "postgresql://u:p@db:5433/postgres"
