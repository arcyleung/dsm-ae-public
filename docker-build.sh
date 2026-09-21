#!/usr/bin/env bash
# One-command production deploy: build image, start WebUI + benchmark worker.
#
# Usage:
#   ./docker-build.sh              # build + up -d
#   ./docker-build.sh --no-cache   # rebuild from scratch
#   ./docker-build.sh --down       # stop stack
#   ./docker-build.sh --logs       # follow logs
#   ./docker-build.sh --smoke      # up + offline mock enqueue + once health
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

RED=$'\033[0;31m'
GRN=$'\033[0;32m'
YLW=$'\033[0;33m'
NC=$'\033[0m'

log()  { printf '%s[dsm-ae]%s %s\n' "$GRN" "$NC" "$*"; }
warn() { printf '%s[dsm-ae]%s %s\n' "$YLW" "$NC" "$*"; }
die()  { printf '%s[dsm-ae]%s %s\n' "$RED" "$NC" "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "missing dependency: $1"; }

need docker
docker compose version >/dev/null 2>&1 || die "docker compose plugin required (Docker Compose v2+)"

# Optional LFS for reports/
if command -v git-lfs >/dev/null 2>&1; then
  git lfs install --local >/dev/null 2>&1 || true
  log "git-lfs available — reports/** will use LFS when committed"
else
  warn "git-lfs not installed — install with: sudo apt-get install -y git-lfs && git lfs install"
  warn "You can still run the stack; commit reports with LFS after installing."
fi

ACTION="up"
NO_CACHE=0
SMOKE=0
for arg in "$@"; do
  case "$arg" in
    --down) ACTION="down" ;;
    --logs) ACTION="logs" ;;
    --no-cache) NO_CACHE=1 ;;
    --smoke) SMOKE=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *) die "unknown arg: $arg" ;;
  esac
done

if [[ "$ACTION" == "down" ]]; then
  docker compose down
  log "stack stopped"
  exit 0
fi
if [[ "$ACTION" == "logs" ]]; then
  docker compose logs -f dsm-ae
  exit 0
fi

# Bootstrap local config
if [[ ! -f .env ]]; then
  cp .env.example .env
  log "created .env from .env.example"
fi
if [[ ! -f models.yaml ]]; then
  cp models.yaml.example models.yaml
  warn "created models.yaml from example — edit api_base/api_key for live endpoints"
fi

mkdir -p reports data logs work data/job_secrets reports/queue/progress

# Free publish port if an old host serve-queue is still bound
PORT_CHECK="$(grep -E '^DSM_AE_PUBLISH_PORT=' .env 2>/dev/null | cut -d= -f2- || true)"
PORT_CHECK="${PORT_CHECK:-8765}"
if command -v ss >/dev/null 2>&1; then
  if ss -ltn 2>/dev/null | grep -qE ":${PORT_CHECK}\\b"; then
    warn "port ${PORT_CHECK} is in use — stopping host process via PID file if present"
    if [[ -f logs/serve-queue.pid ]]; then
      oldpid="$(cat logs/serve-queue.pid 2>/dev/null || true)"
      if [[ -n "${oldpid}" ]] && kill -0 "${oldpid}" 2>/dev/null; then
        kill "${oldpid}" 2>/dev/null || true
        sleep 1
        kill -9 "${oldpid}" 2>/dev/null || true
      fi
    fi
    # Kill listeners on the port by PID from ss (not pkill -f self-match)
    if command -v fuser >/dev/null 2>&1; then
      fuser -k "${PORT_CHECK}/tcp" 2>/dev/null || true
      sleep 1
    fi
    if ss -ltn 2>/dev/null | grep -qE ":${PORT_CHECK}\\b"; then
      die "port ${PORT_CHECK} still in use. Free it or set DSM_AE_PUBLISH_PORT in .env"
    fi
    log "port ${PORT_CHECK} free"
  fi
fi

BUILD_ARGS=(build)
if [[ "$NO_CACHE" == "1" ]]; then
  BUILD_ARGS+=(--no-cache)
fi

log "building image…"
docker compose "${BUILD_ARGS[@]}"

log "starting stack…"
docker compose up -d

# Wait for health
PORT="$(grep -E '^DSM_AE_PUBLISH_PORT=' .env 2>/dev/null | cut -d= -f2- || true)"
PORT="${PORT:-8765}"
BASE="$(grep -E '^DSM_AE_PUBLIC_BASE=' .env 2>/dev/null | cut -d= -f2- || true)"
BASE="${BASE:-/dsm-ae}"
BASE="${BASE%/}"

log "waiting for health on :${PORT}…"
ok=0
for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 0.5
done
[[ "$ok" == "1" ]] || die "service did not become healthy — try: docker compose logs dsm-ae"

HEALTH="$(curl -fsS "http://127.0.0.1:${PORT}/api/health")"
log "healthy: ${HEALTH}"

if [[ "$SMOKE" == "1" ]]; then
  log "smoke: enqueue offline mock job via CLI in container"
  docker compose exec -T dsm-ae \
    dsm-ae queue enqueue -m mock/well_attuned -p hello_metacog --k 1 --label docker-smoke \
    --db data/queue.db || warn "enqueue smoke failed (worker may still pick jobs from UI)"
  sleep 3
  docker compose exec -T dsm-ae dsm-ae queue list --db data/queue.db --limit 5 || true
fi

cat <<MSG

${GRN}DSM-AE is up${NC}

  WebUI:     http://localhost:${PORT}${BASE}/
  Matrix:    http://localhost:${PORT}${BASE}/matrix
  API docs:  http://localhost:${PORT}${BASE}/docs
  Health:    http://localhost:${PORT}/api/health

Add / refresh endpoints:
  1. Edit ${YLW}models.yaml${NC} (api_base, api_key, rpm per model_name)
  2. Restart worker path:  ${YLW}docker compose restart dsm-ae${NC}
  3. Enqueue from UI or:
       docker compose exec dsm-ae dsm-ae queue enqueue \\
         -m <model_name> --full-suite --k 10 --label prod-run

Logs:   ./docker-build.sh --logs
Stop:   ./docker-build.sh --down

Reports live in ./reports (commit with Git LFS — see README).
MSG
