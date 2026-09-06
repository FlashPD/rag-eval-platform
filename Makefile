.PHONY: install format lint typecheck test check run db-upgrade db-downgrade

PYTHON := .venv/bin/python

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements-dev.lock
	$(PYTHON) -m pip install --no-deps -e .

format:
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

lint:
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy

test:
	$(PYTHON) -m pytest

check: lint typecheck test

run:
	$(PYTHON) -m uvicorn ragops.api:app --reload

db-upgrade:
	$(PYTHON) -m alembic upgrade head

db-downgrade:
	$(PYTHON) -m alembic downgrade -1
