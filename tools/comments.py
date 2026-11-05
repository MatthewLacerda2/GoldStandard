"""The comments of a code file, without its string literals.

A check that reads what code says about itself reads its comments, never its
strings: a test's made-up fixture is not a claim about the repository. The
marker lint (`tools/markers.py`) and the docs lint (`tools/docs_lint/`) both
read comments through `comments`, which gives the text of each comment by
1-based line, in one of five syntaxes.

Python is read with `tokenize`, exactly, and a comment keeps its `#`; text
that is not valid Python raises `tokenize.TokenError` or `SyntaxError`. The
others are line-based approximations, not parsers, with their delimiters
stripped except a `#`, and they can be wrong both ways:

- `hash` (shell, YAML, the `Makefile`, ...): a `#` at the start of a line or
  after whitespace, outside quotes and not escaped with a backslash, starts a
  comment, so `echo "a # b"`, `$#` and `${#x}` are not comments. Quotes are
  tracked within a line, so a stray apostrophe hides the comment after it; a
  `#` straight after code (`x := 1#c` in Make) is missed; a `#` line inside a
  multi-line string or a heredoc, or one in a `.gitignore` pattern
  (`build/ #x`), is read as a comment.
- `css` and `html`: `/* */` and `<!-- -->`, even inside a quoted string; an
  inline `<script>`'s `//` comments are not read.
- `slash` (TypeScript, JavaScript): `//` and `/* */` outside quotes and
  template literals. A quote ends at its line's end, so one inside a regular
  expression or JSX text costs at most the rest of that line; a template
  literal nested inside `${}` ends its outer one early.

A comment invented by a misreading fails closed: the finding is answered by
rewording the line or by an allow.
"""

from __future__ import annotations

import io
import re
import tokenize

Comments = dict[int, list[str]]

# The group is the comment's text inside its delimiters.
_BLOCKS = {
    "css": re.compile(r"/\*(.*?)\*/", re.DOTALL),
    "html": re.compile(r"<!--(.*?)-->", re.DOTALL),
}


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


def _python(text: str) -> Comments:
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    return {t.start[0]: [t.string] for t in tokens if t.type == tokenize.COMMENT}


def _hash(text: str) -> Comments:
    found = {at: comment_of(line) for at, line in enumerate(text.split("\n"), 1)}
    return {at: [comment] for at, comment in found.items() if comment is not None}


def _blocks(text: str, pattern: re.Pattern[str]) -> Comments:
    found: Comments = {}
    for match in pattern.finditer(text):
        first = text.count("\n", 0, match.start()) + 1
        for offset, part in enumerate(match[1].split("\n")):
            found.setdefault(first + offset, []).append(part)
    return found


def _slash(text: str) -> Comments:
    found: Comments = {}
    at, line, quote = 0, 1, ""
    while at < len(text):
        char = text[at]
        if char == "\n":
            line += 1
            quote = "" if quote in "'\"" else quote
        elif quote:
            if char == "\\":
                at += 1  # the escaped character is skipped, a newline counted
                if text[at : at + 1] == "\n":
                    line += 1
            elif char == quote:
                quote = ""
        elif text.startswith("//", at):
            end = _find(text, "\n", at)
            found.setdefault(line, []).append(text[at + 2 : end])
            at = end
            continue
        elif text.startswith("/*", at):
            end = _find(text, "*/", at + 2)
            for offset, part in enumerate(text[at + 2 : end].split("\n")):
                found.setdefault(line + offset, []).append(part)
            line += text.count("\n", at, end)
            at = end + 2
            continue
        elif char in "'\"`":
            quote = char
        at += 1
    return found


def _find(text: str, what: str, start: int) -> int:
    """Where `what` is in `text` from `start`, or the end of the text."""
    found = text.find(what, start)
    return len(text) if found < 0 else found


def comments(syntax: str, text: str) -> Comments:
    """The comments on each 1-based line of `text`, in the file's `syntax`."""
    if syntax == "python":
        return _python(text)
    if syntax == "slash":
        return _slash(text)
    if syntax in _BLOCKS:
        return _blocks(text, _BLOCKS[syntax])
    return _hash(text)
