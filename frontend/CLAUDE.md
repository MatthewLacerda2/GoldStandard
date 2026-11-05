# Frontend — local contract

React 19 + TanStack Router/Query + Tailwind, with a token-based design system
enforced by ESLint. The root `CLAUDE.md` is the source of truth; this file is
the frontend-local view. Gates live in the root `Makefile` (`make frontend`)
and run identically in CI.

## Data flow (pages never fetch)

`routes/` → `lib/api/<domain>.ts` → `lib/api/client.ts`. `client.ts` is the
single place auth/token handling and the API base URL live (streaming is the
only allowed exception). `lib/schemas/` mirrors the backend Pydantic models
by hand; `make front-contract` holds it, by field name and kind, to
`openapi.json`, the backend's answers as `make openapi` writes them. Its
failure says how to fix each finding.

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
- ≤ 550 lines of code per `.ts`/`.tsx` — blank and comment lines don't count
  (`mock-*.ts` exempt).

## Promises (type-aware ESLint errors)

`eslint.config.ts` gives the parser a TypeScript program (`projectService`), so
`no-floating-promises`, `no-misused-promises`, and `await-thenable` are errors.
A deliberately un-awaited promise must say so with `void`.

## i18n (an ESLint error too)

User-facing strings go through `i18next` (`src/i18n/`), never hardcoded in
components. `local/no-untranslated-text` flags a JSX text node containing a
letter, and a string literal passed to `placeholder`, `title`, `aria-label` or
`alt` — an allowlist, so new props stay unaffected until they're added to it.
Letter-free text (`·`, `—`, `/`, `:`, digits) and anything in an expression
container — `{t("items.heading")}` and `{item.name}` alike — are untouched.

## No promises in comments (an ESLint error too)

`local/no-marker-comment` fails a comment carrying `TODO`, `FIXME`, `XXX` or
`HACK` as a whole upper-case word: do the work now, or file an issue and delete
the comment. Strings are data and never trip it. The rare comment that must
carry the word says why, inline: `// lint: allow(marker) <why>` in the comment
on that line or on the line directly above it — the same spelling the
backend's `house_lint.py` reads. ESLint's own `eslint-disable` comments still
silence it, as they do any rule, and nothing yet asks them for a reason.

## Dead code (`make front-deadcode`)

`scripts/check-deadcode.ts` runs knip (`knip.ts`), which fails on a file
nothing imports, an export nothing imports and a dependency nothing uses, and
`scripts/check-i18n-keys.ts`, which fails on a locale key nothing in `src/`
reads, and on a key `src/` asks for (`t("a.b")`, an `i18nKey`) that a locale
lacks (tests don't count either way). Delete what they name, or add the
missing key to each locale named. An export that stays on purpose says why on
itself, once, `/** @keep <why> */`; a keep tag spelled any other way, without
a reason or on an export something imports fails, and so does `@public`,
`@beta` or `@alias`, which knip always skips. A key or namespace read in a way
the check cannot see goes in its `KEPT`, with the reason. Vendored
`components/ui/` primitives keep their whole API.

## Gate before pushing

`make frontend` = `front-lint` (`bun run check`: tsc + eslint + prettier) ·
`front-deadcode` (`scripts/check-deadcode.ts`: knip + `@keep` + i18n keys,
both ways) · `front-build` (vite) · `front-test` (vitest) · `front-contract`
(`scripts/check-contract.ts`). Green before you push. Once `make setup` has
run, each commit touching `frontend/` runs `front-lint` first; `make front-fix`
fixes what eslint and prettier can.

## Merge drivers

Once `make setup` has run, a merge or rebase settles the locale files (key by
key), `routeTree.gen.ts` (regenerated) and the house-rule registries
(`eslint-rules/index.ts`, `eslint.config.ts`: both insertions kept) itself:
`scripts/merge-driver.ts`, named per file in the root `.gitattributes`. A
conflict left in one of them is a real one, with markers; resolve it by hand.
