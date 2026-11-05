"""The mutation gate (``tools/mutation_gate.py``): a PR that changes sensitive
code passes only with a ``## Mutation`` block for the content its head commit
carries, unedited beyond its decisions, with a decision on every line; a PR
that touches nothing sensitive passes asking nothing.

The verdict is pure (``problems``, ``expected_from``) and tested without git;
the tests at the end drive the whole check against a real repository."""

import pytest

from tests.tools.gate_repo import GUARD, GUARD_SOURCE
from tools import mutation_block as block
from tools import mutation_gate as gate
from tools import mutation_source as source

ALLOWED = "utils.guard.x_allowed"
SURVIVOR = f"{ALLOWED}__mutmut_3"
HASHES = source.function_sources(GUARD_SOURCE)
CONTENT = "c" * 64


def _diff(functions=(ALLOWED,), lines=()) -> gate.Expected:
    """What a diff that changed ``functions`` calls for."""
    return gate.Expected(list(lines), {f: HASHES[f.rpartition(".")[2]] for f in functions})


def _body(lines=(), counts=None, functions=(ALLOWED,), content=CONTENT) -> str:
    """A body whose block is what the tool writes for ``functions``, run with ``counts``."""
    counts = counts or {"killed": 4}
    report = block.Report(
        content=content,
        files=[GUARD],
        mutated={f: (sum(counts.values()), HASHES[f.rpartition(".")[2]]) for f in functions},
        counts=counts if functions else {},
        lines=list(lines),
    )
    return f"Why this PR exists.\n\n{block.render(report)}\n\nCloses #1"


def _problems(body: str, diff: gate.Expected | None = None) -> list[str]:
    return gate.problems(body, [GUARD], CONTENT, diff or _diff())


def test_a_sensitive_change_without_the_block_is_red():
    (problem,) = _problems("Why this PR exists.")
    assert "no `## Mutation` block" in problem


def test_a_sensitive_change_with_its_block_is_green():
    assert _problems(_body()) == []


def test_nothing_guarded_touched_asks_nothing():
    assert gate.problems("", [], CONTENT, gate.Expected()) == []


def test_a_block_for_other_content_is_red():
    (problem,) = _problems(_body(content="d" * 64))
    assert "for other content" in problem


def test_a_line_without_a_decision_is_red_until_one_is_written():
    survived = [block.Decision("survived", SURVIVOR)]
    body = _body(lines=survived, counts={"killed": 3, "survived": 1})
    (problem,) = _problems(body)
    assert SURVIVOR in problem and "no decision" in problem
    decided = body.replace(f"{SURVIVOR}`: {block.UNDECIDED}", f"{SURVIVOR}`: times out even alone")
    assert _problems(decided) == []


@pytest.mark.parametrize("text", ["", "TODO", "todo: look later", " Todo."])
def test_anything_starting_with_the_placeholder_is_no_decision(text):
    assert not block.Decision("survived", SURVIVOR, text).decided


def test_a_survivor_deleted_by_hand_is_red():
    survived = [block.Decision("survived", SURVIVOR, "kept: see the test")]
    body = _body(lines=survived, counts={"killed": 3, "survived": 1})
    edited = "\n".join(line for line in body.splitlines() if SURVIVOR not in line)
    (problem,) = _problems(edited)
    assert "not this PR's own" in problem


def test_counts_that_do_not_add_up_are_red():
    body = _body(counts={"killed": 3})
    assert _problems(body) == []
    assert _problems(body.replace("3 killed", "2 killed"))


def test_a_block_naming_another_function_is_red():
    assert _problems(_body(functions=("utils.guard.xǁCheckerǁcheck",)))
    assert _problems(_body(functions=()))


def test_a_function_mutmut_cannot_mutate_needs_a_no_mutant_decision():
    diff = _diff(functions=("utils.guard.x_decorated",))
    name = gate.no_mutant_name("utils.guard.x_decorated", HASHES["x_decorated"])
    open_line = block.Decision(block.NO_MUTANT, name)
    assert _problems(_body(lines=[open_line], functions=()), diff)
    decided = block.Decision(block.NO_MUTANT, name, "test_guard covers it")
    assert _problems(_body(lines=[decided], functions=()), diff) == []
    stale = block.Decision(block.NO_MUTANT, f"utils.guard.x_decorated #{'0' * 8}", "old text")
    assert _problems(_body(lines=[stale], functions=()), diff)  # the function changed since


def test_a_module_level_line_must_be_there_and_decided():
    line = block.Decision(block.MODULE_LEVEL, f"{GUARD}:5 -5 #abcd1234")
    diff = _diff(functions=(), lines=[line])
    assert _problems(_body(functions=()), diff)  # missing
    decided = block.Decision(line.status, line.name, "test_guard pins the limit")
    assert _problems(_body(lines=[decided], functions=()), diff) == []


def test_a_block_in_another_format_is_red():
    body = _body()
    assert _problems(body.replace(f"format: {block.FORMAT}", "format: 99"))
    assert _problems(body.replace(f"format: {block.FORMAT}\n", ""))


def _expected(new: str, lines: set[int], old: str = GUARD_SOURCE) -> gate.Expected:
    removed = lines if old != new else set()
    texts = {GUARD: (old, new)}
    return gate.expected_from([GUARD], {GUARD}, texts, {GUARD: source.Lines(lines, removed)})


def test_a_changed_line_names_the_function_holding_it():
    new = GUARD_SOURCE.replace("value.strip()", "value.lstrip()")
    assert list(_expected(new, {17}).functions) == ["utils.guard.xǁCheckerǁcheck"]
    assert _expected(new, {17}).lines == []


def test_a_change_outside_the_functions_is_one_module_level_line():
    new = GUARD_SOURCE.replace("LIMIT = 3", "LIMIT = 4")
    (line,) = _expected(new, {5}).lines
    assert line.status == block.MODULE_LEVEL and line.name.startswith(f"{GUARD}:5 -5 #")


def test_a_docstring_change_calls_for_nothing():
    new = GUARD_SOURCE.replace("A sensitive module.", "A sensitive module, reworded.")
    assert _expected(new, {1}) == gate.Expected()


def test_a_guarded_file_gone_from_the_head_is_a_deleted_line():
    (line,) = gate.expected_from([GUARD], set(), {}, {}).lines
    assert (line.status, line.name) == (block.DELETED, GUARD)


def test_only_the_pins_mutmut_line_counts():
    assert gate.mutmut_pin("ruff==1\nmutmut==3.8.1\n") == gate.mutmut_pin("ruff==2\nmutmut==3.8.1")
    assert gate.mutmut_pin("mutmut==3.8.1") != gate.mutmut_pin("mutmut==3.9.0")


def test_the_list_is_read_at_the_base_the_merge_base_and_the_head(monkeypatch):
    # So removing an entry does not free its file in the same PR, and an entry
    # `main` adds after the branch point guards the branch.
    lists = {"origin/main": "a.py\n", "fork": "b.py\n", "head": "# nothing left\n"}
    monkeypatch.setattr(
        gate, "read_many", lambda root, specs: {s: lists[s.partition(":")[0]] for s in specs}
    )
    assert gate.sensitive_entries(None, "origin/main", "head", base="fork") == ["a.py", "b.py"]


def _raw(path: str, old: str, new: str, mode: str = "100644") -> str:
    return f":100644 {mode} {old * 40} {new * 40} M\t{path}"


def test_only_guarded_content_and_a_moved_mutmut_pin_are_touched(monkeypatch):
    raw = [
        _raw(GUARD, "a", "a", mode="100755"),  # a mode change is no change
        _raw("backend/services/fuel.py", "a", "b"),  # not guarded
        _raw(gate.PIN_FILE, "a", "b"),
    ]
    monkeypatch.setattr(gate, "git", lambda root, *args, **kw: "\n".join(raw))
    pins = {"base": "ruff==1\nmutmut==3.8.1\n", "head": "ruff==2\nmutmut==3.8.1\n"}
    monkeypatch.setattr(
        gate, "read_many", lambda root, specs: {s: pins[s.partition(":")[0]] for s in specs}
    )
    assert gate.touched(None, "base", [GUARD], "head") == []
    pins["head"] = "mutmut==3.9.0\n"
    assert gate.touched(None, "base", [GUARD], "head") == [gate.PIN_FILE]


def test_the_diff_ignores_what_a_users_git_config_would_change():
    # A merged hunk, another algorithm or other prefixes would name a
    # module-level line differently from the name CI computes.
    for flag in ("--inter-hunk-context=0", "--diff-algorithm=myers", "--src-prefix=a/"):
        assert flag in gate.DIFF
    assert {"--no-ext-diff", "--no-renames", "--dst-prefix=b/"} <= set(gate.DIFF)


# The whole check, against a real repository: git reads, refs, objects.


def _check(repo, body: str, rev: str = "HEAD") -> int:
    return gate.run(repo.root, "origin/main", body, rev)


def _real_body(repo) -> str:
    base = gate.merge_base(repo.root, "origin/main")
    diff = gate.expected(repo.root, base, [GUARD], [GUARD])
    report = block.Report(
        content=gate.content_hash(repo.root, [GUARD]),
        files=[GUARD],
        mutated={f: (4, h) for f, h in diff.functions.items()},
        counts={"killed": 4},
    )
    return block.render(report)


def test_the_check_reads_the_heads_commits_as_objects(repo):
    repo.edit(GUARD, '"admin"', '"owner"')
    body, head = _real_body(repo), repo.git("rev-parse", "HEAD").strip()
    # CI has the base checked out: the head is only commits it reads, and
    # what the working tree holds does not count.
    repo.git("checkout", "--quiet", "main")
    assert _check(repo, "", rev=head) == 1
    assert _check(repo, body, rev=head) == 0
