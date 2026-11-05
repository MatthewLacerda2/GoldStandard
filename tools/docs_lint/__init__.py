"""The docs lint: limits on what an agent loads, and pointers that hold.

Every `CLAUDE.md` and every skill is read into every session that loads it, so
its length is paid on every session, and left alone it only grows. These rules
hold that text to a size and a shape, and fail naming the file, the rule and
what to do:

    claude-md          a file named `CLAUDE.md`, anywhere, is at most 300 lines
    skill-doc          a `.md` under `.claude/skills/` is at most 500 lines
    skill-code         a code file under `.claude/skills/` is at most 400 lines
                       (a `.claude/skills/` folder at any depth counts)
    skill-frontmatter  a `SKILL.md` opens with the `name` and `description`
                       a skill needs to load
    reference-toc      a long reference page carries a table of contents
    history            a `CLAUDE.md` or a skill cites no issue, pull request
                       or date
    named-path         a path or a `make` target a doc or a code comment
                       names exists (`named_paths`)

Each rule is a module here with a `check(doc)` function, listed once in
`run.RULES`; adding a rule is adding a module and that line. All lines count,
blank ones included. Only tracked files are read: what git does not commit is
loaded by nobody else (what a named path may point at is wider: `core.Tree`).

An exception is written where it applies, with its reason: a one-line HTML
comment `<!-- lint: allow(<rule>) <why> -->` on the line, or in the run of such
comments directly above it; for a whole-file cap, anywhere in the file. In a
code file the allow is a comment (`# lint: allow(<rule>) <why>`, or `//` where
that is the syntax) on the line or the one directly above it. An allow shown
inside a code fence, or in a string, is an example and excuses nothing. There
is no list of exceptions in a config file.

    python3.14 -m tools.docs_lint      # from the repository root
"""
