# GoldStandard

**This is a template repository.** It is not an application — it is a
battle-tested starting point. Clone it, rename the example domain, and build
your product inside a structure whose architecture and quality gates are already
decided for you. The worked example resource is `items`: a single CRUD domain
threaded through every layer so the pattern is obvious and copyable.

The authoritative specification is [`auxmd.md`](./auxmd.md); the operating
contract for anyone (human or agent) working in the repo is
[`CLAUDE.md`](./CLAUDE.md). This README summarizes the architecture and the
practices — not the line-by-line implementation.

## What this template stands for

The point of the template is not any single rule. It is that **structure is
enforced, not suggested.** One `Makefile` defines every quality gate, and CI
runs those exact targets, so local and CI can never drift. Conventions live in
linters and config — expressed and checked — rather than in prose that nobody
reads. Establish the foundation first; build features on top of it second.

## The architecture

**Backend — a strict 4-layer separation (non-negotiable):**

```
api/ (handlers)  →  schemas/ (Pydantic)  →  repositories/ (DB)  →  models/ (ORM)
                         ↘ services/ (business logic) ↗
```

- Handlers parse input, call repositories/services, and shape the response.
- **The database is touched in `repositories/` and nowhere else** — no raw SQL
  or ORM query leaks into a handler, service, or util. Repositories `flush()`;
  the caller `commit()`s.
- Schemas (Pydantic) are the contract for every request and response.
- Config is centralized in `pydantic-settings` behind a cached `get_settings()`.
- Auth is single-tenant JWT; passwords are PBKDF2-hashed.

**Frontend — SDK-layered, pages never `fetch`:**

```
routes/pages  →  lib/api/<domain>.ts  →  lib/api/client.ts (the one place auth lives)
                       ↘ lib/schemas/<domain>.ts (types mirror the backend) ↗
```

- A page never talks to the network directly; it calls the typed SDK, which
  calls the single `apiFetch` client where token handling lives.
- The **design system is an allowlist, not a guideline**: only semantic color
  tokens and a typography token scale are valid — raw Tailwind palette classes,
  hex/`rgb()` literals, legacy `text-*` sizes, and arbitrary `text-[Npx]` all
  fail lint. UI is composed from ShadCN primitives; hand-rolled form controls
  are rejected. One exported component per file. All user-facing copy goes
  through i18next.

## The practices (what is enforced)

- **`make check` is the law.** `make backend` and `make frontend` each run their
  layer's lint + build + test; CI calls the same targets. Gates must be green
  before pushing.
- **Length discipline (backend):** files ≤ 350 lines, endpoint handlers ≤ 50,
  tests ≤ 50 — enforced by a custom AST linter (`tools/house_lint.py`), not by
  honor system. Type annotations and Pydantic I/O models are linted in.
- **A tested local ESLint plugin (frontend):** the design-system rules above are
  real rules with their own colocated test suites, run by Vitest alongside the
  app tests. `max-lines: 550` per file.
- **Tests roll back, never truncate:** each test runs inside a transaction that
  is rolled back, so app code must use the handed-in session. Fixtures live in
  the nearest `conftest.py` and are shared up the tree.
- **Worktree-per-session:** new work happens in a named git worktree off the
  latest default branch, with a DB-isolated test database per worktree so
  parallel sessions never collide.

## Layout

```
backend/    FastAPI · SQLAlchemy 2.0 async · Pydantic v2 · pytest · Ruff
frontend/   React 19 · Vite · TanStack Router/Query · Tailwind v4 · ShadCN · Vitest
docker/     postgres (pgvector/pgvector:pg16)
Makefile    the single task runner; CI invokes these targets
CLAUDE.md   the operating contract
auxmd.md    the full architecture & pattern specification
```

## Getting started

```sh
cp .env.example .env

# Backend gates (creates backend/.venv, installs, then lints/builds/tests)
make back-install
make backend PYTHON=.venv/bin/python

# Frontend gates
make front-install
make frontend

# Everything
make check
```

The backend tests need a Postgres with `pgvector` reachable via `DATABASE_URL`
(`docker compose up -d --wait postgres` provides one). Running the full stack is
`docker compose up --build` — postgres + backend + an nginx-served frontend that
reverse-proxies `/api/*`.

## Intentional non-goals (documented upgrade paths)

The skeleton deliberately stops short in a few places so the upgrade is a known
step rather than a rewrite: schema changes use additive `create_all` (add
Alembic when you need ordered/destructive migrations); auth is single-tenant
(reintroduce a `tenant_id` FK + a `get_tenant` dependency for multi-tenancy);
and the frontend schemas are hand-mirrored (generate them from the backend
OpenAPI spec when the surface grows).
