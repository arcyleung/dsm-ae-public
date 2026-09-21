#!/bin/bash
set -euo pipefail

# Harbor verifier phase entrypoint for dsm-ae/erosion_tier2
mkdir -p /logs/verifier

python - <<'PY'
from pathlib import Path
from dsm_ae.harbor.pack_bridge import score_workspace, write_reward

# Score the workspace produced (or fall back to mock trial inside score_workspace).
# For real agent runs, trajectories/ from agent phase (litellm etc) should be
# present under the work_root so score loads real MetricResults instead of re-mocking.
metrics = score_workspace("erosion_tier2", Path("/app"), trial_index=0)
write_reward(metrics, Path("/logs/verifier/reward.json"))
print("DSM-AE Harbor verifier: reward.json written for erosion_tier2")
print(metrics)
PY