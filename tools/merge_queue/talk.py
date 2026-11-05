"""Every command the queue runs, how a failure is read, and the one way it speaks.

A question to GitHub or the remote goes through [`api`] or [`git_net`], which
retry a failure **in transit** (a 5xx, a 429, a timeout, a reset connection, a
failed DNS lookup) for about three minutes before raising [`Unreachable`]: an
outage is not a verdict about any pull request, so the queue stops on it with
exit status 3 instead of handing branches back. Any other failure is GitHub
having answered (a 404, a 422) and is raised at once as [`Refused`], which the
queue reads as an answer about that one pull request.

**REST only.** [`api`] is the only way the queue reaches GitHub, and it runs
`gh api`: `gh pr` and `gh issue` are GraphQL underneath, which some proxies
(a cloud container's, for one) refuse. A test holds every module to it.

A write that may already have happened (the merge) never goes through the
retry, since retrying a merge is how one gets made twice: it uses [`once`] and
is asked about afterwards (`github.GitHub.merge`).
"""

from __future__ import annotations

import json
import re
import subprocess
import time

# `gh` says a REST status as "HTTP 502" (or "status code: 502"); a 429 is
# GitHub asking to be asked later.
TRANSPORT_STATUS = re.compile(r"(status code:|HTTP)\s*(5\d\d|429)\b", re.IGNORECASE)
TRANSPORT_WORDS = (
    "timeout",
    "timed out",
    "deadline exceeded",
    "connection reset",
    "connection refused",
    "broken pipe",
    "unexpected eof",
    "early eof",
    "no such host",
    "name resolution",
    "could not resolve host",
    "network is unreachable",
    "error connecting to",
    "unable to access",
    "tls handshake",
)
# git and gh saying the credentials were refused. "unable to access" (a
# transport word) also opens git's 401/403 message, so this is asked first; a
# 403 that is a rate limit is not a refusal ([`rate_limited`]).
AUTH_WORDS = (
    "http 401",
    "http 403",
    "status code: 401",
    "status code: 403",
    "returned error: 401",
    "returned error: 403",
    "authentication failed",
    "bad credentials",
    "could not read username",
    "permission denied (publickey)",
)
# This machine failing rather than the network: nothing is known about the
# branch, and every later command would fail the same way.
MACHINE_WORDS = ("no space left on device", "cannot allocate memory", "read-only file system")

# Seconds before each retry of a failure in transit: about three minutes in all.
RETRY_DELAYS = (5, 10, 20, 40, 60, 60)
# The least wait before retrying a rate limit: about six minutes in all.
RATE_LIMIT_SECONDS = 60


class Unreachable(Exception):
    """GitHub or the network did not answer, retries and all. Never a yes or a no."""


class MachineDown(Exception):
    """This machine failed (disk, memory): nothing was decided about any branch."""


class Refused(Exception):
    """GitHub, or git, answered no: a pull request that does not exist, a 422."""


class AuthFailed(Exception):
    """The credentials were refused (an expired token, a revoked key): not the network."""


def auth(stderr: str) -> bool:
    lowered = stderr.lower()
    return "rate limit" not in lowered and any(word in lowered for word in AUTH_WORDS)


def rate_limited(stderr: str) -> bool:
    """GitHub asking to be asked later (a 403 or 429 naming a rate limit): not
    an answer about anything, so it is retried, with a longer wait."""
    return "rate limit" in stderr.lower()


def transport(stderr: str) -> bool:
    """Whether a failed call failed in transit, or was put off, rather than answered.

    Errs towards *answered*: an unrecognised message is not retried, and a
    refused credential is never transit ([`auth`]). A rate limit is ([`rate_limited`]).
    """
    if rate_limited(stderr):
        return True
    if auth(stderr):
        return False
    lowered = stderr.lower()
    return bool(TRANSPORT_STATUS.search(stderr)) or any(w in lowered for w in TRANSPORT_WORDS)


def machine(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(word in lowered for word in MACHINE_WORDS)


def once(command: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """A command, captured and never fatal; this machine failing is raised."""
    done = subprocess.run(command, capture_output=True, text=True, check=False, cwd=cwd)
    if done.returncode != 0 and machine(done.stderr):
        raise MachineDown(f"{' '.join(command[:3])}: {done.stderr.strip()}")
    return done


def retried(command: list[str], cwd: str | None = None) -> subprocess.CompletedProcess:
    """[`once`], retried while it fails in transit; [`Unreachable`] once it never answers."""
    for attempt, delay in enumerate((*RETRY_DELAYS, None), start=1):
        done = once(command, cwd)
        if done.returncode != 0 and auth(done.stderr):
            raise AuthFailed(f"{' '.join(command[:3])}: {done.stderr.strip()}")
        if done.returncode == 0 or not transport(done.stderr):
            return done
        if delay is None:
            raise Unreachable(
                f"unreachable after {attempt} tries of {' '.join(command[:4])}:"
                f" {done.stderr.strip()}"
            )
        time.sleep(max(delay, RATE_LIMIT_SECONDS) if rate_limited(done.stderr) else delay)
    raise AssertionError("unreachable")  # the loop always returns or raises


def api_command(path: str, method: str = "GET", fields: dict[str, str] | None = None) -> list[str]:
    """The `gh api` call for one REST request. `--paginate` on every GET: a
    listing's later pages are never silently dropped (`--slurp` makes one JSON
    array of the pages)."""
    command = ["gh", "api", "--method", method, path]
    if method == "GET":
        command += ["--paginate", "--slurp"]
    for key, value in (fields or {}).items():
        command += ["-f", f"{key}={value}"]
    return command


def api(path: str, method: str = "GET", fields: dict[str, str] | None = None) -> object:
    """One REST request through `gh api`, its JSON parsed (`None` when empty).

    A GET answers the list of its pages (`github.py` joins them). Retried in
    transit; a call GitHub answered with an error is [`Refused`]. Writes go
    through here too when retrying them is harmless (a re-run, a branch
    deletion); the merge does not ([`once`]).
    """
    done = retried(api_command(path, method, fields))
    if done.returncode != 0:
        raise Refused(f"gh api {method} {path}: {done.stderr.strip()}")
    return json.loads(done.stdout) if done.stdout.strip() else None


def git(*args: str, cwd: str) -> subprocess.CompletedProcess:
    """Local `git`. Callers read `returncode` themselves."""
    return once(["git", *args], cwd)


def git_net(*args: str, cwd: str) -> subprocess.CompletedProcess:
    """`git` that talks to the remote (fetch, push), retried in transit."""
    return retried(["git", *args], cwd)


def say(line: str, *rest: str) -> None:
    """One `queue:` line, and its detail indented under it."""
    print(f"queue: {line}", flush=True)
    for extra in rest:
        print(f"  {extra}", flush=True)
