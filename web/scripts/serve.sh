#!/usr/bin/env bash
# Detached Vite preview for the Vue blog. Survives the CLI session.
#   bash web/scripts/serve.sh          # start (default)
#   bash web/scripts/serve.sh stop
#   bash web/scripts/serve.sh status
#   bash web/scripts/serve.sh restart
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WEB="$ROOT/web"
LOG="$ROOT/logs/dsm-ae-blog.log"
PIDFILE="$ROOT/logs/dsm-ae-blog.pid"
PORT=4174
URL="http://127.0.0.1:${PORT}/dsm-ae-blog/"

running_pid() {
  if [[ -f "$PIDFILE" ]]; then
    local pid
    pid="$(tr -d '[:space:]' <"$PIDFILE" || true)"
    if [[ -n "${pid}" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
      return 0
    fi
  fi
  return 1
}

port_pids() {
  ss -tlnp 2>/dev/null | awk -v p=":${PORT}" '$4 ~ p"$" {print}' \
    | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u
}

cmd_status() {
  local pid
  if pid="$(running_pid)"; then
    echo "running pid=${pid} ${URL}"
    return 0
  fi
  echo "stopped"
  return 1
}

cmd_stop() {
  local pid
  if pid="$(running_pid)"; then
    kill "$pid" 2>/dev/null || true
    sleep 0.4
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
  echo "stopped"
}

cmd_start() {
  local pid
  if pid="$(running_pid)"; then
    echo "already running pid=${pid} ${URL}"
    return 0
  fi
  mkdir -p "$ROOT/logs"
  cd "$WEB"
  npm run build
  # Drop a leftover listener on 4174 (session-tied preview, stale vite).
  local extra
  extra="$(port_pids || true)"
  if [[ -n "${extra}" ]]; then
    echo "${extra}" | xargs -r kill 2>/dev/null || true
    sleep 0.4
    extra="$(port_pids || true)"
    if [[ -n "${extra}" ]]; then
      echo "${extra}" | xargs -r kill -9 2>/dev/null || true
      sleep 0.2
    fi
  fi
  : >"$LOG"
  # New session so a Grok/CLI process-group teardown does not kill vite.
  setsid npm run preview >>"$LOG" 2>&1 </dev/null &
  pid=$!
  echo "$pid" >"$PIDFILE"
  local i
  for i in $(seq 1 40); do
    if curl -sf -o /dev/null "$URL"; then
      echo "started pid=${pid} ${URL}"
      echo "log ${LOG}"
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "failed to start; last log:" >&2
      tail -n 40 "$LOG" >&2 || true
      rm -f "$PIDFILE"
      return 1
    fi
    sleep 0.25
  done
  echo "started pid=${pid} but ${URL} did not answer yet; see ${LOG}" >&2
  return 1
}

case "${1:-start}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status) cmd_status ;;
  *)
    echo "usage: $0 {start|stop|restart|status}" >&2
    exit 2
    ;;
esac
