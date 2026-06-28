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

- **Plain language over decoration.** Prefer plain language that explains what
  we — or the code — are doing, not highly technical decoration. The user is
  trying to architect intelligence, not ornament an implementation.
- **Solve the problem, not the solution.** It must always be clear to you the
  *problem* the user wants to solve, rather than the solution they're reaching
  for. A solution is just one way to create value for a problem; it is
  downstream of the problem. You and the user must share the fundamental truths
  of the problem — know its axioms — before building anything. It is your duty
  to hold the user to this too: if they are polishing a solution before the
  problem is pinned down, say so.
- **Align before building.** The user must have a clear, defined idea of what
  they are trying to say. If the idea isn't yet clear — to them or to you —
  stop: don't plan, don't implement. Get the idea defined for both of you
  first. Alignment of understanding comes before everything downstream.
- **Readable first, then tight.** First structure a good architecture and write
  code that is readable and organized. Then tighten it — denser, more compact —
  but compactness serves readability, it is not the finish line. If the clearest
  version of something isn't the densest, leave it clear. Don't end on clever
  one-liners nobody can debug later.
- **Push back when it's earned.**
  - If a feature or addition doesn't move the model's final performance, say so
    and say why it isn't pulling its weight.
  - If an idea contradicts what the literature has settled, flag it immediately.
    But calibrate: push hard on documented dead-ends, stay curious about
    genuinely untried ground. Research means trying what the literature hasn't
    settled — don't suppress a novel idea just because it's unproven. The line
    is "documented to fail" versus "simply not yet tried."
- **Overriding these rules.** In the end, all rules may be overridden by the
  user — so long as the user says why, and the explanation still holds in the
  current context.

## Issues and Pull Requests

How we plan work and land it. These are process rules; like everything above,
the user can override them with a reason that holds.

### Issues

An issue is the agreed *purpose and direction* of a piece of work, written
before it — a best-effort intention, not a hard spec. It has three parts:

- **Context** — the problem or feature, and what we want once it's addressed.
- **Suggestion** — the changes to make, and/or how.
- **Definition of done** — what the resulting Pull Request should deliver.

Because it is written before the work, an issue can't foresee everything: its
*Suggestion* may not survive contact with the code, and its *Definition of done*
may miss something. Treat it as a starting point and let what you discover refine
the details — never treat an incomplete or slightly-wrong issue as a reason to
stop. When the work meaningfully diverges, the **Pull Request is the source of
truth** for what was actually done: say so there, and if the gap matters later,
reflect it back into the issue or spin off a new one.

- **Title** starts with a scope tag — `[FE]` frontend, `[BE]` backend, `[FS]`
  fullstack, `[OT]` other (DevOps, root-folder files, docs-only). Tags are
  scan/query cues, not hard walls; common sense lets work cross a tag when the
  outcome needs it. Still separate by responsibility — if an issue grows too
  big, split the rest into another one.
- **Primary label** (at least one): `feat` (new feature/enhancement), `fix`
  (bug or problem), `refactor` (changes how we do things).
- **Additive labels** (only alongside a primary): `docs`, `planning` (we don't
  yet know how to implement it), `human` (can't be finished by an agent alone).
- **`minor`** — a very small change (~30 lines or fewer), so small its
  resolution may just ride along in another issue's PR. May appear alone or with
  anything.
- **Assignment** — no assignee means free for grabs; an assignee means it's
  taken. When we start *actually working* an issue (not just planning), assign
  the user and tell them. Picking an issue doesn't require opening a PR yet.

If the user postpones a change that must still happen, suggest opening an issue
so we don't lose track of it.

### Pull Requests

Run the gates locally first (see the no-drift meta-pattern) — green before you
push. A PR need not address an issue; when it does, title it
`{issue_number}-{branch_name}` (e.g. `42-feat/item-tags`) and start the
description with `Closes #{issue_number}`.

- **Every PR is assigned to someone.** If the user asked you to open it, assign
  them; if it closes an issue, assign them there too. If that issue is already
  assigned to someone else, say so and let the user decide — you may keep
  writing the PR meanwhile.
- **Never merge without the user's say-so.** Once given, carry it through
  without pausing: commit, push, then merge as soon as CI is green (or
  immediately if CI doesn't run). If CI fails, stop and report instead.
- **"Do" / "resolve" / "work" an issue** means the full chain by default, no
  asking between steps: assign the user, create the worktree, implement, run the
  gates, push, and open a ready-for-review PR — assigned to them, closing the
  issue.
- **If you can't finish** (environment failure, gates that won't pass, a spec
  gap), don't go silent: push what you have, open the PR as a **draft**, comment
  the bottleneck, and tag the user.

Structure the description as four sections, in order:

1. **Context** — what the PR addresses (feature, bug, refactor…).
2. **Solution** — how it adds value. Skip how you got there unless it's needed
   to explain the solution, and skip the technical domain unless it's new to the
   repository.
3. **Surface** — what the change touches: name the nearest common parent folder,
   then the core files and what each adds or edits (frontend: which pages/
   routes). The flow, not deep technical detail.
4. **Result** — what changes from now on.

The user no longer hand-writes issue or PR descriptions — you do — so there's no
need to mark them "AI-generated"; that's the default. The user may still write
comments. Before an issue is written, the user must show they have thought it
through — first principles and purpose — and the idea must be clear to both
sides. Don't transcribe a vague ask into an issue: surface gaps, challenge
assumptions, reach shared understanding first.

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
- **Typed SDK:** generate `lib/schemas/` from the backend OpenAPI spec.
