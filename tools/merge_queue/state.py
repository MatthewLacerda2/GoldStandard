"""One queue at a time, and what a queue remembers between runs.

**The lock.** Two queues race each other's rebases, pushes and merges. So
every run that may write takes an exclusive `fcntl.flock` on [`LOCK`] in the
**common** git directory, which every worktree of the clone shares, and keeps
it until the process ends. It is one queue per **clone**: two clones of the
repository (two machines) do not see each other's lock. Between those the
merge is still pinned to the head it judged and the rebase is pushed with a
lease, so a race is refused rather than overwritten; run one queue per
repository all the same. The kernel drops it however the
process dies, so a crash leaves nothing stale. The holder writes its pid and
start time, so a second run refuses naming both.

**The memory** ([`STATE`], beside it). A watch ends after `--for` minutes and
is restarted with its `resume:` line, so what it knows must outlive it:

- `first_seen`: when the queue first saw each pull request (which ages it,
  `order.overdue`) and its current head (which gives a fresh push its grace
  for CI to show up, `checks.RUN_APPEARS_SECONDS`);
- `passes`: how many merges went ahead of each one in line;
- `said`: the last hand-back said for each one, with its head, so a watch
  does not say the same one again until something changes (a push, a new
  reason). A hand-back is not a removal: the queue keeps asking, and a pull
  request whose answer turns into a pass merges on its own;
- `reruns`: the runs the queue re-ran on `main`, so a red is re-run once;
- `unsettled`: merges GitHub had not confirmed yet, whose branch and worktree
  are cleaned up once it does.
"""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

LOCK = "merge-queue.lock"
STATE = "merge-queue.json"


class Held(Exception):
    """Another queue holds the lock; the message names it."""


def acquire(path: Path) -> IO[str]:
    """Take the lock, kept for as long as the returned file stays open."""
    handle = open(path, "a+", encoding="utf-8")  # noqa: SIM115 (held for the run)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        who = handle.read().strip() or "a queue that has not written its pid yet"
        handle.close()
        raise Held(
            f"another queue is already running on this clone (pid and start: {who})."
            " Let it finish, or stop that process, then run this again."
        ) from None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()} {datetime.now(UTC).isoformat(timespec='seconds')}\n")
    handle.flush()
    return handle


class Memory:
    """The queue's memory, read from and written back to [`STATE`]. `read_only`
    (`make mergeable`, a dry run) reads it, so a dry run sees the clocks the
    real queue keeps, and never writes it; `None` keeps it in this process only."""

    def __init__(self, path: Path | None, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        data: dict = {}
        if path is not None and path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except OSError, ValueError:
                data = {}
        self.first_seen: dict[str, dict] = data.get("first_seen", {})
        self.passes: dict[str, int] = data.get("passes", {})
        self.said: dict[str, str] = data.get("said", {})
        self.reruns: set[int] = set(data.get("reruns", []))
        self.unsettled: dict[str, dict] = data.get("unsettled", {})

    def seen(self, number: int, head: str, now: datetime) -> dict:
        """When this pull request was first in line (`line`), and when its head
        was first seen (`at`)."""
        entry = self.first_seen.get(str(number))
        stamp = now.isoformat(timespec="seconds")
        if entry is None:
            entry = {"line": stamp, "head": head, "at": stamp}
        elif entry.get("head") != head:
            entry = {**entry, "head": head, "at": stamp}
        self.first_seen[str(number)] = entry
        return entry

    def forget(self, number: int) -> None:
        """A pull request that left the line: merged, closed, or unlabelled."""
        for table in (self.first_seen, self.passes, self.said):
            table.pop(str(number), None)

    def passed_over(self, numbers: list[int]) -> None:
        for number in numbers:
            self.passes[str(number)] = self.passes.get(str(number), 0) + 1

    def first_time(self, number: int, head: str, reason: str) -> bool:
        """Whether this hand-back is news; remembers it when it is."""
        key, said = str(number), f"{head} {reason}"
        if self.said.get(key) == said:
            return False
        self.said[key] = said
        return True

    def save(self) -> None:
        if self.path is None or self.read_only:
            return
        data = {
            "first_seen": self.first_seen,
            "passes": self.passes,
            "said": self.said,
            "reruns": sorted(self.reruns),
            "unsettled": self.unsettled,
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=1), encoding="utf-8")
        temporary.replace(self.path)
