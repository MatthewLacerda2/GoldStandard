"""Whether `main` itself is green, and whether a green pull request may land on it.

Each pull request's CI ran against `main` as it was then, and the queue merges
a clean branch as it is, so two green pull requests can break `main` together.
`main`'s own push runs catch that after the fact; this reads them
(`checks.jobs`, `checks.main_red`: per job, since a push run skips the layers
it did not touch) and holds every green pull request while a job is red,
except the one that proves the fix: its branch contains the commit that broke
the job, and its own run ran that job and passed it (`checks.proves_fixed`).

`main`'s commits are read once a pass, and a commit whose check runs had all
finished is kept for [`KEEP_SECONDS`] across passes (a manual re-run can still
change it, so not for ever). A new red is re-run once, in case it is a
runner's blip, and the queue says when `main` turns red or green.
"""

from __future__ import annotations

import time

from tools.merge_queue import checks, github, repo, talk
from tools.merge_queue.state import Memory

HELD_LINE = (
    "green, but `main` itself is red: it merges once `main` is green again, or now if"
    " its branch contains the commit that broke each red job and its own run ran that"
    " job and passed it (it then carries the fix)."
)
UNREAD = "green, but `main`'s own CI could not be read this pass; asked again on the next:"
# How long a commit's finished check runs are trusted without asking again.
KEEP_SECONDS = 300


class MainGate:
    """`main`'s state as the queue holds it: read once a pass, said when it changes."""

    def __init__(
        self,
        hub: github.GitHub,
        clone: repo.Clone,
        required: list[checks.Required],
        memory: Memory,
        dry: bool,
    ) -> None:
        self.hub, self.clone, self.required = hub, clone, required
        self.memory, self.dry = memory, dry
        self.reds: list[checks.Red] | None = None  # this pass's reading
        self.unread = ""  # why this pass could not read it
        self.said = ""  # the last thing said about `main`
        self.kept: dict[str, tuple[float, list[dict]]] = {}  # finished commits' runs

    def new_pass(self) -> None:
        self.reds, self.unread = None, ""

    def runs_of(self, sha: str) -> list[dict]:
        """A commit's check runs: asked again unless they had all finished lately."""
        at, runs = self.kept.get(sha, (0.0, []))
        if time.monotonic() - at < KEEP_SECONDS:
            return runs
        runs = self.hub.check_runs(sha)
        if runs and all(run.get("status") == "completed" for run in runs):
            self.kept[sha] = (time.monotonic(), runs)
        return runs

    def state(self) -> list[checks.Red]:
        """The jobs red on `main`, a new red re-run once; said when it changes.
        A refusal is kept for the pass: it holds the green pull requests (it is
        `main`'s question, not theirs) and is asked again on the next."""
        if self.reds is not None or self.unread:
            return self.reds or []
        try:
            commits = [(sha, self.runs_of(sha)) for sha in self.clone.main_commits()]
        except talk.Refused as answer:
            self.unread = str(answer)
            return []
        found = [checks.main_red(job, commits) for job in checks.jobs(self.required, commits)]
        self.reds = [red for red in found if red is not None]
        for run in dict.fromkeys(github.run_id(red.run) for red in self.reds):
            self.rerun(run, [red for red in self.reds if github.run_id(red.run) == run])
        said = " ".join(red.line() for red in self.reds)
        if said != self.said:
            if self.reds:
                talk.say("`main` is red:", *[red.line() for red in self.reds], HELD_LINE)
            elif self.said:
                talk.say("`main` is green again; the line moves.")
            self.said = said
        return self.reds

    def rerun(self, run: int | None, reds: list[checks.Red]) -> None:
        """Re-run a new red run's failed jobs once, in case it is a runner's blip.
        Best effort: a refusal is said, and the line stays held either way."""
        fresh = not any(red.rerunning or red.reran for red in reds)
        if run is None or not fresh or run in self.memory.reruns:
            return
        line = reds[0].line()
        if self.dry:
            talk.say(f"`main`: would re-run its failed jobs once: {line}")
            return
        self.memory.reruns.add(run)
        refused = self.hub.rerun_failed(run)
        again = (
            f"could not re-run it: {refused}" if refused else "re-ran it once, in case of a blip."
        )
        talk.say(f"`main`: {line}", again)

    def holds(self, head: str, runs: list[dict]) -> list[str]:
        """Why `main`'s state holds this green head, whose check runs are `runs`;
        empty when it does not."""
        reds = self.state()
        if self.unread:
            return [UNREAD, self.unread]
        why = []
        try:
            for red in reds:
                if not self.clone.contains(head, red.first):
                    why.append(f"{red.line()}; this branch does not contain {red.first[:7]}.")
                elif not checks.proves_fixed(red, runs):
                    name = red.check.context
                    why.append(
                        f"{red.line()}; this branch's own run did not run `{name}` and pass it."
                    )
        except talk.Refused as answer:
            return [UNREAD, str(answer)]
        return [HELD_LINE, *why] if why else []
