# Single task runner. CI invokes these exact targets so local and CI never drift.
# Override the interpreter in CI with: make backend PYTHON=python
# Locally a venv is used: make backend PYTHON=.venv/bin/python (see backend/README note).

PYTHON ?= python3.12
BUN    ?= bun

.DEFAULT_GOAL := check

# ---------------------------------------------------------------------------
# Aggregate gates
# ---------------------------------------------------------------------------
.PHONY: check backend frontend
check: backend frontend

backend: back-lint back-build back-test
frontend: front-lint front-build front-test

# ---------------------------------------------------------------------------
# Backend gates  (run from backend/, driven by $(PYTHON))
# ---------------------------------------------------------------------------
.PHONY: back-lint back-build back-test back-install
back-lint:
	cd backend && $(PYTHON) -m ruff check .
	cd backend && $(PYTHON) -m ruff format --check .
	cd backend && $(PYTHON) tools/house_lint.py

back-build:
	cd backend && $(PYTHON) -c "import main"

back-test:
	cd backend && $(PYTHON) -m pytest

back-install:
	cd backend && python3.12 -m venv .venv
	cd backend && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# ---------------------------------------------------------------------------
# Frontend gates  (run from frontend/, driven by $(BUN))
# ---------------------------------------------------------------------------
.PHONY: front-lint front-build front-test front-install
front-lint:
	cd frontend && $(BUN) run check

front-build:
	cd frontend && $(BUN) run build

front-test:
	cd frontend && $(BUN) run test

front-install:
	cd frontend && $(BUN) install

# ---------------------------------------------------------------------------
# Repository setup  (run once in a repo made from this template; needs `gh`)
# ---------------------------------------------------------------------------
# The issue labels CLAUDE.md's rules are written against. `--force` updates a
# label that already exists, such as GitHub's stock `bug` and `documentation`;
# the stock labels that overlap these are deleted (`-`: already gone is fine).
.PHONY: labels
labels:
	gh label create infrastructure --force --color D93F0B --description "Tools and guardrails for the development process: CI, gates, harnesses."
	gh label create architecture   --force --color B60205 --description "The project's structure and conventions: layer boundaries, API contracts, formats."
	gh label create bug            --force --color EE0701 --description "Something isn't working."
	gh label create foundation     --force --color 0E8A16 --description "Groundwork that makes the template more complete."
	gh label create feature        --force --color A2EEEF --description "A new capability or resource."
	gh label create documentation  --force --color 0075CA --description "Edit/add documentation; never waits its turn."
	gh label create planning       --force --color FBCA04 --description "Changes a decision or the design, or not settled yet. Do not start."
	gh label create human          --force --color 5319E7 --description "Needs a human in the loop end to end. Do not start."
	gh label create agent          --force --color F95F2B --description "Filed by an agent on its own; treated like any other issue."
	gh label create dependencies   --force --color 0386F6 --description "A Dependabot bump (.github/dependabot.yml)."
	-@for l in enhancement duplicate invalid question wontfix "good first issue" "help wanted"; do \
		gh label delete "$$l" --yes 2>/dev/null; done
