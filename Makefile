# Single task runner. CI invokes these exact targets so local and CI never drift.
# Override the interpreter in CI with: make backend PYTHON=python
# Locally a venv is used: make backend PYTHON=.venv/bin/python (README, Getting started).

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
# Clone setup and the pre-commit hook  (`make setup` once per clone)
# ---------------------------------------------------------------------------
# One setting in the repository config, so it covers every worktree of the
# clone at once. It replaces any hooks path set before, which also stops hooks
# kept in .git/hooks from running. The path is relative to each worktree, so a
# worktree on a branch that predates .githooks/ runs no hook at all.
.PHONY: setup pre-commit-scope pre-commit pre-commit-back pre-commit-front back-fix front-fix
setup:
	git config core.hooksPath .githooks
	@echo "setup: each commit and merge now runs 'make pre-commit' (.githooks/), in every worktree of this clone."
	@echo "setup: hooks in .git/hooks no longer run, and a branch without .githooks/ runs none."
	@echo "setup: to commit work in progress anyway, use 'git commit --no-verify'."

# The layers the index changes, as one loop: the hook reads it through
# `pre-commit-scope`, and a `make pre-commit` by hand reads it here.
staged_layers = for l in backend frontend; do git diff --cached --quiet -- $$l || echo $$l; done
STAGED_LAYERS ?= $(shell $(staged_layers))

# The hook runs this while git's environment still points at the index being
# committed, and passes what it prints to `pre-commit`. The lint gates read the
# working tree, so a touched layer whose files on disk are not what the commit
# lands is refused: lint would judge something other than the commit. That is
# an unstaged edit, an untracked file, or, under `git commit <path>`, a staged
# file the pathspec leaves out.
pre-commit-scope:
	@layers="$(STAGED_LAYERS)"; for l in $$layers; do \
		if ! git diff --quiet -- $$l || [ -n "$$(git ls-files --others --exclude-standard -- $$l)" ]; then \
			echo "pre-commit: $$l/ has changes that are not part of this commit, and lint reads the files on disk." >&2; \
			git diff --name-only -- $$l | sed 's/^/pre-commit:   /' >&2; \
			git ls-files --others --exclude-standard -- $$l | sed 's/^/pre-commit:   /' >&2; \
			echo "pre-commit: stage what belongs and commit without a path, or unstage the rest and set it" >&2; \
			echo "pre-commit: aside: git stash push --keep-index --include-untracked" >&2; \
			exit 1; \
		fi; \
	done; echo $$layers

# What .githooks/pre-commit runs: each touched layer's lint gate, never its
# tests or build. A layer the commit does not touch is skipped and says so; a
# touched one whose tools are not installed fails rather than passing unchecked.
# A fast check that reads the whole repository joins the prerequisites here.
# docs-lint is one: it reads the docs on disk, which pre-commit-scope does not
# compare with the index.
pre-commit: docs-lint pre-commit-back pre-commit-front
	@echo "pre-commit: ok"

pre-commit-back:
	@if [ -z "$(filter backend,$(STAGED_LAYERS))" ]; then \
		echo "pre-commit: backend skipped, nothing staged under backend/."; \
	elif ! (cd backend && $(PYTHON) -m ruff --version) >/dev/null 2>&1; then \
		echo "pre-commit: no ruff for PYTHON=$(PYTHON) (run from backend/): run 'make back-install'."; \
		exit 1; \
	elif ! $(MAKE) --no-print-directory back-lint; then \
		echo "pre-commit: backend lint failed. Fix: make back-fix PYTHON=$(PYTHON) (file and test length by hand)."; \
		exit 1; \
	fi

pre-commit-front:
	@if [ -z "$(filter frontend,$(STAGED_LAYERS))" ]; then \
		echo "pre-commit: frontend skipped, nothing staged under frontend/."; \
	elif ! command -v $(BUN) >/dev/null 2>&1 || [ ! -x frontend/node_modules/.bin/eslint ]; then \
		echo "pre-commit: no $(BUN) on PATH, or frontend/node_modules missing: install Bun, then 'make front-install'."; \
		exit 1; \
	elif ! $(MAKE) --no-print-directory front-lint; then \
		echo "pre-commit: frontend lint failed. Fix: make front-fix (type errors by hand)."; \
		exit 1; \
	fi

# What a failed lint points at. Every fixer runs even when one leaves errors
# behind, the formatter last, and the target fails if a fixer left errors.
# House-lint findings and type errors are not theirs: those are fixed by hand.
back-fix:
	cd backend && { $(PYTHON) -m ruff check --fix .; s=$$?; $(PYTHON) -m ruff format . && exit $$s; }

front-fix:
	cd frontend && { $(BUN) run eslint --fix .; s=$$?; $(BUN) run prettier --write . && exit $$s; }

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
