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

# What the driver sets and the conftest reads: the base of every name.
ENV = "GS_MUTATION_DB"


def admin_dsn(database_url: str) -> str:
    """The maintenance ``postgres`` database of the server ``database_url``
    (a normalized SQLAlchemy asyncpg URL) names, as a raw asyncpg DSN."""
    head = database_url.rpartition("/")[0]
    return f"{head.replace('postgresql+asyncpg://', 'postgresql://')}/postgres"


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


async def sweep(admin_dsn: str, base: str) -> list[str]:
    """Drop every database of ``base``'s runs; return their names."""
    conn = await asyncpg.connect(admin_dsn)
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
