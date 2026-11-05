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


@pytest.mark.parametrize(
    "comment", ["todos", "TODO_LIST", "MYTODO", "_HACK", "hacker", "XXXL", "todo", "Fixme"]
)
def test_a_word_that_only_contains_a_marker_passes(comment: str):
    assert _markers(f"# {comment}\n") == []


def test_markers_in_strings_and_docstrings_pass():
    source = '"""TODO in a docstring."""\n\nWORDS = ("TODO", "FIXME")\nNOTE = f"HACK {1}"\n'
    assert _markers(source) == []


def test_an_allow_on_the_line_or_directly_above_passes():
    assert _markers("# TODO is the format  lint: allow(marker) it names the word\n") == []
    assert _markers("# lint: allow(marker) `TODO` is quoted below\n# - TODO: ...\n") == []


def test_an_allow_excuses_only_the_line_below_it():
    source = "# lint: allow(marker) a reason\n# TODO\n# XXX\nx = 1  # FIXME\n"
    assert [v.split(": '")[0] for v in _markers(source)] == [f"{PATH}:3", f"{PATH}:4"]


def test_an_allow_needs_a_reason():
    assert len(_markers("# TODO  lint: allow(marker)\n")) == 1
    assert len(_markers("# TODO  lint: allow(marker) -- \n")) == 1
    assert len(_markers("# TODO  lint: allow(marker): —\n")) == 1
    assert len(_markers("# lint: allow(marker) # FIXME\n")) == 1
    assert _markers("# TODO  lint: allow(marker): — the format\n") == []


def test_an_allow_for_another_rule_or_in_a_string_does_not_excuse():
    assert len(_markers("# FIXME  lint: allow(other) a reason\n")) == 1
    assert len(_markers('x = "lint: allow(marker) a reason"  # FIXME\n')) == 1
    assert len(_markers('NOTE = "lint: allow(marker) a reason"\n# FIXME\n')) == 1
