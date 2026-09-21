#!/usr/bin/env bash
# Switch the SWE-bench-Pro jobs onto the Go-free dataset.
#
# Go is not measurable on this aarch64 box: the Go runtime dies under
# qemu-x86_64 (lfstack / SIGSEGV) on a clean checkout with no agent involved,
# and every mitigation failed (GOMAXPROCS=1, asyncpreemptoff, GOGC=off). The
# trials do not fail cheaply -- the agent runs to completion (10-34 min) and
# only then does the verifier return tests_run=0, which HarborTrial.scoreable
# correctly refuses to score.
#
# WHY THIS DOES NOT WAIT FOR A FULL DRAIN
# ---------------------------------------
# The first version waited for the live-trial count to reach zero. That
# condition is unreachable: with ~50 tasks still queued per job, Harbor
# backfills a new trial the moment one finishes, so the count oscillates
# (observed 4 -> 3 -> 4) and never settles. A gate on an unreachable condition
# is a gate that never fires.
#
# Instead we wait for a *low-water moment* -- when the work that would be
# discarded is small -- and then switch. Concretely: proceed as soon as no
# in-flight trial has more than MAX_LOST_BYTES of agent output. Trials at 0B
# are still in setup and lose nothing; a trial mid-reasoning has hundreds of KB
# and is worth waiting out. Every in-flight task is re-queued by the relaunch
# (Harbor skips only *completed* trials), so an interrupted trial is re-run,
# not lost from the sample.
#
# Orphans are excluded from the live set: Harbor reaps a timed-out trial
# (writes exception.txt) but leaves its container running at ~100% CPU
# forever, so counting those would block indefinitely.
set -uo pipefail

DSM=/home/bmc/dsm-dgx
MAX_LOST_BYTES=${MAX_LOST_BYTES:-20000}   # ~20KB: setup / first few steps only
MAX_WAIT_MIN=${MAX_WAIT_MIN:-90}          # cap: Go spend outweighs a partial trial
log() { echo "$(date -u +%H:%M) $*"; }

# Largest agent-output size among genuinely live trials (0 if none).
#
# Measured over a bounded tail, and only over *printable* bytes. Raw file size
# is not a usable proxy for "how much reasoning would be lost": an agent that
# cats a binary into its transcript inflates it without doing any work. One
# trial hit 198MB at ~25MB/min this way, 33% of it non-printable machine code,
# which would have pinned the gate open forever. Capping the sample at 2MB
# also keeps this cheap when a transcript is enormous.
peak_live_bytes() {
  local peak=0 d base lower oc sz
  for d in "$DSM"/runs/swebenchpro-*/*/; do
    [ -d "$d" ] || continue
    [ -f "$d/verifier/reward.txt" ] && continue   # finished
    [ -f "$d/exception.txt" ] && continue         # reaped; container may orphan
    oc="$d/agent/opencode.txt"
    [ -f "$oc" ] || continue
    base=$(basename "$d")
    lower=$(printf '%s' "$base" | tr '[:upper:]' '[:lower:]')
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qi -- "$lower" || continue
    sz=$(tail -c 2000000 "$oc" 2>/dev/null | tr -dc '[:print:][:space:]' | wc -c)
    [ "$sz" -gt "$peak" ] && peak=$sz
  done
  printf '%s' "$peak"
}

deadline=$(( $(date +%s) + MAX_WAIT_MIN * 60 ))
while :; do
  peak=$(peak_live_bytes)
  if [ "$peak" -le "$MAX_LOST_BYTES" ]; then
    log "low-water reached (peak ${peak}B <= ${MAX_LOST_BYTES}B); switching"
    break
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    log "waited ${MAX_WAIT_MIN}m (peak ${peak}B); switching anyway — interrupted trials are re-queued"
    break
  fi
  log "peak live agent output ${peak}B; waiting"
  sleep 180
done

log "stopping swebenchpro sessions"
tmux kill-session -t dsm-swebenchpro-terra 2>/dev/null || true
tmux kill-session -t dsm-swebenchpro-luna 2>/dev/null || true
sleep 3

log "repointing configs at swebenchpro-nogo"
sed -i 's|datasets/swebenchpro$|datasets/swebenchpro-nogo|' \
  "$DSM"/configs/swebenchpro-terra.yaml \
  "$DSM"/configs/swebenchpro-luna.yaml
grep -H 'path:.*swebenchpro' \
  "$DSM"/configs/swebenchpro-terra.yaml \
  "$DSM"/configs/swebenchpro-luna.yaml

log "relaunching on 43 non-Go tasks (concurrency 2)"
"$DSM"/launch_runs.sh swebenchpro-terra swebenchpro-luna
sleep 20
log "post-relaunch: sessions=$(tmux ls 2>/dev/null | grep -c dsm-swebenchpro) harbor_procs=$(pgrep -fc harbor || echo 0)"
tmux ls
