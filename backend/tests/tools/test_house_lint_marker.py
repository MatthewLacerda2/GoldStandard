"""Tests for the house linter's ``marker`` rule: no comment promising work later."""

from pathlib import Path

import pytest

from tools import house_lint

PATH = Path("app/x.py")


def _markers(source: str) -> list[str]:
    return [v for v in house_lint.check_source(PATH, source) if "file an issue" in v]


@pytest.mark.parametrize("marker", house_lint.MARKERS)
def test_each_marker_in_a_comment_fails(marker: str):
    violations = _markers(f"x = 1  # {marker}: tidy this\n")
    assert violations == [
        f"{PATH}:1: '{marker}' comment: do it now, or file an issue and delete the comment"
    ]


@pytest.mark.parametrize("comment", ["todos", "TODO_LIST", "hacker", "XXXL", "todo", "Fixme"])
def test_a_word_that_only_contains_a_marker_passes(comment: str):
    assert _markers(f"# {comment}\n") == []


def test_markers_in_strings_and_docstrings_pass():
    source = '"""TODO in a docstring."""\n\nWORDS = ("TODO", "FIXME")\nNOTE = f"HACK {1}"\n'
    assert _markers(source) == []


def test_an_allow_on_the_same_line_passes():
    assert _markers("# TODO is the format  lint: allow(marker) it names the word\n") == []


def test_an_allow_in_the_comment_run_directly_above_passes():
    source = "# lint: allow(marker) the next line quotes the format\n# - TODO: ...\n\n# XXX\n"
    [violation] = _markers(source)
    assert violation.startswith(f"{PATH}:4: 'XXX'")


def test_an_allow_needs_a_reason():
    assert len(_markers("# TODO  lint: allow(marker)\n")) == 1
    assert len(_markers("# TODO  lint: allow(marker) -- \n")) == 1


def test_an_allow_for_another_rule_or_across_code_does_not_excuse():
    assert len(_markers("# FIXME  lint: allow(other) a reason\n")) == 1
    assert len(_markers("# lint: allow(marker) a reason\nx = 1\n# FIXME\n")) == 1
