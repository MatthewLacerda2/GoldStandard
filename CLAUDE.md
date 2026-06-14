# CLAUDE.md — the contract

This is a **template repository**. It encodes battle-tested, "gold standard"
patterns: a strict 4-layer backend, an SDK-layered frontend, a token-based
design system, and a single `Makefile` that defines every quality gate. Build
new features by following the worked `items` example through every layer.

The rules below are load-bearing. They are enforced by automated gates, not by
convention — keep them green.

## Working agreement

These govern how the agent operates in this repo. **Any of them can be
overridden by the user in the current or a previous prompt** — an explicit
instruction wins.

- **Never commit or push** unless the user told you to in the current or a
  previous prompt.
- **Foundations come first.** The infrastructure, architecture, and gold-standard
  conventions/patterns must already be in place before any feature change is
  made. Don't build on top of a structure that isn't there yet — establish it.
- **Shared understanding before code.** Before implementing a change, the user
  must have a clear idea of what they want, and you must confirm you're on the
  same page. If the request is ambiguous, clarify first — don't guess and build.
- **Push back on dead weight.** If the user is trying to add something that
  doesn't add value to the project, you MUST push back. If you spot something
  that can be removed without losing value, you may suggest removing it.
- **Don't multiply Markdown.** Do not create new Markdown files without asking
  the user first. You may edit existing ones, as long as you tell the user what
  you changed.
- **Prefer expression over description.** An expressive, declarative structure
  (code, config, a linter rule that enforces a convention) is preferred over
  prose documenting that the convention exists. Make the codebase state the rule;
  don't just write about it.

## The no-drift meta-pattern

One `Makefile` defines every gate; **CI runs those exact targets.** Never add a
check that only runs in CI, or only locally.

```
make check      # everything
make backend    # back-lint + back-build + back-test
make frontend   # front-lint + front-build + front-test
```

**Gates must be green before you push.** Scope your run to the layer you touched
(`make backend` / `make frontend`) and run `make check` before opening a PR.

## Server-start guardrails

Do **not** auto-start dev servers, `docker compose up`, or long-running
processes to "check" something. Use the gates (build/test) to verify. If a human
needs a running app, ask them to start it.

## Backend rules

- **4-layer separation (non-negotiable):**
  `api/` (handlers) → `schemas/` (Pydantic) → `repositories/` (DB) → `models/`
  (ORM), with `services/` for business logic that isn't a repo.
- **DB access is forbidden anywhere except `repositories/`.** No raw SQL or ORM
  query in a handler, service, or util. Repositories take an `AsyncSession` and
  never open their own session (the test rollback depends on this).
- Repositories `flush()`; the handler/caller `commit()`s.
- **Length limits** (enforced by `tools/house_lint.py`):
  - File ≤ 350 lines (opt a data module out with a `# lint: data-file` marker in
    the first 15 lines; `tests/**` exempt).
  - Endpoint handler ≤ 50 lines.
  - Test ≤ 50 lines.
- All I/O models are Pydantic; type annotations are enforced (ruff `ANN`).
- Config via `pydantic-settings` accessed through `@lru_cache get_settings()`.

## Frontend rules

- **Pages never `fetch`.** `routes/` → `lib/api/<domain>.ts` →
  `lib/api/client.ts`. `client.ts` is the single place auth/token handling lives.
  (Streaming is the only allowed exception.)
- `lib/schemas/` mirrors the backend Pydantic models.
- **Design-system compliance:**
  - **Compose `components/ui/**` (shadcn) primitives**; never hand-roll a text
    `<input>`/`<select>`/`<textarea>`. Add primitives with
    `bunx shadcn@latest add <name>`.
  - **Typography tokens only** (`text-display`, `text-h1`…`text-caption`,
    `text-kpi-*`). No legacy `text-xs…3xl`, no arbitrary `text-[Npx]`. Tokens
    carry weight/line-height — don't repeat `font-*` next to them.
  - **Color is an allowlist.** Only semantic tokens; no raw palette classes
    (`bg-red-500`), no hex/`rgb()` literals in `className`/`style`.
  - **One exported React component per file** (`components/ui/**`, barrels, and
    Router objects exempt).
- `max-lines: 550` per `.ts`/`.tsx` (`mock-*.ts` files exempt).

## Language & i18n

- All code, comments, and docs are **English only**.
- User-facing frontend strings go through `i18next` (`src/i18n/`), never
  hardcoded in components.

## Worktree-per-session workflow

- New work: `git pull` the latest default branch → create a named git worktree
  off it → push a remote branch of the same name. Prefix `feat/` or `fix/`.
- Each worktree is DB-isolated: tests derive a per-worktree DB name so parallel
  sessions never collide.
- Name each session after what it's doing.

## Upgrade paths (intentionally deferred in the skeleton)

- **Migrations:** `init_db()` uses `create_all` (additive only). Add Alembic
  when schema changes need to be destructive/ordered.
- **Multi-tenancy:** reintroduce a `tenant_id` FK + a `get_tenant` dependency.
- **Typed SDK:** generate `lib/schemas/` from the backend OpenAPI spec.
