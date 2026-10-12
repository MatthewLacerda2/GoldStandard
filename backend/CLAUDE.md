# Backend — local contract

FastAPI + async SQLAlchemy, organized as a strict 4-layer stack. The root
`CLAUDE.md` is the source of truth; this file is the backend-local view. Gates
live in the root `Makefile` (`make backend`) and run identically in CI.

## Layers (one direction, no shortcuts)

`api/` (handlers) → `schemas/` (Pydantic I/O) → `repositories/` (DB access) →
`models/` (ORM). `services/` holds business logic that isn't a repository.

- **DB access lives only in `repositories/`.** No raw SQL or ORM query in a
  handler, service, or util. `core/database.py`'s `init_db()` is the single
  bootstrap-time exception.
- Repositories take an `AsyncSession` and `flush()`; the **caller commits**.
  Repositories never open their own session — the test rollback depends on it.
- All request/response bodies are Pydantic models — enforced by
  `tools/house_lint.py`, which reads each file's `schemas` imports and requires
  every `@router` handler parameter to be a schema type, a path/query scalar,
  or an injected dependency, and every return to be a schema type, a `list` of
  one, or `None`. That the annotations exist at all is ruff's job (`ANN`).
- Config is `pydantic-settings`, read through `@lru_cache get_settings()`.

## Size limits (enforced by `tools/house_lint.py`)

- File ≤ 350 lines — opt a data module out with `# lint: data-file` in the
  first 15 lines; `tests/**` is exempt.
- Endpoint handler ≤ 50 lines. Test ≤ 50 lines.

## Worked example

`items` runs cleanly through every layer — `api/v1/items.py`,
`schemas/items.py`, `repositories/items.py`, `models/item.py`. Copy its shape
for new resources rather than inventing a new one.

## Gate before pushing

`make backend` = `back-lint` (ruff + ruff-format + `house_lint.py`) ·
`back-build` (imports `main`) · `back-test` (pytest). Green before you push.

## Mutation testing — `make back-mutate` (mutmut, a signal, not a gate)

Coverage says a line *ran*; mutation testing says whether any test would
*notice* if that line were wrong. mutmut rewrites the code one small change at
a time (`==` → `!=`, `<=` → `<`, a constant nudged, an argument dropped) and
runs the tests that reach that function. A mutant no test fails on
**survived**: the behaviour it changed is unasserted. It is never part of
`make backend`, `make check` or CI, and it has no score to hit.

**What is mutated:** `core/`, `repositories/`, `services/`, `utils/`
(`[tool.mutmut]` in `pyproject.toml`), so a new module there is in by default.
Not `api/`, `models/` or `schemas/`. The tests are the whole suite: mutmut maps
each function to the tests that reach it, so never hand-pick test files — a
test left out makes its mutants look like survivors.

**When Claude runs it:** once a change is ready (gates green, before the PR) and
it touched mutated code, on the functions it changed. Postgres must be up, as
for the tests.

```bash
make back-mutate ONLY="repositories.items.x_list_owned*"   # one function
make back-mutate ONLY="utils.security*"                    # one module
make back-mutate ALL=1                                     # the whole scope
cd backend && .venv/bin/python -m mutmut results           # the survivors
cd backend && .venv/bin/python -m mutmut show <mutant>     # one mutant's diff
```

A bare `make back-mutate` refuses: the scope grows with the project, and the
functions you changed are what one change needs. Each mutant's tests get a
database of their own (`tests/conftest.py`), because parallel runs on one
database block each other on uncommitted rows until they time out, and a
timeout counts as killed. In the summary line 🎉 is killed, 🙁 survived, ⏰
timed out, and 🫥 means **no test reaches the function** — untested, not safe.

**Triage: every survivor ends in a decision.**

- **A real gap** → a test that kills it, written about the domain case the
  mutant hides (another owner's item is not returned), not about the line.
- **A mutant nobody could observe** → `# pragma: no mutate` on the line, with
  the reason on that line. Only for three cases, **never to spare a test**:
  *equivalent* (the same result for every input the code can receive),
  *unreachable* (a guard every caller already satisfies), and *text nobody
  parses* (a log line, an exception message callers never read). mutmut reads
  the pragma only where a statement starts. Never keep a list of accepted
  survivors outside the code: mutant ids renumber on every edit.
- **A bug the new test reveals** → report it, and mark the test `xfail` with
  the reason unless fixing it is the task at hand.
- Don't chase 100%: a test that exists only to kill an irrelevant mutant is
  worse than the pragma.

The PR says what was run and what was decided: killed, survived, pragma'd.
Results live in `backend/mutants/` (git-ignored); delete it when
`[tool.mutmut]` changes or the results look stale.
