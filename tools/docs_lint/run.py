"""Run every rule over the tracked files and report what they found."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Iterable
from functools import cache
from pathlib import Path, PurePosixPath

from tools.docs_lint import caps, frontmatter, history, named_paths, toc
from tools.docs_lint.core import Doc, Tree, Violation

ROOT = Path(__file__).resolve().parents[2]

# Every rule, each a function of one file. A new rule is a module in this
# package, listed here.
RULES: tuple[Callable[[Doc], list[Violation]], ...] = (
    caps.check,
    frontmatter.check,
    toc.check,
    history.check,
    named_paths.check,
)


def is_read(path: str) -> bool:
    """Whether any rule reads this file: every Markdown page, every file under a
    `.claude/skills/` folder, and the code whose comments `named-path` reads."""
    return (
        PurePosixPath(path).suffix == ".md"
        or "/.claude/skills/" in f"/{path}"
        or named_paths.reads(path)
    )


def lint(
    tracked: Iterable[str], read: Callable[[str], str | None], tree: Tree | None = None
) -> list[Violation]:
    """Every violation among the `tracked` paths; `read` gives a file's text, or
    `None` for one that is tracked but gone from the tree. What exists is
    `tree`, by default the tracked paths and the Makefile `read` gives."""
    paths = frozenset(tracked)
    if tree is None:
        tree = Tree(paths, named_paths.makefile_targets(read("Makefile") or ""))
    found: list[Violation] = []
    for path in sorted(p for p in paths if is_read(p)):
        text = read(path)
        if text is None:
            continue
        doc = Doc(PurePosixPath(path), text, tree)
        for rule in RULES:
            found.extend(rule(doc))
    return sorted(found, key=lambda v: (v.path, v.line, v.rule))


def _git_files(root: Path, *args: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", *args], cwd=root, capture_output=True, check=True
    )
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def tracked_files(root: Path) -> list[str]:
    return _git_files(root)


def tree_of(root: Path) -> Tree:
    """What exists under `root`: the files on disk that git tracks or would
    track, the Makefile's targets, and what git ignores."""
    listed = {*_git_files(root), *_git_files(root, "--others", "--exclude-standard")}
    makefile = root / "Makefile"
    targets = makefile.read_text(encoding="utf-8") if makefile.is_file() else ""

    @cache
    def ignored(path: str) -> bool:
        check = ["git", "check-ignore", "--quiet", path]
        return subprocess.run(check, cwd=root, capture_output=True).returncode == 0

    present = frozenset(p for p in listed if (root / p).is_file())
    return Tree(present, named_paths.makefile_targets(targets), ignored)


def read_from(root: Path) -> Callable[[str], str | None]:
    def read(path: str) -> str | None:
        file = root / path
        return file.read_text(encoding="utf-8", errors="replace") if file.is_file() else None

    return read


def main() -> int:
    violations = lint(tracked_files(ROOT), read_from(ROOT), tree_of(ROOT))
    for v in violations:
        print(v)
    if violations:
        print(f"\ndocs-lint: {len(violations)} violation(s)", file=sys.stderr)
        return 1
    print("docs-lint: clean")
    return 0
