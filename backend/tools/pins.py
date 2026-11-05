"""Is the running environment the one the requirement files pin? (stdlib only)

Every ``name==version`` line of the files given is compared with the version
``importlib.metadata`` finds installed for the interpreter running this. A venv
made before a pin moved still runs, on versions CI no longer uses, so a gate
run there judges nothing: every backend gate starts here and fails fast with
the install step instead. Lines that pin nothing exactly (``>=``, ``-r``, a
comment) are not read, nor is a pin behind an environment marker
(``; python_version < ...``), which would need ``packaging`` to evaluate.

    python tools/pins.py requirements.txt requirements-dev.txt
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

# `name[extras]==version`, the extras dropped: they install more packages, not
# a different version of this one.
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([^\s;#]+)\s*(#.*)?$")
INSTALL = "run make back-install"


def pins(text: str) -> dict[str, str]:
    """The exact pins of one requirement file's text: name to version."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = _PIN.match(line.strip())
        if match:
            found[match[1]] = match[2]
    return found


def drift(pinned: dict[str, str]) -> list[str]:
    """One line per pin the environment does not hold at its version."""
    problems: list[str] = []
    for name, version in pinned.items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name} is not installed, the pin is {version}")
            continue
        if installed != version:
            problems.append(f"{name} is {installed}, the pin is {version}")
    return problems


def main(argv: list[str]) -> int:
    """Check every file named on the command line; exit 1 on any drift."""
    pinned: dict[str, str] = {}
    for name in argv:
        pinned |= pins(Path(name).read_text(encoding="utf-8"))
    problems = drift(pinned)
    for problem in problems:
        print(f"pins: {problem}")
    if problems:
        print(f"pins: {sys.executable} has drifted from {' and '.join(argv)}: {INSTALL}")
        return 1
    print(f"pins: {len(pinned)} pins installed as pinned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
