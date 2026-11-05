"""Which `independent-review` triggers a change hits: the one list of their paths.

The `independent-review` skill (*When*) says in words what sends a pull request
to the review before it merges; this file is that list as paths, and the merge
queue reads it (`tools/merge_queue/`): a pull request that hits a trigger merges
only with an `Independent review` comment for its head. So a trigger's paths
change here, and `tools/tests/test_review_triggers.py` fails while the skill's
*When* names a path no trigger here covers.

Patterns read as `tools/ci_paths.py` reads them: `*` stops at a `/`, `**` does
not. Beside the paths, three triggers look at more than a file's name:

- **database access** also counts any changed line of backend code outside the
  tests that builds or runs a statement ([`QUERY`]), wherever it lives;
- **CI and the gates** counts `frontend/package.json` only when a key the gates
  read changes ([`PACKAGE_GATES`]): a dependency bump is not a CI change;
- **refactor** is the `refactor` label (on the pull request or an issue it
  closes), or more than [`REFACTOR_LINES`] lines added.

What it cannot see (code moved across layers in a small diff, a query built in
a way [`QUERY`] does not name, a gate that starts reading a file not listed
here) is still the orchestrator's to catch reading the diff: this is the floor
under that judgement, not the whole of it.

    git diff --name-only origin/main...HEAD | python3.14 -m tools.review_triggers
"""

from __future__ import annotations

import json
import re
import sys

from tools.ci_paths import counts

TRIGGERS: dict[str, tuple[str, ...]] = {
    "database access": (
        "backend/repositories/**",
        "backend/models/**",
        "backend/core/database.py",
    ),
    # The Pydantic schemas and their hand-made frontend mirror, and the
    # contract file the backend build checks the app against.
    "the API contract": (
        "backend/schemas/**",
        "frontend/src/lib/schemas/**",
        "frontend/openapi.json",
    ),
    "auth": (
        "backend/api/deps.py",
        "backend/utils/security.py",
        "backend/api/endpoints.py",
        "frontend/src/lib/api/client.ts",
    ),
    # The workflows, the protection on `main`, the task runner, the repository
    # tools (`make tools` is a gate, and the CI path list lives there), the
    # hooks, and the lint and test config each layer's gates run.
    "CI and the gates": (
        ".github/workflows/**",
        ".github/rulesets/**",
        "Makefile",
        "tools/**",
        ".githooks/**",
        "backend/tools/**",
        "backend/pyproject.toml",
        "backend/pytest.ini",
        "backend/conftest.py",
        "backend/tests/conftest.py",
        "frontend/eslint-rules/**",
        "frontend/eslint.config.*",
        "frontend/**/tsconfig*.json",
        # The scripts the frontend gates run (the API contract check, its
        # baseline among them).
        "frontend/scripts/**",
        "frontend/vite.config.*",
        "frontend/vitest.config.*",
        "frontend/.prettierrc*",
        "frontend/.prettierignore",
        "frontend/bunfig.toml",
        "frontend/.husky/**",
    ),
}

REFACTOR_LINES = 1000
REFACTOR_LABEL = "refactor"

# `frontend/package.json` holds the gates' scripts and the Bun version CI
# installs beside the dependencies: only these keys make it a CI change.
PACKAGE = "frontend/package.json"
PACKAGE_GATES = ("scripts", "packageManager")

# A changed line that builds or runs a statement. Bare calls only for the
# statement builders (`x.update(…)` on a dict is not `update(…)`).
QUERY = re.compile(
    r"(?<![.\w])(select|insert|update|delete|text|union_all|exists)\("
    r"|\.(execute|scalars?|where|filter|filter_by|returning|on_conflict_do_\w+|query)\("
    r"|\bsession\.(get|add|add_all|delete|merge|flush|refresh)\("
)
BACKEND_TESTS = "backend/tests/"


def querying(diff: str) -> list[str]:
    """The backend files (tests aside) whose changed lines build or run a query.

    `diff` is a unified diff (`git diff -U0`); added and removed lines both count.
    """
    found: list[str] = []
    path = ""
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.rsplit(" b/", 1)[-1]
            continue
        changed = line[:1] in ("+", "-") and not line.startswith(("+++ ", "--- "))
        backend = path.startswith("backend/") and not path.startswith(BACKEND_TESTS)
        query = changed and backend and path.endswith(".py") and QUERY.search(line[1:])
        if query and path not in found:
            found.append(path)
    return found


def gated(before: str | None, after: str | None) -> bool:
    """Whether a `package.json` change touches a key the gates read.

    `before` and `after` are the file at the merge base and at the head, `None`
    where git has no such file. A side that is missing or does not parse counts
    as a change: failing safe sends a pull request to review, never past it.
    """
    try:
        old, new = json.loads(before or ""), json.loads(after or "")
    except json.JSONDecodeError:
        return True
    if not isinstance(old, dict) or not isinstance(new, dict):
        return True
    return any(old.get(key) != new.get(key) for key in PACKAGE_GATES)


def hits(
    paths: list[str],
    additions: int = 0,
    labels: list[str] | tuple[str, ...] = (),
    queries: list[str] | tuple[str, ...] = (),
    package_gated: bool = False,
) -> list[str]:
    """The triggers a change hits, each with what tripped it; empty when none.

    `queries` are the files [`querying`] found; `package_gated` is [`gated`]'s
    answer for [`PACKAGE`], asked only when the change touches it.
    """
    found = []
    for trigger, patterns in TRIGGERS.items():
        touched = sorted(p for p in paths if counts(patterns, p))
        if trigger == "database access":
            touched = sorted({*touched, *queries})
        if trigger == "CI and the gates" and package_gated and PACKAGE in paths:
            touched.append(PACKAGE)
        if touched:
            more = f" (+{len(touched) - 3} more)" if len(touched) > 3 else ""
            found.append(f"{trigger}: {', '.join(touched[:3])}{more}")
    if REFACTOR_LABEL in labels:
        found.append(f"refactor: labelled `{REFACTOR_LABEL}`")
    elif additions > REFACTOR_LINES:
        found.append(f"refactor: {additions} lines added (over {REFACTOR_LINES})")
    return found


def main(lines: list[str]) -> str:
    """The triggers the changed paths in `lines` hit, one per line."""
    paths = [line.strip() for line in lines if line.strip()]
    return "\n".join(hits(paths)) or "no trigger: the review is not required."


if __name__ == "__main__":
    print(main(sys.stdin.readlines()))
