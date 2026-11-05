"""Which of `ci.yml`'s jobs a change runs: the one list of paths CI reads.

Every ready pull request and every push to `main` gets a CI run, so that its
final `CI ok` job always reports. What a change skips is the **jobs**: the
first one, `changes`, pipes the changed paths into this script and every heavy
job reads one of the lines it prints:

    backend=true|false    the backend gates (Postgres, pip, `make backend`)
    frontend=true|false   the frontend gates (Bun, `make frontend`)
    code=true|false       anything a gate reads changed (any non-Markdown file,
                          or a page a layer counts), for a job that checks the
                          whole repository rather than one layer

A layer's patterns are read in order, the last one a path matches decides
whether it counts, and a `!` excludes, which is how GitHub reads a workflow's
`paths:` filter. `*` stops at a `/`, `**` does not. Markdown counts for a layer
only when that layer's gates read it: `make front-lint` runs `prettier --check
.` over all of `frontend/`, pages included, while nothing in `make backend`
reads a `.md` file, so the backend excludes them. Before excluding Markdown
from a layer, check its gates; a page they read and the list skips is a
change that merges unchecked and turns `main` red.

Every tracked file is either claimed by a layer or listed in `UNGATED`, and
`tools/tests/test_ci_paths.py` holds the repository to that, so a new top-level
folder cannot slip past every gate unnoticed.

An empty or unreadable diff runs everything: there is nothing to say it was
safe to skip.

    git -c core.quotePath=false diff --name-only --no-renames BASE HEAD \
        | python3.14 tools/ci_paths.py
"""

from __future__ import annotations

import sys
from pathlib import PurePosixPath

# A change to the task runner or to the workflow itself can break either
# layer's gates, and only running them shows it.
_SHARED = ("Makefile", ".github/workflows/ci.yml")

LAYERS: dict[str, tuple[str, ...]] = {
    # docker/, docker-compose.yml and .env.example define the Postgres the
    # backend tests run against. frontend/openapi.json is the API contract the
    # backend build checks the app against, so it counts for both layers, and
    # so does the fixture holding the merge driver's writer to the backend's.
    # The mutation gate's workflow is read by the backend's tests of that gate.
    "backend": (
        "backend/**",
        "frontend/openapi.json",
        "frontend/scripts/openapi-form.json",
        ".github/workflows/mutation-gate.yml",
        "docker/**",
        "docker-compose.yml",
        ".env.example",
        *_SHARED,
        "!**/*.md",
    ),
    # No `!**/*.md`: Prettier checks frontend/'s Markdown too. .gitattributes
    # names the frontend's merge drivers, and their tests merge with it.
    # tools/markers.py says which files ESLint must read, and
    # eslint-rules/marker-scope.test.ts reads it.
    "frontend": ("frontend/**", ".gitattributes", "tools/markers.py", *_SHARED),
}

# Tracked files no layer's gates read. A change to only these runs just the
# jobs that run on every change (`changes`, `tools`, `CI ok`). `tools/` is
# here because the `tools` job runs `make tools` on every change anyway (a
# file a layer's gates also read is claimed by that layer as well, as
# `tools/markers.py` is by the frontend), and `.githooks/` because its tests
# are in `tools/tests/`.
UNGATED = (
    "**/*.md",
    ".githooks/**",
    ".claude/**",
    ".github/dependabot.yml",
    ".github/rulesets/**",
    ".gitignore",
    "tools/**",
)


def counts(patterns: tuple[str, ...], path: str) -> bool:
    """Whether `path` passes the ordered filter `patterns` spell."""
    result = False
    for pattern in patterns:
        excluded = pattern.startswith("!")
        if PurePosixPath(path).full_match(pattern.removeprefix("!")):
            result = not excluded
    return result


def decide(files: list[str]) -> dict[str, bool]:
    """The `changes` job's answer for a change to `files`."""
    if not files:
        return {**dict.fromkeys(LAYERS, True), "code": True}
    answer = {name: any(counts(p, f) for f in files) for name, p in LAYERS.items()}
    answer["code"] = any(answer.values()) or any(not f.endswith(".md") for f in files)
    return answer


def main(lines: list[str]) -> str:
    """The output lines for the changed paths in `lines`, one per answer."""
    files = [line.strip() for line in lines if line.strip()]
    return "\n".join(f"{k}={str(v).lower()}" for k, v in decide(files).items())


if __name__ == "__main__":
    print(main(sys.stdin.readlines()))
