"""The dead-code gate: what it must flag, and what its policy lets pass.

Vulture's own analysis is vulture's to test. These pin what is ours: that
the gate finds anything at all (an empty scan stays green forever), and the
policy in ``tools/deadcode.py``'s docstring.
"""

from pathlib import Path

from tools.deadcode import check


def _project(tmp_path: Path, app: str, test: str = "") -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text(app, encoding="utf-8")
    (tmp_path / "tests" / "test_app.py").write_text(test, encoding="utf-8")
    return tmp_path


def _messages(root: Path) -> list[str]:
    return [line.split(": ", 1)[1] for line in check(root)]


def test_a_function_and_a_class_nothing_uses_are_flagged(tmp_path: Path):
    root = _project(tmp_path, "def dead():\n    pass\n\n\nclass Dead:\n    pass\n")
    assert sorted(_messages(root)) == ["unused class 'Dead'", "unused function 'dead'"]


def test_fields_entry_points_and_convention_names_pass(tmp_path: Path):
    app = """
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class Row(BaseModel):
    name: str = "x"


class Middleware:
    def dispatch(self):
        pass


@router.get("/rows")
def list_rows() -> list[Row]:
    return [Row()]


Middleware()
"""
    assert check(_project(tmp_path, app)) == []


def test_what_only_a_test_calls_is_flagged(tmp_path: Path):
    app = "def only_tested():\n    pass\n\n\ndef used():\n    pass\n\n\nused()\n"
    test = "from app import only_tested\n\n\ndef test_it():\n    only_tested()\n"
    root = _project(tmp_path, app, test)
    assert _messages(root) == ["unused function 'only_tested', used only by tests"]


def test_an_allow_needs_a_reason_and_must_excuse_something(tmp_path: Path):
    app = """
# lint: allow(deadcode) the worked example's next step
def kept():
    pass


def unexcused():  # lint: allow(deadcode) —
    pass


# lint: allow(deadcode) nothing below is dead
def used():
    pass


used()
"""
    assert sorted(_messages(_project(tmp_path, app))) == [
        "allow(deadcode) excuses nothing",
        "allow(deadcode) without a reason",
        "unused function 'unexcused'",
    ]
