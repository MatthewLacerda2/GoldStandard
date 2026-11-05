"""Which pull request goes first, and which one waits for which. Pure.

**Fewest conflicts first.** Reordering cannot make two conflicting pull
requests merge cleanly (whichever lands second still conflicts), but it
decides how many rebases a set costs: the broad change lands last and takes
the one rebase, instead of every small one that landed after it. Conflicts
are counted pairwise among the pull requests in line, with
`git merge-tree --write-tree` (no checkout, milliseconds).

**Then the priority of its labels** (`CLAUDE.md`, *Issues*: `infrastructure`
→ `architecture` → `fix` → `foundation` → `feat`; `documentation` never waits
its turn, so it ranks with the first), read from the pull request and from the
issues it closes, the most urgent one deciding. **Then the oldest.**

**Nothing starves**: one that has waited [`OVERDUE_MINUTES`] in line, or seen
[`OVERDUE_PASSES`] others merge ahead of it, goes first whatever it conflicts
with.

**The queue never sits on a pending run.** `main` needs neither an up-to-date
branch nor a serial wait, so a green pull request merges while others are
still running, unless one ahead of it in this order is still in line and
conflicts with it ([`blocker`]): merging it first would undo the order that
was chosen to save a rebase. That wait is bounded ([`still_waits`]).
"""

from __future__ import annotations

from datetime import datetime

# `CLAUDE.md`'s priority, most urgent first (a test holds the two together).
PRIORITY = ("infrastructure", "architecture", "fix", "foundation", "feat")
ANY_TIME = "documentation"
OVERDUE_MINUTES = 60
OVERDUE_PASSES = 3
# How long a green pull request waits for a conflicting one ahead that is still running.
BLOCKED_MINUTES = 30


def tier(labels: list[str]) -> int:
    """The priority of the most urgent label; unlabelled goes after `feat`."""
    ranks = [PRIORITY.index(label) for label in labels if label in PRIORITY]
    if ANY_TIME in labels:
        ranks.append(0)
    return min(ranks, default=len(PRIORITY))


def conflict_paths(status: int, output: str) -> list[str] | None:
    """The paths `git merge-tree --write-tree --name-only` reported in conflict.

    `None` when it merged cleanly or could not answer: exit 1 alone is not a
    conflict (git also says 1 for an object it cannot find); a conflict prints
    the merged tree's id first, then the paths, then a blank line.
    """
    first, *rest = output.split("\n")
    tree = first.strip()
    if status != 1 or len(tree) not in (40, 64) or any(c not in "0123456789abcdef" for c in tree):
        return None
    paths = rest[: rest.index("")] if "" in rest else rest
    return sorted({p for p in paths if p})


def overdue(first_seen: str | None, passes: int, now: datetime) -> bool:
    if passes >= OVERDUE_PASSES:
        return True
    if not first_seen:
        return False
    return (now - datetime.fromisoformat(first_seen)).total_seconds() / 60 >= OVERDUE_MINUTES


def ordered(
    pulls: list[dict], clashes: set[frozenset[int]], tiers: dict[int, int], late: set[int]
) -> list[dict]:
    """Overdue first, then fewest conflicts, then priority, then oldest."""
    numbers = {p["number"] for p in pulls}
    many = {n: sum(1 for pair in clashes if n in pair and pair <= numbers) for n in numbers}
    return sorted(
        pulls,
        key=lambda p: (
            p["number"] not in late,
            many[p["number"]],
            tiers.get(p["number"], len(PRIORITY)),
            p.get("created_at", ""),
            p["number"],
        ),
    )


def blocker(number: int, ahead: list[int], clashes: set[frozenset[int]]) -> int | None:
    """The first pull request ahead in line that conflicts with `number`, if any."""
    return next((n for n in ahead if frozenset((n, number)) in clashes), None)


def still_waits(since: datetime, now: datetime) -> bool:
    """Whether a green pull request blocked since `since` keeps waiting.

    A pending run has no deadline of its own, so the wait has one: past
    [`BLOCKED_MINUTES`] the green one goes first, and the conflict it causes is
    the other's rebase, a bounded cost where waiting on a stuck run is not.
    """
    return (now - since).total_seconds() < BLOCKED_MINUTES * 60
