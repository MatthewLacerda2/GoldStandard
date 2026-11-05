"""``make back-mutate-diff`` (``tools/mutate_diff.py``) mutates only the
sensitive functions the branch changed, refuses results and trees it cannot
vouch for, and writes the block the mutation gate accepts."""

import json

import pytest
from mutmut.mutation.file_mutation import mutate_file_contents

from tests.tools.gate_repo import GUARD
from tools import mutate, mutate_diff
from tools import mutation_block as block
from tools import mutation_gate as gate

ALLOWED = "utils.guard.x_allowed__mutmut_*"


def _results(root, overrides: dict[str, int] | None = None) -> None:
    """mutmut's results for the guard as a run over its current source leaves
    them: every mutant killed (exit code 1) unless ``overrides`` says otherwise."""
    mutated = mutate_file_contents(GUARD, (root / GUARD).read_text())
    codes = {f"utils.guard.{m}": 1 for m in mutated.mutant_names} | (overrides or {})
    meta = root / "backend" / "mutants" / "utils" / "guard.py.meta"
    meta.parent.mkdir(parents=True, exist_ok=True)
    payload = {"exit_code_by_key": codes, "hash_by_function_name": mutated.hash_by_function_name}
    meta.write_text(json.dumps(payload))


@pytest.fixture
def runs(monkeypatch, repo) -> list[list[str]]:
    """``make back-mutate`` as if it ran: what it was handed, and the results
    it would leave."""
    calls: list[list[str]] = []
    monkeypatch.setattr(mutate, "main", lambda names: calls.append(names) or _results(repo.root))
    return calls


def _main(repo, *argv: str) -> int:
    return mutate_diff.main(list(argv), root=repo.root)


def _block(repo) -> str:
    return (repo.root / mutate_diff.REPORT).read_text()


def test_only_the_changed_function_is_mutated_and_the_gate_accepts_the_block(repo, runs):
    repo.edit(GUARD, '"admin"', '"owner"')  # allowed, nothing else
    repo.edit("backend/services/fuel.py", "n * 2", "n * 3")  # not sensitive
    assert _main(repo) == 0
    assert runs == [[ALLOWED]]
    assert gate.run(repo.root, "origin/main", _block(repo)) == 0


def test_a_change_in_a_nested_function_mutates_the_method_holding_it(repo, runs):
    repo.edit(GUARD, "value.strip()", "value.lstrip()")
    _main(repo)
    assert runs == [["utils.guard.xǁCheckerǁcheck__mutmut_*"]]


def test_a_survivor_is_a_line_to_decide(repo, runs, monkeypatch):
    repo.edit(GUARD, '"admin"', '"owner"')
    survivor = "utils.guard.x_allowed__mutmut_2"
    monkeypatch.setattr(mutate, "main", lambda names: _results(repo.root, {survivor: 0}))
    assert _main(repo) == 1
    assert f"- survived `{survivor}`: {block.UNDECIDED}" in _block(repo)
    assert gate.run(repo.root, "origin/main", _block(repo)) == 1
    decided = _block(repo).replace(f": {block.UNDECIDED}", ": kept, see test_guard")
    assert gate.run(repo.root, "origin/main", decided) == 0


def test_a_changed_function_mutmut_skips_is_a_line_and_runs_nothing(repo, runs):
    repo.edit(GUARD, "1 + 1", "1 + 2")  # inside a decorated function
    assert _main(repo) == 1
    assert runs == []
    assert "- no mutant `utils.guard.x_decorated #" in _block(repo)
    assert gate.run(repo.root, "origin/main", _block(repo)) == 1


def test_a_module_level_change_needs_a_decision(repo, runs):
    repo.edit(GUARD, "LIMIT = 3", "LIMIT = 4")
    assert _main(repo) == 1
    assert f"- module-level `{GUARD}:5 -5 #" in _block(repo)


def test_a_branch_touching_nothing_sensitive_runs_nothing(repo, runs):
    repo.edit("backend/services/fuel.py", "n * 2", "n * 3")
    assert _main(repo) == 0
    assert runs == []
    assert not (repo.root / mutate_diff.REPORT).exists()


@pytest.mark.parametrize("path", [GUARD, "backend/tests/test_guard_new.py"])
def test_anything_uncommitted_under_backend_is_refused(repo, runs, path):
    repo.edit(GUARD, '"admin"', '"owner"')
    repo.write(path, "# a test nobody pushed\n")
    assert _main(repo) == 2
    assert runs == []


def test_a_pr_whose_head_is_another_commit_is_refused(repo, runs, monkeypatch):
    repo.edit(GUARD, '"admin"', '"owner"')
    monkeypatch.setattr(mutate_diff, "_gh", lambda *args, **kw: "0" * 40)
    assert _main(repo, "--pr", "7") == 2
    assert runs == []


def test_no_run_refuses_results_for_another_source(repo, runs):
    repo.edit(GUARD, '"admin"', '"owner"')
    _results(repo.root)
    repo.edit(GUARD, "attempts < LIMIT", "attempts <= LIMIT")
    assert _main(repo, "--no-run") == 2
    assert runs == []


def test_with_a_pr_the_block_goes_into_its_body_keeping_the_rest(repo, runs, monkeypatch):
    repo.edit(GUARD, '"admin"', '"owner"')
    head = repo.git("rev-parse", "HEAD").strip()
    edits: list[str] = []

    def gh(*args, stdin=None):
        if "edit" in args:
            edits.append(stdin)
        return head if "headRefOid" in args else "Why.\n\nCloses #7\n"

    monkeypatch.setattr(mutate_diff, "_gh", gh)
    assert _main(repo, "--pr", "7") == 0
    [body] = edits
    assert body.startswith("Why.") and block.HEADING in body and "Closes #7" in body
