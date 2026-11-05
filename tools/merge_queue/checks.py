"""Whether CI passed: on a pull request's head, and on `main`. Pure.

**What counts as CI is what the `main` ruleset requires** (README, *Protecting
`main`*): the contexts `.github/rulesets/main.json` lists ([`required`]),
`CI ok`, which `ci.yml` ends in, and the `mutation gate`, a workflow of its
own on `pull_request_target` whose check runs land on the pull request's head
too. A workflow added as another required check is judged here the day it is
listed there, with nothing to change in the queue. A context listed with an `integration_id` is
read only from that app's check runs, so another app cannot post a check of
the same name and stand in for it.

**On a head** ([`head`]), every required context's newest check run decides:

- **No run is not green.** `CI ok` gets its check run only once the jobs it
  needs have finished, so a context with no run while any other check on the
  head is still going is pending. With nothing going, it is waited on for
  [`RUN_APPEARS_SECONDS`] (GitHub creates the run a little after the push or
  the `ready_for_review`), then is an answer of its own, never a pass.
- **A skipped run is not a run.** A draft skips every job, `CI ok` included;
  a ready pull request whose newest `CI ok` is skipped was never checked.
- **Red is an answer at once**, even while another context is still running.

**On `main`** the verdict is **per job**, not per required context: a push
run skips the jobs whose layer the push did not touch, so after a merge that
turned `backend` red, a docs-only merge's green `CI ok` says nothing about the
backend. The jobs judged are the required contexts and every job of the same
workflow run ([`jobs`]: the check runs sharing a check suite with one). For
each job ([`main_red`]), `main`'s first parents are walked newest first (each
merge and each direct push gets its own run, and `ci.yml` never cancels one on
`main`, so a red there means a job really failed). A commit on which the job
is still running, skipped or cancelled says nothing and the one before it
decides, unless it is a re-run of a run that failed: a red being re-run is
still red until it says otherwise. The **red streak** is the newest commits on
which the job failed, back to the last on which it passed; its oldest commit
is the one that broke it. A pull request carries the fix only when its branch
contains that commit **and** its own run ran that job and passed it
([`proves_fixed`]): a run that skipped the job proves nothing about it.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

GREEN, PENDING, RED, NO_RUN = "green", "pending", "red", "no run"

# How long after a job finishes the next one may still be unqueued: `CI ok`
# appears a few seconds after the last job it needs.
SETTLING_SECONDS = 60
# How long a required context may have no run on a head before that is an answer.
RUN_APPEARS_SECONDS = 300
# Conclusions that judged nothing: the commit before decides.
UNJUDGED = frozenset({"skipped", "cancelled", "stale"})

NO_RUN_HELP = (
    "Absent checks are not green. Mark the pull request draft and ready again,"
    " or push a commit, to get a run."
)


@dataclass(frozen=True)
class Required:
    """One required status check: its context, and the app that must post it."""

    context: str
    app: int | None = None


@dataclass
class Verdict:
    state: str
    lines: list[str]


@dataclass(frozen=True)
class Red:
    """A job red on `main`: where the streak began, and its newest run."""

    check: Required
    first: str  # the oldest red commit: the one that broke it
    newest: str  # the newest red commit
    run: dict  # the newest red check run
    rerunning: bool  # a re-run of it is going: still red until it says otherwise
    reran: bool  # it has been run more than once already

    def line(self) -> str:
        how = "is being re-run" if self.rerunning else "failed"
        since = "" if self.newest == self.first else f" (red since {self.first[:7]})"
        url = self.run.get("html_url") or "the run"
        return f"`{self.check.context}` {how} on `main` at {self.newest[:7]}{since}: {url}"


def required(ruleset: str) -> list[Required]:
    """The status checks a ruleset (`.github/rulesets/main.json`) requires.

    A ruleset that requires none leaves nothing to say CI passed, so it is an
    error, never an empty list the queue would read as "nothing to wait for".
    """
    data = json.loads(ruleset)
    found = []
    for rule in data.get("rules") or []:
        if rule.get("type") != "required_status_checks":
            continue
        for check in (rule.get("parameters") or {}).get("required_status_checks") or []:
            found.append(Required(check["context"], check.get("integration_id")))
    if not found:
        raise ValueError("the ruleset requires no status check, so nothing says CI passed")
    return found


def same_app(required: Required, run: dict) -> bool:
    return required.app is None or (run.get("app") or {}).get("id") == required.app


def mine(required: Required, runs: list[dict]) -> list[dict]:
    """The check runs that answer for `required`, oldest first."""
    found = [run for run in runs if run.get("name") == required.context and same_app(required, run)]
    return sorted(found, key=lambda run: run.get("id") or 0)


def stirring(run: dict, now: datetime) -> bool:
    """Whether a check run is unfinished, or finished so lately that the job
    after it (`CI ok`, last of all) may not have been queued yet."""
    if run.get("status") != "completed":
        return True
    done = run.get("completed_at")
    if not done:
        return False
    return (now - datetime.fromisoformat(done)).total_seconds() < SETTLING_SECONDS


def one(
    required: Required,
    runs: list[dict],
    others: frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> tuple[str, str]:
    """One required context's state on a head, and a line saying it. `others`
    are the other required contexts, whose runs never stand in for this one's."""
    now = now or datetime.now(UTC)
    found = mine(required, runs)
    name = f"`{required.context}`"
    if not found:
        return NO_RUN, f"{name} has no run on this commit."
    run = found[-1]
    if run.get("status") != "completed":
        return PENDING, f"{name} is {run.get('status') or 'queued'}."
    conclusion = run.get("conclusion")
    if conclusion == "success":
        return GREEN, f"{name} passed."
    if conclusion == "skipped":
        return NO_RUN, f"{name} was skipped on this commit (a draft's run): it checked nothing."
    later = [
        r
        for r in runs
        if (r.get("id") or 0) > (run.get("id") or 0)
        and same_app(required, r)
        and r.get("name") not in others
    ]
    if any(stirring(r, now) for r in later):
        # A re-run of the failed jobs, or a reopened pull request's new run, is
        # going (or just finished); `CI ok` reports again once its jobs finish.
        return PENDING, f"{name} failed, and a newer run is going: waiting for it."
    return RED, f"{name} concluded {conclusion}: {run.get('html_url') or 'the run'}"


def head(
    required: list[Required], runs: list[dict], waited: float, now: datetime | None = None
) -> Verdict:
    """A head's CI verdict. `runs` are every check run on the head; `waited`
    is how long the queue has watched this head, in seconds."""
    now = now or datetime.now(UTC)
    names = frozenset(each.context for each in required)
    found = [one(each, runs, names - {each.context}, now) for each in required]
    by_state = {state: [line for s, line in found if s == state] for state in (RED, PENDING)}
    absent = [line for s, line in found if s == NO_RUN]
    going = sorted({r.get("name") or "?" for r in runs if stirring(r, now)})
    if by_state[RED]:
        return Verdict(RED, by_state[RED])
    if by_state[PENDING]:
        return Verdict(PENDING, by_state[PENDING])
    if absent and going:
        return Verdict(PENDING, [*absent, f"CI is still running: {', '.join(going)}."])
    if absent:
        if waited < RUN_APPEARS_SECONDS:
            return Verdict(PENDING, [*absent, "Not yet an answer this soon after the push."])
        return Verdict(NO_RUN, [*absent, NO_RUN_HELP])
    return Verdict(GREEN, [f"CI passed: {', '.join(f'`{r.context}`' for r in required)}."])


def says(required: Required, runs: list[dict]) -> str | None:
    """What one commit on `main` says: `success`, `red`, `rerunning`, or `None`."""
    found = mine(required, runs)
    if not found:
        return None
    run = found[-1]
    if run.get("status") != "completed":
        earlier = [r.get("conclusion") for r in found[:-1] if r.get("status") == "completed"]
        failed = [c for c in earlier if c != "success" and c not in UNJUDGED]
        return "rerunning" if failed else None
    conclusion = run.get("conclusion")
    if conclusion in UNJUDGED:
        return None
    return "success" if conclusion == "success" else "red"


def suite(run: dict) -> object:
    return (run.get("check_suite") or {}).get("id")


def jobs(required: list[Required], commits: list[tuple[str, list[dict]]]) -> list[Required]:
    """The required contexts and the jobs of the workflow run that last reported
    each on `main`: the check runs sharing a check suite with its newest
    finished run, on the newest commit that has one. A job removed or renamed
    in that workflow drops out of the list with the first push run without it,
    so an old red of a job that no longer exists holds nothing."""
    found = list(required)
    for each in required:
        for _, runs in commits:
            done = [run for run in mine(each, runs) if run.get("status") == "completed"]
            if not done:
                continue
            for run in runs:
                job = Required(run.get("name") or "", each.app)
                if suite(run) == suite(done[-1]) and job.context and job not in found:
                    found.append(job)
            break
    return found


def proves_fixed(red: Red, runs: list[dict]) -> bool:
    """Whether a head's own check runs show `red`'s job fixed: it ran and passed
    (skipped is not), or the head has no run of it at all, because the pull
    request removes or renames the job. That last is what a `main` red on a
    job that no longer exists needs, and the pull request's own required
    checks still had to pass first."""
    return one(red.check, runs)[0] == GREEN or not mine(red.check, runs)


def main_red(required: Required, commits: Iterable[tuple[str, list[dict]]]) -> Red | None:
    """`required`'s red streak on `main`, or `None` when it is not red.

    `commits` are `(sha, check runs)` newest first: the walk stops at the first
    commit on which it passed.
    """
    streak: list[tuple[str, list[dict], str]] = []
    for sha, runs in commits:
        said = says(required, runs)
        if said == "success":
            break
        if said is not None:
            streak.append((sha, runs, said))
    if not streak:
        return None
    (newest, runs, how), first = streak[0], streak[-1][0]
    found = mine(required, runs)
    return Red(required, first, newest, found[-1], how == "rerunning", len(found) > 1)
