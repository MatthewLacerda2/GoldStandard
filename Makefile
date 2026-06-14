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
