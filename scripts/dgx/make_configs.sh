#!/usr/bin/env bash
# Generate the four Harbor job configs (2 benchmarks x 2 models) on the DGX.
# Run ON THE DGX.
#
# Concurrency rationale: models.yaml pins rpm=6 for gpt-5.6-terra and
# gpt-5.6-luna. n_concurrent_trials=2 per job keeps at most 8 agents in flight
# across all four jobs, which stays inside the endpoint budget while still
# making progress. Do not raise this without also raising rpm.
set -euo pipefail

ROOT=/home/bmc/dsm-dgx
mkdir -p "$ROOT/configs"

for bench in swebenchpro nl2repobench; do
  for model in terra luna; do
    cat > "$ROOT/configs/${bench}-${model}.yaml" <<EOF
# DSM-AE ~10% sample run: ${bench} x gpt-5.6-${model}
# Sample is fixed by reports/behaviour-task/sample-manifest.json (seed 42).
job_name: ${bench}-gpt56${model}
jobs_dir: ${ROOT}/runs
n_attempts: 1
orchestrator:
  type: local
  n_concurrent_trials: 2
  quiet: false
environment:
  type: docker
  force_build: true
  delete: true
agents:
  - name: opencode
    model_name: openai/gpt-5.6-${model}
    kwargs:
      version: 1.18.18
datasets:
  - path: ${ROOT}/datasets/${bench}
EOF
    echo "wrote $ROOT/configs/${bench}-${model}.yaml"
  done
done
