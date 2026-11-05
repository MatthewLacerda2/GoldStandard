"""`tools/review_triggers.py`: which changes owe an independent review, and that
the skill's *When* names no path the list misses."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tools import review_triggers
from tools.ci_paths import counts

SKILL = Path(__file__).resolve().parents[2] / ".claude/skills/independent-review/SKILL.md"


def hit(*paths: str, **more) -> list[str]:
    return [line.split(":")[0] for line in review_triggers.hits(list(paths), **more)]


def skill_paths() -> list[str]:
    """Every path the skill's *When* section names in backticks."""
    text = SKILL.read_text()
    when = text.split("\n## When\n", 1)[1].split("\n## ", 1)[0]
    tokens = re.findall(r"`([^`\s]+)`", when)
    return [t for t in tokens if "/" in t or re.search(r"\.\w+$", t) or t == "Makefile"]


class Triggers(unittest.TestCase):
    def test_each_trigger_by_its_paths(self) -> None:
        self.assertEqual(hit("backend/repositories/items.py"), ["database access"])
        self.assertEqual(hit("frontend/src/lib/schemas/items.ts"), ["the API contract"])
        self.assertEqual(hit("backend/api/endpoints.py"), ["auth"])
        self.assertEqual(hit(".github/workflows/ci.yml", "tools/x.py"), ["CI and the gates"])
        self.assertEqual(hit("frontend/tsconfig.app.json"), ["CI and the gates"])
        self.assertEqual(hit("frontend/scripts/contract/baseline.txt"), ["CI and the gates"])

    def test_everything_else_owes_nothing(self) -> None:
        self.assertEqual(
            hit("README.md", "frontend/src/routes/login.tsx", "backend/api/v1/x.py"), []
        )

    def test_a_query_outside_the_repositories_is_database_access(self) -> None:
        diff = (
            "diff --git a/backend/api/v1/x.py b/backend/api/v1/x.py\n"
            "+    rows = await session.execute(select(Item))\n"
            "diff --git a/backend/tests/t.py b/backend/tests/t.py\n"
            "+    await session.execute(select(Item))\n"
        )
        found = review_triggers.querying(diff)
        self.assertEqual(found, ["backend/api/v1/x.py"])
        self.assertEqual(hit("backend/api/v1/x.py", queries=found), ["database access"])

    def test_package_json_counts_only_when_a_gate_key_changes(self) -> None:
        old = json.dumps({"scripts": {"check": "tsc"}, "dependencies": {"a": "1"}})
        bump = json.dumps({"scripts": {"check": "tsc"}, "dependencies": {"a": "2"}})
        gate = json.dumps({"scripts": {"check": "true"}, "dependencies": {"a": "1"}})
        self.assertFalse(review_triggers.gated(old, bump))
        self.assertTrue(review_triggers.gated(old, gate))
        self.assertTrue(review_triggers.gated(None, old))
        package = review_triggers.PACKAGE
        self.assertEqual(hit(package, package_gated=True), ["CI and the gates"])
        self.assertEqual(hit(package), [])

    def test_a_refactor_is_its_label_or_its_size(self) -> None:
        self.assertEqual(hit("x.py", labels=["refactor"]), ["refactor"])
        self.assertEqual(hit("x.py", additions=review_triggers.REFACTOR_LINES + 1), ["refactor"])
        self.assertEqual(hit("x.py", additions=review_triggers.REFACTOR_LINES), [])


class TheSkill(unittest.TestCase):
    def test_every_path_its_when_names_is_a_trigger_here(self) -> None:
        paths = skill_paths()
        self.assertIn("backend/repositories/", paths)  # the section is still read
        patterns = [p for group in review_triggers.TRIGGERS.values() for p in group]
        for path in paths:
            probe = f"{path}probe.py" if path.endswith("/") else path
            self.assertTrue(counts(tuple(patterns), probe), f"{path} is in the skill, not here")

    def test_the_skill_points_here(self) -> None:
        self.assertIn("tools/review_triggers.py", SKILL.read_text())


class CommandLine(unittest.TestCase):
    def test_it_prints_the_triggers_or_says_none(self) -> None:
        self.assertEqual(review_triggers.main(["Makefile\n"]), "CI and the gates: Makefile")
        self.assertIn("no trigger", review_triggers.main(["README.md\n"]))


if __name__ == "__main__":
    unittest.main()
