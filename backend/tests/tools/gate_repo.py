"""The throwaway repository the mutation tools' tests drive (the ``repo``
fixture in this directory's conftest), its sources, and ``CHECKOUT``, this
repository's root, for the tests that read its real files.

A plain module, so tests may import it.
"""

import subprocess
from pathlib import Path

# The checkout's root. These tests never run inside mutmut's copy
# (`pyproject.toml` leaves `tests/tools` out of its selection).
CHECKOUT = Path(__file__).resolve().parents[3]

GUARD = "backend/utils/guard.py"
GUARD_SOURCE = """\
\"\"\"A sensitive module.\"\"\"

import functools

LIMIT = 3


def allowed(role, attempts):
    if role == "admin":
        return True
    return attempts < LIMIT


class Checker:
    def check(self, token):
        def clean(value):
            return value.strip()

        return clean(token) != ""


@functools.cache
def decorated():
    return 1 + 1
"""

SENSITIVE_LIST = f"# sensitive\n{GUARD}\nhash-only backend/tools/mutation_gate.py\n"


class Repo:
    def __init__(self, root: Path) -> None:
        self.root = root

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, check=True
        ).stdout

    def write(self, path: str, text: str) -> None:
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text)

    def edit(self, path: str, old: str, new: str, *, commit: bool = True) -> None:
        """Change ``path``, committed unless asked not to: the gate reads commits."""
        file = self.root / path
        assert old in file.read_text(), old
        file.write_text(file.read_text().replace(old, new))
        if commit:
            self.commit()

    def commit(self) -> None:
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", "change")
