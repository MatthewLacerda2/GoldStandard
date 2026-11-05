---
name: ci-merge
description: Take a finished branch through to merged — what a ready pull request claims, what to run before marking one ready, CI, the merge itself, a red pull request, rebasing. Use when a branch is ready, when a pull request has gone red, or when merging anything into `main`, batch or not.
---

# Getting a branch merged

`CLAUDE.md` states the rules — *Pull Requests* says when a pull request merges,
*The no-drift meta-pattern* says the gates are green before a push. This is how
to keep them. `issue-batch` adds what changes when several branches are in
flight at once.

## What a ready pull request claims

**A ready pull request claims the branch is finished; a draft makes no claim.**

- **Open it as a draft on the first push.** Draft is not decoration on
  unfinished work; it is how work survives a session that ends badly. The
  durable context is the issue, written to be read cold — never rely on a
  hand-back comment existing.
- **Ready means finished.** Never ready a pull request just to get a CI run: in a
  batch it merges the moment CI is green, so a temporary test loop readied for
  a run merges with the loop still in it. The no-drift rule is what makes this
  cheap here — the local gates *are* the CI targets, so the proof on a draft is
  `make check`, run locally.

## Before marking it ready

**Green locally.** `make backend` or `make frontend` for the layer you touched
while working, `make check` before marking it ready. CI runs these exact
targets, so a local green is a real prediction — as long as your environment
matches CI's (*CI as it runs today*, below). A `.venv` or a `node_modules` that
has drifted from its manifest is green on nothing.

**Not every red is the branch's.**

- Before fixing a red gate in code the branch did not touch, run it on
  `origin/main`. If it fails there too, it is a bug to cite or file, not this
  branch's to fix.
- A failure the machine caused — `No space left on device`, `Cannot allocate
  memory`, a killed process — says nothing about the code: free the space and
  run it again. Never "fix" code that was never wrong.
- A gate this machine cannot run at all (no docker for the test database, say)
  is **named in the pull request**, with the CI job that answers for it — never
  claimed green.

## CI as it runs today

Every CI fact this skill relies on lives in this section, so a change to the
workflows is a change here.

- **One workflow, `ci.yml`, runs on every ready pull request and every push to
  `main`**, and ends in **`CI ok`**, the one check that says CI passed. Its
  first job, `changes`, asks `tools/ci_paths.py` which layers the change
  touches, and the `backend` and `frontend` jobs run only for theirs (that file
  holds the paths). `tools` (`make tools`: ruff and tests for `tools/`, and the
  docs lint) runs on every change. A Markdown-only branch still gets `CI ok`,
  green with the layer jobs skipped.
- **A draft runs nothing.** Every job is skipped on a draft, so marking a pull
  request ready is the moment anything is checked (`ready_for_review` starts
  the run); until then the local gates are all you have.
- **CI's environment:** `make backend PYTHON=python` on a clean Python 3.14 with
  `requirements.txt` installed fresh, and `bun install --frozen-lockfile`. The
  `tools` job installs only ruff, at the pin in `backend/requirements-dev.txt`.
- **Absent and passing are different states.** A branch that conflicts with
  `main` gets no run at all, and on the pull request page that reads exactly
  like checks that have not started. Wait for `CI ok` on the head commit, and
  never write a wait loop that reads zero completed checks as success:
  `gh pr checks <n>` alongside `gh run list --branch <branch>` tells you
  whether a run exists.
- **Nothing but you stops a red merge** until the repo applies the ruleset that
  requires `CI ok` (README, *Protecting `main`*); a repo made from the template
  starts without it. `gh api repos/{owner}/{repo}/rulesets` says which.

## The merge, one branch at a time

1. `git fetch origin && git rebase origin/main` in the branch's worktree, then
   push with `--force-with-lease`.
2. **Independent review, when a trigger hits.** Invoke the `independent-review`
   skill: it names the triggers, dispatches the unbiased reviewer, and says how
   the coder answers. It runs on the **draft**, before step 3: findings are part
   of being finished, and ready means finished. A pull request that hits no
   trigger skips this step.
3. **Mark it ready.** That is what starts CI.
4. **Wait for the runs that should exist** on the rebased head, and check that
   they exist (*CI as it runs today*).
5. **Merge, once merging is approved.** `CLAUDE.md`, *Pull Requests*, says when:
   in a batch, starting the batch was the approval; in a conversation, the
   user's word. Nobody waits to read the code. Merge as soon as CI is green, or
   immediately if CI does not run, and a triggered pull request once its
   `Independent review` comment exists too. If CI fails, stop and fix forward
   or report. A pull request the user said to leave alone waits for them.
6. `gh pr merge`, then remove the worktree and delete the branch —
   `deleteBranchOnMerge` is off, so both are yours to do.

Within one layer, merges serialize: the second branch is rebased and
re-verified after the first lands. Across layers they do not (`issue-batch`,
*Merges serialize per layer, not globally*, has why).

## A red ready pull request stays ready

It is fixed forward in the next commit, never quietly drafted back. Draft is for
work that is genuinely unfinished, blocked, or handed over.

## Rebasing

**Expect conflicts where every feature appends** (`issue-batch`, *The files
where everything collides*, lists them). Two authors both being right is the
common case, and the resolution is usually to keep both sides, ordered
deliberately rather than by merge accident.

- **Mechanical resolutions** — an import list, a locale key, a
  `requirements.txt` line — are fine to do directly.
- **Hand one back** when resolving it needs to know *why* the code is shaped as
  it is: a router whose auth dependency matters, two prose paragraphs that need
  ordering, a token whose name is a decision.
