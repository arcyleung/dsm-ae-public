#!/usr/bin/env bash
# Pull finished Harbor run bundles from the DGX into evalhub-runs/ as .tar.gz,
# matching the layout the existing bundles use so src/dsm_ae/harbor/ ingests
# them unchanged:  <run>/<instance>/agent/trajectory.json
#                  <run>/<instance>/verifier/reward.txt
#                  <run>/<instance>/result.json
#
# Usage:
#   scripts/dgx/pull_results.sh              # list what is available
#   scripts/dgx/pull_results.sh <run-dir>    # fetch one (name under ~/dsm-dgx/runs)
#   scripts/dgx/pull_results.sh --all
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SSH="$REPO_ROOT/scripts/dgx/dgx_ssh.sh"
REMOTE_RUNS=/home/bmc/dsm-dgx/runs
DEST="$REPO_ROOT/evalhub-runs"

if [ $# -eq 0 ]; then
  echo "Available runs on the DGX:"
  "$SSH" "ls -1 $REMOTE_RUNS 2>/dev/null"
  echo
  echo "Fetch one with: $0 <run-dir>   (or --all)"
  exit 0
fi

if [ "$1" == "--all" ]; then
  mapfile -t RUNS < <("$SSH" "ls -1 $REMOTE_RUNS 2>/dev/null")
else
  RUNS=("$@")
fi

mkdir -p "$DEST"
for run in "${RUNS[@]}"; do
  [ -z "$run" ] && continue
  echo "==> $run"
  # Tar on the remote side and stream it back; avoids a second copy on the DGX.
  "$SSH" "cd $REMOTE_RUNS && tar czf - '$run'" > "$DEST/${run}_output.tar.gz"
  echo "    wrote $DEST/${run}_output.tar.gz ($(du -h "$DEST/${run}_output.tar.gz" | cut -f1))"
done

echo
echo "Extract for the adapter with:"
echo "  mkdir -p $REPO_ROOT/evalhub-extract && \\"
echo "  for f in $DEST/*_output.tar.gz; do tar xzf \"\$f\" -C $REPO_ROOT/evalhub-extract; done"
