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

restored_snapshot=false
if [[ -s "${snapshot_path}" ]]; then
  echo "Restoring cached ${dataset} retrieval index from ${snapshot_path}"
  if pg_restore --list "${snapshot_path}" >/dev/null && \
    pg_restore \
      --clean \
      --if-exists \
      --exit-on-error \
      --no-owner \
      --no-privileges \
      --dbname "${postgres_url}" \
      "${snapshot_path}"; then
    restored_snapshot=true
  else
    echo "Cached ${dataset} snapshot is unusable; rebuilding it" >&2
    # pg_restore can fail after creating some objects. Reset the dedicated CI
    # database so migrations and ingestion rebuild from a known-empty schema.
    psql \
      --set ON_ERROR_STOP=1 \
      --dbname "${postgres_url}" \
      --command 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
  fi
else
  echo "No cached ${dataset} retrieval index found; building it now"
fi

# Applying migrations after restore supports additive migrations and verifies that
# the snapshot is a valid ragops database. Ingestion is intentionally repeated on
# cache hits: its idempotent path validates the corpus checksum, BM25 artifact,
# embedding configuration, and completed index state without recomputing vectors.
python -m alembic upgrade head
ragops ingest --dataset "${dataset}" --device cpu

if [[ "${restored_snapshot}" != true ]]; then
  temporary_snapshot="${snapshot_path}.tmp"
  trap 'rm -f "${temporary_snapshot}"' EXIT
  pg_dump \
    --format custom \
    --no-owner \
    --no-privileges \
    --file "${temporary_snapshot}" \
    "${postgres_url}"
  pg_restore --list "${temporary_snapshot}" >/dev/null
  mv "${temporary_snapshot}" "${snapshot_path}"
  trap - EXIT
  echo "Created cacheable ${dataset} retrieval index at ${snapshot_path}"
fi
