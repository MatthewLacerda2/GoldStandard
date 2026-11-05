"""Test databases under mutation testing: one per pytest process.

mutmut runs the suite in many processes at once. On the worktree's one test
database (``tests/conftest.py``) they would race: two processes creating the
schema together, or one holding a row another inserts, make a test fail for a
reason the mutant has nothing to do with, and a failed test counts as a kill.
That hides survivors instead of failing loudly.

So ``make back-mutate`` (``tools/mutate.py``) exports a base name in ``ENV``,
and under it the conftest names its database ``<base>_<pid>``: created the
first time a test asks for one (most mutants' tests never do), dropped when its
session ends. ``sweep`` drops what a killed process left behind, before and
after every run. The name is the process', so it is taken when a test asks,
never at import.
"""

import hashlib
import os

import asyncpg
from sqlalchemy import make_url

# What the driver sets and the conftest reads: the base of every name.
ENV = "GS_MUTATION_DB"

# URL parameters SQLAlchemy's asyncpg dialect keeps for its own adapter, which
# `asyncpg.connect` would refuse as unknown arguments.
_ADAPTER_ONLY = ("prepared_statement_cache_size", "prepared_statement_name_func")


def admin_connect_args(database_url: str) -> dict:
    """``asyncpg.connect`` arguments for the maintenance ``postgres`` database
    of the server ``database_url`` (a normalized SQLAlchemy asyncpg URL) names.

    They are the ones SQLAlchemy's dialect hands asyncpg for the app's own
    connections, so every URL parameter (``ssl=require``, a timeout) reaches
    this connection under the same name. A raw DSN would not do: asyncpg reads
    a DSN by libpq's names (``sslmode``) and sends any other one to the server
    as a setting, which it refuses.
    """
    url = make_url(database_url).set(database="postgres")
    _, args = url.get_dialect()().create_connect_args(url)
    return {key: value for key, value in args.items() if key not in _ADAPTER_ONLY}


async def drop(conn: asyncpg.Connection, name: str) -> None:
    """Drop ``name``, cutting any connection still open to it."""
    await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def base_name(repo_root: str) -> str:
    """``test_gs_mut_<12 hex>``: this worktree's, computed by the driver.

    Inside ``mutants/`` the path would differ, so the conftest never derives it
    itself. Short enough that ``<base>_<pid>`` fits Postgres' 63 bytes.
    """
    digest = hashlib.sha1(repo_root.encode()).hexdigest()[:12]
    return f"test_gs_mut_{digest}"


# lint: allow(deadcode) the conftest names its database with it during a mutation run
def process_name(base: str) -> str:
    """This process' own database."""
    return f"{base}_{os.getpid()}"


async def sweep(admin_args: dict, base: str) -> list[str]:
    """Drop every database of ``base``'s runs; return their names.
    ``admin_args`` is what ``admin_connect_args`` returns."""
    conn = await asyncpg.connect(**admin_args)
    try:
        rows = await conn.fetch(
            "SELECT datname FROM pg_database WHERE starts_with(datname, $1)", f"{base}_"
        )
        names = sorted(row["datname"] for row in rows)
        for name in names:
            await drop(conn, name)
    finally:
        await conn.close()
    return names
