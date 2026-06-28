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
- All request/response bodies are Pydantic models. Type annotations are
  enforced (ruff `ANN`).
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
