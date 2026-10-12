"""`make back-mutate` runs what it is told, and never the whole scope by accident."""

from tools.mutate import _names


def test_a_bare_run_is_refused():
    assert _names([]) is None


def test_named_mutants_run_alone():
    assert _names(["repositories.items.x_get_owned*"]) == ["repositories.items.x_get_owned*"]


def test_all_runs_the_whole_scope():
    assert _names(["--all"]) == []


def test_all_with_names_is_ambiguous_and_refused():
    assert _names(["--all", "utils.security*"]) is None
