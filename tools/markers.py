"""No comment promises work later: the `marker` rule for files no layer lints.

A comment carrying one of the `MARKERS` as a whole upper-case word is work
nobody is assigned to: do it now, or file an issue and delete the comment.
`backend/tools/house_lint.py` holds the backend's Python to this and the
frontend's ESLint rule `local/no-marker-comment` its TypeScript (`LAYER_LINTED`);
this holds every other tracked file that takes comments (`FILES`). The rest
take none, or are prose and generated files (`NOT_READ`), and
`tools/tests/test_markers.py` fails on a tracked file none of the three names.

Only comment text is read, for the marker and the allow alike. In a `#` file, a
`#` at the start of a line or after whitespace, outside quotes and not escaped
with a backslash, starts a comment, so `echo "a # b"`, `$#` and `${#x}` are not
comments. Quotes are tracked within a line only, which can hide a comment (a
stray apostrophe before it) but never invents one.

The rare comment that must carry the word says why, inline:
`lint: allow(marker) <why>` in the comment on the line or on the line directly
above it, the spelling the other two lints read. An allow without a reason
excuses nothing.

    python3.14 tools/markers.py   # scans the tracked files; exit 1 on a finding
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path, PurePosixPath

MARKERS = ("TODO", "FIXME", "XXX", "HACK")
ADVICE = "do it now, or file an issue and delete the comment"

# What each layer's own lint reads.
LAYER_LINTED = ("backend/**/*.py", "frontend/**/*.ts", "frontend/**/*.tsx")

# The comment syntax of every other tracked file that takes comments. Patterns
# that match nothing today still name a kind a project grows: shell scripts,
# and git hooks under `.githooks/`.
FILES = {
    "python": ("**/*.py",),
    "hash": (
        "Makefile",
        "**/*.sh",
        ".githooks/*",
        "**/.husky/*",
        ".github/**/*.yml",
        ".github/**/*.yaml",
        "**/Dockerfile",
        "docker-compose.yml",
        ".env.example",
        "**/*.toml",
        "**/*.ini",
        "**/requirements*.txt",
        "**/.gitignore",
        "**/.dockerignore",
        "**/.prettierignore",
        "**/nginx.conf",
        "**/baseline.txt",
    ),
    "css": ("**/*.css",),
    "html": ("**/*.html",),
}

# Tracked files no check reads: they take no comments (JSON, the lockfile), are
# prose that names the words to explain them (Markdown), or are generated.
NOT_READ = (
    "**/*.json",
    "**/*.lock",
    "**/*.md",
    "frontend/.prettierrc",
    "frontend/src/routeTree.gen.ts",
)

_MARKER_WORD = re.compile(rf"(?<![A-Za-z0-9_])(?:{'|'.join(MARKERS)})(?![A-Za-z0-9_])")
# The reason starts at the first character that is not a separator, so it may
# open with a backtick, quote or bracket.
_ALLOW = re.compile(r"lint: allow\(marker\)[\s:—-]*[^\s:—-]")
_BLOCKS = {
    "css": re.compile(r"/\*.*?\*/", re.DOTALL),
    "html": re.compile(r"<!--.*?-->", re.DOTALL),
}
ROOT = Path(__file__).resolve().parent.parent


def comment_of(line: str) -> str | None:
    """The `#` comment on `line`, from its `#` to the end, or None if it has none."""
    quote, escaped = None, False
    for at, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            quote = None if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (at == 0 or line[at - 1].isspace()):
            return line[at:]
    return None


def _python_comments(text: str) -> dict[int, str]:
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return {t.start[0]: t.string for t in tokens if t.type == tokenize.COMMENT}


def _block_comments(text: str, pattern: re.Pattern[str]) -> dict[int, str]:
    comments: dict[int, str] = {}
    for match in pattern.finditer(text):
        first = text.count("\n", 0, match.start()) + 1
        for offset, part in enumerate(match[0].split("\n")):
            comments[first + offset] = f"{comments.get(first + offset, '')} {part}"
    return comments


def comments(syntax: str, text: str) -> dict[int, str]:
    """The comment text on each 1-based line of `text`, in the file's `syntax`."""
    if syntax == "python":
        return _python_comments(text)
    if syntax in _BLOCKS:
        return _block_comments(text, _BLOCKS[syntax])
    found = {at: comment_of(line) for at, line in enumerate(text.split("\n"), 1)}
    return {at: comment for at, comment in found.items() if comment is not None}


def check(path: str, text: str, syntax: str = "hash") -> list[str]:
    """A finding per line whose comment has a marker no allow excuses."""
    try:
        by_line = comments(syntax, text)
    except (SyntaxError, tokenize.TokenError) as exc:
        return [f"{path}: could not read its comments: {exc}"]
    findings: list[str] = []
    for line, comment in by_line.items():
        match = _MARKER_WORD.search(comment)
        allowed = any(_ALLOW.search(by_line.get(at, "")) for at in (line, line - 1))
        if match and not allowed:
            findings.append(f"{path}:{line}: '{match[0]}' comment: {ADVICE}")
    return findings


def matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(PurePosixPath(path).full_match(pattern) for pattern in patterns)


def syntax_of(path: str) -> str | None:
    """The comment syntax this check reads `path` in, or None if it is not read."""
    if matches(path, LAYER_LINTED + NOT_READ):
        return None
    return next((name for name, globs in FILES.items() if matches(path, globs)), None)


def tracked() -> list[str]:
    """Every tracked path, spelled as is (no quoting of non-ASCII names)."""
    listing = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [path for path in listing.split("\0") if path]


def main() -> int:
    """Scan the tracked files this check reads; print each finding."""
    findings: list[str] = []
    for path in tracked():
        syntax, file = syntax_of(path), ROOT / path
        if (
            syntax and file.is_file()
        ):  # a tracked file deleted locally has nothing to read
            findings += check(path, file.read_text(encoding="utf-8"), syntax)
    print("\n".join(findings) or "markers: clean")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
