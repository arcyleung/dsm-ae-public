#!/usr/bin/env bash
# Restart the SWE-bench-Pro jobs on the Go-free dataset WITHOUT re-running the
# non-Go trials that already completed.
#
# WHY A NEW job_name IS REQUIRED
# ------------------------------
# Harbor refuses to resume a job directory whose stored JobConfig differs from
# the one it is handed (harbor/job.py:253 — `if existing_config != self.config`
# -> FileExistsError). Repointing `datasets[].path` at swebenchpro-nogo is
# exactly such a difference, so the original `runs/swebenchpro-gpt56*` dirs can
# never be resumed under the switched config. This invalidated the assumption
# the switch plan rested on ("Harbor skips completed trials in the same
# jobs_dir") — that holds only when the config is byte-identical.
#
# WHY WE SEED
# -----------
# A fresh job_name starts with an empty directory, so Harbor would re-run the
# 20 non-Go trials already finished (~10h of duplicated agent time). Their
# outputs are on disk and valid, so we copy the completed non-Go trial dirs
# into the new job dir first and let Harbor's per-trial skip logic find them.
#
# Go trials are deliberately NOT seeded: they are unscoreable on this hardware
# (verifier returns tests_run=0) and are absent from the nogo dataset anyway.
#
# Idempotent: re-running skips trials already present at the destination.
set -uo pipefail

DSM=/home/bmc/dsm-dgx
GO_RE='flipt|navidrome|gravitational|future-arch'
log() { echo "$(date -u +%H:%M) $*"; }

for model in gpt56terra gpt56luna; do
  src="$DSM/runs/swebenchpro-$model"
  dst="$DSM/runs/swebenchpro-nogo-$model"
  [ -d "$src" ] || { log "no source dir for $model; skipping"; continue; }
  mkdir -p "$dst"

  copied=0 skipped_go=0 already=0
  for d in "$src"/*/; do
    [ -d "$d" ] || continue
    [ -f "$d/verifier/reward.txt" ] || continue          # only completed trials
    name=$(basename "$d")
    if printf '%s' "$name" | grep -qiE "$GO_RE"; then
      skipped_go=$((skipped_go + 1)); continue
    fi
    if [ -d "$dst/$name" ]; then
      already=$((already + 1)); continue
    fi
    cp -r "$d" "$dst/$name" && copied=$((copied + 1))
  done
  log "$model: seeded $copied (already present $already, Go skipped $skipped_go)"
done

log "seeding complete"
for model in gpt56terra gpt56luna; do
  dst="$DSM/runs/swebenchpro-nogo-$model"
  log "  $dst -> $(find "$dst" -name reward.txt 2>/dev/null | wc -l) rewards present"
done
