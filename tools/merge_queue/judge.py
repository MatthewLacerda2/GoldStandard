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
6. **`main` is not red**, or the branch carries the fix (`main_gate.py`).

It decides and says nothing: the queue speaks.
"""

from __future__ import annotations

from tools import review_triggers
from tools.merge_queue import checks, closing, github, repo, review
from tools.merge_queue.main_gate import MainGate

DRAFT, HANDED, CONFLICT, PENDING, HELD, GREEN = (
    "draft",
    "handed back",
    "conflict",
    "pending",
    "held",
    "green",
)


class Judge:
    def __init__(self, hub: github.GitHub, clone: repo.Clone, gate: MainGate) -> None:
        self.hub, self.clone, self.gate = hub, clone, gate
        self.labels: dict[int, list[str]] = {}  # the pull request's and its issues'
        self.reviewed: set[str] = set()  # heads whose review record was found
        self.commits: dict[str, list[str]] = {}  # each head's commit messages

    def closing(self, pull: dict) -> list[str]:
        """Why what it closes may not be closed; empty when it may. Keeps the
        labels of the pull request and of the issues it closes, for the order."""
        repo_name = self.hub.repo
        described = set(closing.closes(pull["body"], repo_name))
        committed = set(closing.closes("\n".join(self.messages(pull)), repo_name))
        closed = {number: self.hub.issue(number) for number in sorted(described | committed)}
        self.labels[pull["number"]] = [
            *pull.get("labels", []),
            *(label for item in closed.values() for label in closing.labels(item)),
        ]
        refused = closing.refusal(closed, frozenset(committed - described))
        return refused or closing.unnamed(pull["branch"], pull["body"], repo_name)

    def messages(self, pull: dict) -> list[str]:
        """The branch's commit messages, asked once per head."""
        if pull["head"] not in self.commits:
            self.commits[pull["head"]] = self.hub.commit_messages(pull["number"])
        return self.commits[pull["head"]]

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
        runs = self.hub.check_runs(pull["head"])
        result = checks.head(self.gate.required, runs, waited)
        if result.state in (checks.RED, checks.NO_RUN):
            return HANDED, result.lines
        if result.state == checks.PENDING:
            return PENDING, result.lines
        held = self.gate.holds(pull["head"], runs)
        return (HELD, held) if held else (GREEN, result.lines)
