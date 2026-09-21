#!/usr/bin/env bash
# DSM-AE container entrypoint — serve WebUI + optional embedded worker.
set -euo pipefail

cd "${DSM_AE_HOME:-/app}"

mkdir -p reports data logs work data/job_secrets reports/queue/progress

# Bootstrap models.yaml from example if operator did not mount one
if [[ ! -f models.yaml ]]; then
  if [[ -f models.yaml.example ]]; then
    echo "[dsm-ae] models.yaml missing — copying models.yaml.example (offline mock works; add keys for live endpoints)"
    cp models.yaml.example models.yaml
  else
    echo "[dsm-ae] WARNING: no models.yaml and no example — live diagnose will fail"
  fi
fi

HOST="${DSM_AE_HOST:-0.0.0.0}"
PORT="${DSM_AE_PORT:-8765}"
PUBLIC_BASE="${DSM_AE_PUBLIC_BASE:-/dsm-ae}"
DB="${DSM_AE_DB:-data/queue.db}"
REPORTS="${DSM_AE_REPORTS_DIR:-reports}"
MODELS_YAML="${DSM_AE_MODELS_YAML:-models.yaml}"
POLL="${DSM_AE_WORKER_POLL:-2}"
STALE="${DSM_AE_STALE_SECONDS:-3600}"
TOKEN_ARGS=()
if [[ -n "${DSM_AE_QUEUE_TOKEN:-}" ]]; then
  TOKEN_ARGS+=(--token "${DSM_AE_QUEUE_TOKEN}")
fi

WORKER_FLAG="--with-worker"
if [[ "${DSM_AE_WITH_WORKER:-1}" == "0" || "${DSM_AE_WITH_WORKER:-1}" == "false" ]]; then
  WORKER_FLAG="--no-worker"
fi

YAML_ARGS=()
if [[ -f "${MODELS_YAML}" ]]; then
  YAML_ARGS+=(--models-yaml "${MODELS_YAML}")
fi

echo "[dsm-ae] starting serve-queue host=${HOST} port=${PORT} public_base=${PUBLIC_BASE} worker=${WORKER_FLAG}"
exec dsm-ae serve-queue \
  --host "${HOST}" \
  --port "${PORT}" \
  --public-base "${PUBLIC_BASE}" \
  --db "${DB}" \
  --reports-dir "${REPORTS}" \
  --poll "${POLL}" \
  --stale-seconds "${STALE}" \
  ${WORKER_FLAG} \
  "${YAML_ARGS[@]}" \
  "${TOKEN_ARGS[@]}"
