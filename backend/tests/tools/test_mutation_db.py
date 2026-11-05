"""The test databases (``tests/conftest.py`` with ``tools/mutation_db.py``):
the URL's parameters reach both the test database and the maintenance one, and
under mutation testing each process names its own database, drops it when its
session ends, and refuses to run under a bare mutmut."""

import os

import pytest
from sqlalchemy import make_url

from core.database import normalize_database_url
from tests import conftest
from tools import mutation_db

# A server that requires TLS, as a hosted database does, plus a timeout.
WITH_PARAMS = "postgresql+asyncpg://u:p%2Fw@db:5433/app?ssl=require&command_timeout=30"


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


def test_the_maintenance_database_is_on_the_same_server_with_the_same_parameters():
    assert mutation_db.admin_connect_args(WITH_PARAMS) == {
        "host": "db",
        "port": 5433,
        "user": "u",
        "password": "p/w",
        "database": "postgres",
        "ssl": "require",
        "command_timeout": "30",
    }


def test_the_maintenance_connection_gets_what_the_apps_connections_get():
    # The dialect's own arguments for the app's URL, but for the database.
    url = make_url(WITH_PARAMS).set(database="postgres")
    _, app_args = url.get_dialect()().create_connect_args(url)
    assert mutation_db.admin_connect_args(WITH_PARAMS) == app_args


def test_libpqs_sslmode_reaches_the_maintenance_connection_as_ssl():
    url = normalize_database_url("postgres://u:p@db/app?sslmode=require")
    assert mutation_db.admin_connect_args(url)["ssl"] == "require"


def test_the_dialects_own_parameters_never_reach_asyncpg():
    url = f"{WITH_PARAMS}&prepared_statement_cache_size=0"
    assert "prepared_statement_cache_size" not in mutation_db.admin_connect_args(url)


def test_the_test_database_keeps_every_url_parameter(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", WITH_PARAMS)
    monkeypatch.delenv(mutation_db.ENV, raising=False)
    monkeypatch.delenv("MUTANT_UNDER_TEST", raising=False)
    url = conftest._test_url()
    assert url.database == conftest._worktree_db_name()
    assert dict(url.query) == {"ssl": "require", "command_timeout": "30"}
    assert (url.host, url.port, url.password) == ("db", 5433, "p/w")
