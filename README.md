# GoldStandard

**This is a template repository.** It is not an application — it is a
battle-tested starting point. Clone it, rename the example domain, and build
your product inside a structure whose architecture and quality gates are already
decided for you. The worked example resource is `items`: a single CRUD domain
threaded through all four backend layers, leaving `services/` an empty
placeholder for logic that outgrows a thin handler.

The operating contract for anyone (human or agent) working in the repo is
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
  layer's lint + build + test, and `make tools` lints and tests the repository's
  own tooling and runs the docs lint and the marker check; CI calls the same
  targets. Gates must be green before pushing.
- **One check says CI passed.** `.github/workflows/ci.yml` runs on every ready
  pull request and every push to `main`, skips the layers a change did not
  touch (`tools/ci_paths.py` holds the list), and ends in a `CI ok` job that
  passes only when every other job passed or was skipped by design.
- **What an agent loads stays small (docs lint):** a `CLAUDE.md` is at most
  300 lines, a skill's Markdown 500 and its code 400; a skill's frontmatter
  carries the `name` and `description` it needs to load; a long reference page
  opens with a `Contents` heading; and neither a `CLAUDE.md` nor a skill cites
  an issue, a pull request or a date (`tools/docs_lint/`, `make docs-lint`). An
  exception is an inline `<!-- lint: allow(<rule>) <why> -->`.
- **Length discipline (backend):** files ≤ 350 lines of code, endpoint
  handlers ≤ 50, tests ≤ 50 (blank lines, comments and docstrings don't
  count) — enforced by a custom AST linter (`backend/tools/house_lint.py`), not by
  honor system. Ruff enforces that type annotations exist; the same AST linter
  enforces that the ones on a `@router` handler are Pydantic I/O models —
  every request and response body is a schema type, a `list` of one, or `None`,
  with path/query scalars and injected dependencies exempt. That is a
  structural check only: what the fields inside a model must contain is yours
  to decide.
- **No promises in comments:** a comment carrying `TODO`, `FIXME`, `XXX` or
  `HACK` fails — do the work now, or file an issue and delete the comment.
  `house_lint.py` reads the backend's Python, `local/no-marker-comment` the
  frontend's TypeScript, and `tools/markers.py` every other tracked file that
  takes comments (scripts, hooks, workflows, the `Makefile`, Dockerfiles,
  config files, CSS, HTML, the root tools' Python). Only Markdown, JSON and
  generated files go unread, and a test fails on a file kind none of them
  names. The rare comment that must carry the word says why:
  `lint: allow(marker) <why>`.
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
tools/      repository tooling: stdlib-only Python, linted and tested by `make tools`
Makefile    the single task runner; CI invokes these targets
CLAUDE.md   the operating contract
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

## Protecting `main` (one-time setup)

In a repo made from this template, require **`CI ok`** on `main` once. It is the
only check the ruleset needs: a job added to `ci.yml` is gated as soon as it is
listed under `CI ok`'s `needs:`, with nothing to change on GitHub. The ruleset
lives in `.github/rulesets/main.json`; apply it with `gh` (repository admin):

```sh
gh api repos/{owner}/{repo}/rulesets --method POST --input .github/rulesets/main.json
```

Or by hand: *Settings → Rules → Rulesets → New branch ruleset*, target the
default branch, add *Require status checks to pass* with `CI ok` from GitHub
Actions.

A workflow that cannot sit under `CI ok`'s `needs:` (one triggered by
`pull_request_target`, say, which runs from the base branch for access a pull
request's own run does not get) is added to the ruleset as a **second required
check**, by its job's name, in `main.json` and on GitHub. It must then keep the
promise `CI ok` keeps, or it leaves pull requests pending forever: no `paths:`
filter, `ready_for_review` in its `types:`, and a final job that reports on
every run, skipping inside when there is nothing to check.

## Where the Claude tokens go

`make claude-usage SINCE=YYYY-MM-DD` (default: the last 7 days) reports where
this repository's Claude Code tokens went: the main session against its
subagents, each by role and by model, and the context each merged pull request
took. It reads only this machine's local transcripts (no cloud session, no other
machine, nothing about plan limits), so it is a signal for the developer, run by
hand, never a gate. `python3.14 -m tools.claude_usage --help` says how it counts
and how a call is tied to a pull request.

## Intentional non-goals (documented upgrade paths)

The skeleton deliberately stops short in a few places so the upgrade is a known
step rather than a rewrite: schema changes use additive `create_all` (add
Alembic when you need ordered/destructive migrations); auth is single-tenant
(reintroduce a `tenant_id` FK + a `get_tenant` dependency for multi-tenancy);
and the frontend schemas are hand-mirrored, held by field name and kind to the
committed `frontend/openapi.json` (generate them from the backend OpenAPI spec
when the surface grows).
