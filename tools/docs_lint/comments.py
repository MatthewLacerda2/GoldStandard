"""The comments of a code file, without its string literals.

A rule that reads what code says about itself reads its comments, never its
strings: a test's made-up fixture is not a claim about the repository. Each
reader gives the text of every comment by 0-based line, its delimiter
stripped. Python is read with `tokenize`, exactly; the others are line-based
approximations, not parsers, and can be wrong both ways:

- `#` files (shell, YAML, the `Makefile`): a `#` at the start of a line or
  after whitespace, outside quotes, starts a comment, so `echo "a # b"`, `$#`
  and `${#x}` are not comments. Quotes are tracked within a line, so a stray
  apostrophe before a `#` hides that comment, and a heredoc is read as code.
- `//` files (TypeScript, JavaScript): `//` and `/* */` outside quotes and
  template literals. A string ends at its line's end, so a quote inside a
  regular expression or JSX text costs at most the rest of that line; a
  template literal nested inside `${}` ends its outer one early.
"""

from __future__ import annotations

import io
import tokenize

Comments = dict[int, list[str]]

C_LIKE_SUFFIXES = frozenset({".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".jsx"})


def python(text: str) -> Comments:
    """Python's comments, read by its own tokenizer; by line, as a `#` file,
    when the text is not valid Python."""
    found: Comments = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                found.setdefault(tok.start[0] - 1, []).append(tok.string[1:])
    except tokenize.TokenError, SyntaxError:
        return hash_comments(text)
    return found


def comment_of(line: str) -> str | None:
    """The `#` comment on `line`, after its `#`, or None if it has none."""
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
            return line[at + 1 :]
    return None


def hash_comments(text: str) -> Comments:
    """The `#` comments of a shell script, a YAML file or a `Makefile`."""
    found = {at: comment_of(line) for at, line in enumerate(text.splitlines())}
    return {at: [comment] for at, comment in found.items() if comment is not None}


def c_like(text: str) -> Comments:
    """The `//` and `/* */` comments of TypeScript or JavaScript."""
    found: Comments = {}
    at, line, quote = 0, 0, ""
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


def of_code(suffix: str, text: str) -> Comments:
    """The comments of a code file with this suffix: `#` unless it is Python or
    a `//` language."""
    if suffix == ".py":
        return python(text)
    if suffix in C_LIKE_SUFFIXES:
        return c_like(text)
    return hash_comments(text)
