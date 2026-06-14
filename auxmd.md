# Template Repository — Architecture & Pattern Spec

Blueprint for a reusable full-stack template extracted from HidroFleet (the
"gold standard"). This document is the contract for scaffolding the template
repo; it captures the stack, the layering, and every enforced rule, **minus**
the project-specific subsystems we chose to drop.

> **Using this document (handoff).** You can hand this whole file to a fresh
> Claude Code session with: *"Use this spec to scaffold a new template
> repository."* For a clean build, that session should:
> 1. Build in the order of **Appendix A** (gates first, then backend, then
>    frontend), running `make backend` / `make frontend` green after each layer
>    — never scaffold everything then debug at the end.
> 2. Treat the **"copy verbatim"** files in Appendix A as exact ports of the
>    patterns (linters, config, db, security, middleware) and the **"skeleton"**
>    files as minimal examples that demonstrate the layering for one sample
>    domain (`items`), so the structure is obvious and extensible.
> 3. Use a single neutral example resource (`items`) end-to-end (model →
>    repository → schema → handler → test → frontend SDK → page) as the worked
>    example; everything else is config/tooling.

## 0. Scope decisions

| Subsystem | In template? | Rationale |
|---|---|---|
| **i18n (i18next)** | ✅ keep | Multi-locale frontend is baseline; cheaper to delete than to add later. |
| **Worktree-per-session** | ✅ keep | Every Claude session works in its own git worktree (DB-isolated). |
| **Multi-tenancy** | ❌ strip | JWT stays, but auth is plain user-based — no `X-Tenant`, no `get_tenant`, no per-tenant scoping in repositories. Re-add by reintroducing a `tenant_id` FK + a `get_tenant` dependency. |
| **AI agent layer** | ❌ strip | No `services/agents/`, no Gemini SDK, no streaming NDJSON chat. |
| **PostGIS / spatial** | ❌ strip | Postgres ships **pgvector only** (`pgvector/pgvector:pg16` directly, no PostGIS layer). No `geoalchemy2`/`shapely`. |
| **Issues / PR governance** | ❌ strip from CLAUDE.md | Each repo runs its own lifecycle; the template's `CLAUDE.md` does not prescribe issue labels or PR-title conventions. |

## 1. Tech stack (pinned to what HidroFleet runs)

**Frontend**
- React 19 + Vite 7, package manager **Bun**
- TanStack Router + TanStack Query
- Tailwind v4 (`@tailwindcss/vite`) with a semantic-token theme in `styles.css`
- ShadCN (Radix primitives) + `lucide-react`
- `i18next` + `react-i18next` + browser language detector
- `class-variance-authority`, `clsx`, `tailwind-merge`
- TypeScript 5.8, ESLint 9 (flat config) + Prettier, Vitest
- React Compiler (`babel-plugin-react-compiler`)

**Backend**
- FastAPI on Python 3.12 (uvicorn)
- SQLAlchemy 2.0 **async** + `asyncpg`
- Pydantic v2 + `pydantic-settings`
- `pyjwt` (auth), stdlib `hashlib` PBKDF2 (password hashing)
- `slowapi` (rate limiting)
- `pytest` + `pytest-asyncio` + `httpx` (tests)
- Ruff (lint/format, dev-only)

**Data**
- PostgreSQL 16 + `pgvector` (image: `pgvector/pgvector:pg16`)

**Infra**
- Docker Compose (postgres + backend + frontend)
- Multi-stage frontend image (bun builder → nginx, reverse-proxies `/api/*`)
- GitHub Actions calling the same `make` targets as local

## 2. Repository layout

```
.
├── CLAUDE.md                      # the contract (see §11)
├── Makefile                       # single task runner; CI calls these targets
├── README.md
├── .env.example
├── docker-compose.yml
├── .github/workflows/
│   ├── backend.yml                # path-filtered, draft-skipped, PR-only
│   └── frontend.yml
├── docker/postgres/Dockerfile     # pgvector/pgvector:pg16 (no PostGIS)
├── backend/
│   ├── Dockerfile                 # python:3.12-slim
│   ├── .dockerignore              # ignores tests/, dev reqs, .env
│   ├── pyproject.toml             # ruff config
│   ├── pytest.ini
│   ├── requirements.txt
│   ├── requirements-dev.txt       # ruff lives here
│   ├── main.py                    # FastAPI app, middleware, lifespan
│   ├── core/
│   │   ├── config.py              # BaseSettings + lru_cache get_settings()
│   │   ├── database.py            # async engine, SessionLocal, init_db()
│   │   ├── logging_middleware.py  # skips /health
│   │   └── rate_limiter.py        # slowapi Limiter
│   ├── api/
│   │   ├── deps.py                # get_db, get_current_user
│   │   ├── endpoints.py           # router composition; auth attached per-router
│   │   └── v1/<domain>.py         # handlers (≤ 50 lines each)
│   ├── schemas/<domain>.py        # Pydantic request/response contracts
│   ├── repositories/<table>.py    # THE ONLY place that touches the DB
│   ├── models/                    # SQLAlchemy ORM
│   ├── services/<domain>/         # business logic that isn't a repo
│   ├── utils/
│   │   └── security.py            # PBKDF2 hashing + JWT encode/decode
│   ├── tools/house_lint.py        # custom AST linter (file/handler/test length)
│   └── tests/                     # pytest; fixtures up the tree (conftest)
└── frontend/
    ├── Dockerfile                 # bun builder → nginx
    ├── nginx.conf                 # serves SPA + proxies /api/*
    ├── .dockerignore
    ├── package.json
    ├── bunfig.toml
    ├── components.json            # shadcn config
    ├── eslint.config.ts           # flat config + local plugin wiring
    ├── .husky/pre-commit          # lint-staged: eslint --fix + prettier
    ├── eslint-rules/              # tested local plugin (one rule per file)
    │   ├── index.ts
    │   ├── <rule>.ts
    │   └── <rule>.test.ts
    └── src/
        ├── styles.css             # @theme inline: typography + color tokens
        ├── components/ui/**        # shadcn primitives (lint-exempt)
        ├── components/**           # app components (1 exported per file)
        ├── lib/
        │   ├── api/client.ts       # apiFetch — the ONE place auth lives
        │   ├── api/<domain>.ts     # SDK methods (call apiFetch)
        │   ├── schemas/<domain>.ts # TS mirrors of Pydantic models
        │   ├── *-store.ts          # cross-route reactive state
        │   └── mock-*.ts           # mock data (max-lines exempt by name)
        ├── routes/                 # TanStack file-based routes
        └── i18n/                   # i18next setup + locale resources
```

## 3. Backend architecture & rules

**The 4-layer separation (non-negotiable):**
```
api/ (handlers)  →  schemas/ (Pydantic)  →  repositories/ (DB)  →  models/ (ORM)
                         ↘ services/ (business logic) ↗
```

- **Handlers** (`api/v1/<domain>.py`) parse input, call repositories/services,
  shape the response. **≤ 50 lines** each (`def` → end, decorators excluded).
- **DB access is forbidden anywhere except `repositories/`.** No raw SQL or ORM
  query in a handler, service, or util. Repositories take an `AsyncSession`
  argument and **never open their own session** (so the test rollback works).
- **Schemas** are the contract: a Pydantic model per request/response. Streaming
  endpoints document a per-line event schema instead of `response_model`.
- **Session lifecycle**: `get_db` yields one `AsyncSession` per request and
  closes it at the end. Repositories `flush()`; the handler/caller `commit()`s.
- **Config**: `pydantic-settings.BaseSettings` subclass, accessed via
  `@lru_cache def get_settings()`. `.env` + env vars; `extra="ignore"`.
- **App bootstrap** (`main.py`): CORS → rate-limit middleware → logging
  middleware → versioned router (`/api/v1`). Lifespan runs `init_db()`:
  `CREATE EXTENSION IF NOT EXISTS vector`, `Base.metadata.create_all` (additive
  only — no Alembic in the skeleton; note it as the upgrade path), optional
  seed of a default admin.
- **`DATABASE_URL` normalization**: coerce `postgres://` / `postgresql://` to
  `postgresql+asyncpg://` before building the engine.
- **Baseline endpoints**: `GET /`, `GET /health` (NOT logged), `GET /security.txt`.

**Auth (single-tenant):**
- `POST /api/v1/auth/login` → JWT (HS256, with `exp`/`iat`/`iss`/`aud`).
- `HTTPBearer(auto_error=False)` so a missing token raises our own 401 (the
  status the frontend keys off to redirect), not the default 403.
- `get_current_user` dependency validates the JWT and loads the active user;
  attached per-router in `endpoints.py` via `dependencies=[Depends(...)]`.
- Passwords: PBKDF2-HMAC-SHA256, random salt, `secrets.compare_digest` verify.

## 4. Frontend architecture & rules

**SDK layering (pages never `fetch`):**
```
routes/pages  →  lib/api/<domain>.ts  →  lib/api/client.ts (apiFetch, auth)
                       ↘ lib/schemas/<domain>.ts (types) ↗
cross-route state: lib/*-store.ts (fed by the SDK, not a hand-kept cache)
```
- `client.ts` is the **single** place auth/token handling lives.
- `lib/schemas/` mirrors the backend Pydantic models (hand-written now;
  OpenAPI-generated is the documented upgrade path).
- Streaming is the one allowed exception to "never fetch from a page".

**Design system:**
- **Typography tokens only** — `styles.css` defines a `@theme inline` scale
  (`text-display`, `text-h1`…`text-caption`, `text-kpi-*`). Tokens carry
  weight/line-height; don't repeat `font-*` next to them. No legacy
  `text-xs…3xl`, no arbitrary `text-[Npx]`.
- **Color is an allowlist** — `styles.css` clears Tailwind's default palette
  (`--color-*: initial`), so any raw palette class (`bg-red-500`) generates no
  CSS and fails lint. Only semantic tokens. No hex/`rgb()` literals in
  `className`/`style`.
- **ShadCN composition** — compose `components/ui/**` primitives; never
  hand-roll a text `<input>`/`<select>`/`<textarea>`. Add missing primitives
  with `bunx shadcn@latest add <name>`.
- **One exported React component per file** (barrels and Router objects exempt;
  `components/ui/**` exempt).

## 5. Quality gates (the heart of the template)

`Makefile` is the single runner; CI invokes the **same** targets so local and
CI never drift.

```
make check      # everything
make frontend   # front-lint + front-build + front-test
make backend    # back-lint + back-build + back-test
```

**Backend lint** = `ruff check` + `tools/house_lint.py`:
- Ruff `select = ["F","E","W","B"]` (dead code, pycodestyle, bugbear). `E501`
  left to the formatter. FastAPI `Depends()`/`Query()` allowlisted (not B008).
  *(Template adds `I`/`UP` and `ruff format --check` from day one — HidroFleet
  deferred them only to avoid churn on in-flight branches.)*
- **`house_lint.py`** (pure stdlib, AST-based, tested):
  - **File ≤ 350 lines** — opt out a data module with a `# lint: data-file`
    header marker (scanned in first 15 lines); `tests/**` exempt.
  - **Endpoint handler ≤ 50 lines** — any `@router.<method>`-decorated function.
  - **Test ≤ 50 lines** — any `test_*` under `tests/` (fixtures/helpers exempt).
- **NEW for the template (you flagged this):** enforce **type annotations**
  via ruff `ANN` rules (or a `mypy`/`pyright` gate) and **Pydantic for all
  I/O models**. HidroFleet uses Pydantic everywhere but does not lint-enforce
  annotations — the template closes that gap.

**Frontend lint** = `tsc --noEmit && eslint . && prettier --check .`:
- **Local ESLint plugin** in `eslint-rules/` (one rule per file + colocated
  `*.test.ts`, run by Vitest):
  - `one-exported-component-per-file`
  - `no-legacy-text-scale`, `no-arbitrary-text`
  - `no-color-literal`
  - `no-hand-rolled-form-control`
  - `no-redundant-font-utility` (warn-equivalent, autofix)
- `better-tailwindcss/no-unknown-classes` against the real theme (the color
  allowlist mechanism), with an `ignore` list for genuine non-Tailwind classes.
- `@typescript-eslint/no-unused-vars` (error; `_`-prefix to opt out),
  `@typescript-eslint/no-shadow` (error), `react-compiler` (warn).
- **`max-lines: 550`** per `.ts`/`.tsx` (mock-`*.ts` files exempt).

**Mock-data convention (frontend):** every mock file is `mock-<name>.ts`,
colocated with its consumer; shared mocks move up into a `mocks/` folder
(named by the folder, e.g. `lib/mocks/mock-*.ts`). The `mock-*.ts` name is what
exempts it from `max-lines`. *(Backend's equivalent is the `# lint: data-file`
header marker, not a filename convention.)*

**Husky pre-commit** runs `lint-staged` (`eslint --fix` + `prettier`) on staged
files; activates on `bun install`. CI sets `HUSKY=0`.

## 6. Docker & Compose

- **`docker-compose.yml`**: three services.
  - `postgres` — built from `docker/postgres/Dockerfile` (`pgvector/pgvector:pg16`),
    `healthcheck: pg_isready`, named volume, `restart: unless-stopped`.
  - `backend` — built from `backend/Dockerfile`, `env_file: .env`,
    `depends_on: postgres: condition: service_healthy`, its own healthcheck
    (urllib GET `/health`), `DATABASE_URL` overridden to the `postgres` service host.
  - `frontend` — multi-stage image, nginx reverse-proxies `/api/*` to the backend.
- **`backend/Dockerfile`**: `python:3.12-slim`, `PYTHONDONTWRITEBYTECODE`/
  `PYTHONUNBUFFERED`, install `requirements.txt` first (layer cache), copy
  package, run uvicorn.
- **`frontend/Dockerfile`**: `oven/bun:1-alpine` builder (`--frozen-lockfile`)
  → `nginx` runtime serving `dist/`.
- **`.dockerignore`**: backend ignores `tests/`, `pytest.ini`,
  `requirements-dev.txt`, `.env*` (keep `.env.example`), caches.

## 7. CI (`.github/workflows/`)

- Separate `backend.yml` / `frontend.yml`, **PR-only**, **path-filtered**,
  **draft-skipped** (`if: !github.event.pull_request.draft`).
- Backend job: `docker compose up -d --build --wait postgres` → setup-python
  3.12 → install reqs → `make backend PYTHON=python`.
- Frontend job: `setup-bun` → `bun install --frozen-lockfile` → `make frontend`,
  with `HUSKY=0`.

## 8. Testing conventions

- `pytest` + `pytest-asyncio`; **per-test ≤ 50 lines** (enforced).
- **Shared fixtures live in the nearest `conftest.py`**, never redefined
  per-file (auth headers, client, factories).
- **Teardown = transaction rollback** (savepoint bubble), not TRUNCATE — so app
  code must use the handed-in session, never open `SessionLocal`. Don't assert
  hardcoded auto-increment IDs (sequences don't roll back).
- **Unit-first**: mock external services; assert the endpoint contract (status,
  persistence, inputs passed downstream), not third-party behavior.
- Frontend: Vitest runs both app unit tests **and** the ESLint-rule test suites.

## 9. Worktrees & parallel sessions (kept)

- New work: `git pull` latest default branch → create a named git worktree off
  it → push a remote branch of the same name. Prefix `feat/` or `fix/`.
- Each worktree is DB-isolated: tests derive a per-worktree DB name in conftest
  so parallel sessions never collide; a sweep target drops orphaned DBs.
- Name each Claude session after what it's doing.

## 10. The "no-drift" meta-pattern

The thing that makes this a gold standard isn't any single rule — it's that
**one `Makefile` defines every gate and CI runs those exact targets.** Replicate
that first; everything else hangs off it.

## 11. Template `CLAUDE.md` — what to carry over

Keep (generic, load-bearing):
- Server-start guardrails (don't auto-start dev servers / compose).
- Design-system compliance (shadcn composition, tokens, color allowlist).
- Backend file/handler/test length limits + the repo-only DB rule.
- English-only docs/code; i18n note for the frontend.
- Worktree-per-session workflow.
- Quality-gate scoping (`make frontend`/`make backend`/`make check`) + "gates
  green before push".

Drop (project-specific):
- Issue labels, PR-title conventions, the issue/PR lifecycle prose.
- The AI-agent / Gemini sections, telemetry ingestion, LHG migration.
- Multi-tenant and PostGIS-specific notes.

---

## Appendix A — Complete file manifest & build order

Every file the template should contain, in the order to create it. Legend:
**[V]** = copy/port the HidroFleet pattern essentially verbatim (the value is in
the exact implementation); **[S]** = skeleton/example, write minimal code that
demonstrates the layer; **[G]** = generated by tooling, don't hand-write.

The worked example domain is **`items`** — a single CRUD resource that exercises
every layer. Replace/duplicate it per real domain later.

### Step 1 — Repo root & gates (do this first; nothing else passes without it)

```
CLAUDE.md                         [S] the contract — see §11 for what to keep/drop
Makefile                          [V] the single task runner; CI calls these targets
README.md                         [S] how-to-run + stack summary
.gitignore                        [S] venv, node_modules, dist, .env, caches
.env.example                      [S] DATABASE_URL, JWT_SECRET, DEFAULT_ADMIN_PASSWORD
docker-compose.yml                [V] postgres + backend + frontend (§6)
docker/postgres/Dockerfile        [V] FROM pgvector/pgvector:pg16 (no PostGIS)
.github/workflows/backend.yml     [V] PR-only, path-filtered, draft-skipped
.github/workflows/frontend.yml    [V] same shape, HUSKY=0
```

### Step 2 — Backend core & tooling (no domain yet; `make back-build` green)

```
backend/Dockerfile                [V] python:3.12-slim, reqs first, uvicorn
backend/.dockerignore             [V] ignores tests/, dev reqs, .env*
backend/pyproject.toml            [V] ruff: select F,E,W,B (+I,UP for template); Depends allowlist
backend/pytest.ini                [V] asyncio mode
backend/requirements.txt          [S] fastapi, uvicorn, sqlalchemy[asyncio], asyncpg,
                                      pydantic, pydantic-settings, pyjwt, slowapi, python-dotenv
backend/requirements-dev.txt      [S] ruff, pytest, pytest-asyncio, httpx
backend/__init__.py               [S]
backend/main.py                   [V] app + CORS + rate-limit + logging mw + lifespan + /health
backend/core/__init__.py          [S]
backend/core/config.py            [V] BaseSettings + lru_cache get_settings()
backend/core/database.py          [V] async engine, SessionLocal, init_db(), URL normalize
backend/core/logging_middleware.py[V] logs all but /health
backend/core/rate_limiter.py      [V] slowapi Limiter(get_remote_address)
backend/utils/__init__.py         [S]
backend/utils/security.py         [V] PBKDF2 hash/verify + JWT encode/decode
backend/tools/__init__.py         [S]
backend/tools/house_lint.py       [V] AST linter: file≤350, handler≤50, test≤50, # lint: data-file
```

### Step 3 — Backend domain (auth + users + example `items`; `make backend` green)

```
backend/models/__init__.py        [S] imports every model so create_all sees them
backend/models/base.py            [V] DeclarativeBase + shared mixins (id UUID, timestamps)
backend/models/user.py            [S] User (email, password_hash, is_active)
backend/models/item.py            [S] Item — the example resource
backend/api/__init__.py           [S]
backend/api/deps.py               [V] get_db, get_current_user (single-tenant)
backend/api/endpoints.py          [V] router composition; auth attached per-router
backend/api/v1/__init__.py        [S]
backend/api/v1/auth.py            [S] POST /login → JWT (handler ≤ 50 lines)
backend/api/v1/users.py           [S] list/create/activate (handlers ≤ 50 lines)
backend/api/v1/items.py           [S] CRUD for the example resource
backend/schemas/__init__.py       [S]
backend/schemas/auth.py           [S] LoginRequest / TokenResponse
backend/schemas/users.py          [S] UserCreate / UserRead
backend/schemas/items.py          [S] ItemCreate / ItemRead
backend/repositories/__init__.py  [S]
backend/repositories/users.py     [V] the ONLY user DB access (pattern reference)
backend/repositories/items.py     [S] CRUD repo for items
backend/services/__init__.py      [S] (empty placeholder — where business logic goes)
```

### Step 4 — Backend tests (`make back-test` green)

```
backend/tests/__init__.py             [S]
backend/tests/conftest.py             [V] engine/session fixtures + rollback teardown
backend/tests/api/__init__.py         [S]
backend/tests/api/conftest.py         [V] client, auth_headers, factories (shared, up the tree)
backend/tests/api/v1/__init__.py      [S]
backend/tests/api/v1/test_auth.py     [S] login happy + 401
backend/tests/api/v1/test_users.py    [S] list/create + 401 (each test ≤ 50 lines)
backend/tests/api/v1/test_items.py    [S] CRUD + 404 + persistence assert
backend/tests/tools/__init__.py       [S]
backend/tests/tools/test_house_lint.py[V] proves the custom linter works
```

### Step 5 — Frontend tooling & linters (`make front-lint`/`front-test` green)

```
frontend/package.json                 [V] deps from §1; scripts: check/fix/test/build
frontend/bun.lockb                    [G] bun install
frontend/bunfig.toml                  [S]
frontend/tsconfig.json                [S] strict; paths "@/*" → src/*
frontend/vite.config.ts               [S] react + tailwind + tanstack-router + tsconfig-paths
frontend/index.html                   [S]
frontend/.prettierrc / .prettierignore[S]
frontend/components.json              [S] shadcn config
frontend/nginx.conf                   [V] serve SPA + proxy /api/*
frontend/Dockerfile                   [V] bun builder → nginx
frontend/.dockerignore                [V]
frontend/.husky/pre-commit            [V] lint-staged
frontend/eslint.config.ts             [V] flat config + local plugin wiring + max-lines 550 + color allowlist
frontend/eslint-rules/index.ts        [V] plugin barrel
frontend/eslint-rules/utils.ts        [V] shared AST helpers
frontend/eslint-rules/tester.ts       [V] RuleTester harness
frontend/eslint-rules/one-exported-component-per-file.ts   [V] (+ .test.ts)
frontend/eslint-rules/no-arbitrary-text.ts                 [V] (+ .test.ts)
frontend/eslint-rules/no-legacy-text-scale.ts              [V] (+ .test.ts)
frontend/eslint-rules/no-color-literal.ts                  [V] (+ .test.ts)
frontend/eslint-rules/no-hand-rolled-form-control.ts       [V] (+ .test.ts)
frontend/eslint-rules/no-redundant-font-utility.ts         [V] (+ .test.ts)
```

### Step 6 — Frontend app (`make frontend` green end-to-end)

```
frontend/src/main.tsx                 [S] router + query client + i18n bootstrap
frontend/src/styles.css               [V] @theme inline: typography + color tokens (the design system)
frontend/src/routeTree.gen.ts         [G] TanStack router plugin
frontend/src/routes/__root.tsx        [S] shell layout
frontend/src/routes/index.tsx         [S] sample page consuming the items SDK
frontend/src/routes/login.tsx         [S] login form (composes shadcn primitives)
frontend/src/components/ui/button.tsx [S] shadcn primitives — add via `bunx shadcn add` as needed
frontend/src/components/ui/input.tsx  [S]   (label, card, … pulled in on demand)
frontend/src/lib/api/client.ts        [V] apiFetch — the ONE place auth/token lives
frontend/src/lib/api/auth.ts          [S] login()
frontend/src/lib/api/items.ts         [S] list/create/update/delete items
frontend/src/lib/schemas/auth.ts      [S] TS mirror of backend auth schemas
frontend/src/lib/schemas/items.ts     [S] TS mirror of backend item schemas
frontend/src/lib/auth-store.ts        [S] token/session store (cross-route state)
frontend/src/i18n/index.ts            [V] i18next init + language detector
frontend/src/i18n/locales/en.json     [S] (+ pt.json / es.json as desired)
```

### Build-order summary

1. **Root + gates** → 2. **Backend core/tooling** (`make back-build`) →
3. **Backend domain** + 4. **tests** (`make backend`) → 5. **Frontend
tooling/linters** (`make front-test`) → 6. **Frontend app** (`make frontend`)
→ finally `make check` green, commit, push.

The `[V]` files are the template's actual value — port them faithfully. The
`[S]` files exist only to make the structure legible and the gates exercisable;
keep them minimal.
