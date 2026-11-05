"""Where this repository's Claude Code tokens go: a report for the developer, run by hand.

    make claude-usage SINCE=2026-10-05
    python3.14 -m tools.claude_usage --since 2026-10-05 [--no-prs]

Reads the Claude Code transcripts of this repository on THIS machine (the main
checkout, every worktree, and the subagents of each session) and prints:

- **main session against subagents, each by role and by model:** the API calls
  (turns), the context they carried, the mean and the largest context per turn,
  the output, and each row's share of all the context;
- **context per merged pull request:** the pull requests merged in the window,
  each with the context of the calls tied to it, what no pull request owns, and
  the plain average (all the context over the number merged).

``tools/claude_transcripts.py`` says how calls are counted and roles found;
``tools/claude_prs.py`` says how a call is tied to a pull request.

**What it cannot see.** Only this machine's local transcripts: no cloud
session, no other computer (their pull requests still count, their tokens do
not, so the average runs low when work happened elsewhere). And nothing about
the account's plan limits (the 5-hour and weekly ones), which are not exposed:
this estimates where the spend goes, not the number a limit counts.

It is a signal for the developer, never a gate: it is not in ``make check`` or
CI, and no agent runs it during its work.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import partial
from pathlib import Path

from tools.claude_prs import GitHubUnavailable, PullRequest, Resolver, gh_page, merged_since
from tools.claude_transcripts import Call, collect, project_folders, transcript_files

PROJECTS = Path.home() / ".claude" / "projects"
NOT_SEEN = "Not seen: cloud sessions, other machines, and the account's plan limits."


@dataclass
class Row:
    turns: int = 0
    context: int = 0
    max_context: int = 0
    output: int = 0

    def add(self, call: Call) -> None:
        self.turns += 1
        self.context += call.context
        self.max_context = max(self.max_context, call.context)
        self.output += call.output


def repo_root() -> Path:
    """The main checkout, even when run from a worktree: transcripts are kept
    by working directory, and every worktree's folder is named after it."""
    here = Path(__file__).resolve().parents[1]
    run = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=here,
        capture_output=True,
        text=True,
    )
    return Path(run.stdout.strip()).parent if run.returncode == 0 else here


def summarise(calls: Iterable[Call]) -> dict[tuple[str, str, str], Row]:
    rows: dict[tuple[str, str, str], Row] = {}
    for call in calls:
        rows.setdefault((call.scope, call.role, call.model), Row()).add(call)
    return dict(sorted(rows.items(), key=lambda kv: (kv[0][0] != "main", -kv[1].context)))


def human(n: float) -> str:
    for size, unit in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(n) >= size:
            return f"{n / size:.1f}{unit}"
    return f"{n:.0f}"


def table(head: tuple[str, ...], body: list[tuple[str, ...]], align: str) -> list[str]:
    """Aligned columns, `align` holding one `<` (left) or `>` (right) per column."""
    widths = [max(len(row[i]) for row in [head, *body]) for i in range(len(head))]
    fmt = "  ".join(f"{{:{a}{w}}}" for a, w in zip(align, widths, strict=True))
    return [fmt.format(*row).rstrip() for row in [head, *body]]


def render_usage(rows: dict[tuple[str, str, str], Row]) -> list[str]:
    head = ("scope", "role", "model", "turns", "context", "ctx/turn", "max ctx", "output", "share")
    total = sum(r.context for r in rows.values()) or 1

    def line(scope: str, role: str, model: str, part: list[Row]) -> tuple[str, ...]:
        ctx, turns = sum(r.context for r in part), sum(r.turns for r in part)
        return (
            scope,
            role,
            model,
            str(turns),
            human(ctx),
            human(ctx / turns),
            human(max(r.max_context for r in part)),
            human(sum(r.output for r in part)),
            f"{100 * ctx / total:.0f}%",
        )

    body = [line(scope, role, model, [r]) for (scope, role, model), r in rows.items()]
    for scope in ("main", "subagent"):
        if part := [r for k, r in rows.items() if k[0] == scope]:
            body.append(line(scope, "(all)", "", part))
    return table(head, body, align="<<<>>>>>>")


def render_prs(calls: list[Call], prs: list[PullRequest] | str) -> list[str]:
    total = sum(c.context for c in calls)
    if isinstance(prs, str):
        return [f"Context per merged pull request: unknown ({prs})."]
    if not prs:
        return ["Context per merged pull request: no pull request merged in the window."]
    resolver = Resolver(prs)
    owned: dict[int, Row] = {pr.number: Row() for pr in prs}
    loose = Row()
    for call in calls:
        pr = resolver.owner(call.refs, call.branch, call.time)
        (owned[pr.number] if pr else loose).add(call)
    head = ("pull request", "turns", "context", "title")
    body = []
    for pr in sorted(prs, key=lambda p: p.number):
        row = owned[pr.number]
        body.append((f"#{pr.number}", str(row.turns), human(row.context), pr.title[:60]))
    body.append(("(none)", str(loose.turns), human(loose.context), "not tied to one merged PR"))
    return [
        "Context per merged pull request:",
        *table(head, body, align="<>><"),
        f"Average: {human(total / len(prs))} per merged PR ({human(total)} over {len(prs)}).",
    ]


def render(calls: list[Call], since: str, prs: list[PullRequest] | str) -> str:
    lines = [
        f"Claude Code usage since {since} (UTC), this machine's local transcripts only",
        "",
        *render_usage(summarise(calls)),
        "",
        *render_prs(calls, prs),
        NOT_SEEN,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="make claude-usage",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    default_since = (datetime.now(UTC).date() - timedelta(days=7)).isoformat()
    parser.add_argument(
        "--since",
        default=default_since,
        type=lambda s: date.fromisoformat(s).isoformat(),
        help="first day of the window, YYYY-MM-DD (UTC; default: 7 days ago)",
    )
    parser.add_argument(
        "--projects",
        type=Path,
        default=PROJECTS,
        help="Claude Code's projects folder (default: %(default)s)",
    )
    parser.add_argument(
        "--repo", type=Path, default=None, help="the checkout to report on (default: this one)"
    )
    parser.add_argument("--no-prs", action="store_true", help="skip GitHub (no gh call)")
    args = parser.parse_args(argv)
    repo = args.repo.resolve() if args.repo else repo_root()
    folders = project_folders(args.projects, repo)
    calls = collect(transcript_files(folders, args.since), args.since)
    if not calls:
        print(f"No Claude Code call since {args.since} in {args.projects} for this repository.")
        return 0
    prs: list[PullRequest] | str = "skipped by --no-prs"
    if not args.no_prs:
        try:
            prs = merged_since(args.since, fetch=partial(gh_page, cwd=repo))
        except GitHubUnavailable as exc:
            prs = str(exc)
    print(render(calls, args.since, prs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
