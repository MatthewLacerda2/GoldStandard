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
- **A check only a person can run goes under `## For a human`**, as unticked
  `- [ ]` items. Finished does not wait for it (`CLAUDE.md`, *Pull Requests*),
  so the description is where it waits instead, and that one heading is how
  `make checks` finds it once the pull request has merged.

## Before marking it ready

**Green locally.** `make backend` or `make frontend` for the layer you touched
while working, `make check` before marking it ready. CI runs these exact
targets, so a local green is a real prediction — as long as your environment
matches CI's (*CI as it runs today*, below). A `.venv` or a `node_modules` that
has drifted from its manifest is green on nothing; every backend gate refuses a
`.venv` off its pins (`back-pins`), and `node_modules` is still yours to check.

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
- **`regression` runs on every pull request**: one closing a `fix` issue needs
  a changed test that fails on the base (`make regression PR=N` locally), or
  an exception line in its description; it reads the description when it
  runs, so re-run it after an edit.
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
4. **Label it `queue`, once merging is approved.** `CLAUDE.md`, *Pull
   Requests*, says when: in a batch, starting the batch was the approval; in a
   conversation, the user's word. Nobody waits to read the code. A pull request
   the user said to leave alone is not labelled.
5. **The queue does the rest** (*Feeding the merge queue*, below): it waits for
   `CI ok` on the head, rebases a conflict, merges as soon as everything is
   green, deletes the branch and frees the worktree, and hands back what needs
   somebody. If CI fails, the hand-back says so: fix forward or report.

Merging by hand is the fallback for a repo where the queue cannot run: wait for
`CI ok` on the head and check that it exists (*CI as it runs today*), merge
with a merge commit, then remove the worktree and delete the branch
(`deleteBranchOnMerge` is off).

The queue merges a branch that merges cleanly as it is, without a re-run on the
new `main`; what two branches in one layer break together shows as a red
`main` (`issue-batch`, *Merges serialize per layer, not globally*, has why).

## Feeding the merge queue

`make queue` (`tools/merge_queue/`; its package docstring is the design) waits,
rebases and merges so nobody holds a context open through CI. You read diffs
and label; it spends no tokens.

- **Label `queue` once the pull request is reviewed and ready**: marked ready,
  and its `Independent review` comment posted when a trigger hits. Label it over
  REST, `gh api repos/{owner}/{repo}/issues/N/labels -f 'labels[]=queue'`
  (`gh pr edit` is GraphQL, which some proxies refuse). The label is
  the go-ahead, not the proof. Before every merge the queue checks it again:
  every check `.github/rulesets/main.json` requires (today `CI ok`) passed on
  the head commit, the review record names that head (`independent-review`,
  *Answering the findings*), what the description closes may be closed, it
  does not conflict with `main`, and `main` is not red.
- **One watch per clone, in the background**:
  `make queue ARGS=--watch > <scratchpad>/queue.log 2>&1`, and follow the log
  for `HANDED BACK|stopped:|resume:` rather than the watch itself. A watch ends
  after `--for` minutes (70 by default); its last line is the command that
  resumes it, and the line before says the exit status in words. A second
  queue on the same clone exits at once (a lock). `make queue PRS="12 14"`
  takes named pull requests, label or not, until each merged or was handed back.
- **Ask without acting**: `make mergeable PR=N` asks every question the queue
  asks before it merges, read-only (a coder can ask it before readying);
  `ARGS="--watch --dry-run"` runs one read-only pass. Never merge by hand beside
  a running queue: a pull request that must go now is labelled.

**Reading its hand-backs.** Each is one line, `queue: HANDED BACK #N: <reason>`,
with the detail indented under it, and the reason is the first thing to fix. A
hand-back is not a removal: the queue keeps asking, and a pull request whose
answer turns into a pass (a push, an edited description, a review record)
merges on its own.

- **A red `CI ok`, or a conflict its rebase stopped on** (the paths are named):
  back to the coder. The fix is a push; the queue takes the new head.
- **No `CI ok` on the head**, or a skipped one: absent is not green. Mark it
  draft and ready again, or push, to get a run.
- **The review lane**: no `Independent review` record, or one naming another
  head. Run `independent-review` on what was pushed since, then post a record
  naming the new head. A rebase that left the change as it was needs nothing:
  the queue counts the record for it.
- **What it closes**, in the description or in a commit message (the merge
  commit keeps them, and `fixes #N` there closes #N too): an issue labelled
  `planning` or `human`, a number that is a pull request or a closed issue, or
  a branch `N-…` whose description does not name #N. A description is an edit
  away, a commit message a reworded commit; a stage label only the user removes.
- **`` `main` is red: ``** is not a hand-back but a hold: a merge broke `main`
  (two green branches, red together). It is judged per job, since a push run
  skips the layers it did not touch: a later docs-only merge's green `CI ok`
  does not clear a red `backend`. The queue re-runs the failed jobs once, then
  holds every green pull request unless its branch contains the commit that
  broke the job and its own run ran that job and passed it. Fixing it outranks the batch: a `fix` branch cut from the
  current `main`, labelled `queue`, and the line moves once it merges.

The exit status is the most urgent thing to read: 0 nothing to read, 1
something was handed back, 3 GitHub, the network or the machine failed (run it
again), 4 another queue holds this clone's lock, 5 the credentials were refused.

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
