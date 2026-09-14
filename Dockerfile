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

# Preinstall the CPU-only wheel before resolving the cross-platform lock. Without
# this, PyPI's Linux torch metadata pulls several gigabytes of unused CUDA libraries.
RUN TORCH_VERSION=$(sed -n 's/^torch==//p' requirements-dev.lock) \
    && test -n "${TORCH_VERSION}" \
    && python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==${TORCH_VERSION}" \
    && python -m pip install --no-cache-dir -r requirements-dev.lock \
    && python -m pip install --no-cache-dir --no-deps . \
    && python -c "import torch; assert torch.version.cuda is None" \
    && python -m pip uninstall --yes pip setuptools

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
