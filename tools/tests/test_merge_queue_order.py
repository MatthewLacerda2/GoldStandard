"""`tools/merge_queue/order.py`: who goes first, and `CLAUDE.md`'s priority as
the queue reads it."""

from __future__ import annotations

import re
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tools.merge_queue import order

CLAUDE = Path(__file__).resolve().parents[2] / "CLAUDE.md"
NOW = datetime(2026, 10, 1, tzinfo=UTC)


def pulls(*numbers: int) -> list[dict]:
    return [{"number": n, "created_at": f"2026-10-{n:02d}"} for n in numbers]


class Priority(unittest.TestCase):
    def test_it_is_claude_md_s(self) -> None:
        found = re.search(r"\*\*Priority(.*?)\*\*", CLAUDE.read_text(), re.DOTALL)
        assert found is not None, "CLAUDE.md has no **Priority** line"
        named = re.findall(r"`(\w+)`", found.group(1))
        self.assertEqual(tuple(named[:-1]), order.PRIORITY)
        self.assertEqual(named[-1], order.ANY_TIME)

    def test_the_most_urgent_label_decides(self) -> None:
        self.assertEqual(order.tier(["feat", "fix"]), order.PRIORITY.index("fix"))
        self.assertEqual(order.tier(["feat", "documentation"]), 0)
        self.assertEqual(order.tier([]), len(order.PRIORITY))


class Order(unittest.TestCase):
    def test_fewest_conflicts_then_tier_then_oldest(self) -> None:
        clashes = {frozenset((1, 2)), frozenset((1, 3))}
        ranked = order.ordered(pulls(1, 2, 3, 4), clashes, {3: 0, 2: 1}, set())
        self.assertEqual([p["number"] for p in ranked], [4, 3, 2, 1])

    def test_an_overdue_one_goes_first_whatever_it_conflicts_with(self) -> None:
        ranked = order.ordered(pulls(1, 2), {frozenset((1, 2))}, {}, {2})
        self.assertEqual(ranked[0]["number"], 2)

    def test_overdue_by_age_or_by_passes(self) -> None:
        old = (NOW - timedelta(minutes=order.OVERDUE_MINUTES)).isoformat()
        self.assertTrue(order.overdue(old, 0, NOW))
        self.assertTrue(order.overdue(None, order.OVERDUE_PASSES, NOW))
        self.assertFalse(order.overdue(NOW.isoformat(), 0, NOW))

    def test_a_blocker_is_the_first_conflicting_one_ahead_and_the_wait_ends(self) -> None:
        self.assertEqual(order.blocker(3, [1, 2], {frozenset((2, 3))}), 2)
        self.assertIsNone(order.blocker(3, [1], {frozenset((2, 3))}))
        late = NOW + timedelta(minutes=order.BLOCKED_MINUTES)
        self.assertFalse(order.still_waits(NOW, late))


class ConflictPaths(unittest.TestCase):
    def test_merge_tree_output(self) -> None:
        tree = "a" * 40
        self.assertEqual(order.conflict_paths(1, f"{tree}\nb.py\na.py\n\nnotes"), ["a.py", "b.py"])
        self.assertIsNone(order.conflict_paths(0, f"{tree}\n"))
        self.assertIsNone(order.conflict_paths(1, "fatal: not a valid object"))


if __name__ == "__main__":
    unittest.main()
