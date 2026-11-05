"""No comment promises work later: the `marker` rule for files no layer lints.

A comment carrying one of the `MARKERS` as a whole upper-case word is work
nobody is assigned to: do it now, or file an issue and delete the comment.
`backend/tools/house_lint.py` holds Python to this and the frontend's ESLint
rule `local/no-marker-comment` holds TypeScript; this holds the `#`-comment
files kept outside both, the ones `FILES` lists.

Only comments are read: a `#` at the start of a line or after whitespace,
outside quotes, starts one, so `echo "#1"`, `$#` and `${#x}` are not. Quotes are
tracked within a line only, which can hide a comment (a stray apostrophe
before it) but never invents one.

The rare comment that must carry the word says why, inline:
`lint: allow(marker) <why>` on the line or in the comment lines directly above
it, the spelling the other two lints read. An allow without a reason excuses
nothing.

    python3.14 tools/markers.py   # scans the tracked files; exit 1 on a finding
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

MARKERS = ("TODO", "FIXME", "XXX", "HACK")
ADVICE = "do it now, or file an issue and delete the comment"

# Tracked files that take `#` comments and that no layer's lint reads.
FILES = (
    "Makefile",
    "**/*.sh",
    ".githooks/*",
    ".github/**/*.yml",
    ".github/**/*.yaml",
    "**/Dockerfile",
    "docker-compose.yml",
    ".env.example",
)

_MARKER_WORD = re.compile(rf"(?<![A-Za-z0-9_])(?:{'|'.join(MARKERS)})(?![A-Za-z0-9_])")
_ALLOW = re.compile(r"lint: allow\(marker\)[\s:—-]*\w")
ROOT = Path(__file__).resolve().parent.parent


def comment_of(line: str) -> str | None:
    """The comment on `line`, from its `#` to the end, or None if it has none."""
    quote = None
    for at, char in enumerate(line):
        if quote:
            quote = None if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (at == 0 or line[at - 1].isspace()):
            return line[at:]
    return None


def allowed(lines: list[str], index: int) -> bool:
    """Whether line `index` (0-based), or the comments directly above it, allow it."""
    if _ALLOW.search(lines[index]):
        return True
    for line in reversed(lines[:index]):
        if not line.lstrip().startswith("#"):
            return False
        if _ALLOW.search(line):
            return True
    return False


def check(path: str, text: str) -> list[str]:
    """A finding per line of `text` whose comment has a marker no allow excuses."""
    lines = text.splitlines()
    findings: list[str] = []
    for index, line in enumerate(lines):
        match = _MARKER_WORD.search(comment_of(line) or "")
        if match and not allowed(lines, index):
            findings.append(f"{path}:{index + 1}: '{match[0]}' comment: {ADVICE}")
    return findings


def is_checked(path: str) -> bool:
    """Whether the tracked file at `path` is one this rule reads."""
    return any(PurePosixPath(path).full_match(pattern) for pattern in FILES)


def main() -> int:
    """Scan the tracked files `FILES` names; print each finding."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    findings = [
        finding
        for path in tracked
        if is_checked(path)
        for finding in check(path, (ROOT / path).read_text(encoding="utf-8"))
    ]
    print("\n".join(findings) or "markers: clean")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
