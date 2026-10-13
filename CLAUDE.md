# CLAUDE.md — the contract

This is a **template repository**. It encodes battle-tested, "gold standard"
patterns: a strict 4-layer backend, an SDK-layered frontend, a token-based
design system, and a single `Makefile` that defines every quality gate. Build
new features by following the worked `items` example through every layer.

The rules below are load-bearing. They are enforced by automated gates, not by
convention — keep them green.

## How we work

This section is about collaboration and judgment — how we talk about the work
and decide what's worth building. Like the working agreement below, **any of
these can be overridden by the user** (see the closing note).

- **The project serves its development first.** Claude is never tied to the
  current way of doing things. First it looks for how to make developing the
  project faster and less work; then it makes the project itself better; only
  then does it use it. That is why the priority order (*Issues*) puts
  infrastructure first: tests, tools, gates and harnesses pay off on every
  branch that comes after them. A big feature often needs a refactor before it
  can land cleanly: suggest that refactor first, as its own branch, merged
  before the feature and never folded into it.
- **Plain language over decoration.** Prefer plain language that explains what
  we — or the code — are doing, not highly technical decoration. The user is
  trying to architect intelligence, not ornament an implementation.
- **A request is a suggestion.** Every request the user makes is weighed before
  it is built: first, is it the best idea for developing the project; then, is
  it the best way to get what the user wants. Say so when it isn't, and propose
  the better shape.
- **Solve the problem, not the solution.** Claude must hold a clear picture of
  the *problem* being solved, not just the solution the user is reaching for. A
  solution is one way to create value for a problem; it is downstream of it. You
  and the user must share the problem's fundamental truths — its axioms — before
  anything is built. If the user hasn't given that picture, or you don't have
  it, stop and ask: questions are always welcome, and planning or implementing
  on a guess is not. Hold the user to this too: if they are polishing a solution
  before the problem is pinned down, say so.
- **Readable first, then tight.** First structure a good architecture and write
  code that is readable and organized. Then tighten it — denser, more compact —
  but compactness serves readability, it is not the finish line. If the clearest
  version of something isn't the densest, leave it clear. Don't end on clever
  one-liners nobody can debug later.
- **Cut what doesn't justify itself.** If you realize a feature isn't
  justifying itself, say so. Cutting what can't justify being kept, or can be
  absorbed into something else, is always ideal: remove it, unless that changes
  what the template teaches, in which case propose it.
- **Take the initiative.** Don't wait to be told to improve the template. A
  change that makes it better, or makes developing it better, and is a clear win
  with no downside is **implemented, not proposed**: implementing now and
  validating later beats waiting. The exception is **changing a decision** —
  what this template teaches: a layer boundary, an API contract, the design
  system's tokens, a lint rule, a rule or convention in this file. There you
  propose and the user decides, unless one option is a plain win-win, which you
  take. **Making a description true or complete is never the exception**: any
  README, comment, docstring, skill or `CLAUDE.md` that is stale, or missing
  something that matters for developing or using the template, is fixed on your
  own say-so. That licence covers describing what is already decided, never
  deciding something new: a convention that isn't in the file yet is a change to
  it. Initiative still runs through the normal flow (a worktree branch, the
  gates, a PR), and an issue carrying `planning` or `human` is never started.
- **Overriding these rules.** In the end, all rules may be overridden by the
  user — so long as the user says why, and the explanation still holds in the
  current context.

## Issues and Pull Requests

How we plan work and land it. How an issue or a PR reads is Claude's call; the
rules here are the repo's — what gets filed, what the labels mean, in what
order work lands, and when it merges. Like everything above, the user can
override them with a reason that holds.

### Issues

An issue is the *purpose and direction* of a piece of work, written before it —
an intention, not a spec. A future Claude reads it cold, often unattended, with
nobody to ask, so it says what problem it solves and what done looks like. Its
plan may not survive contact with the code: let
what you discover refine it, and never treat an incomplete or slightly-wrong
issue as a reason to stop. When the work diverges, the **pull request is the
source of truth** for what was done; if the gap matters later, reflect it back
into the issue or file a new one.

**File what you notice — it is a duty, not an option.** Whatever you find — a
bug, a gap, a stale doc, a way to make development faster or need less work —
is folded into the task at hand or filed as an issue right away, batch or not,
never dropped and never saved for the end. Fold in what is small or in the way;
file the rest, because a branch that grows to cover everything it noticed is
one nobody can follow. If the user postpones something that must still happen,
file it then and there.

**Labels.** `make labels` is the set, with each one's meaning; run it once in a
repo made from this template — it also deletes GitHub's stock labels, which
overlap these (`enhancement` is `feat` under another name).

- **Type** (one): `infrastructure` (tools and guardrails for the development
  process — CI, gates, harnesses; nothing of it ships in the app),
  `architecture` (the structure and its conventions — layer boundaries, API
  contracts, formats), `fix` (something broken or overlooked — a missing
  translation key counts), `foundation` (groundwork inside the app that later
  features stand on, though nobody would ask for it on its own), `feat` (a new
  capability or resource), `documentation`.
- **Size** (at most one, alongside the type): `minor` is a small change — it
  may be folded into another PR on the same ground, though it doesn't have to
  be, and among issues of the same priority it goes first, being cheap.
  `refactor` is a big one — a refactor, or anything large — and flags the PR
  for the independent review.
- **Stage** (at most one): `planning` and `human`. Both mean **do not start**,
  absolutely, and they are the only thing that does: an issue carrying neither
  is startable the moment it exists, including one filed a minute ago. An issue
  you file gets `planning` when it would change a decision (*Take the
  initiative*) or the product's design, conflict with a rule here, or when the
  idea itself isn't settled yet — a postponed, half-formed ask is filed so it
  isn't lost, never so it gets built. The user settles it first. A `fix`
  usually should not; the deciding happened when the code broke. `human` is for
  what an agent cannot finish alone.
- **`agent`** — on every issue Claude files without being asked. It only records
  who decided to file it; the issue is treated like any other.

**Priority — `infrastructure` → `architecture` → `fix` → `foundation` →
`feat`; `documentation` never waits its turn.** A missing gate or tool and a
missing boundary or contract both halt everything downstream, then what is
broken, then the groundwork that makes the template more complete, then what is
new. A bug in the development tooling itself — CI, the `Makefile` gates, the
lint rules — ranks as `infrastructure` whatever its label, because while it
stands every branch pays for it. Priority orders what gets **merged**, not what
gets **worked**.

**The dependency graph is the plan.** Record how issues relate with GitHub's
**Blocked by / Blocks** and **sub-issues**; there are no rigid batches. Split by
responsibility, never by parallelism — sub-issues that all land in the same file
are one branch. Never split an API change into a backend half and a frontend
half: the frontend schemas are hand-mirrored and no gate holds the halves
together. A `planning` issue that would change how another is built blocks it.

**Assignment** — no assignee means free for grabs; an assignee means it's
taken. When we start *actually working* an issue (not just planning), assign
the user and tell them.

**Two skills carry the working protocols** — `issue-batch` and
`independent-review` (which `issue-batch` depends on) — so this file can hold
the reasoning and they can hold the steps. Each one names its own scope and when
to reach for it; invoke them rather than reconstructing a procedure from memory,
and name them when briefing a subagent. Where a rule here is stated in one line
and a skill has ten, the line is the rule and the skill is how to keep it; where
they disagree, this file wins and the skill is wrong — fix it in the change that
finds it.

### Pull Requests

Run the gates locally first (see the no-drift meta-pattern) — green before you
push. A PR need not address an issue; when it closes one, its description says
`Closes #N` — check the number, because a wrong one closes the wrong issue
silently.

**Nobody reads the code line by line.** With good infrastructure around it, and a
problem that isn't too complex, the code comes out good. A person's review then
buys little either way: a trivial change gets a glance that adds nothing, and a
change complex enough to need a real read is too complex to review in reasonable
time. So the guardrails — the gates, CI, the house lints and the independent
review — are what keep the code in line. Don't expect anyone to review a PR, and
never leave one waiting for that. If a change only feels safe once a person has
read it, a guardrail is missing: that is an `infrastructure` issue, not a reason
to ask for a review.

- **Every PR is assigned to someone.** If the user asked you to open it, assign
  them; if it closes an issue, assign them there too. If that issue is already
  assigned to someone else, say so and let the user decide — you may keep
  writing the PR meanwhile.
- **When to merge depends on how the work started.**
  - **In a batch** (`issue-batch`), starting the batch is the approval: merge
    each PR once its gates and CI are green and, when triggered, its independent
    review is answered.
  - **In a conversation**, the conversation is usually about one theme, and its
    PR is where that theme lands. Keep the PR open while the user is still adding
    to it; when they seem done, offer the merge, and merge on their word.
  - Either way, once merging is approved carry it through without pausing: merge
    as soon as CI is green (or immediately if CI doesn't run). If CI fails, stop
    and report instead. A PR the user said to leave alone waits for them.
- **"Do" / "resolve" / "work" an issue** means the full chain by default, no
  asking between steps: assign the user, create the worktree, implement, run the
  gates, push, and open a ready-for-review PR — assigned to them, closing the
  issue.
- **If you can't finish** (environment failure, gates that won't pass, a spec
  gap), don't go silent: push what you have, open the PR as a **draft**, comment
  the bottleneck, and tag the user.
- **A PR the gates cannot fully judge gets an independent review before it
  merges** — database access, the API contract, auth, a refactor, CI and the
  gates. The `independent-review` skill has the triggers and how to keep the
  reviewer unbiased; run it on request for any PR, batch or not.
- **Decisions are written down, never waited on.** A judgement call the issue
  left open is yours to take when something points the way — a rule in this
  file, a convention the codebase already follows (the worked `items` example
  first), or a run of past decisions in the same direction. Take it and record
  it, with its reason, in the PR. A decision with none of those behind it goes
  back to the user, and the PR is a draft that names it. A check only a human
  can do (the page in a real browser, how it looks) never keeps a PR a draft:
  its checklist goes in the PR for the user to run later, and a failure found
  then is a bug. What stays the user's call is listed in *Take the initiative*.

## Working agreement

These govern how the agent operates in this repo. **Any of them can be
overridden by the user in the current or a previous prompt** — an explicit
instruction wins.

- **Committing and pushing are your call; merging is not.** Commit and push
  whenever you judge a meaningful part of the job done, with the gates for what
  you touched green — on your own branch, never on `main`, and never force-push
  a branch someone else is working on. When to merge is *Pull Requests*' rule.
- **Foundations come first.** The infrastructure, architecture, and gold-standard
  conventions/patterns must already be in place before any feature change is
  made. Don't build on top of a structure that isn't there yet — establish it.
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
A red gate is never handed off as "probably pre-existing": re-run that target on
`origin/main`, and only if it is red there too, say so with the output.

## Server-start guardrails

Do **not** auto-start dev servers, `docker compose up`, or long-running
processes to "check" something. Use the gates (build/test) to verify. If a human
needs a running app, ask them to start it.

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
- Cloud sessions are welcome — they keep worktrees off the local disk — but not
  required. There is no merge queue: nothing here is compiled, CI takes about a
  minute, and a rebase-and-re-verify is cheap (`issue-batch` has the numbers).

## Upgrade paths (intentionally deferred in the skeleton)

- **Migrations:** `init_db()` uses `create_all` (additive only). Add Alembic
  when schema changes need to be destructive/ordered.
- **Typed SDK:** generate `lib/schemas/` from the backend OpenAPI spec.
