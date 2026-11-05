"""Where one pull request stands: the questions the queue and `make mergeable` ask.

[`Judge.assess`] asks them in the order a fix is cheapest to make, so a
hand-back names the first thing to do:

1. **open, ready, into `main`**;
2. **what it closes may be closed** (`closing.py`), a description edit away;
3. **the review lane** (`review.py`): a pull request that hits a trigger
   (`tools/review_triggers.py`) has an `Independent review` record for its head;
4. **no conflict with `main`**: a conflicting branch gets no CI run at all, so
   this comes before CI. The queue then rebases it (`queue.Queue.rebase`);
5. **CI passed on the head** (`checks.head`);
6. **`main` is not red**, or the branch carries the fix ([`MainGate`]).

It decides and says nothing: the queue speaks.
"""

from __future__ import annotations

from collections.abc import Iterator

from tools import review_triggers
from tools.merge_queue import checks, closing, github, repo, review, talk
from tools.merge_queue.state import Memory

DRAFT, HANDED, CONFLICT, PENDING, HELD, GREEN = (
    "draft",
    "handed back",
    "conflict",
    "pending",
    "held",
    "green",
)
HELD_LINE = (
    "green, but `main` itself is red: it merges once `main` is green again, or now if"
    " its branch contains the commit that broke it (it then carries the fix, which"
    " its own green run proves)."
)
UNREAD = "green, but `main`'s own CI could not be read this pass; asked again on the next:"


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
        self.read: dict[str, list[dict]] = {}  # this pass's check runs, by commit

    def new_pass(self) -> None:
        self.reds, self.unread, self.read = None, "", {}

    def runs(self) -> Iterator[tuple[str, list[dict]]]:
        """`main`'s commits with their check runs, newest first, each asked once a pass."""
        for sha in self.clone.main_commits():
            if sha not in self.read:
                self.read[sha] = self.hub.check_runs(sha)
            yield sha, self.read[sha]

    def state(self) -> list[checks.Red]:
        """The required contexts red on `main`, a new red re-run once; said when
        it changes. A refusal is kept for the pass: it holds the green pull
        requests (it is `main`'s question, not theirs) and is asked again next."""
        if self.reds is not None or self.unread:
            return self.reds or []
        try:
            found = [checks.main_red(each, self.runs()) for each in self.required]
        except talk.Refused as answer:
            self.unread = str(answer)
            return []
        self.reds = [red for red in found if red is not None]
        for red in self.reds:
            self.rerun(red)
        said = " ".join(red.line() for red in self.reds)
        if said != self.said:
            if self.reds:
                talk.say("`main` is red:", *[red.line() for red in self.reds], HELD_LINE)
            elif self.said:
                talk.say("`main` is green again; the line moves.")
            self.said = said
        return self.reds

    def rerun(self, red: checks.Red) -> None:
        """Re-run a new red's failed jobs once, in case it is a runner's blip."""
        run = github.run_id(red.run)
        if red.rerunning or red.reran or run is None or run in self.memory.reruns:
            return
        if self.dry:
            talk.say(f"`main`: would re-run {red.context} once: {red.line()}")
            return
        self.memory.reruns.add(run)
        refused = self.hub.rerun_failed(run)
        talk.say(
            f"`main`: {red.line()}",
            f"could not re-run it: {refused}"
            if refused
            else "re-ran it once, in case it is a blip.",
        )

    def holds(self, head: str) -> list[str]:
        """Why `main`'s state holds this green head; empty when it does not."""
        reds = self.state()
        if self.unread:
            return [UNREAD, self.unread]
        try:
            why = [
                f"{red.line()}; this branch does not contain {red.first[:7]}."
                for red in reds
                if not self.clone.contains(head, red.first)
            ]
        except talk.Refused as answer:
            return [UNREAD, str(answer)]
        return [HELD_LINE, *why] if why else []


class Judge:
    def __init__(self, hub: github.GitHub, clone: repo.Clone, gate: MainGate) -> None:
        self.hub, self.clone, self.gate = hub, clone, gate
        self.labels: dict[int, list[str]] = {}  # the pull request's and its issues'
        self.reviewed: set[str] = set()  # heads whose review record was found

    def closing(self, pull: dict) -> list[str]:
        """Why what it closes may not be closed; empty when it may. Keeps the
        labels of the pull request and of the issues it closes, for the order."""
        numbers = closing.closes(pull["body"], self.hub.repo)
        closed = {number: self.hub.issue(number) for number in numbers}
        self.labels[pull["number"]] = [
            *pull.get("labels", []),
            *(label for item in closed.values() for label in closing.labels(item)),
        ]
        return closing.refusal(closed) or closing.unnamed(pull["branch"], pull["body"])

    def triggers(self, pull: dict) -> list[str]:
        head = pull["head"]
        paths = self.clone.changed(head)
        queries = review_triggers.querying(self.clone.backend_diff(head))
        package = review_triggers.PACKAGE in paths and review_triggers.gated(
            *self.clone.package_sides(head)
        )
        labels = self.labels.get(pull["number"], pull.get("labels", []))
        return review_triggers.hits(paths, pull.get("additions", 0), labels, queries, package)

    def review(self, pull: dict) -> list[str]:
        """Why its review lane is not satisfied; empty when it is (or it has none)."""
        head = pull["head"]
        if head in self.reviewed:
            return []
        hits = self.triggers(pull)
        if not hits:
            return []
        coders = {pull.get("author", ""), *pull.get("assignees", [])} - {""}
        named = review.records(self.hub.comments(pull["number"]), coders)
        ok, why = review.verdict(named, head, lambda sha: self.clone.same_change(sha, head))
        if ok:
            self.reviewed.add(head)
            return []
        return [*why, *(f"trigger: {hit}" for hit in hits)]

    def assess(self, pull: dict, waited: float) -> tuple[str, list[str]]:
        """Where it stands: DRAFT, HANDED, CONFLICT, PENDING, HELD or GREEN, and why.

        `waited` is how long the queue has watched this head, in seconds.
        """
        if pull["state"] != "open":
            return HANDED, [f"it is {pull['state']}."]
        if pull["draft"]:
            return DRAFT, ["it is a draft; the queue takes it once it is ready."]
        if pull["base"] != repo.BASE:
            return HANDED, [f"it targets `{pull['base']}`, not `{repo.BASE}`."]
        refused = self.closing(pull) or self.review(pull)
        if refused:
            return HANDED, refused
        clash = self.clone.conflicts(self.clone.main, pull["head"])
        if clash is not None or pull.get("mergeable") is False:
            where = ", ".join(f"`{p}`" for p in clash or []) or "files only GitHub sees"
            return CONFLICT, [f"it conflicts with `{repo.BASE}` in {where}."]
        result = checks.head(self.gate.required, self.hub.check_runs(pull["head"]), waited)
        if result.state in (checks.RED, checks.NO_RUN):
            return HANDED, result.lines
        if result.state == checks.PENDING:
            return PENDING, result.lines
        held = self.gate.holds(pull["head"])
        return (HELD, held) if held else (GREEN, result.lines)
