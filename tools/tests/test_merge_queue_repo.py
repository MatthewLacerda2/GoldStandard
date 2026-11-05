"""`tools/merge_queue/repo.py` and `aftermath.py` against real git: a bare
`origin` and a clone of it in a temporary directory, no network."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.merge_queue import aftermath, repo, talk


def git(cwd: Path, *args: str) -> str:
    who = ("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false")
    done = subprocess.run(["git", *who, *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


class Clone(unittest.TestCase):
    def setUp(self) -> None:
        place = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.origin, self.work = place / "origin.git", place / "work"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.origin)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.work)], check=True)
        git(self.work, "remote", "add", "origin", str(self.origin))
        self.commit("a.txt", "one\ntwo\nthree\n", "base")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        git(self.work, "fetch", "-q", "origin")
        self.clone = repo.Clone(str(self.work))

    def commit(self, name: str, text: str, message: str) -> str:
        (self.work / name).write_text(text)
        git(self.work, "add", name)
        git(self.work, "commit", "-q", "-m", message)
        return git(self.work, "rev-parse", "HEAD")

    def branch(self, name: str, file: str, text: str) -> str:
        git(self.work, "checkout", "-q", "-b", name, "origin/main")
        head = self.commit(file, text, name)
        git(self.work, "push", "-q", "origin", f"HEAD:{name}")
        git(self.work, "checkout", "-q", "--detach", "origin/main")
        return head

    def advance_main(self, file: str, text: str) -> str:
        git(self.work, "checkout", "-q", "--detach", "origin/main")
        sha = self.commit(file, text, "main moves")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        return sha

    def test_changed_paths_and_conflicts(self) -> None:
        one = self.branch("one", "a.txt", "ONE\ntwo\nthree\n")
        two = self.branch("two", "a.txt", "uno\ntwo\nthree\n")
        three = self.branch("three", "b.txt", "new\n")
        self.clone.fetch([])
        self.assertEqual(self.clone.changed(one), ["a.txt"])
        self.assertEqual(self.clone.conflicts(one, two), ["a.txt"])
        self.assertIsNone(self.clone.conflicts(one, three))

    def test_a_clean_rebase_is_pushed_with_a_lease_and_keeps_the_change(self) -> None:
        head = self.branch("feat", "b.txt", "new\n")
        broke = self.advance_main("c.txt", "main\n")
        self.clone.fetch([])
        self.assertFalse(self.clone.contains(head, broke))
        fresh, lines = self.clone.rebase("feat", head, push=True)
        self.assertEqual(lines, [])
        assert fresh is not None
        self.assertEqual(git(self.origin, "rev-parse", "feat"), fresh)
        self.assertTrue(self.clone.contains(fresh, broke))
        self.assertTrue(self.clone.same_change(head, fresh))
        self.assertEqual(git(self.work, "worktree", "list").count("\n"), 0)  # thrown away

    def test_a_conflicting_rebase_names_the_paths_and_pushes_nothing(self) -> None:
        head = self.branch("feat", "a.txt", "ONE\ntwo\nthree\n")
        self.advance_main("a.txt", "uno\ntwo\nthree\n")
        self.clone.fetch([])
        self.assertEqual(self.clone.conflicts(self.clone.main, head), ["a.txt"])
        fresh, lines = self.clone.rebase("feat", head, push=True)
        self.assertIsNone(fresh)
        self.assertIn("`a.txt`", lines[0])
        self.assertEqual(git(self.origin, "rev-parse", "feat"), head)

    def test_whitespace_is_part_of_the_change(self) -> None:
        # Dedenting a guarded call out of its loop changes what it does; a
        # whitespace-blind comparison would keep the old review record valid.
        guarded = self.branch("guarded", "g.py", "for x in xs:\n    grant(x)\n")
        dedented = self.branch("dedented", "g.py", "for x in xs:\n    pass\ngrant(x)\n")
        self.clone.fetch([])
        self.assertFalse(self.clone.same_change(guarded, dedented))
        once = self.branch("once", "g.py", "for x in xs:\ngrant(x)\n")
        self.assertFalse(self.clone.same_change(guarded, once))

    def test_a_rebase_that_moves_the_lines_keeps_the_change(self) -> None:
        head = self.branch("feat", "a.txt", "one\ntwo\nTHREE\n")
        self.advance_main("a.txt", "zero\none\ntwo\nthree\n")  # shifts the hunk
        self.clone.fetch([])
        fresh, _ = self.clone.rebase("feat", head, push=False)
        assert fresh is not None
        self.assertTrue(self.clone.same_change(head, fresh))

    def test_a_changed_change_is_not_the_same(self) -> None:
        head = self.branch("feat", "b.txt", "new\n")
        other = self.branch("other", "b.txt", "different\n")
        self.clone.fetch([])
        self.assertFalse(self.clone.same_change(head, other))

    def test_main_first_parents_and_the_ruleset(self) -> None:
        newest = self.advance_main("c.txt", "x\n")
        self.clone.fetch([])
        self.assertEqual(self.clone.main_commits()[0], newest)
        with self.assertRaises(talk.Refused):
            self.clone.ruleset()  # this `main` has no ruleset file

    def test_the_worktree_of_a_merged_branch_is_freed_only_when_clean(self) -> None:
        head = self.branch("feat", "b.txt", "new\n")
        git(self.work, "push", "-q", "origin", f"{head}:main")  # as if merged
        wt = self.work.parent / "wt"
        git(self.work, "worktree", "add", "-q", str(wt), "feat")
        after = aftermath.Aftermath(hub=None, root=str(self.work), dry=False)
        (wt / "dirty.txt").write_text("work in flight\n")
        self.assertIn("uncommitted", after.worktrees({"branch": "feat"})[0])
        (wt / "dirty.txt").unlink()
        lines = after.worktrees({"branch": "feat"})
        self.assertIn("removed", lines[0])
        self.assertFalse(wt.exists())
        self.assertIn("local branch `feat` deleted.", lines)


if __name__ == "__main__":
    unittest.main()
