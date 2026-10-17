SHELL := /bin/bash

VENV := .venv
PYTHON := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy

.PHONY: help install format lint test check verify smoke

help:
	@printf '%s\n' \
		'install  create .venv and install runtime + dev dependencies' \
		'format   apply ruff formatting and safe fixes' \
		'lint     ruff format/check + mypy --strict' \
		'test     unit tests' \
		'check    lint + test (no Docker required)' \
		'verify   check + local mTLS/spool smoke (Docker required)' \
		'smoke    build both Tier 1 images and boot-smoke each (Docker required)'

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

check: lint test

verify: check
	./scripts/smoke-local.sh

smoke:
	./scripts/smoke-image.sh
