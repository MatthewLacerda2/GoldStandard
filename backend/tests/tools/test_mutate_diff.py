"""``make back-mutate-diff`` (``tools/mutate_diff.py``) mutates only the
sensitive functions the branch changed, refuses results and trees it cannot
vouch for, and writes the block the mutation gate accepts.

The planning, the verdicts and the block are tested on their own; the tests
at the end drive ``main`` against a real repository, mutmut faked."""

import json

import pytest
from mutmut.mutation.file_mutation import mutate_file_contents

from tests.tools.gate_repo import GUARD, GUARD_SOURCE, SENSITIVE_LIST
from tools import mutate, mutate_diff
from tools import mutation_block as block
from tools import mutation_gate as gate

ALLOWED = "utils.guard.x_allowed__mutmut_*"
ENTRIES = gate.load_sensitive(SENSITIVE_LIST)


def _plan(source: str, lines: set[int]) -> mutate_diff.Plan:
    plan = mutate_diff.Plan()
    mutate_diff.plan_file(plan, GUARD, source, lines)
    return plan


def test_only_the_changed_function_is_planned():
    plan = _plan(GUARD_SOURCE, {9})
    assert list(plan.functions) == [ALLOWED] and plan.unmutated == []


def test_a_change_in_a_nested_function_plans_the_method_holding_it():
    assert list(_plan(GUARD_SOURCE, {17}).functions) == ["utils.guard.xǁCheckerǁcheck__mutmut_*"]


def test_a_changed_function_mutmut_skips_is_a_no_mutant_line():
    plan = _plan(GUARD_SOURCE, {24})  # inside the decorated function
    assert plan.functions == {}
    (line,) = plan.unmutated
    assert line.status == block.NO_MUTANT and line.name.startswith("utils.guard.x_decorated #")


def _results(root, source: str = GUARD_SOURCE, overrides: dict[str, int] | None = None) -> None:
    """mutmut's results for the guard as a run over ``source`` leaves them:
    every mutant killed (exit code 1) unless ``overrides`` says otherwise."""
    mutated = mutate_file_contents(GUARD, source)
    codes = {f"utils.guard.{m}": 1 for m in mutated.mutant_names} | (overrides or {})
    meta = root / "backend" / "mutants" / "utils" / "guard.py.meta"
    meta.parent.mkdir(parents=True, exist_ok=True)
    payload = {"exit_code_by_key": codes, "hash_by_function_name": mutated.hash_by_function_name}
    meta.write_text(json.dumps(payload))


def test_verdicts_are_read_from_mutmuts_results(tmp_path):
    _results(tmp_path, overrides={"utils.guard.x_allowed__mutmut_2": 0})
    found, stale = mutate_diff.verdicts(tmp_path, _plan(GUARD_SOURCE, {9}))
    assert stale == [] and found["utils.guard.x_allowed__mutmut_2"] == "survived"
    assert set(found.values()) == {"killed", "survived"}


def test_results_for_another_source_or_short_of_a_verdict_are_stale(tmp_path):
    edited = GUARD_SOURCE.replace("attempts < LIMIT", "attempts <= LIMIT")
    _results(tmp_path)  # a run over the old source
    assert mutate_diff.verdicts(tmp_path, _plan(edited, {11}))[1] == ["utils.guard.x_allowed"]
    _results(tmp_path, overrides={"utils.guard.x_allowed__mutmut_1": None})  # not checked yet
    assert mutate_diff.verdicts(tmp_path, _plan(GUARD_SOURCE, {9}))[1] == ["utils.guard.x_allowed"]


def test_the_block_written_is_the_one_the_gate_accepts_once_decided(tmp_path):
    plan = _plan(GUARD_SOURCE, {9})
    survivor = "utils.guard.x_allowed__mutmut_2"
    _results(tmp_path, overrides={survivor: 0})
    found, _ = mutate_diff.verdicts(tmp_path, plan)
    diff = gate.Expected(functions={"utils.guard.x_allowed": plan.functions[ALLOWED].source})
    report = mutate_diff.report([GUARD], "c" * 64, plan, found, diff)
    body = block.render(report)
    assert f"- survived `{survivor}`: {block.UNDECIDED}" in body
    assert gate.problems(body, [GUARD], "c" * 64, diff)  # undecided
    decided = body.replace(f": {block.UNDECIDED}", ": kept, see test_guard")
    assert gate.problems(decided, [GUARD], "c" * 64, diff) == []


def test_anything_uncommitted_under_backend_or_guarded_is_dirty():
    status = f" M {GUARD}\n?? backend/tests/test_new.py\n M README.md\n?? frontend/x.ts\n"
    assert mutate_diff.dirty(status, ENTRIES) == ["backend/tests/test_new.py", GUARD]


def test_native_windows_is_refused_before_any_work(monkeypatch, capsys):
    monkeypatch.setattr(mutate.platform, "system", lambda: "Windows")
    monkeypatch.setattr(mutate_diff.subprocess, "run", pytest.fail)  # no fetch, no gh
    assert mutate_diff.main(["--pr", "7"]) == 2
    assert "WSL" in capsys.readouterr().err


# `main`, against a real repository; mutmut's run is faked.


@pytest.fixture
def runs(monkeypatch, repo) -> list[list[str]]:
    """``make back-mutate`` as if it ran: what it was handed, and the results
    it would leave for the source the repository has now."""
    calls: list[list[str]] = []

    def run(names: list[str]) -> int:
        calls.append(names)
        _results(repo.root, (repo.root / GUARD).read_text())
        return 0

    monkeypatch.setattr(mutate, "main", run)
    return calls


def test_main_mutates_the_changed_function_and_writes_the_block_into_the_pr(
    repo, runs, monkeypatch
):
    repo.edit(GUARD, '"admin"', '"owner"')  # allowed, nothing else
    head = repo.git("rev-parse", "HEAD").strip()
    edits: list[str] = []

    def gh(*args, stdin=None):
        edits.append(stdin) if "edit" in args else None
        return head if "headRefOid" in args else "Why.\n\nCloses #7\n"

    monkeypatch.setattr(mutate_diff, "_gh", gh)
    assert mutate_diff.main(["--pr", "7"], root=repo.root) == 0
    assert runs == [[ALLOWED]]
    [body] = edits
    assert body.startswith("Why.") and "Closes #7" in body
    assert block.parse(body).content == gate.hash_of([GUARD], gate.blobs(repo.root, [GUARD]))


def test_a_dirty_tree_or_a_pr_at_another_commit_is_refused(monkeypatch):
    status = {"status": "?? backend/tests/test_guard_new.py\n"}
    monkeypatch.setattr(gate, "git", lambda root, cmd, *a: status.get(cmd, "a" * 40))
    assert "commit or remove first" in mutate_diff._refusal(None, ENTRIES, None)
    status.clear()
    assert mutate_diff._refusal(None, ENTRIES, None) is None
    monkeypatch.setattr(mutate_diff, "_gh", lambda *args, **kw: "0" * 40)
    assert "push (or pull) first" in mutate_diff._refusal(None, ENTRIES, "7")
