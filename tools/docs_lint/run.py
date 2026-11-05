"""Run every rule over the tracked files and report what they found."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

from tools.docs_lint import caps, frontmatter, history, toc
from tools.docs_lint.core import Doc, Violation

ROOT = Path(__file__).resolve().parents[2]

# Every rule, each a function of one file. A new rule is a module in this
# package, listed here.
RULES: tuple[Callable[[Doc], list[Violation]], ...] = (
    caps.check,
    frontmatter.check,
    toc.check,
    history.check,
)


def is_read(path: str) -> bool:
    """Whether any rule reads this file: every Markdown page, and every file
    under a `.claude/skills/` folder."""
    return PurePosixPath(path).suffix == ".md" or "/.claude/skills/" in f"/{path}"


def lint(tracked: Iterable[str], read: Callable[[str], str | None]) -> list[Violation]:
    """Every violation among the `tracked` paths; `read` gives a file's text, or
    `None` for one that is tracked but gone from the tree."""
    paths = frozenset(tracked)
    found: list[Violation] = []
    for path in sorted(p for p in paths if is_read(p)):
        text = read(path)
        if text is None:
            continue
        doc = Doc(PurePosixPath(path), text, paths)
        for rule in RULES:
            found.extend(rule(doc))
    return sorted(found, key=lambda v: (v.path, v.line, v.rule))


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def read_from(root: Path) -> Callable[[str], str | None]:
    def read(path: str) -> str | None:
        file = root / path
        return file.read_text(encoding="utf-8", errors="replace") if file.is_file() else None

    return read


def main() -> int:
    violations = lint(tracked_files(ROOT), read_from(ROOT))
    for v in violations:
        print(v)
    if violations:
        print(f"\ndocs-lint: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("docs-lint: clean")
    return 0
