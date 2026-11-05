"""No comment promises work later: the `marker` rule for files no layer lints.

A comment carrying one of the `MARKERS` as a whole upper-case word is work
nobody is assigned to: do it now, or file an issue and delete the comment.
`backend/tools/house_lint.py` holds the backend's Python to this and the
frontend's ESLint rule `local/no-marker-comment` its TypeScript (`LAYER_LINTED`);
this holds every other tracked file that takes comments (`FILES`). The rest
take none, or are prose and generated files (`NOT_READ`), and
`tools/tests/test_markers.py` fails on a tracked file none of the three names.

Only comment text is read, for the marker and the allow alike, each comment
on its own and without its delimiters. In a `#` file, a `#` at the start of a
line or after whitespace, outside quotes and not escaped with a backslash,
starts a comment, so `echo "a # b"`, `$#` and `${#x}` are not comments. The
readers are line-based approximations, not parsers, and they can be wrong both
ways:

- they miss a comment: one behind a stray apostrophe (quotes are tracked
  within a line only), or a `#` straight after code (`x := 1#c` in Make);
- they invent one: a `#` line inside a multi-line string, a `#` that is part
  of a `.gitignore` pattern (`build/ #x`), a `/*` or `<!--` inside a quoted
  string in CSS or HTML.

An invented comment fails closed: the finding is answered by rewording the
line or by an allow. HTML is read for `<!-- -->` only, not the `//` comments of
an inline `<script>`.

The rare comment that must carry the word says why, inline:
`lint: allow(marker) <why>` in a comment on the line or on the line directly
above it, the spelling the other two lints read. An allow excuses nothing
without a reason: something after it besides separators and markers, so
`# lint: allow(marker) # TODO` is no reason, while a reason may quote the word.

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
_ALLOW = re.compile(r"lint: allow\(marker\)(.*)")
# A reason is any character that is not a separator, so it may open with a
# backtick, quote or bracket.
_REASON = re.compile(r"[^\s:—#*/-]")
# The group is the comment's text inside its delimiters.
_BLOCKS = {
    "css": re.compile(r"/\*(.*?)\*/", re.DOTALL),
    "html": re.compile(r"<!--(.*?)-->", re.DOTALL),
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


def _python_comments(text: str) -> dict[int, list[str]]:
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return {t.start[0]: [t.string] for t in tokens if t.type == tokenize.COMMENT}


def _block_comments(text: str, pattern: re.Pattern[str]) -> dict[int, list[str]]:
    comments: dict[int, list[str]] = {}
    for match in pattern.finditer(text):
        first = text.count("\n", 0, match.start()) + 1
        for offset, part in enumerate(match[1].split("\n")):
            comments.setdefault(first + offset, []).append(part)
    return comments


def comments(syntax: str, text: str) -> dict[int, list[str]]:
    """The comments on each 1-based line of `text`, in the file's `syntax`."""
    if syntax == "python":
        return _python_comments(text)
    if syntax in _BLOCKS:
        return _block_comments(text, _BLOCKS[syntax])
    found = {at: comment_of(line) for at, line in enumerate(text.split("\n"), 1)}
    return {at: [comment] for at, comment in found.items() if comment is not None}


def grants(comment: str) -> bool:
    """Whether `comment` carries an allow with a reason: something after it
    besides separators and markers."""
    allow = _ALLOW.search(comment)
    return bool(allow and _REASON.search(_MARKER_WORD.sub("", allow[1])))


def check(path: str, text: str, syntax: str = "hash") -> list[str]:
    """A finding per line whose comment has a marker no allow excuses."""
    try:
        by_line = comments(syntax, text)
    except (SyntaxError, tokenize.TokenError) as exc:
        return [f"{path}: could not read its comments: {exc}"]
    findings: list[str] = []
    for line, found in by_line.items():
        match = next(filter(None, map(_MARKER_WORD.search, found)), None)
        near = [*by_line.get(line, []), *by_line.get(line - 1, [])]
        if match and not any(map(grants, near)):
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


def scan(path: str, root: Path = ROOT) -> list[str]:
    """The findings in the tracked file `path`, if this check reads it."""
    syntax, file = syntax_of(path), root / path
    if not syntax or not file.is_file():  # a file deleted locally has nothing to read
        return []
    try:
        text = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [f"{path}: not UTF-8 text, so its comments cannot be read"]
    return check(path, text, syntax)


def main() -> int:
    """Scan the tracked files this check reads; print each finding."""
    findings = [finding for path in tracked() for finding in scan(path)]
    print("\n".join(findings) or "markers: clean")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
