---
name: issue-write
description: Write an issue for this repo — what it must contain, which labels it carries, and when Claude may file one unprompted. Use when filing an issue, splitting an idea into issues, or deciding whether something noticed mid-work deserves one.
---

# Writing an issue

The unit of work here is a well-specified issue. A future Claude reads it **cold**
and says *"I understand the assignment, I know how to proceed."* That is what lets
an issue run unattended, overnight, with nobody to ask.

It is still an *intention*, not a contract. `CLAUDE.md` is explicit: the
*Suggestion* may not survive contact with the code, and when the work diverges the
**pull request** is the source of truth. Write the issue so someone can start
without you — not so nobody may deviate.

## What it contains

`CLAUDE.md` fixes the three sections. This is what each has to carry to be
readable cold:

- **Context** — the problem, and what we want once it is addressed. This is the
  half that survives: a reason written down can be re-judged when circumstances
  change; one that was never written can only be obeyed or ignored.
- **Suggestion** — the shape of the work, *not* the implementation intrinsics.
  Name the decisions the implementer must make and leave them theirs. Mark the
  ones already settled **`(decided)`** — issue #4 does this, and it is the cheapest
  way to tell "I chose this" apart from "someone must choose".
- **Definition of done** — the observable result, and the boundary. Say what is
  explicitly **out of scope**; a boundary stated once saves an argument later.
  Every issue's last line is the gate it must leave green: `make backend`,
  `make frontend`, or `make check`.

**Evidence beats assertion.** Quote the file, the lint rule, the failing test, the
line that is actually wrong. Issue #8 opens with *"`core/rate_limiter.py` builds a
`Limiter` with no `default_limits`, and there is no `@limiter.limit(...)`
decorator anywhere"* — nobody has to re-derive that. "We should rate-limit login"
is worth less.

**Cite what it relates to.** Sibling issues, the pull request that exposed it, the
rule in `CLAUDE.md` it turns on, the upgrade path in `README.md` it finally takes.
A future reader arrives with no memory of today.

**Title carries a scope tag** — `[FE]`, `[BE]`, `[FS]`, `[OT]` — then a sentence
that says the outcome, not the area. `[BE] Apply a global rate limit so the
wired-up limiter actually enforces something`, not `[BE] Rate limiting`.

## The three gates

An idea becomes an issue only when all three hold. If any fails, **push back
instead of complying**:

1. **Understanding** — restate the *problem*, not the solution the user reached
   for. `CLAUDE.md`'s "solve the problem, not the solution" is a gate, not a
   sentiment: a solution is downstream of a problem, and an issue written from the
   solution inherits whatever was wrong upstream of it. If unsure, restate and
   confirm; do not guess.
2. **Value** — real value to the project. No busywork, no features for their own
   sake. In a template that also means: does this teach the downstream reader
   something worth copying, or is it decoration on an example?
3. **Craft** — this stack's good practice and this template's own stated
   standards. They are not suggestions here; most of them are lint rules.

### What "Craft" means in this repo

An issue that cannot be implemented without breaking one of these is the wrong
shape — say so and propose the right one.

- **The 4-layer backend, one direction.** `api/` → `schemas/` → `repositories/` →
  `models/`, with `services/` beside it. **The database is touched in
  `repositories/` and nowhere else** (`core/database.py`'s `init_db()` is the one
  bootstrap exception). Repositories `flush()`; the **caller commits** — the
  rollback-per-test fixture in `backend/tests/conftest.py` depends on it, so an
  issue proposing a repository that opens its own session is proposing to break
  the test suite's isolation.
- **Pydantic is the contract**, both ways, and `frontend/src/lib/schemas/` mirrors
  it **by hand**. Nothing checks that the two agree. Any issue that changes a
  request or response body is `[FS]` and owns both sides.
- **The frontend SDK layering.** Pages never `fetch`; they call
  `lib/api/<domain>.ts`, which calls `lib/api/client.ts` — the single place the
  bearer token and base URL live.
- **The design system is an allowlist, not a guideline.** Semantic color tokens
  and the typography scale only; raw palette classes, hex/`rgb()` literals, legacy
  `text-*` sizes and `text-[Npx]` all fail lint. UI composes shadcn primitives
  from `components/ui/`; hand-rolled form controls are rejected. One exported
  component per file.
- **All user-facing strings go through i18next**, in every locale under
  `src/i18n/locales/`, not just `en`. Code, comments and docs are English only.
- **Length discipline is enforced, not encouraged.** Backend: file ≤ 350,
  endpoint handler ≤ 50, test ≤ 50 (`backend/tools/house_lint.py`). Frontend:
  `max-lines` 550. An issue whose honest shape is a 600-line module is an issue
  that needs splitting by responsibility first.
- **The no-drift rule.** Every gate is a `Makefile` target and CI runs those exact
  targets. An issue that proposes a new check must put it in the `Makefile`;
  a check that lives only in a workflow file, or only on a developer's machine, is
  rejected on sight.
- **Prefer expression over description.** If the outcome of an issue is "everyone
  remembers to do X", the issue is wrong — ask for the lint rule, the type, or the
  config that makes X the only reachable option. `frontend/eslint-rules/` is what
  that looks like when it is done properly, tests and all.
- **Foundations come first.** Infrastructure, architecture and the gold-standard
  patterns are in place before a feature is built on them. An issue that builds on
  a structure that does not exist yet is two issues.

## Filing what you notice

Claude may open an issue autonomously, and should, for anything that will recur or
that a tool would solve more than once — provided the benefit outweighs the cost
of building it.

The strongest issues come from doing the work: a claim in `README.md` that quietly
became false, a lint rule whose message misleads, a fixture that only works by
accident, a dependency wired up and never armed. Those are findings, and findings
are cheap to lose. A `bug` is always filable — the test above is about whether
something is worth *building*, never about whether a defect is worth *recording*.

**File rather than fix** when the thing found is outside the branch in hand. A
branch that grows to cover everything it noticed is a branch nobody can review.
When the user postpones something that must still happen, offer the issue then and
there.

**Do not transcribe a vague ask.** `CLAUDE.md` puts the bar before the issue, not
after it: the idea must be clear to both sides first. Surface the gaps, challenge
the assumptions, reach shared understanding — *then* write.

## Labels

This repo's scheme, from `CLAUDE.md`: **one type label, plus at most one stage
label.** The same set is used across all of the user's repos, so an issue reads the
same wherever it was filed. A fresh clone of the template has none of them
(GitHub's defaults are not these) — see *The label set* below.

**Type — one:**

- `architecture` — the project's structure and conventions: a layer boundary, the
  Pydantic ↔ `lib/schemas/` contract, a file or response format, where a
  responsibility is allowed to live.
- `infrastructure` — the tools and guardrails around the development process: a
  `Makefile` gate, a CI workflow, an eslint rule, a test harness.
- `bug` — something is broken.
- `documentation` — documentation.
- `foundation` — groundwork that makes the template more complete: a piece of the
  worked example that simply is not built yet.
- `feature` — a new capability or resource, built on top of all of that.

The first three are one band in most schemes and three here, and the priority order
below is the reason. The question that separates them is **what the change is
about**: the shape of the product is `architecture`, the machinery that constrains
how it gets written is `infrastructure`, and something merely missing rather than
wrong is `foundation`. Concretely — a layer boundary or an API contract is
`architecture`; a `Makefile` gate or an eslint rule is `infrastructure`; an
unwritten half of the `items` example is `foundation`.

**Stage — at most one, and its absence means ready:**

- `planning` — **never started.** It carries both "we do not yet know how" and
  "nobody has decided this is worth doing"; both are the user's call.
- `human` — cannot be finished by an agent alone. **Treat as not-ready.**

**`minor`** — ~30 lines or fewer, small enough that its resolution may ride along
in another issue's pull request. A size marker, not a type: it stands alone or
joins anything.

No amount of the issue looking startable overrides a stage label, and no amount of
it looking vague substitutes for one. **The judgement lives in the label**, so put
it on honestly: a Claude-written issue **must** carry one if it is a breaking
change, changes user-facing behaviour, needs a judgement call, or proposes a
structural change — anything that moves what the template *teaches* is in that last
group.

A `bug` usually should **not** carry one — it is specific, the deciding already
happened when the code broke, and nothing is gained by making it wait.

## Priority

**`architecture` → `infrastructure` → `bug` → `foundation` → `feature`.**
`documentation` never waits its turn.

That is `CLAUDE.md`'s "foundations come first" expressed as an order: if the way we
build is not solid — a boundary or convention missing (`architecture`), a gate or
tool missing (`infrastructure`) — that halts everything downstream. Then what is
broken. Then the groundwork that makes the template more complete. Then what is new.

Priority orders what gets **merged**, not what gets **worked**.

## Relationships

Use GitHub's **Blocked by / Blocks**, and **sub-issues** when one is literal
groundwork for another. Link when one lays groundwork, makes the next meaningfully
easier, or would conflict too much if done concurrently.

**The dependency graph is the plan** — there are no rigid batches.

**Do not split for parallelism.** Split by responsibility. Sub-issues that all
land in the same file are one issue; see the `issue-batch` skill for why that
costs more than it saves. In particular, **never split an API change into a `[BE]`
and an `[FE]`** — `frontend/src/lib/schemas/` is hand-mirrored and no gate holds
the two halves together, so splitting them buys a contract break that CI cannot
see. That is one `[FS]` issue.

If a `planning` issue would change how another is implemented or thought of, mark
that other one **blocked by** it.

## Closing

The pull request that closes an issue is titled `{issue_number}-{branch_name}` and
its description opens with `Closes #{issue_number}` — and **check the number**. A
typo'd `Closes #N` closes the wrong issue or none, silently, and nothing verifies
it.

## The label set (for a downstream repo)

The nine labels above already exist here. A repo generated from this template
starts with GitHub's stock set instead, which has none of them under these
meanings, and nothing in these skills works until it does. One block, run once
(`--force` because `bug` and `documentation` ship stock with different
descriptions):

```sh
gh label create architecture   --force --color B60205 --description "The project's structure and conventions: layer boundaries, API contracts, formats."
gh label create infrastructure --force --color D93F0B --description "Tools and guardrails for the development process: CI, gates, harnesses."
gh label create bug            --force --color EE0701 --description "Something isn't working."
gh label create documentation  --force --color 0075CA --description "Edit/add documentation; never waits its turn."
gh label create foundation     --force --color 0E8A16 --description "Groundwork that makes the template more complete."
gh label create feature        --force --color A2EEEF --description "A new capability or resource."
gh label create planning       --force --color FBCA04 --description "Not decided, or approach not settled. Do not start."
gh label create human          --force --color 5319E7 --description "Needs a human in the loop end to end. Do not start."
gh label create minor          --force --color C2E0C6 --description "~30 lines or fewer; may ride along in another PR."
```

GitHub's stock `enhancement` duplicates `feature` and is worth deleting, so nobody
reaches for the wrong one.
