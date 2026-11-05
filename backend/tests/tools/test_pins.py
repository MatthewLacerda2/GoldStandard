"""The venv-against-its-pins check every backend gate starts with."""

from importlib import metadata

from tools import pins

REQUIREMENTS = """\
# a comment
ruff==0.17.3
uvicorn[standard] == 0.54.0  # with extras and a comment
httpx>=0.28
-r other.txt
tomli==2.0.1; python_version < "3.11"
"""


def test_only_exact_pins_are_read_with_their_extras_dropped():
    assert pins.pins(REQUIREMENTS) == {"ruff": "0.17.3", "uvicorn": "0.54.0"}


def test_a_pin_off_the_installed_version_or_missing_is_drift():
    pytest_version = metadata.version("pytest")
    problems = pins.drift(
        {"pytest": pytest_version, "ruff": "0.0.1", "not-a-real-package-xyz": "1.0"}
    )
    assert problems == [
        f"ruff is {metadata.version('ruff')}, the pin is 0.0.1",
        "not-a-real-package-xyz is not installed, the pin is 1.0",
    ]


def test_main_fails_with_the_install_step_and_passes_a_match(tmp_path, capsys):
    good, bad = tmp_path / "good.txt", tmp_path / "bad.txt"
    good.write_text(f"pytest=={metadata.version('pytest')}\n")
    bad.write_text("pytest==0.0.1\n")
    assert pins.main([str(good)]) == 0
    assert pins.main([str(good), str(bad)]) == 1
    assert pins.INSTALL in capsys.readouterr().out
