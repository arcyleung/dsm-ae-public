#!/usr/bin/env bash
# Launch the four DSM-AE benchmark runs on the DGX, in tmux so they survive
# disconnection. Run this ON THE DGX (it is uploaded to ~/dsm-dgx by the
# operator flow described in scripts/dgx/README-runs.md).
#
#   ./launch_runs.sh                # all four
#   ./launch_runs.sh swebenchpro-terra
#
# Concurrency is deliberately low: models.yaml pins rpm=6 for both gpt-5.6
# models, so n_concurrent_trials=2 per job (4 jobs => <=8 in flight) keeps the
# endpoint well inside its budget while still using the box.
set -euo pipefail

ROOT=/home/bmc/dsm-dgx
export PATH="$HOME/harbor-venv/bin:$PATH"
# SWE-bench-Pro and NL2Repo images are amd64-only; the DGX is aarch64 and runs
# them under the qemu-x86_64 binfmt emulator installed via tonistiigi/binfmt.
export DOCKER_DEFAULT_PLATFORM=linux/amd64

mkdir -p "$ROOT/logs" "$ROOT/runs"

# Emulated x86 is slow: agent setup (apt-get install nodejs npm for opencode)
# blows the default 360s budget, so multiply setup generously.
COMMON_FLAGS=(
  --env-file "$ROOT/.env.models"
  --agent-setup-timeout-multiplier 12
  --agent-timeout-multiplier 2
  --verifier-timeout-multiplier 4
  --max-retries 1
)

launch() {
  local job="$1"
  local session="dsm-$job"
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "SKIP $job (tmux session '$session' already exists)"
    return
  fi
  tmux new-session -d -s "$session" \
    "harbor run -c $ROOT/configs/$job.yaml ${COMMON_FLAGS[*]} \
       > $ROOT/logs/$job.log 2>&1"
  echo "LAUNCHED $job -> tmux session '$session', log $ROOT/logs/$job.log"
}

JOBS=("$@")
if [ ${#JOBS[@]} -eq 0 ]; then
  JOBS=(swebenchpro-terra swebenchpro-luna nl2repobench-terra nl2repobench-luna)
fi

for j in "${JOBS[@]}"; do launch "$j"; done

echo
echo "Sessions:"; tmux ls 2>/dev/null || true
