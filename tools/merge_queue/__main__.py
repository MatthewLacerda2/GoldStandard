"""`make queue` / `make mergeable`: the command line, the lock, the exit status.

    make queue PRS="12 14"               # these, label or not, until merged or handed back
    make queue ARGS=--watch              # the `queue`-labelled ones, for --for minutes
    make queue ARGS="--watch --dry-run"  # one read-only pass: what it would do
    make mergeable PR=12                 # may it merge now? read-only, no grace

Exit status, the most urgent thing to read about the run:

- **0** nothing to read: merged, or still in line (the `resume:` line restarts it);
- **1** something was handed back (`grep 'HANDED BACK'` the output);
- **3** GitHub, the network or this machine failed: nothing was decided, so run
  the same command again;
- **4** another queue holds this repository's lock: nothing was attempted;
- **5** GitHub or the remote refused the credentials (an expired token, a
  revoked key): renew them, then run it again; retrying would not help.

`make mergeable` answers 0 when the pull request may merge now, 1 when not.
"""

from __future__ import annotations

import argparse
import sys

from tools.merge_queue import checks, github, judge, repo, talk
from tools.merge_queue.queue import Queue
from tools.merge_queue.state import LOCK, STATE, Held, Memory, acquire

LABEL = "queue"
# A watch takes new pull requests for this long by default. A background
# command in an agent session is stopped at two hours, and the watch must end
# on its own well before.
FOR_MINUTES = 70
CAP_MINUTES = 110
POLL_SECONDS = 30
HANDED_STATUS, DOWN_STATUS, LOCKED_STATUS, AUTH_STATUS = 1, 3, 4, 5
# `make` turns any failing recipe into its own status 2, so the status is also
# said in words, on the line before the last.
MEANING = {
    0: "nothing to read",
    HANDED_STATUS: "something was handed back",
    DOWN_STATUS: "GitHub, the network or this machine failed; run it again",
    LOCKED_STATUS: "another queue holds the lock; nothing was attempted",
    AUTH_STATUS: "the credentials were refused; renew them, then run it again",
}


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="make queue", description=__doc__.split("\n\n")[0])
    parser.add_argument("prs", metavar="PR", type=int, nargs="*", help="pull requests to merge")
    parser.add_argument("--watch", action="store_true", help="take the labelled ones as they come")
    parser.add_argument(
        "--for",
        dest="watch_for",
        type=float,
        default=FOR_MINUTES,
        metavar="MINUTES",
        help=f"stop after this long (default {FOR_MINUTES})",
    )
    parser.add_argument("--dry-run", action="store_true", help="one pass that only reads")
    parser.add_argument("--label", default=LABEL, help="the go-ahead label")
    parser.add_argument("--poll", type=float, default=POLL_SECONDS, help="seconds between passes")
    parser.add_argument("--mergeable", type=int, metavar="PR", help="judge one PR, read-only")
    parser.add_argument("--root", default=".", help="the checkout to work from")
    opts = parser.parse_args(argv)
    if opts.mergeable is not None and (opts.prs or opts.watch):
        parser.error("--mergeable judges one pull request on its own.")
    if opts.mergeable is None and opts.watch == bool(opts.prs):
        parser.error('name pull requests (PRS="a b") or pass --watch, not both or neither.')
    if not 0 < opts.watch_for <= CAP_MINUTES:
        parser.error(f"--for must be between 0 and {CAP_MINUTES} minutes.")
    opts.dry_run = opts.dry_run or opts.mergeable is not None
    return opts


def resume(opts: argparse.Namespace, queue: Queue) -> str:
    """The command that carries on where this run stopped; empty when nothing is left.

    A named run resumes every name whose turn is not over, not only those
    already in line, which is empty when GitHub fails on the first pass.
    """
    if opts.watch:
        return f'watch: resume: make queue ARGS="--watch --for {opts.watch_for:g}"'
    left = [n for n in dict.fromkeys(opts.prs) if n not in queue.ended]
    return f'queue: resume: make queue PRS="{" ".join(map(str, left))}"' if left else ""


def mergeable(hub: github.GitHub, clone: repo.Clone, judged: judge.Judge, number: int) -> int:
    """May `number` merge now? Every question the queue asks before it merges,
    with no grace for a run still to appear and nothing done about the answer."""
    pull = hub.pull(number)
    clone.fetch([pull["head"]])
    state, lines = judged.assess(pull, waited=float("inf"))
    if state == judge.CONFLICT:
        lines = [*lines, "The queue would rebase it onto `main` and wait for CI on the new head."]
    yes = state == judge.GREEN
    talk.say(f"mergeable #{number}: {'yes' if yes else 'no'}", *lines)
    return 0 if yes else HANDED_STATUS


def report(queue: Queue) -> None:
    """The run in three lines: merged, handed back, still in line."""
    merged = ", ".join(f"#{n}" for n in queue.merged) or "none"
    handed = "; ".join(f"#{n} ({why})" for n, why in queue.handed.items()) or "none"
    waiting = "; ".join(f"#{n} ({why})" for n, why in sorted(queue.in_line.items())) or "none"
    talk.say(f"summary: merged {merged}.", f"handed back: {handed}", f"still in line: {waiting}")


def run(opts: argparse.Namespace) -> tuple[int, str]:
    """The run's exit status, and its `resume:` line (empty when there is none)."""
    clone = repo.Clone(opts.root)
    writes = not opts.dry_run
    try:
        held = acquire(clone.common_dir() / LOCK) if writes else None  # noqa: F841 (kept)
    except Held as busy:
        talk.say(str(busy))
        return LOCKED_STATUS, ""
    queue = None
    try:
        hub = github.GitHub(clone.repository())
        clone.fetch([])
        required = checks.required(clone.ruleset())
        memory = Memory(clone.common_dir() / STATE if writes else None)
        judged = judge.Judge(hub, clone, judge.MainGate(hub, clone, required, memory, opts.dry_run))
        if opts.mergeable is not None:
            return mergeable(hub, clone, judged, opts.mergeable), ""
        queue = Queue(opts, hub, clone, memory, judged)
        queue.watch() if opts.watch else queue.named(opts.prs)
    except talk.AuthFailed as refused:
        talk.say(f"stopped: {refused}", "The credentials were refused; renew them first.")
        return AUTH_STATUS, stopped(opts, queue)
    except (talk.Unreachable, talk.MachineDown) as down:
        talk.say(f"stopped: {down}", "Nothing was decided past this point; run it again.")
        return DOWN_STATUS, stopped(opts, queue)
    except (talk.Refused, ValueError) as answer:
        if opts.mergeable is not None:
            talk.say(f"mergeable #{opts.mergeable}: no", str(answer))
            return HANDED_STATUS, ""
        talk.say(f"stopped: {answer}", "Nothing was decided past this point.")
        return DOWN_STATUS, stopped(opts, queue)
    report(queue)
    last = "" if opts.dry_run else resume(opts, queue)
    return (HANDED_STATUS if queue.handed else 0), last


def stopped(opts: argparse.Namespace, queue: Queue | None) -> str:
    """The report and the `resume:` line of a run that stopped on a failure."""
    if queue is None:
        return ""
    report(queue)
    return "" if opts.dry_run else resume(opts, queue)


def main(argv: list[str] | None = None) -> int:
    opts = parse(sys.argv[1:] if argv is None else argv)
    status, last = run(opts)
    meaning = MEANING[status]
    if opts.mergeable is not None and status in (0, HANDED_STATUS):
        meaning = "it may merge now" if status == 0 else "it may not merge now"
    talk.say(f"exit {status}: {meaning}.")
    if last:
        print(last, flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
