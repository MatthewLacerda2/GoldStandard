# Frontend — local contract

React 19 + TanStack Router/Query + Tailwind, with a token-based design system
enforced by ESLint. The root `CLAUDE.md` is the source of truth; this file is
the frontend-local view. Gates live in the root `Makefile` (`make frontend`)
and run identically in CI.

## Data flow (pages never fetch)

`routes/` → `lib/api/<domain>.ts` → `lib/api/client.ts`. `client.ts` is the
single place auth/token handling and the API base URL live (streaming is the
only allowed exception). `lib/schemas/` mirrors the backend Pydantic models.

## Design system (all ESLint errors — see `eslint.config.ts`)

- **Compose shadcn primitives** from `components/ui/`. Never hand-roll a text
  `<input>`/`<select>`/`<textarea>`; add primitives with
  `bunx shadcn@latest add <name>`.
- **Typography tokens only** (`text-display`, `text-h1`…`text-caption`,
  `text-kpi-*`). No legacy `text-xs…3xl`, no arbitrary `text-[Npx]`. Tokens
  carry weight/line-height — don't repeat `font-*` next to them.
- **Color is an allowlist** of semantic tokens. No raw palette classes
  (`bg-red-500`), no hex/`rgb()` literals in `className`/`style`.
- **One exported React component per file** (`components/ui/**`, barrels, and
  Router objects exempt).
- ≤ 550 lines per `.ts`/`.tsx` (`mock-*.ts` exempt).

## i18n

User-facing strings go through `i18next` (`src/i18n/`), never hardcoded in
components.

## Gate before pushing

`make frontend` = `front-lint` (`bun run check`: tsc + eslint + prettier) ·
`front-build` (vite) · `front-test` (vitest). Green before you push.
