SHELL := /bin/bash

VENV := .venv
PYTHON := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy

.PHONY: help install hooks format lint test check check-secrets verify smoke sbom sbom-nucleus nucleus-smoke

help:
	@printf '%s\n' \
		'install  create .venv and install runtime + dev dependencies' \
		'format   apply ruff formatting and safe fixes' \
		'lint     ruff format/check + mypy --strict' \
		'test     unit tests' \
		'hooks    install the pre-commit hook in .git/hooks' \
		'check    lint + secret guard + test (no Docker required)' \
		'verify   check + local mTLS/spool smoke (Docker required)' \
		'smoke    build the Tier 1 collector images and boot-smoke each (Docker required)' \
		'sbom     generate CycloneDX SBOMs for the collector images (after make smoke)' \
		'sbom-nucleus   generate CycloneDX SBOMs for the nucleus images' \
		'nucleus-smoke  build and verify the offline nucleus on both architectures'

install:
	@if [ ! -x "$(PYTHON)" ]; then uv venv --python 3.12 $(VENV); fi
	uv pip install --python $(PYTHON) -e ".[dev]"

format:
	$(RUFF) format src tests scripts
	$(RUFF) check --fix src tests scripts

lint:
	$(RUFF) format --check src tests scripts
	$(RUFF) check src tests scripts
	$(MYPY) --strict src

test:
	$(PYTEST) -q

check-secrets:
	./scripts/check-secrets.sh

check: lint test check-secrets

hooks:
	$(VENV)/bin/pre-commit install

verify: check
	./scripts/smoke-local.sh

smoke:
	./scripts/smoke-image.sh

sbom:
	./scripts/sbom.sh

sbom-nucleus:
	./scripts/sbom.sh edge-platform-nucleus:arm64 edge-platform-nucleus:amd64

nucleus-smoke:
	./scripts/smoke-nucleus.sh
