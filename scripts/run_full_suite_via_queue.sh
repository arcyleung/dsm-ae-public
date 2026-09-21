#!/usr/bin/env bash
# Enqueue full-suite diagnosis jobs and drain them with the queue worker.
# Preferred multi-model path (durable queue + matrix rebuild). Offline scripts
# under scripts/run_full_suite_*.sh remain for legacy/in-flight runs.
#
# Usage:
#   ./scripts/run_full_suite_via_queue.sh                    # default: GPT models
#   ./scripts/run_full_suite_via_queue.sh mock/well_attuned   # mock (no models.yaml)
#   MODELS="gpt-5.6-terra gpt-5.6-sol" ./scripts/run_full_suite_via_queue.sh
#   K=1 J=1 RPM=  ./scripts/run_full_suite_via_queue.sh mock/well_attuned
#
# Env:
#   MODELS          space-separated model ids (overrides argv)
#   K               bootstrap trials (default 3)
#   J               pack×trial concurrency (default 2)
#   RPM             optional rpm override (default: unset → models.yaml)
#   MODELS_YAML     credentials file (default models.yaml; unused for mock/*)
#   REPORTS_DIR     report root (default reports)
#   DB              queue sqlite path (default data/queue.db)
#   SKIP_WORKER     if set, only enqueue (do not run worker)
set -euo pipefail
cd "$(dirname "$0")/.."

K="${K:-3}"
J="${J:-2}"
MODELS_YAML="${MODELS_YAML:-models.yaml}"
REPORTS_DIR="${REPORTS_DIR:-reports}"
DB="${DB:-data/queue.db}"

if [[ -n "${MODELS:-}" ]]; then
  # shellcheck disable=SC2206
  MODEL_LIST=($MODELS)
elif [[ $# -gt 0 ]]; then
  MODEL_LIST=("$@")
else
  MODEL_LIST=(gpt-5.6-terra gpt-5.6-sol)
fi

echo "===== enqueue full suite $(date -Is) ====="
echo "models: ${MODEL_LIST[*]}"
echo "k=$K concurrency=$J db=$DB reports=$REPORTS_DIR"

ENQUEUE_EXTRA=()
if [[ -n "${RPM:-}" ]]; then
  ENQUEUE_EXTRA+=(--rpm "$RPM")
fi

for M in "${MODEL_LIST[@]}"; do
  safe=$(echo "$M" | tr './' '_')
  dsm-ae queue enqueue \
    -m "$M" \
    --full-suite \
    --k "$K" \
    -j "$J" \
    --label "${safe}-full" \
    --db "$DB" \
    "${ENQUEUE_EXTRA[@]+"${ENQUEUE_EXTRA[@]}"}"
done

dsm-ae queue list --db "$DB" || true

if [[ -n "${SKIP_WORKER:-}" ]]; then
  echo "===== SKIP_WORKER set; not starting worker ====="
  exit 0
fi

WORKER_EXTRA=()
# models.yaml only needed for live models; mock/* works offline
needs_yaml=0
for M in "${MODEL_LIST[@]}"; do
  case "$M" in
    mock/*) ;;
    *) needs_yaml=1 ;;
  esac
done
if [[ "$needs_yaml" -eq 1 ]]; then
  if [[ ! -f "$MODELS_YAML" ]]; then
    echo "error: $MODELS_YAML not found (credentials/rate-limits only; see models.yaml.example)" >&2
    exit 1
  fi
  WORKER_EXTRA+=(--models-yaml "$MODELS_YAML")
fi

echo "===== worker drain $(date -Is) ====="
dsm-ae worker \
  --db "$DB" \
  --reports-dir "$REPORTS_DIR" \
  --once \
  "${WORKER_EXTRA[@]+"${WORKER_EXTRA[@]}"}"

echo "===== done $(date -Is) ====="
echo "matrix: ${REPORTS_DIR}/dsm-ae-matrix.html"
echo "status: dsm-ae queue list --db $DB"
