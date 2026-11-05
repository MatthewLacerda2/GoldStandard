"""`make back-mutate`: mutation testing of the backend, with its databases.

Wraps ``mutmut run`` (configured under ``[tool.mutmut]`` in ``pyproject.toml``)
with what the config cannot express:

- it refuses on native Windows, where mutmut cannot run, with the way forward
  (WSL), and refuses a bare run: the whole scope is rarely what one change
  needs, so ``--all`` asks for it on purpose;
- every pytest process gets a database of its own (``tools/mutation_db.py``),
  and whatever a killed process left behind is dropped before and after;
- it names each function's first mutant beside its glob, so mutmut's clean
  pass runs only that function's tests (``with_clean_pass_names``);
- when mutmut fails before any verdict, it says why (``explain_failed_run``).

Usage, from ``backend/`` (needs Postgres up, like the tests)::

    python -m tools.mutate "utils.security.x_verify_password__mutmut_*"
    python -m tools.mutate --all

Results stay in ``mutants/`` (git-ignored): ``mutmut results`` lists what was
not killed, ``mutmut show <name>`` prints one mutant's diff. What to do with a
survivor: backend/CLAUDE.md, "Mutation testing".
"""

import asyncio
import json
import os
import platform
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

import asyncpg
from sqlalchemy.exc import ArgumentError

from tools import mutation_db

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent

USAGE = (
    "[back-mutate] say what to mutate:\n"
    '  make back-mutate ONLY="utils.security.x_verify_password__mutmut_*"   # one function\n'
    '  make back-mutate ONLY="utils.security*"                              # one module\n'
    "  make back-mutate ALL=1                                               # the whole scope"
)

# mutmut forks a process per mutant and cannot run on native Windows. A
# refusal here means "move to WSL", never "skip it".
NATIVE_WINDOWS = (
    "[back-mutate] mutmut cannot run on native Windows (it forks a process per mutant).\n"
    "  Run it under WSL: clone the repo inside the WSL filesystem (~/..., not /mnt/c,\n"
    "  where every file read crosses into Windows), `make back-install`, start Postgres\n"
    "  and export DATABASE_URL as for the tests, then the same command. Skipping is not\n"
    "  an option in sensitive code: the `mutation gate` check stays red without the run."
)

# Enough of pytest's report to hold an import error's traceback.
_ERROR_TAIL_LINES = 60
# What mutmut and pytest write into `mutants/` themselves, never a copy.
_NOT_COPIES = {"__pycache__", ".pytest_cache"}
# What ends a glob of one function's mutants, and what makes a name a glob.
_ALL_MUTANTS = "__mutmut_*"
_GLOB = set("*?[")


def _names(argv: list[str]) -> list[str] | None:
    """The mutant names to run (empty means everything), or None to refuse."""
    names = [arg for arg in argv if arg != "--all"]
    if "--all" in argv:
        return None if names else []
    return names or None


def with_clean_pass_names(names: list[str]) -> list[str]:
    """``names``, each ``<module>.x_name__mutmut_*`` followed by its first mutant.

    mutmut picks the clean pass's tests by matching each name against the
    functions it mapped, keyed ``<module>.x_name`` without ``__mutmut_N``, so a
    glob ending in ``__mutmut_*`` matches none, and with no test found the
    clean pass runs the whole suite: slow, and any flaky test fails the run. An
    exact name is looked up by its function instead. mutmut numbers a
    function's mutants from 1, so the mutants run are the same.
    """
    result: list[str] = []
    for name in names:
        result.append(name)
        function = name.removesuffix(_ALL_MUTANTS)
        if function != name and not _GLOB & set(function):
            result.append(f"{function}__mutmut_1")
    return result


def stale_copies(mutants: Path, backend: Path) -> list[str]:
    """Files in ``mutants/`` that the checkout no longer has.

    mutmut copies files in and never removes one, so after a pull a test that
    was deleted is still collected inside ``mutants/``, against code that
    moved on, and the first pass fails. A mutated module differs from its
    original by design; only a copy whose original is gone is stale.
    """
    return sorted(
        str(rel)
        for copy in mutants.rglob("*.py")
        if not set((rel := copy.relative_to(mutants)).parts) & _NOT_COPIES
        and not (backend / rel).exists()
    )


def explain_failed_run(mutants: Path, env: dict[str, str], backend: Path = BACKEND) -> None:
    """Say why the suite did not run, which mutmut leaves unsaid.

    Under the fork server, mutmut runs its first passes in a child and keeps
    their output there, so a suite that cannot even import inside ``mutants/``
    (a file missing from ``also_copy``, a conftest that raises) ends in "Failed
    to run clean test", never pytest's error. Collecting the suite there again,
    outside mutmut, prints it. A stale ``mutants/`` is named first.
    """
    if not mutants.is_dir():
        return
    if stale := stale_copies(mutants, backend):
        print(
            f"[back-mutate] mutants/ is stale: {len(stale)} file(s) the checkout no longer has,"
            f" e.g. {', '.join(stale[:3])}. Delete mutants/ and run again.",
            file=sys.stderr,
        )
    probe = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=mutants,
        env=env,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        print(
            "[back-mutate] the suite imports inside mutants/, so a test failed on the unmutated"
            " code: run it there by hand (backend/CLAUDE.md, Mutation testing)",
            file=sys.stderr,
        )
        return
    output = (probe.stdout + probe.stderr).strip().splitlines()
    print(
        "[back-mutate] the suite does not import inside mutants/; pytest says:",
        *output[-_ERROR_TAIL_LINES:],
        sep="\n",
        file=sys.stderr,
    )


def _admin_args() -> dict:
    """The maintenance database, from the URL the tests use."""
    from core.config import get_settings
    from core.database import normalize_database_url

    url = os.environ.get("DATABASE_URL") or get_settings().DATABASE_URL
    return mutation_db.admin_connect_args(normalize_database_url(url))


# Postgres down or refusing us, or settings that do not load (a URL SQLAlchemy
# cannot read among them): mutmut has failed on it too (or will), and says so.
_UNREACHABLE = (OSError, ValueError, ArgumentError, asyncpg.PostgresError, asyncpg.InterfaceError)


def _sweep(base: str) -> None:
    """Drop this worktree's mutation databases, never raising: in the driver's
    ``finally`` a traceback would replace mutmut's exit code and the diagnosis."""
    try:
        dropped = asyncio.run(mutation_db.sweep(_admin_args(), base))
    except _UNREACHABLE as exc:
        print(f"[back-mutate] could not drop the test databases: {type(exc).__name__}: {exc}")
        return
    if dropped:
        print(f"[back-mutate] dropped {len(dropped)} leftover mutation database(s)")


def native_windows() -> bool:
    """Whether this is native Windows, saying where to go when it is. Every
    entry point that runs mutants asks first, before any other work."""
    if platform.system() != "Windows":
        return False
    print(NATIVE_WINDOWS, file=sys.stderr)
    return True


def unmatched(mutants: Path, names: list[str]) -> list[str]:
    """The names no generated mutant matches (mutmut asserts and stops on
    one, and a bare word the shell expanded, ``utils`` for ``utils*``, is the
    usual cause). Read from the ``.meta`` files the generation step writes."""
    keys: list[str] = []
    for meta in mutants.rglob("*.meta"):
        try:
            keys += json.loads(meta.read_text()).get("exit_code_by_key", {})
        except json.JSONDecodeError, UnicodeDecodeError:
            # A run killed while writing it: its names are unknown, not absent,
            # so nothing can be said to match nothing.
            print(f"[back-mutate] {meta} is unreadable; delete mutants/", file=sys.stderr)
            return []
    return [n for n in names if not any(key == n or fnmatch(key, n) for key in keys)]


def main(argv: list[str]) -> int:
    if native_windows():
        return 2
    names = _names(argv)
    if names is None:
        print(USAGE, file=sys.stderr)
        return 2
    # Named after this worktree here: inside `mutants/` its path would differ.
    base = mutation_db.base_name(str(REPO_ROOT))
    env = {
        **os.environ,
        mutation_db.ENV: base,
        # On macOS, a forked child that reads the system proxy settings (any
        # httpx client does) can segfault, and a crash counts as a kill. With
        # a `*_proxy` variable set, the environment is read instead.
        "no_proxy": "*",
    }
    _sweep(base)
    try:
        command = [sys.executable, "-m", "mutmut", "run", *with_clean_pass_names(names)]
        code = subprocess.call(command, cwd=BACKEND, env=env)
        if code != 0 and (missing := unmatched(BACKEND / "mutants", names)):
            print(
                f"[back-mutate] no mutant matches {', '.join(missing)}: a function's mutants are"
                " `<module>.x_<function>__mutmut_*`, a module's `<module>*` (quote the glob)",
                file=sys.stderr,
            )
        elif code != 0:
            explain_failed_run(BACKEND / "mutants", env)
        return code
    finally:
        _sweep(base)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
