"""`make back-mutate`: mutation testing of the backend.

Wraps ``mutmut run`` (configured under ``[tool.mutmut]`` in ``pyproject.toml``)
with the two things the config cannot express: a bare run is refused, since the
whole scope is rarely what one change needs, and the test databases a killed
mutant process never dropped are swept afterwards, whatever the outcome.

Usage, from ``backend/`` (needs Postgres up, like the tests)::

    python -m tools.mutate "repositories.items.x_list_owned*"   # what you changed
    python -m tools.mutate --all                                  # the whole scope

Results stay in ``mutants/`` (git-ignored): ``mutmut results`` lists the
survivors, ``mutmut show <name>`` prints one's diff. What to do with a
survivor: backend/CLAUDE.md, "Mutation testing".
"""

import asyncio
import subprocess
import sys

from tests.conftest import drop_mutation_databases

USAGE = (
    "[back-mutate] say what to mutate:\n"
    '  make back-mutate ONLY="repositories.items.x_list_owned*"   # the functions you changed\n'
    "  make back-mutate ALL=1                                      # the whole scope"
)


def _names(argv: list[str]) -> list[str] | None:
    """The mutant names to run (empty means everything), or None to refuse."""
    names = [arg for arg in argv if arg != "--all"]
    if "--all" in argv:
        return None if names else []
    return names or None


def main(argv: list[str]) -> int:
    names = _names(argv)
    if names is None:
        print(USAGE, file=sys.stderr)
        return 2
    try:
        return subprocess.call([sys.executable, "-m", "mutmut", "run", *names])
    finally:
        _sweep()


def _sweep() -> None:
    try:
        dropped = asyncio.run(drop_mutation_databases())
    except OSError as exc:
        # Postgres down: mutmut has already failed on it, and said so.
        print(f"[back-mutate] could not reach Postgres to sweep: {exc}", file=sys.stderr)
        return
    print(f"[back-mutate] swept {len(dropped)} leftover mutation database(s)")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
