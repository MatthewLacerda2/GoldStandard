"""Is the running environment the one the requirement files pin? (stdlib only)

Every ``name==version`` line of the files given is compared with the version
``importlib.metadata`` finds installed for the interpreter running this. A venv
made before a pin moved still runs, on versions CI no longer uses, so a gate
run there judges nothing: every backend gate starts here and fails fast with
the install step instead.

What a line may carry: extras (``uvicorn[standard]``), a comment, a ``\\``
continuation and the options after the pin (``--hash=...``). Versions compare
as PEP 440 does for ``==``: ``2.0`` is ``2.0.0``, and a pin without a local
label (``+cpu``) matches any. ``===`` compares the strings, as pip does.

What it does not check, by design (it answers whether the ``==`` pins hold):

- a requirement that is not an exact pin (``>=``, ``~=``), or ``-r`` and other
  option lines;
- a pin behind an environment marker (``; python_version < ...``), which would
  need ``packaging`` to evaluate;
- that a pin's extras are installed: the extras of ``uvicorn[standard]`` are
  other packages, which only their own pin would hold;
- packages installed but no longer pinned.

It fails, rather than passing what it cannot judge, on a file with no pin it
can read and on a pin it cannot compare (a wildcard ``==1.*``, a version that
is not PEP 440).

    python tools/pins.py requirements.txt requirements-dev.txt
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

INSTALL = "run make back-install"

# `name[extras] == version`, then markers or options, which are cut off first.
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(===?)\s*(\S+)$")
_OPTION = re.compile(r"\s-")
# The canonical PEP 440 spellings: epoch, release, pre, post, dev, local.
_VERSION = re.compile(
    r"^(?:(\d+)!)?(\d+(?:\.\d+)*)((?:a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?(?:\+([a-z0-9.]+))?$"
)


def _lines(text: str) -> list[str]:
    """Logical lines, as pip reads them: comments dropped, continuations joined."""
    joined = re.sub(r"\\\n", " ", text)
    return [re.sub(r"(^|\s)#.*", "", line).strip() for line in joined.splitlines()]


def pins(text: str) -> dict[str, tuple[str, str]]:
    """The exact pins of one requirement file's text: name to (operator, version)."""
    found: dict[str, tuple[str, str]] = {}
    for line in _lines(text):
        if not line or line.startswith("-") or ";" in line:
            continue
        match = _PIN.match(_OPTION.split(line, maxsplit=1)[0].strip())
        if match:
            found[match[1]] = (match[2], match[3])
    return found


def _key(version: str) -> tuple | None:
    """What ``==`` compares in a version, or None if it is not PEP 440."""
    match = _VERSION.match(version.lower())
    if not match:
        return None
    epoch, release, pre, post, dev, local = match.groups()
    numbers = [int(n) for n in release.split(".")]
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers.pop()
    return int(epoch or 0), tuple(numbers), pre, post, dev, local


def _mismatch(operator: str, pinned: str, installed: str) -> str | None:
    """Why ``installed`` does not satisfy the pin, or None when it does."""
    if operator == "===":
        return None if installed == pinned else f"is {installed}, the pin is ==={pinned}"
    want, have = _key(pinned), _key(installed)
    if want is None or have is None:
        return f"is {installed}, and the pin =={pinned} cannot be checked: pin a plain version"
    if want[5] is None:
        have = (*have[:5], None)
    return None if want == have else f"is {installed}, the pin is {pinned}"


def drift(pinned: dict[str, tuple[str, str]]) -> list[str]:
    """One line per pin the environment does not hold at its version."""
    problems: list[str] = []
    for name, (operator, version) in pinned.items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name} is not installed, the pin is {version}")
            continue
        why = _mismatch(operator, version, installed)
        if why:
            problems.append(f"{name} {why}")
    return problems


def main(argv: list[str]) -> int:
    """Check every file named on the command line; exit 1 on any drift."""
    pinned: dict[str, tuple[str, str]] = {}
    problems: list[str] = []
    for name in argv:
        found = pins(Path(name).read_text(encoding="utf-8"))
        if not found:
            problems.append(f"{name} has no == pin this check can read")
        pinned |= found
    problems += drift(pinned)
    for problem in problems:
        print(f"pins: {problem}")
    if problems:
        print(f"pins: {sys.executable} does not match {' and '.join(argv)}: {INSTALL}")
        return 1
    print(f"pins: {len(pinned)} pins installed as pinned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
