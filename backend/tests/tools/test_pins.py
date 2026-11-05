"""The venv-against-its-pins check every backend gate starts with."""

from importlib import metadata

import pytest

from tools import pins

REQUIREMENTS = """\
# a comment
ruff==0.17.3
uvicorn[standard] == 0.54.0  # with extras and a comment
httpx>=0.28
-r other.txt
tomli==2.0.1; python_version < "3.11"
fastapi==0.162.0 \\
    --hash=sha256:abc \\
    --hash=sha256:def
pytest==9.2.0 --no-binary pytest
mypkg===1.0-custom
"""


def test_exact_pins_are_read_past_extras_options_and_continuations():
    assert pins.pins(REQUIREMENTS) == {
        "ruff": ("==", "0.17.3"),
        "uvicorn": ("==", "0.54.0"),
        "fastapi": ("==", "0.162.0"),
        "pytest": ("==", "9.2.0"),
        "mypkg": ("===", "1.0-custom"),
    }


def test_a_pin_off_the_installed_version_or_missing_is_drift():
    problems = pins.drift(
        {
            "pytest": ("==", metadata.version("pytest")),
            "ruff": ("==", "0.0.1"),
            "not-a-real-package-xyz": ("==", "1.0"),
        }
    )
    assert problems == [
        f"ruff is {metadata.version('ruff')}, the pin is 0.0.1",
        "not-a-real-package-xyz is not installed, the pin is 1.0",
    ]


@pytest.mark.parametrize(
    ("pinned", "installed"),
    [("2.0", "2.0.0"), ("2.0.0", "2"), ("1!2.0rc1", "1!2.0.0rc1"), ("2.0", "2.0+cpu")],
)
def test_versions_compare_as_pep_440_equality(pinned: str, installed: str):
    assert pins._mismatch("==", pinned, installed) is None


@pytest.mark.parametrize(
    ("pinned", "installed"),
    [("2.0", "2.0.1"), ("2.0", "2.0rc1"), ("2.0", "2.0.post1"), ("2.0+cpu", "2.0+gpu")],
)
def test_a_different_release_or_label_is_drift(pinned: str, installed: str):
    assert pins._mismatch("==", pinned, installed) is not None


def test_a_pin_it_cannot_compare_fails_with_a_reason():
    assert "cannot be checked" in pins._mismatch("==", "1.*", "1.4")
    assert pins._mismatch("===", "1.0", "1.0.0") is not None


def test_main_fails_with_the_install_step_and_passes_a_match(tmp_path, capsys):
    good, bad = tmp_path / "good.txt", tmp_path / "bad.txt"
    good.write_text(f"pytest=={metadata.version('pytest')}\n")
    bad.write_text("pytest==0.0.1\n")
    assert pins.main([str(good)]) == 0
    assert pins.main([str(good), str(bad)]) == 1
    assert pins.INSTALL in capsys.readouterr().out


def test_a_file_with_no_readable_pin_fails(tmp_path, capsys):
    empty = tmp_path / "requirements.txt"
    empty.write_text("# nothing\n-r other.txt\nhttpx>=0.28\n")
    assert pins.main([str(empty)]) == 1
    assert "has no == pin this check can read" in capsys.readouterr().out
