.DEFAULT_GOAL := help

CONDA ?= conda
ENV_PREFIX ?= .conda-env
ENV_FILE ?= environment.yml
PYTHON ?= $(ENV_PREFIX)/bin/python
TEST_ARGS ?=

.PHONY: help env install develop lint format check test test-integration build

help:
	@printf '%s\n' \
	  'env               Create the project Conda environment' \
	  'install           Install the package and runtime dependencies' \
	  'develop           Install editable package with test and lint dependencies' \
	  'lint              Check Python code, imports and formatting with Ruff' \
	  'format            Sort imports and format Python code with Ruff' \
	  'check             Run lint and all tests' \
	  'test              Run all tests (TEST_ARGS="-v" for verbose output)' \
	  'test-integration  Run tests against the dummy CMIP6 and decadal pools' \
	  'build             Build a package wheel in dist/' \
	  '' \
	  'Overrides: PYTHON=python TEST_ARGS="-v" ENV_PREFIX=.conda-env'

env:
	$(CONDA) env create --yes --prefix "$(ENV_PREFIX)" --file "$(ENV_FILE)"

install:
	"$(PYTHON)" -m pip install .

develop:
	"$(PYTHON)" -m pip install -e '.[test,lint]'

lint:
	"$(PYTHON)" -m ruff check src tests
	"$(PYTHON)" -m ruff format --check src tests

format:
	"$(PYTHON)" -m ruff check --select I --fix src tests
	"$(PYTHON)" -m ruff format src tests

check: lint test

test:
	"$(PYTHON)" -m pytest $(TEST_ARGS)

test-integration:
	"$(PYTHON)" -m pytest tests/test_realistic_pools.py $(TEST_ARGS)

build:
	"$(PYTHON)" -m pip wheel --no-deps --wheel-dir dist .
