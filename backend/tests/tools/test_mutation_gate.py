"""The mutation gate (``tools/mutation_gate.py``): a PR that changes sensitive
code passes only with a ``## Mutation`` block for the content its head commit
carries, unedited beyond its decisions, with a decision on every line; a PR
that touches nothing sensitive passes asking nothing."""

import pytest

from tests.tools.gate_repo import GUARD
from tools import mutation_block as block
from tools import mutation_gate as gate
from tools import mutation_source as source

ALLOWED = "utils.guard.x_allowed"
SURVIVOR = f"{ALLOWED}__mutmut_3"


def _report(repo, lines=(), counts=None, functions=(ALLOWED,)) -> block.Report:
    """A block as the tool writes it for a change to ``functions``, run with
    the ``counts`` given."""
    counts = counts or {"killed": 4}
    hashes = source.function_sources((repo.root / GUARD).read_text())
    return block.Report(
        content=gate.content_hash(repo.root, [GUARD]),
        files=[GUARD],
        mutated={f: (sum(counts.values()), hashes[f.rpartition(".")[2]]) for f in functions},
        counts=counts if functions else {},
        lines=list(lines),
    )


def _body(repo, **kwargs) -> str:
    return f"Why this PR exists.\n\n{block.render(_report(repo, **kwargs))}\n\nCloses #1"


def _check(repo, body: str, rev: str = "HEAD") -> int:
    return gate.run(repo.root, "origin/main", body, rev)


def test_a_sensitive_change_without_the_block_is_red(repo, capsys):
    repo.edit(GUARD, '"admin"', '"owner"')
    assert _check(repo, "Why this PR exists.") == 1
    assert "no `## Mutation` block" in capsys.readouterr().out


def test_a_sensitive_change_with_its_block_is_green(repo):
    repo.edit(GUARD, '"admin"', '"owner"')
    assert _check(repo, _body(repo)) == 0


def test_a_pr_touching_nothing_sensitive_passes_asking_nothing(repo, capsys):
    repo.edit("backend/services/fuel.py", "n * 2", "n * 3")
    assert _check(repo, "") == 0
    assert "nothing to ask" in capsys.readouterr().out


def test_the_head_is_judged_as_objects_whatever_is_checked_out(repo):
    # CI runs the base's gate with the base checked out; the head is data.
    repo.edit(GUARD, '"admin"', '"owner"')
    head = repo.git("rev-parse", "HEAD").strip()
    repo.git("checkout", "--quiet", "main")
    assert _check(repo, "", rev=head) == 1


def test_a_block_for_other_content_is_red(repo, capsys):
    repo.edit(GUARD, '"admin"', '"owner"')
    body = _body(repo)
    repo.edit(GUARD, '"owner"', '"root"')  # a commit after the run
    assert _check(repo, body) == 1
    assert "for other content" in capsys.readouterr().out


def test_only_committed_content_counts(repo):
    repo.edit(GUARD, '"admin"', '"owner"', commit=False)
    assert _check(repo, "") == 0


def test_a_mode_change_alone_touches_nothing(repo):
    (repo.root / GUARD).chmod(0o755)
    repo.commit()
    assert _check(repo, "") == 0


def test_a_line_without_a_decision_is_red_until_one_is_written(repo):
    repo.edit(GUARD, '"admin"', '"owner"')
    survived = [block.Decision("survived", SURVIVOR)]
    body = _body(repo, lines=survived, counts={"killed": 3, "survived": 1})
    assert _check(repo, body) == 1
    decided = body.replace(f"{SURVIVOR}`: {block.UNDECIDED}", f"{SURVIVOR}`: times out even alone")
    assert _check(repo, decided) == 0


@pytest.mark.parametrize("text", ["", "TODO", "todo: look later", " Todo."])
def test_anything_starting_with_the_placeholder_is_no_decision(text):
    assert not block.Decision("survived", SURVIVOR, text).decided


def test_a_survivor_deleted_by_hand_is_red(repo, capsys):
    repo.edit(GUARD, '"admin"', '"owner"')
    survived = [block.Decision("survived", SURVIVOR, "kept: see the test")]
    body = _body(repo, lines=survived, counts={"killed": 3, "survived": 1})
    assert _check(repo, body) == 0
    edited = "\n".join(line for line in body.splitlines() if SURVIVOR not in line)
    assert _check(repo, edited) == 1
    assert "not this PR's own" in capsys.readouterr().out


def test_counts_that_do_not_add_up_are_red(repo):
    repo.edit(GUARD, '"admin"', '"owner"')
    body = _body(repo, counts={"killed": 3})
    assert _check(repo, body) == 0
    assert _check(repo, body.replace("3 killed", "2 killed")) == 1


def test_a_block_naming_another_function_is_red(repo):
    repo.edit(GUARD, '"admin"', '"owner"')  # allowed
    assert _check(repo, _body(repo, functions=("utils.guard.xǁCheckerǁcheck",))) == 1
    assert _check(repo, _body(repo, functions=())) == 1


def test_a_function_mutmut_cannot_mutate_needs_a_no_mutant_decision(repo):
    repo.edit(GUARD, "return 1 + 1", "return 1 + 2")  # decorated: no mutant
    hashes = source.function_sources((repo.root / GUARD).read_text())
    name = gate.no_mutant_name("utils.guard.x_decorated", hashes["x_decorated"])
    open_line = block.Decision(block.NO_MUTANT, name)
    assert _check(repo, _body(repo, lines=[open_line], functions=())) == 1
    decided = block.Decision(block.NO_MUTANT, name, "test_guard covers it")
    assert _check(repo, _body(repo, lines=[decided], functions=())) == 0


def test_a_change_outside_the_functions_is_a_module_level_line(repo):
    repo.edit(GUARD, "LIMIT = 3", "LIMIT = 4")
    assert _check(repo, _body(repo, functions=())) == 1
    base = gate.merge_base(repo.root, "origin/main")
    (line,) = gate.expected(repo.root, base, [GUARD], [GUARD]).lines
    assert line.status == block.MODULE_LEVEL and line.name.startswith(f"{GUARD}:5 -5 #")
    decided = block.Decision(line.status, line.name, "test_guard pins the limit")
    assert _check(repo, _body(repo, lines=[decided], functions=())) == 0


def test_a_docstring_change_needs_no_decision(repo):
    repo.edit(GUARD, "A sensitive module.", "A sensitive module, reworded.")
    assert _check(repo, _body(repo, functions=())) == 0


def test_a_sensitive_file_moved_out_of_the_list_is_a_deleted_line(repo):
    repo.git("mv", GUARD, "backend/services/guard.py")
    repo.commit()
    assert _check(repo, "") == 1
    decided = block.Decision(block.DELETED, GUARD, "moved to services, test_guard follows it")
    report = block.Report(gate.content_hash(repo.root, [GUARD]), [GUARD], lines=[decided])
    assert _check(repo, block.render(report)) == 0


def test_removing_a_files_entry_does_not_take_it_out_of_the_gate(repo):
    repo.edit(GUARD, '"admin"', '"owner"', commit=False)
    repo.write(gate.SENSITIVE_LIST, "# nothing left\n")
    repo.commit()
    assert _check(repo, "") == 1


def test_an_entry_main_added_after_the_branch_point_guards_the_branch(repo):
    repo.edit("backend/services/fuel.py", "n * 2", "n * 3")
    repo.git("checkout", "--quiet", "main")
    repo.write(gate.SENSITIVE_LIST, f"{GUARD}\nbackend/services/fuel.py\n")
    repo.commit()
    repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
    repo.git("checkout", "--quiet", "feat/change")
    assert _check(repo, "") == 1


def test_a_change_to_the_gate_itself_needs_its_block(repo):
    repo.write("backend/tools/mutation_gate.py", "def run():\n    return 0\n")
    repo.commit()
    assert _check(repo, "") == 1


def test_a_block_in_another_format_is_red(repo):
    repo.edit(GUARD, '"admin"', '"owner"')
    body = _body(repo)
    assert _check(repo, body.replace(f"format: {block.FORMAT}", "format: 99")) == 1
    assert _check(repo, body.replace(f"format: {block.FORMAT}\n", "")) == 1


def test_a_user_inter_hunk_context_changes_no_name(repo):
    # A merged hunk would name the unchanged line between two edits too, and
    # the name would differ from the one CI computes.
    repo.edit(GUARD, "LIMIT = 3", "A = 1\nB = 2\nC = 3")
    repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
    repo.edit(GUARD, "A = 1\nB = 2\nC = 3", "A = 9\nB = 2\nC = 9")
    repo.git("config", "diff.interHunkContext", "3")
    base = gate.merge_base(repo.root, "origin/main")
    (line,) = gate.expected(repo.root, base, [GUARD], [GUARD]).lines
    assert line.name.startswith(f"{GUARD}:5,7 -5,7 #")
