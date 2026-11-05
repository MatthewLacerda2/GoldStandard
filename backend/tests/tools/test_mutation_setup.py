"""What holds the mutation setup together across files: the sensitive list
against mutmut's scope, the workflow's shape, and the block's round trip."""

import tomllib

import yaml

from tests.tools.gate_repo import CHECKOUT
from tools import mutation_block as block
from tools import mutation_gate as gate


def _entries() -> list[str]:
    return gate.load_sensitive((CHECKOUT / gate.SENSITIVE_LIST).read_text())


def test_every_sensitive_path_exists_and_mutmut_mutates_it():
    # A sensitive file mutmut cannot mutate would demand a run that tests nothing.
    config = tomllib.loads((CHECKOUT / "backend" / "pyproject.toml").read_text())
    scope = config["tool"]["mutmut"]["source_paths"]
    for entry in _entries():
        path = entry.removeprefix(gate.HASH_ONLY)
        assert (CHECKOUT / path).exists(), f"{path} is listed but does not exist"
        if entry.startswith(gate.HASH_ONLY):
            continue
        inside = entry.removeprefix("backend/")
        assert any(inside == s or inside.startswith(f"{s}/") for s in scope), entry


def test_the_gates_own_files_are_guarded_never_mutated():
    entries = _entries()
    for path in (
        "backend/tools/mutation_gate.py",
        "backend/mutation-sensitive.txt",
        ".github/workflows/mutation-gate.yml",
    ):
        assert gate.guarded(path, entries) and not gate.is_sensitive(path, entries)


def test_a_directory_entry_covers_everything_under_it():
    entries = gate.load_sensitive("backend/auth/  # login\nbackend/core/rbac.py\n")
    assert gate.is_sensitive("backend/auth/tokens.py", entries)
    assert gate.is_sensitive("backend/core/rbac.py", entries)
    assert not gate.is_sensitive("backend/core/rbac_helpers.py", entries)


def test_ci_runs_the_base_branchs_gate_on_the_head_read_as_data():
    text = (CHECKOUT / ".github/workflows/mutation-gate.yml").read_text()
    workflow = yaml.safe_load(text)
    trigger = workflow[True]  # PyYAML reads the bare key `on` as True
    assert set(trigger) == {"pull_request_target"}  # the workflow and code are the base's
    assert "paths" not in trigger["pull_request_target"]  # a required check always reports
    assert {"edited", "synchronize", "ready_for_review"} <= set(
        trigger["pull_request_target"]["types"]
    )
    assert workflow["permissions"] == {"contents": "read"}
    (job,) = workflow["jobs"].values()
    assert job["name"] == "mutation gate"
    checkout = next(s for s in job["steps"] if s.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.ref }}"
    step = next(s for s in job["steps"] if "back-mutation-gate" in s.get("run", ""))
    assert "${{" not in step["run"] and 'REV="$HEAD_SHA"' in step["run"]
    assert step["env"]["PR_BODY"] == "${{ github.event.pull_request.body }}"


def _report(decision: str = block.UNDECIDED, source: str = "1a2b3c4d") -> block.Report:
    survivor = block.Decision("survived", "utils.guard.x_allowed__mutmut_2", decision)
    return block.Report(
        content="0" * 64,
        files=["backend/utils/guard.py"],
        mutated={"utils.guard.x_allowed": (5, source)},
        counts={"killed": 4, "survived": 1},
        lines=[survivor, block.Decision(block.MODULE_LEVEL, "backend/utils/guard.py:5 #9f")],
    )


def test_a_rendered_block_parses_back_to_itself():
    report = _report()
    assert block.parse(f"Intro\n\n{block.render(report)}\n\nCloses #1") == report
    assert block.consistent(report)


def test_splicing_keeps_the_text_around_the_block_and_the_decisions_that_hold():
    body = f"Intro\n\n{block.render(_report('kept: equivalent'))}\n\nCloses #1\n"
    spliced = block.splice(body, _report())
    assert spliced.startswith("Intro\n") and spliced.rstrip().endswith("Closes #1")
    assert spliced.count(block.HEADING) == 1
    assert "__mutmut_2`: kept: equivalent" in spliced


def test_a_decision_on_a_mutant_does_not_survive_its_function_changing():
    body = block.render(_report("kept: equivalent"))
    spliced = block.splice(body, _report(source="99999999"))
    assert f"__mutmut_2`: {block.UNDECIDED}" in spliced


def test_a_body_without_a_block_gets_one_appended():
    assert block.splice("Intro", _report()).startswith(f"Intro\n\n{block.HEADING}")
