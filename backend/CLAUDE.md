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

Every limit counts **lines of code**: blank lines, comment-only lines and the
docstring of a module, class or function don't count, so documenting code
never pushes it over. Any other string still counts.

- File ≤ 350 lines — opt a data module out with `# lint: data-file` in the
  first 15 lines; `tests/**` is exempt.
- Endpoint handler ≤ 50 lines. Test ≤ 50 lines.

The root `tools/` folder is held to the same limits: `make tools` runs
`house_lint.py --lengths tools`, the length rules alone.

## No promises in comments (`marker`, also `tools/house_lint.py`)

A comment carrying `TODO`, `FIXME`, `XXX` or `HACK` as a whole upper-case word
fails: do the work now, or file an issue and delete the comment. Strings are
data and never trip it. The rare comment that must carry the word says why,
inline: `# lint: allow(marker) <why>` in the comment on that line or on the
line directly above it.

## Worked example

`items` runs cleanly through every layer — `api/v1/items.py`,
`schemas/items.py`, `repositories/items.py`, `models/item.py`. Copy its shape
for new resources rather than inventing a new one.

## Dead code (enforced by `tools/deadcode.py`)

A function, class, method or attribute nothing uses fails, and so does one
only `tests/` uses: delete it with the test that is its only use. Framework
entry points (route handlers, fixtures, validators) pass by decorator, names a
framework calls by convention by `IGNORE_NAMES`, each with its reason. Code
that stays on purpose says why where it is: `# lint: allow(deadcode) <why>` on
the reported line or the one above. ORM columns and Pydantic fields are never
reported; the frontend's contract gate judges the fields it reads.

## Gate before pushing

`make backend` = `back-pins` first (`tools/pins.py`: the venv against every
`==` pin in `requirements*.txt`; `make back-install` when it fails) ·
`back-lint` (ruff + ruff-format + `house_lint.py`) ·
`back-deadcode` (`tools/deadcode.py`: code nothing calls, or only the tests
do) · `back-build` (imports `main`, and fails when `frontend/openapi.json` no longer
matches what the endpoints answer: run `make openapi` and commit it) ·
`back-test` (pytest). Green before you push. Once `make setup` has run, each
commit touching `backend/` runs `back-lint` first; `make back-fix` fixes what ruff can.

## Mutation testing (mutmut)

Coverage says a line *ran*; mutation testing says whether a test would
*notice* if it were wrong. mutmut rewrites a function one small change at a
time (`<` to `<=`, `and` to `or`, a constant nudged, a `return` dropped) and
runs the tests that reach it. A mutant no test fails on **survived**: the
behaviour it changed is unasserted.

**A signal, not a gate, except in sensitive code.** Claude runs it only where
it pays: a delicate rule, a new mechanism or a rewrite, or when asked, scoped
to the functions in question. No score, no sweep, never in `make backend`,
`make check` or CI. The exception is the paths in `mutation-sensitive.txt`
(the auth surface): a PR that changes one must carry a run on the functions it
touched, with every mutant not killed answered in writing, and the `mutation
gate` check stays red until it does. Never a threshold: a survivor may stay
if someone wrote down why.

```bash
make back-mutate ONLY="utils.security.x_verify_password__mutmut_*"  # one function
make back-mutate ONLY="utils.security*"                              # one module
make back-mutate-diff PR=<n>        # sensitive code: run, and write the block into PR #n
make back-mutate-diff NO_RUN=1      # rewrite the block from the results already there
cd backend && .venv/bin/python -m mutmut show <mutant>              # one mutant's diff
```

A method is `<module>.xǁ<Class>ǁ<method>__mutmut_*`. A bare `make
back-mutate` refuses; the whole scope takes `ALL=1`. Postgres must be up, as
for the tests: each test process gets a database of its own
(`tools/mutation_db.py`). `back-mutate-diff` works on committed, pushed
content only: commit the killing test before the run.

**On Windows it runs under WSL, and a refusal never means "skip it".** mutmut
cannot run on native Windows, so `back-mutate` and `back-mutate-diff` refuse
there before doing anything and say how to move (a checkout inside the WSL
filesystem, not `/mnt/c`). `back-mutation-gate` runs no mutant and does not
refuse.

**Triage: every survivor ends in a decision.**

- **A real gap**: a test that kills it, written about the case the mutant
  hides (a malformed hash is refused), not about the mutated line.
- **A mutant nobody can observe**: `# pragma: no mutate` with the reason on
  that line, for exactly three cases and never to spare a test: *equivalent*
  (the same result for every input the code can receive), *unreachable* (a
  guard every caller already satisfies), *text nobody parses* (a log line).
  An exact boundary or a rare branch is a gap, not a pragma. mutmut hides
  every mutant that starts on the pragma's line, so in sensitive code the gate
  refuses one that hides more than one. Never keep a list of accepted
  survivors outside the code: mutant ids renumber on every edit.
- **A bug the new test reveals**: fixed in the same PR when small, otherwise
  filed, and the test marked `xfail` naming the issue.
- **A decision written in the block** is for what the code cannot carry: a
  `no mutant` line (a decorated function, such as a route handler, which
  mutmut never mutates), a `module-level` line (a constant or an import), a
  mutant that times out even alone. Name the test that covers it.
- Don't chase 100%: a test that exists only to kill an irrelevant mutant is
  worse than the pragma.

**Verdicts that lie.** A timeout can be an import failure or machine load, and
a kill can be a one-off: rerun a mutant alone (`ONLY="<exact name>"`) before it
decides anything. "no tests" means untested, not safe. `backend/mutants/`
goes stale (mutmut copies files in and never removes one): delete it after
pulling, after changing `[tool.mutmut]`, or when results look odd. The tools'
docstrings hold the rest.
