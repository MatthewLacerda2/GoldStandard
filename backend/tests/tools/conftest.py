"""A throwaway git repository shaped like this one, for the mutation tools'
tests: ``main`` holds a sensitive ``backend/utils/guard.py``, a hash-only entry
and an ordinary ``backend/services/fuel.py``, and the working tree is the PR's
branch (``gate_repo.py`` holds the source and the helper).

Built once per session and copied for each test: a copy costs no git process.
"""

import shutil
from pathlib import Path

import pytest

from tests.tools.gate_repo import GUARD, GUARD_SOURCE, SENSITIVE_LIST, Repo


@pytest.fixture(scope="session")
def _template_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    repo = Repo(tmp_path_factory.mktemp("gate-template"))
    repo.git("init", "--quiet", "--initial-branch=main")
    repo.git("config", "user.email", "gate@example.com")
    repo.git("config", "user.name", "gate")
    repo.git("config", "commit.gpgsign", "false")
    repo.write("backend/mutation-sensitive.txt", SENSITIVE_LIST)
    repo.write(GUARD, GUARD_SOURCE)
    repo.write("backend/services/fuel.py", "def litres(n):\n    return n * 2\n")
    repo.write(".gitignore", "mutants/\n")
    repo.commit()
    # What `make back-mutate-diff` and the gate compare against.
    repo.git("update-ref", "refs/remotes/origin/main", "HEAD")
    repo.git("checkout", "--quiet", "-b", "feat/change")
    return repo.root


@pytest.fixture
def repo(_template_repo: Path, tmp_path: Path) -> Repo:
    root = tmp_path / "repo"
    shutil.copytree(_template_repo, root, symlinks=True)
    return Repo(root)
