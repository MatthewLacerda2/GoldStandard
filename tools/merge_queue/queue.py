"""The queue's passes: every pull request in line judged, the first one free merged.

One pass ([`Queue.sweep`]) asks, for each pull request, where it stands
(`judge.Judge.assess`), rebases the ones that conflict with `main`, puts the
ones still in line in `order.ordered`'s order and merges the first green one
nothing ahead of it blocks. A merge moves `main`, so the pass ends there and
the next one starts from the new `main`. A watch is passes until `--for` runs
out; a named run is passes until every named pull request merged or was
handed back.
"""

from __future__ import annotations

import time
from argparse import Namespace
from datetime import UTC, datetime
from itertools import combinations

from tools.merge_queue import aftermath, github, judge, order, repo, talk
from tools.merge_queue.state import Memory

# How long an idle watch sleeps between looks when nothing is in line.
IDLE_SECONDS = 60
IN_LINE = (judge.PENDING, judge.HELD, judge.GREEN)


class Queue:
    def __init__(
        self,
        opts: Namespace,
        hub: github.GitHub,
        clone: repo.Clone,
        memory: Memory,
        judged: judge.Judge,
    ) -> None:
        self.opts, self.hub, self.clone, self.memory = opts, hub, clone, memory
        self.judge = judged
        self.dry = opts.dry_run
        self.after = aftermath.Aftermath(hub, clone.root, self.dry)
        self.blocked: dict[int, tuple[datetime, int]] = {}  # since when, and by whom
        self.narrated: dict[int, str] = {}
        self.failed: dict[str, list[str]] = {}  # rebases that failed, by head and `main`
        self.refused: dict[int, tuple[str, str]] = {}  # a merge GitHub refused: at what, why
        self.merged: list[int] = []
        self.handed: dict[int, str] = {}
        self.ended: set[int] = set()  # whose turn is over: merged, handed back, closed
        self.in_line: dict[int, str] = {}

    # -- speaking ------------------------------------------------------------

    def narrate(self, number: int, line: str) -> None:
        """A progress line, said once until it changes."""
        if self.narrated.get(number) != line:
            self.narrated[number] = line
            talk.say(f"#{number}: {line}")

    def hand_back(self, pull: dict, lines: list[str]) -> tuple[str, list[str]]:
        """Say a hand-back: once per head and reason in a watch, every time in a list."""
        number, reason = pull["number"], lines[0]
        news = not self.opts.watch or self.memory.first_time(number, pull["head"], reason)
        if self.dry:
            # Said and counted as a real pass would, so its exit status matches.
            talk.say(f"would hand back #{number}: {reason}", *lines[1:])
            self.handed[number] = reason
        elif news:
            talk.say(f"HANDED BACK #{number}: {reason}", *lines[1:])
            self.handed[number] = reason
        self.ended.add(number)
        self.in_line.pop(number, None)
        self.narrated.pop(number, None)
        return judge.HANDED, lines

    # -- one pull request ----------------------------------------------------

    def assess(self, pull: dict) -> tuple[str, list[str]]:
        number, head = pull["number"], pull["head"]
        at = f"{head} {self.clone.main}"
        if self.refused.get(number, ("", ""))[0] == at:
            return self.hand_back(pull, [self.refused[number][1]])
        if pull["draft"]:
            # Its clocks start once it is ready: a draft's age is not time in line.
            self.memory.forget(number)
            return judge.DRAFT, ["it is a draft; the queue takes it once it is ready."]
        seen = self.memory.seen(number, head, datetime.now(UTC))
        waited = (datetime.now(UTC) - datetime.fromisoformat(seen["at"])).total_seconds()
        try:
            state, lines = self.judge.assess(pull, waited)
        except talk.Refused as answer:
            return self.hand_back(pull, [str(answer)])
        if state == judge.HANDED:
            return self.hand_back(pull, lines)
        if state == judge.CONFLICT:
            return self.rebase(pull, lines)
        return state, lines

    def rebase(self, pull: dict, why: list[str]) -> tuple[str, list[str]]:
        """It conflicts with `main`: rebase it in a throwaway worktree, push if clean.

        A clean branch is never rebased (it merges as it is); this one cannot
        merge, and gets no CI run, until its branch is on `main`. A rebase that
        stops on a conflict is handed back with the paths, never resolved.
        """
        number, head = pull["number"], pull["head"]
        if pull.get("head_repo") != pull.get("base_repo"):
            return self.hand_back(
                pull,
                [*why, "Its branch is on a fork, which the queue cannot push to: rebase it there."],
            )
        key = f"{head} {self.clone.main}"
        if key not in self.failed:
            fresh, lines = self.clone.rebase(pull["branch"], head, push=not self.dry)
            if fresh == head:
                # Only GitHub's flag said so, and the branch already holds
                # `main`'s tip: GitHub has not recomputed it yet.
                return judge.PENDING, ["GitHub still calls it conflicting; asked again next pass."]
            if fresh is not None:
                done = "would rebase it cleanly and push" if self.dry else "rebased it and pushed"
                talk.say(f"#{number}: {why[0]} {done} {fresh[:7]}.")
                return judge.PENDING, ["rebased onto `main`; waiting for CI on the new head."]
            self.failed[key] = lines
        return self.hand_back(pull, self.failed[key])

    # -- a pass --------------------------------------------------------------

    def sweep(self, pulls: list[dict]) -> bool:
        """One pass. True when it merged something (and so `main` moved)."""
        self.settle()
        self.judge.gate.new_pass()
        self.judge.gate.state()  # said, and a new red re-run, whether or not a PR is green
        states: dict[int, str] = {}
        for pull in pulls:
            number = pull["number"]
            state, lines = self.assess(pull)
            if state in IN_LINE:
                states[number] = state
                self.in_line[number] = lines[0] if lines else state
                if state != judge.GREEN:
                    self.narrate(number, " ".join(lines[:2]) or "waiting.")
            else:
                self.in_line.pop(number, None)
        line = [p for p in pulls if p["number"] in states]
        clashes = self.clashes(line)
        now = datetime.now(UTC)
        late = {
            p["number"]
            for p in line
            if order.overdue(
                self.memory.first_seen.get(str(p["number"]), {}).get("line"),
                self.memory.passes.get(str(p["number"]), 0),
                now,
            )
        }
        tiers = {p["number"]: order.tier(self.judge.labels.get(p["number"], [])) for p in line}
        ranked = order.ordered(line, clashes, tiers, late)
        for at, pull in enumerate(ranked):
            number = pull["number"]
            if states[number] != judge.GREEN:
                self.blocked.pop(number, None)
                continue
            # One `main`'s red holds cannot go first: the fix must not wait on it.
            before = [p["number"] for p in ranked[:at] if states[p["number"]] != judge.HELD]
            if self.waits(number, order.blocker(number, before, clashes), now):
                continue
            if self.land(pull, [p["number"] for p in ranked if p["number"] != number]):
                return True
        return False

    def waits(self, number: int, ahead: int | None, now: datetime) -> bool:
        """Whether a green one keeps waiting for `ahead`, which conflicts and goes first."""
        if ahead is None:
            self.blocked.pop(number, None)
            return False
        if self.blocked.get(number, (now, ahead))[1] != ahead:
            self.blocked.pop(number)  # a new blocker starts a new wait
        since, _ = self.blocked.setdefault(number, (now, ahead))
        if order.still_waits(since, now):
            self.narrate(number, f"green; waits for #{ahead}, which goes first and conflicts.")
            return True
        talk.say(
            f"#{number}: green, and waited {order.BLOCKED_MINUTES} min for #{ahead}; goes first."
        )
        self.blocked.pop(number, None)
        return False

    def clashes(self, line: list[dict]) -> set[frozenset[int]]:
        pairs = set()
        for one, other in combinations(line, 2):
            if self.clone.conflicts(one["head"], other["head"]) is not None:
                pairs.add(frozenset((one["number"], other["number"])))
        return pairs

    def land(self, pull: dict, others: list[int]) -> bool:
        """Merge it, then its aftermath. True when `main` moved."""
        number, head = pull["number"], pull["head"]
        if self.dry:
            # A real pass ends at its merge, since `main` moved; so does this one.
            talk.say(f"#{number}: would merge {head[:7]} into `{repo.BASE}`.")
            self.merged.append(number)
            for line in self.after.run(pull)[1]:
                talk.say(f"#{number}: {line}")
            return True
        ok, why = self.hub.merge(number, head)
        if ok is None:
            self.narrate(number, why)
            return False
        if not ok:
            # Out of line until its head or `main` moves: retried every pass, it
            # would also hold every pull request that conflicts with it.
            self.refused[number] = (f"{head} {self.clone.main}", why)
            self.hand_back(pull, [why])
            return False
        # Recorded before the aftermath: a merge is done whatever follows it.
        self.merged.append(number)
        self.ended.add(number)
        self.handed.pop(number, None)
        self.in_line.pop(number, None)
        self.memory.forget(number)
        self.memory.passed_over(others)
        self.memory.save()
        talk.say(f"merged #{number}: {pull.get('title', '')}")
        settled, lines = self.after.run(pull)
        if not settled:
            keep = ("number", "branch", "head_repo", "base_repo")
            self.memory.unsettled[str(number)] = {key: pull.get(key) for key in keep}
        for line in lines:
            talk.say(f"#{number}: {line}")
        self.memory.save()
        return True

    def settle(self) -> None:
        """Clean up after the merges GitHub had not confirmed when they were made."""
        for key, pull in list(self.memory.unsettled.items()):
            merged = None if self.dry else self.hub.merged(pull["number"])
            if merged is None:
                continue  # unasked, or GitHub did not answer: next pass
            del self.memory.unsettled[key]
            lines = self.after.cleanup(pull) if merged else ["GitHub says it did not merge."]
            for line in lines:
                talk.say(f"#{key}: {line}")

    # -- the loops -----------------------------------------------------------

    def queued(self) -> list[dict]:
        """Every open pull request into `main` labelled for the queue, read whole."""
        listed = self.hub.open_pulls(repo.BASE)
        return [self.hub.pull(p["number"]) for p in listed if self.opts.label in p["labels"]]

    def watch(self) -> None:
        """Take the labelled pull requests as they come, until `--for` runs out."""
        stop = time.monotonic() + self.opts.watch_for * 60
        talk.say(f"watching `{self.opts.label}` pull requests for {self.opts.watch_for:g} min.")
        while True:
            pulls = self.queued()
            listed = {p["number"] for p in pulls}
            for key in list(self.memory.first_seen):
                if int(key) not in listed:
                    self.memory.forget(int(key))
            self.in_line = {n: why for n, why in self.in_line.items() if n in listed}
            self.clone.fetch([p["head"] for p in pulls])
            moved = self.sweep(pulls)
            if not self.dry:
                self.memory.save()
            if self.dry or time.monotonic() >= stop:
                return
            if not moved:
                time.sleep(self.opts.poll if self.in_line else IDLE_SECONDS)

    def named(self, numbers: list[int]) -> None:
        """The pull requests named, label or not, until each merged or was handed back."""
        stop = time.monotonic() + self.opts.watch_for * 60
        left = list(dict.fromkeys(numbers))
        while left:
            pulls = []
            for number in left:
                try:
                    pull = self.hub.pull(number)
                except talk.Refused as answer:
                    self.hand_back({"number": number, "head": ""}, [str(answer)])
                    continue
                if pull["state"] == "merged":
                    talk.say(f"#{number}: already merged.")
                    self.ended.add(number)
                    self.in_line.pop(number, None)
                elif pull["draft"]:
                    self.hand_back(pull, ["it is a draft; mark it ready first."])
                else:
                    pulls.append(pull)
            self.clone.fetch([p["head"] for p in pulls])
            moved = self.sweep(pulls)
            if not self.dry:
                self.memory.save()
            left = [n for n in left if n not in self.ended]
            if self.dry or time.monotonic() >= stop:
                return
            if left and not moved:
                time.sleep(self.opts.poll)
