---
name: independent-review
description: Get an unbiased review of a pull request before it merges — a fresh, read-only reviewer that never saw the coder's reasoning, then the findings answered on the PR. Use before merging a PR that touches database access, the API contract, auth, CI or the gates, or is a refactor; and whenever the user asks for a PR (open or already merged) to be reviewed. Batch or not.
---

# Independent review

## Why it exists

A coder reviewing its own diff reviews what it *meant* to write, not what it
wrote. The gates catch what a machine can state; they cannot tell you that a
query leaks another user's rows or that the frontend schema no longer matches the
backend's. So a PR that touches what the gates cannot see gets one more read, by
an agent that reads it the way an outsider would and is never told what to think
of it. **Everything below exists to keep the coder's bias out of the reviewer.**

The review itself is Claude Code's built-in `code-review` skill. It ships with
Claude Code and is updated whenever the model changes, so this skill only says
**when** to run it, **how to dispatch it without bias**, and **what to do with
what it finds**. It never restates how to review — that part would go stale here
and stay current there.

## When

Before the merge, when the PR hits any **trigger**:

- **Database access** — it adds or changes a query, a repository in
  `backend/repositories/`, or a model in `backend/models/`.
- **The API contract** — it changes a request or response shape: a Pydantic
  schema in `backend/schemas/` or its hand-made mirror in
  `frontend/src/lib/schemas/`. Nothing checks that the two agree, so this review
  is the only check.
- **Auth** — `backend/api/deps.py`, `backend/utils/security.py`, which side of
  `get_current_user` a router sits on in `backend/api/endpoints.py`, or how
  `frontend/src/lib/api/client.ts` carries the token.
- **A refactor**, on either side: code moved across files or layers with the
  intent of unchanged behaviour, or any PR adding more than ~1000 lines.
- **CI and the gates** — `.github/workflows/`, the `Makefile`,
  `backend/tools/house_lint.py`, `frontend/eslint-rules/`,
  `frontend/eslint.config.ts`, or the lint and test config the gates run.

And **on demand**: whenever the user asks for a PR to be reviewed, open or
already merged (*Catching up on a merged PR*, below).

## Dispatch

- **A fresh agent**: the `Agent` tool with `subagent_type: "general-purpose"`.
  **Never `"fork"`** — a fork inherits the coder's whole context, and with it the
  bias this skill exists to avoid. No `isolation: "worktree"` (it edits nothing)
  and no model override (it runs on the current model, the one `code-review` is
  tuned for).
- **Read-only.** It may read the PR, the repository and the issue, and run
  read-only commands (`gh pr view`, `gh pr diff`, `gh issue view`, `git show`).
  It makes no edits, commits, pushes, PR comments or issue comments.
- **The prompt carries only what an outsider would get:** the PR number, the
  issue it closes, the steering for the PR's nature, and the template below.
  **Not** a summary of the change, the coder's rationale, what was already
  checked, which differences are "known and fine", or what you expect it to
  find. The PR description is fair game — it is what the author tells every
  reader — and the reviewer tests its claims rather than trusting them.
- **One reviewer per PR**, all dispatched in the same message when there are
  several. A stacked PR is reviewed on its own diff (`gh pr diff` compares
  against its base); say so in the prompt, so the reviewer does not report the
  base's code as this PR's.

### Prompt template

```
Review PR #<n> of this repository. <If stacked: "Its base is PR #<m>; review
only this PR's own diff.">
It closes issue #<i> — read it with `gh issue view <i>`; it is what the PR is
meant to deliver. <Or: "It closes no issue; its description says what it is
for.">

Run the `code-review` skill on the PR at `high`, without `--comment` and
without `--fix`. You are read-only: no edits, commits, pushes, PR comments or
issue comments. You may run read-only commands.

Look especially for: <the steering list for each trigger the PR hits, pasted
whole>.

Answer with one entry per finding — file:line, the defect in one sentence, a
concrete failure scenario (inputs or state → wrong result or crash), and
whether it must be fixed before merge. Verify each one against the code before
reporting it. An empty list is a valid answer.
```

### Steering, by trigger

Paste every list whose trigger the PR hits.

- **Database access** — the database is touched in `repositories/` and nowhere
  else; repositories `flush()` and the caller commits (the rollback-per-test
  fixture depends on it); reads stay scoped to their owner, so one user never
  sees another's rows; NULLs; the ordering and tie-breaks callers rely on; caps
  and pagination; N+1 queries and lazy loads that fail under async; `create_all`
  is additive, so a column changed or removed in a model is not changed in an
  existing database; tests that would fail before the change and pass after.
- **The API contract** — the Pydantic schema and its `lib/schemas/` mirror agree
  field by field (names, optional versus required, types, enums, defaults);
  status codes and error bodies; every frontend caller of a changed endpoint;
  both halves in this one PR, never split.
- **Auth** — every new router sits on the intended side of `get_current_user`;
  an authenticated user still cannot read or change someone else's data; the
  token lives only in `lib/api/client.ts`; a 401 is handled, not swallowed; no
  secret or hash is logged or returned.
- **Refactor** — behaviour parity (same output for the same input); callers
  left on the old path; layer direction still one way (`api/` → `schemas/` →
  `repositories/` → `models/`); public contracts unchanged; moved code still
  tested; dead code left behind; scope beyond the refactor.
- **CI and the gates** — a red gate still fails the job; triggers still fire
  (draft PRs, path filters, branches); `make` locally and Actions still run the
  same target (the no-drift rule); a lint rule still catches what it claims, and
  its own tests say so; caching cannot mask a failure; permissions and secrets
  minimal.

## Answering the findings

The coder answers: resumed with `SendMessage` when it is a subagent, or this
session when it wrote the PR. The reviewer can be wrong, so every finding is
checked against the code first. Then:

1. **Must-fix** findings are fixed on the PR's branch. Anything declined gets its
   reason. A finding that needs a decision that is genuinely the user's (see
   `CLAUDE.md`, *Take the initiative*) goes to them, and the PR stays a draft
   that names it.
2. The gates are re-run (`make backend`, `make frontend` or `make check`) and the
   branch pushed. In a stack, the PRs above are rebased onto the fix.
3. **One PR comment, headed `Independent review`**, lists every finding and what
   became of it: fixed (with the commit), declined (with why), or sent to the
   user. Say so if there were no findings, too. This comment is the record that
   the review happened.
4. When the fixes rework a query, a contract or the logic substantially, one more
   reviewer reads the new diff. Otherwise one round is the review.

Then the PR merges per `CLAUDE.md`, *Pull Requests*. The review runs alongside
the gates and CI; it never replaces them.

## Catching up on a merged PR

Same dispatch, on the merged PR's number. Its fixes go in a **new PR** off
`main`, whose description names the reviewed PR; the `Independent review`
comment goes on the reviewed PR and links the fix.

## Common mistakes

- Dispatching a `fork`. That is the coder again, with the coder's blind spots.
- Briefing the reviewer with the coder's summary "to save it time". It then
  reviews the summary, not the code.
- Letting the reviewer push its own fixes. It reports; the coder fixes.
- Merging a triggered PR before its `Independent review` comment exists.
- Skipping the review because the diff is small. The trigger is what the change
  touches: a ten-line change to a repository's query is reviewed; a 300-line
  locale sweep is not.
