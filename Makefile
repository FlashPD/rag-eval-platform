.PHONY: install format lint typecheck test check run eval-run db-upgrade db-downgrade stack-up stack-up-full stack-down stack-logs infra-fmt infra-validate

PYTHON := .venv/bin/python
RAGOPS := .venv/bin/ragops
DATASET ?= fixture
VARIANTS ?= bm25
SEED ?= 42

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

eval-run:
	$(RAGOPS) eval run --dataset $(DATASET) --variants $(VARIANTS) --seed $(SEED) $(if $(SAMPLE_SIZE),--sample-size $(SAMPLE_SIZE))

db-upgrade:
	$(PYTHON) -m alembic upgrade head

db-downgrade:
	$(PYTHON) -m alembic downgrade -1

stack-up:
	docker compose up --build -d

stack-up-full:
	docker compose --profile langfuse up --build -d

stack-down:
	docker compose down

stack-logs:
	docker compose logs --follow api worker otel-collector

infra-fmt:
	terraform fmt -recursive infra

infra-validate:
	terraform -chdir=infra/bootstrap init -backend=false
	terraform -chdir=infra/bootstrap validate
	terraform -chdir=infra/aws init -backend=false
	terraform -chdir=infra/aws validate
