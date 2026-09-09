# syntax=docker/dockerfile:1.7

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/artifacts/models \
    SENTENCE_TRANSFORMERS_HOME=/app/artifacts/models

WORKDIR /app

RUN groupadd --system --gid 10001 ragops \
    && useradd --system --uid 10001 --gid ragops --home-dir /app ragops

COPY requirements-dev.lock pyproject.toml README.md ./
COPY src ./src

# The checked-in lock file is used for reproducible CPU builds on both amd64 and arm64.
RUN python -m pip install --no-cache-dir -r requirements-dev.lock \
    && python -m pip install --no-cache-dir --no-deps .

COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config
COPY prompts ./prompts
COPY fixtures ./fixtures
COPY evals/baselines ./evals/baselines

RUN mkdir -p /app/artifacts /app/evals/runs \
    && chown -R ragops:ragops /app

USER ragops

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "ragops.api:app", "--host", "0.0.0.0", "--port", "8000"]
