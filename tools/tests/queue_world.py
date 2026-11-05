"""GitHub and the clone as the merge queue sees them, in memory, for the suites
that run its passes (`test_merge_queue_queue.py`) without a network or a repo."""

from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime, timedelta

from tools.merge_queue import checks, judge
from tools.merge_queue.queue import Queue
from tools.merge_queue.state import Memory

CI_OK = checks.Required("CI ok", 15368)
ACTIONS = 15368


def check_run(
    conclusion="success", status="completed", run_id=1, name="CI ok", app=ACTIONS, suite=1
):
    return {
        "id": run_id,
        "check_suite": {"id": suite},
        "name": name,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "app": {"id": app},
        "html_url": f"https://github.com/o/r/actions/runs/{run_id}/job/{run_id}",
        "details_url": f"https://github.com/o/r/actions/runs/{run_id}/job/{run_id}",
    }


def pull_request(number, created="2026-10-01T00:00:00Z", **fields):
    record = {
        "number": number,
        "title": f"t{number}",
        "url": f"u{number}",
        "state": "open",
        "draft": False,
        "head": f"{number:x}".rjust(40, "a"),
        "branch": f"feat/x{number}",
        "head_repo": "o/r",
        "base": "main",
        "base_repo": "o/r",
        "body": "",
        "author": "dev",
        "assignees": [],
        "labels": [],
        "created_at": created,
        "additions": 10,
        "mergeable": True,
    }
    return {**record, **fields}


class FakeHub:
    """GitHub: each head's check runs, each PR's comments, the issues, the merges."""

    def __init__(self) -> None:
        self.repo = "o/r"
        self.pulls: dict[int, dict] = {}
        self.issues: dict[int, dict] = {}
        self.notes: dict[int, list[tuple[str, str]]] = {}
        self.messages: dict[int, list[str]] = {}
        self.runs: dict[str, list[dict]] = {}
        self.merges: list[int] = []
        self.refusing: set[int] = set()
        self.reran: list[int] = []

    def pull(self, number):
        return self.pulls[number]

    def open_pulls(self, base):
        return [p for p in self.pulls.values() if p["state"] == "open" and p["base"] == base]

    def issue(self, number):
        return self.issues.get(number, {"number": number, "state": "open", "labels": []})

    def comments(self, number):
        return self.notes.get(number, [])

    def commit_messages(self, number):
        return self.messages.get(number, [])

    def check_runs(self, sha):
        return self.runs.get(sha, [])

    def rerun_failed(self, run):
        self.reran.append(run)

    def merged(self, number):
        return number in self.merges

    def merge(self, number, sha):
        if number in self.refusing:
            return False, "GitHub refused the merge: Pull Request is not mergeable"
        self.merges.append(number)
        return True, ""

    def delete_branch(self, branch):
        return f"remote branch `{branch}` deleted."

    def green(self, *pulls):
        for pull in pulls:
            self.runs[pull["head"]] = [check_run()]


class FakeClone:
    """The clone: `clashes` holds the pairs of heads that conflict."""

    def __init__(self) -> None:
        self.root, self.main = "/nowhere", "f" * 40
        self.clashes: set[frozenset[str]] = set()
        self.paths: dict[str, list[str]] = {}
        self.rebases: dict[str, str] = {}  # head -> the head a clean rebase gives
        self.holds: set[tuple[str, str]] = set()  # (head, commit) pairs where head has it
        self.same: set[frozenset[str]] = set()  # pairs of heads with the same change
        self.history: list[str] = [self.main]  # `main`'s first parents, newest first
        self.pushed: list[str] = []

    def fetch(self, heads):
        pass

    def changed(self, head):
        return self.paths.get(head, ["backend/services/x.py"])

    def backend_diff(self, head):
        return ""

    def package_sides(self, head):
        return None, None

    def same_change(self, one, other):
        return one == other or frozenset((one, other)) in self.same

    def conflicts(self, one, other):
        return ["backend/x.py"] if frozenset((one, other)) in self.clashes else None

    def contains(self, head, sha):
        return (head, sha) in self.holds

    def main_commits(self):
        return self.history

    def rebase(self, branch, head, push):
        if head in self.rebases:
            if push:
                self.pushed.append(branch)
            return self.rebases[head], []
        return None, [
            "it conflicts with `main` in `backend/x.py`: resolve it on the branch and push."
        ]


def make_queue(hub, clone, watch=False, dry_run=False, memory=None) -> Queue:
    opts = Namespace(watch=watch, dry_run=dry_run, label="queue", poll=0, watch_for=1, prs=[])
    memory = memory or Memory(None)
    gate = judge.MainGate(hub, clone, [CI_OK], memory, dry_run)
    queue = Queue(opts, hub, clone, memory, judge.Judge(hub, clone, gate))
    queue.after.run = lambda pull: (pull["number"] in hub.merges, ["cleaned."])
    queue.after.cleanup = lambda pull: ["cleaned later."]
    return queue


def long_ago(memory: Memory, number: int, head: str, minutes: int = 10) -> None:
    """Mark a head as seen `minutes` ago, past the grace a fresh push gets."""
    stamp = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(timespec="seconds")
    memory.first_seen[str(number)] = {"line": stamp, "head": head, "at": stamp}
