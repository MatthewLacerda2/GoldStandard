"""`tools/merge_queue/repo.py` and `aftermath.py` against real git: a bare
`origin` and a clone of it in a temporary directory, no network, and no git
config from this machine (`GIT_CONFIG_GLOBAL`, `GIT_CONFIG_NOSYSTEM`): a test
sets the config it means to test against."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import review_triggers
from tools.merge_queue import aftermath, repo, talk


def git(cwd: Path, *args: str) -> str:
    who = ("-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false")
    done = subprocess.run(["git", *who, *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


class Clone(unittest.TestCase):
    def setUp(self) -> None:
        hermetic = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        self.enterContext(mock.patch.dict(os.environ, hermetic))
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
        (self.work / name).parent.mkdir(parents=True, exist_ok=True)
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
        self.assertTrue(self.clone.covers(head, fresh))
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

    def test_a_rebase_that_moves_the_lines_is_still_covered(self) -> None:
        head = self.branch("feat", "a.txt", "one\ntwo\nTHREE\n")
        self.advance_main("a.txt", "zero\none\ntwo\nthree\n")  # shifts the hunk
        self.clone.fetch([])
        fresh, _ = self.clone.rebase("feat", head, push=False)
        assert fresh is not None
        self.assertTrue(self.clone.covers(head, fresh))

    def rebased_by_hand(self, branch: str, file: str, text: str) -> str:
        """`branch` remade on the current `main` by hand, its one file written as `text`."""
        git(self.work, "checkout", "-q", "-B", f"{branch}-2", "origin/main")
        return self.commit(file, text, "rebased by hand")

    def test_whitespace_in_an_existing_file_is_part_of_the_change(self) -> None:
        self.commit("g.py", "def a():\n    for x in xs:\n        pass\n", "g")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        loop = "def a():\n    for x in xs:\n        pass\n        grant(x)\n"
        reviewed = self.branch("guarded", "g.py", loop)
        self.advance_main("c.txt", "main moves\n")
        self.clone.fetch([])
        dedented = self.rebased_by_hand(
            "guarded", "g.py", loop.replace("        grant", "    grant")
        )
        self.assertFalse(self.clone.covers(reviewed, dedented))

    def test_the_same_line_in_another_function_is_another_change(self) -> None:
        two = "def a():\n    pass\n\n\ndef b():\n    pass\n"
        self.commit("f.py", two, "f")
        git(self.work, "push", "-q", "origin", "HEAD:main")
        in_b = two + "    check(user)\n"
        reviewed = self.branch("check", "f.py", in_b)
        self.clone.fetch([])
        in_a = two.replace("def a():\n    pass\n", "def a():\n    pass\n    check(user)\n")
        moved = self.rebased_by_hand("check", "f.py", in_a)
        self.assertFalse(self.clone.covers(reviewed, moved))

    def test_a_conflict_resolved_by_hand_is_another_change(self) -> None:
        reviewed = self.branch("feat", "a.txt", "ONE\ntwo\nthree\n")
        self.advance_main("a.txt", "uno\ntwo\nthree\n")
        self.clone.fetch([])
        resolved = self.rebased_by_hand("feat", "a.txt", "ONE uno\ntwo\nthree\n")
        self.assertFalse(self.clone.covers(reviewed, resolved))

    def test_a_binary_change_counts(self) -> None:
        reviewed = self.branch("blob", "logo.bin", "\x00\x01one")
        self.advance_main("c.txt", "main moves\n")
        self.clone.fetch([])
        fresh, _ = self.clone.rebase("blob", reviewed, push=False)
        assert fresh is not None
        self.assertTrue(self.clone.covers(reviewed, fresh))
        swapped = self.rebased_by_hand("blob", "logo.bin", "\x00\x01two")
        self.assertFalse(self.clone.covers(reviewed, swapped))

    def test_a_hostile_diff_config_still_shows_a_query(self) -> None:
        head = self.branch("q", "backend/repo.py", "rows = session.execute(select(Item))\n")
        for key, value in (("diff.noprefix", "true"), ("diff.external", "/usr/bin/true")):
            git(self.work, "config", key, value)
        git(self.work, "config", "diff.mnemonicPrefix", "true")
        git(self.work, "config", "color.ui", "always")
        self.clone.fetch([])
        diff = self.clone.backend_diff(head)
        self.assertEqual(review_triggers.querying(diff), ["backend/repo.py"])
        self.assertEqual(self.clone.changed(head), ["backend/repo.py"])

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

    def worktree_on_merged_feat(self) -> tuple[Path, aftermath.Aftermath]:
        head = self.branch("feat", "b.txt", "new\n")
        git(self.work, "push", "-q", "origin", f"{head}:main")  # as if merged
        wt = self.work.parent / "wt"
        git(self.work, "worktree", "add", "-q", str(wt), "feat")
        return wt, aftermath.Aftermath(hub=None, root=str(self.work), dry=False)

    def test_a_worktree_with_a_commit_main_lacks_is_kept(self) -> None:
        wt, after = self.worktree_on_merged_feat()
        (wt / "fix.txt").write_text("the fix the merge did not wait for\n")
        git(wt, "add", "fix.txt")
        git(wt, "commit", "-q", "-m", "unpushed fix")
        self.assertIn(
            "1 commit(s) `main` has no equivalent of", after.worktrees({"branch": "feat"})[0]
        )
        self.assertTrue(wt.exists())

    def test_a_locked_worktree_is_left_to_its_session(self) -> None:
        wt, after = self.worktree_on_merged_feat()
        git(self.work, "worktree", "lock", str(wt))
        lines = after.worktrees({"branch": "feat"})
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith(" kept: it is locked, by a session still using it."))
        self.assertTrue(wt.exists())

    def test_an_untracked_file_is_work_whatever_status_hides(self) -> None:
        wt, after = self.worktree_on_merged_feat()
        git(self.work, "config", "status.showUntrackedFiles", "no")
        (wt / "new.txt").write_text("nobody committed this yet\n")
        self.assertIn("uncommitted", after.worktrees({"branch": "feat"})[0])
        self.assertTrue((wt / "new.txt").exists())

    def test_a_worktree_gone_from_disk_is_said_not_crashed_on(self) -> None:
        wt, after = self.worktree_on_merged_feat()
        shutil.rmtree(wt)
        self.assertIn("gone from disk", after.worktrees({"branch": "feat"})[0])

    def test_a_forks_branch_name_is_not_this_clones(self) -> None:
        _, after = self.worktree_on_merged_feat()
        fork = {"branch": "feat", "head_repo": "someone/r", "base_repo": "o/r"}
        self.assertIn("fork", after.worktrees(fork)[0])
        self.assertIn("feat", git(self.work, "branch", "--list", "feat"))

    def test_a_rebase_that_fails_without_a_conflict_says_why(self) -> None:
        head = self.branch("feat", "b.txt", "new\n")
        self.advance_main("c.txt", "main moves\n")
        hooks = self.work.parent / "hooks"
        hooks.mkdir()
        (hooks / "pre-rebase").write_text("#!/bin/sh\necho 'refused by a hook' >&2\nexit 1\n")
        (hooks / "pre-rebase").chmod(0o755)
        git(self.work, "config", "core.hooksPath", str(hooks))
        self.clone.fetch([])
        fresh, lines = self.clone.rebase("feat", head, push=True)
        self.assertIsNone(fresh)
        self.assertIn("failed without a conflict: refused by a hook", lines[0])

    def test_the_rebase_signs_nothing(self) -> None:
        head = self.branch("feat", "b.txt", "new\n")
        self.advance_main("c.txt", "main moves\n")
        git(self.work, "config", "commit.gpgSign", "true")
        git(self.work, "config", "gpg.program", "/nonexistent/gpg")
        self.clone.fetch([])
        fresh, lines = self.clone.rebase("feat", head, push=False)
        self.assertEqual(lines, [])
        self.assertIsNotNone(fresh)


if __name__ == "__main__":
    unittest.main()
