# Single task runner. CI invokes these exact targets so local and CI never drift.
# Override the interpreter in CI with: make backend PYTHON=python
# Locally a venv is used: make backend PYTHON=.venv/bin/python (see backend/README note).

PYTHON ?= python3.14
BUN    ?= bun
# tools/ code is stdlib-only, so it runs on a plain interpreter of its own
# (PYTHON may be a path relative to backend/), and docs-lint and the tools
# tests need nothing installed.
TOOLS_PYTHON ?= python3.14
# Linting tools/ does need ruff, and it is the backend's: the version pinned in
# backend/requirements-dev.txt and the rules in backend/pyproject.toml, so the
# two cannot disagree. Locally it is the backend venv's (`make back-install`),
# and tools-lint fails if that venv has drifted from the pin; CI installs the
# same pin and passes RUFF=ruff.
RUFF ?= backend/.venv/bin/ruff
RUFF_PIN := $(shell sed -n 's/^ruff==//p' backend/requirements-dev.txt)

.DEFAULT_GOAL := check

# ---------------------------------------------------------------------------
# Aggregate gates
# ---------------------------------------------------------------------------
.PHONY: check backend frontend
check: tools backend frontend

backend: back-lint back-build back-test
frontend: front-lint front-build front-test front-contract

# ---------------------------------------------------------------------------
# Repository tools  (tools/: stdlib-only Python serving the whole repo)
# ---------------------------------------------------------------------------
# CI runs this on every change, Markdown-only ones included, so a check that
# reads the docs belongs here, as a target `tools` lists beside `docs-lint`.
# docs-lint goes first: it needs nothing installed, so a docs-only change gets
# its verdict even where tools-lint has no ruff to run.
.PHONY: tools tools-lint docs-lint
tools: docs-lint tools-lint
	$(TOOLS_PYTHON) -m unittest discover --start-directory tools/tests --top-level-directory .
	$(TOOLS_PYTHON) tools/markers.py

tools-lint:
	@found="$$($(RUFF) --version 2>/dev/null)"; [ "$$found" = "ruff $(RUFF_PIN)" ] || { \
		echo "tools-lint: $(RUFF) is '$${found:-missing}', the pin is ruff $(RUFF_PIN): run make back-install"; exit 1; }
	$(RUFF) check --config backend/pyproject.toml tools
	$(RUFF) format --check --config backend/pyproject.toml tools

# The size and shape of what an agent loads: CLAUDE.md files and skills.
docs-lint:
	$(TOOLS_PYTHON) -m tools.docs_lint

# ---------------------------------------------------------------------------
# Backend gates  (run from backend/, driven by $(PYTHON))
# ---------------------------------------------------------------------------
.PHONY: back-lint back-build back-test back-install openapi
back-lint:
	cd backend && $(PYTHON) -m ruff check .
	cd backend && $(PYTHON) -m ruff format --check .
	cd backend && $(PYTHON) tools/house_lint.py

# Imports the app (the build) and checks frontend/openapi.json, the contract
# the frontend's types are held to, against what its endpoints answer.
back-build:
	cd backend && $(PYTHON) -m tools.openapi_contract --check

# Regenerate frontend/openapi.json after a response model changes.
openapi:
	cd backend && $(PYTHON) -m tools.openapi_contract --write

back-test:
	cd backend && $(PYTHON) -m pytest

back-install:
	cd backend && $(PYTHON) -m venv --clear .venv
	cd backend && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt

# ---------------------------------------------------------------------------
# Frontend gates  (run from frontend/, driven by $(BUN))
# ---------------------------------------------------------------------------
.PHONY: front-lint front-build front-test front-contract front-install
front-lint:
	cd frontend && $(BUN) run check

front-build:
	cd frontend && $(BUN) run build

front-test:
	cd frontend && $(BUN) run test

# The frontend's types against frontend/openapi.json: fields unread,
# undeclared or phantom, and requests it cannot pair with an endpoint.
front-contract:
	cd frontend && $(BUN) run contract

front-install:
	cd frontend && $(BUN) install

# ---------------------------------------------------------------------------
# Repository setup  (run once in a repo made from this template; needs `gh`)
# ---------------------------------------------------------------------------
# The issue labels CLAUDE.md's rules are written against. `--force` updates a
# label that already exists, such as GitHub's stock `documentation`; the stock
# labels that overlap these, and labels this set has retired, are deleted (`-`:
# already gone is fine).
.PHONY: labels
labels:
	gh label create infrastructure --force --color D93F0B --description "Tools and guardrails for the development process: CI, gates, harnesses."
	gh label create architecture   --force --color B60205 --description "The project's structure and conventions: layer boundaries, API contracts, formats."
	gh label create fix            --force --color EE0701 --description "Something broken or overlooked (a missing translation key counts)."
	gh label create foundation     --force --color 0E8A16 --description "Groundwork inside the app that later features stand on."
	gh label create feat           --force --color A2EEEF --description "A new capability or resource."
	gh label create refactor       --force --color C5DEF5 --description "A big change, beside its type: flags the PR for the independent review."
	gh label create documentation  --force --color 0075CA --description "Edit/add documentation; never waits its turn."
	gh label create planning       --force --color FBCA04 --description "Changes a decision or the design, or not settled yet. Do not start."
	gh label create human          --force --color 5319E7 --description "Needs a human in the loop end to end. Do not start."
	gh label create agent          --force --color F95F2B --description "Filed by an agent on its own; treated like any other issue."
	gh label create dependencies   --force --color 0386F6 --description "A Dependabot bump (.github/dependabot.yml)."
	-@for l in bug enhancement duplicate invalid question wontfix "good first issue" "help wanted" minor; do \
		gh label delete "$$l" --yes 2>/dev/null; done

# ---------------------------------------------------------------------------
# Developer reports  (run by hand; never a gate, never in CI or a batch)
# ---------------------------------------------------------------------------
# Where this repository's Claude Code tokens went since SINCE (YYYY-MM-DD, UTC;
# default 7 days ago): main session against subagents, by role and by model,
# and the context per merged pull request. It reads this machine's local
# transcripts only (no cloud session, no other machine, no plan limits), and
# asks GitHub through `gh` for what merged; ARGS=--no-prs skips that. No agent
# runs it during its work. `--help` says how it counts.
.PHONY: claude-usage
claude-usage:
	$(TOOLS_PYTHON) -m tools.claude_usage $(if $(SINCE),--since $(SINCE)) $(ARGS)

# ---------------------------------------------------------------------------
# Batch reports  (run by hand; read-only, not a gate, so not in `make check`)
# ---------------------------------------------------------------------------
# Every unticked item under a `## For a human` heading on a pull request
# merged since SINCE (ISO 8601, UTC), as Markdown to paste into a report, then
# the open issues carrying both `planning` and `human`. REST only, through `gh`.
.PHONY: checks
checks:
	@test -n "$(SINCE)" || { echo "checks: since when? e.g. make checks SINCE=2026-01-31T18:00:00Z (UTC)" >&2; exit 1; }
	@$(TOOLS_PYTHON) -m tools.human_checks --since "$(SINCE)"
