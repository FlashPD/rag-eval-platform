#!/usr/bin/env bash

set -euo pipefail

dataset=${1:?usage: prepare_retrieval_index.sh DATASET SNAPSHOT_PATH}
snapshot_path=${2:?usage: prepare_retrieval_index.sh DATASET SNAPSHOT_PATH}
postgres_url=${RAGOPS_POSTGRES_URL:?RAGOPS_POSTGRES_URL must be set}

case "${dataset}" in
  scifact | nfcorpus | fiqa) ;;
  *)
    echo "unsupported CI dataset: ${dataset}" >&2
    exit 2
    ;;
esac

mkdir -p "$(dirname "${snapshot_path}")"

if [[ -s "${snapshot_path}" ]]; then
  echo "Restoring cached ${dataset} retrieval index from ${snapshot_path}"
  pg_restore \
    --clean \
    --if-exists \
    --exit-on-error \
    --no-owner \
    --no-privileges \
    --dbname "${postgres_url}" \
    "${snapshot_path}"
else
  echo "No cached ${dataset} retrieval index found; building it now"
fi

# Applying migrations after restore supports additive migrations and verifies that
# the snapshot is a valid ragops database. Ingestion is intentionally repeated on
# cache hits: its idempotent path validates the corpus checksum, BM25 artifact,
# embedding configuration, and completed index state without recomputing vectors.
python -m alembic upgrade head
ragops ingest --dataset "${dataset}" --device cpu

if [[ ! -s "${snapshot_path}" ]]; then
  pg_dump \
    --format custom \
    --no-owner \
    --no-privileges \
    --file "${snapshot_path}" \
    "${postgres_url}"
  pg_restore --list "${snapshot_path}" >/dev/null
  echo "Created cacheable ${dataset} retrieval index at ${snapshot_path}"
fi
