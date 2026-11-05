"""The pragma check (``tools/pragma_scope.py``): a ``# pragma: no mutate`` a PR
adds or grows in sensitive code stands over exactly one unobservable mutant,
with its reason on its line. mutmut hides every mutant that starts on a
pragma's line, so a second one would go ungenerated and unseen."""

from tests.tools.gate_repo import GUARD
from tools import mutmut_view as view
from tools import pragma_scope as ps

REGION = """\
def f(user, role):
    # pragma: no mutate start - text nobody parses
    note = "hello"
    # pragma: no mutate end
    return role
"""


def _judge(code: str) -> list[str]:
    scan = ps.Scan.of(code)
    return [problem for p in scan.every if p.kind != "end" for problem in ps.judge("m.py", scan, p)]


def test_a_pragma_over_one_equivalent_mutant_stands():
    code = "def add(done, user):\n    done.append(user)  # pragma: no mutate - equivalent: only len(done) is read\n"
    assert _judge(code) == []


def test_a_pragma_over_a_second_killable_mutant_is_refused_and_names_both():
    code = "def check():\n    return True, ''  # pragma: no mutate - nobody reads the note\n"
    (problem,) = _judge(code)
    assert "hides 2 mutants, not one" in problem
    assert "`True` → `False`" in problem and "`''` → `'XXXX'`" in problem
    assert "split the statement" in problem  # the way out is in the message


def test_a_pragma_with_no_reason_is_refused():
    code = "def add(done, user):\n    done.append(user)  # pragma: no mutate\n"
    (problem,) = _judge(code)
    assert "no reason" in problem


def test_another_tools_comment_is_no_reason():
    code = "def add(done, user):\n    done.append(user)  # pragma: no mutate  # fmt: skip\n"
    assert any("no reason" in p for p in _judge(code))
    assert view.reason("# pragma: no mutate - text nobody parses  # fmt: skip") == (
        "text nobody parses"
    )


def test_a_pragma_that_hides_nothing_is_refused():
    code = "def same(x):\n    return x  # pragma: no mutate - nothing to see\n"
    (problem,) = _judge(code)
    assert "hides no mutant" in problem


def _problems(base: str, head: str, touched: set[int]) -> list[str]:
    scan = ps.Scan.of(head)
    picked = ps.judged(scan, ps.Scan.of(base), touched)
    return [problem for p in picked for problem in ps.judge("f.py", scan, p)]


def test_a_pragma_the_base_already_has_is_not_judged_again():
    assert _problems(REGION, REGION, set()) == []
    moved = "\n\n" + REGION  # moved unchanged: the same key
    assert _problems(REGION, moved, {1, 2}) == []


def test_code_written_inside_an_existing_region_is_judged():
    head = REGION.replace('    note = "hello"\n', '    note = "hello"\n    ok = role == "admin"\n')
    assert any("mutants, not one" in p for p in _problems(REGION, head, {4}))


def test_the_check_reads_only_the_sensitive_files_the_pr_changes(repo):
    # Without a rev it reads the working tree; a file off the list is never judged.
    repo.edit(GUARD, "return True", "return True  # pragma: no mutate", commit=False)
    repo.edit("backend/services/fuel.py", "n * 2", "n * 2  # pragma: no mutate", commit=False)
    found = ps.problems(repo.root, "origin/main")
    assert found and all(p.startswith(f"{GUARD}:10:") for p in found)
    assert any("no reason" in p for p in found)


def test_a_sensitive_path_with_a_space_is_found(repo, monkeypatch):
    path = "backend/utils/my dir/ação.py"
    monkeypatch.setattr(ps.gate, "sensitive_entries", lambda *args: ["backend/utils/my dir/"])
    repo.write(path, "def f(x):\n    return x  # pragma: no mutate\n")
    repo.commit()
    base = ps.gate.merge_base(repo.root, "origin/main")
    assert ps.changed_files(repo.root, "origin/main", base, "HEAD") == [path]
