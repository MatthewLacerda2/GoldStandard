"""The merge queue: `make queue` merges cleared pull requests into `main`, spending no tokens.

Without it, whoever merges watches CI, rebases, waits again, merges and
deletes the branch, holding their whole context open the entire time, once
per pull request. However fast this template's CI is, the waiting is the
cost, and a project made from it will have a slower CI. So the orchestrator
reads the diff and puts the `queue` label on the pull request; the queue does
the waiting and the merging, and hands back only what needs somebody, one
line each (`queue: HANDED BACK #N: <reason>`). It is invoked, never a
service: stdlib Python over `gh api` (REST only, `talk.py`) and local `git`.

What it guarantees, and where each guarantee lives:

- **CI really ran on the head commit and passed**: every check the `main`
  ruleset requires (`.github/rulesets/main.json`; today `CI ok`, which every
  `ci.yml` job feeds) concluded `success` on the head (`checks.py`). A skipped
  check is not a run (a draft skips it); no run is not green.
- **The review lane is enforced, not replaced**: a pull request that hits an
  `independent-review` trigger (`tools/review_triggers.py`) merges only with an
  `Independent review` comment naming its head (`review.py`).
- **What it closes may be closed** (`closing.py`): no issue labelled
  `planning` or `human`, no closing keyword aimed at a pull request or at a
  closed issue, and a branch named for an issue names it.
- **Fewest conflicts first, then the label priority in `CLAUDE.md`, then the
  oldest**; nothing starves; a green one never waits on a pending one it does
  not conflict with (`order.py`).
- **A conflict with `main` is rebased in a throwaway worktree** and pushed with
  a lease when clean; otherwise handed back with the paths. It never resolves
  a conflict itself (`repo.py`).
- **A red `main` blocks everything but its fix**: while a required check's
  newest verdict on `main` is red (re-run once, in case of a blip), a green
  pull request stays in line unless its branch contains the commit that broke
  it, which its own green run then proves fixed (`judge.MainGate`).
- **The merge is a merge commit**, only while the head is the one judged
  (REST's `sha`, the `--match-head-commit` of `gh pr merge`), and an
  ambiguous 5xx is asked about before anything is concluded (`github.py`).
- **After the merge**: the remote branch is deleted (only once GitHub says
  merged) and the coder's worktree is freed (`aftermath.py`).
- **One queue at a time** (a lock), and a memory that outlives a watch
  (`state.py`).

It never rebases a branch that merges cleanly: the stack is interpreted and
the ruleset does not require an up-to-date branch, so a clean branch merges as
it is, and what two such merges break together is what `main`'s own runs and
the red-`main` rule catch. It merges one pull request per CI run, never a
train of them. It never runs a gate itself: `make check` is the author's,
before the pull request is marked ready. `make mergeable PR=N` asks the same
questions read-only, so a coder can ask them before readying.
"""
