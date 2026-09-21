#!/usr/bin/env bash
# Standalone treatment trial on gpt-5.6-luna — does NOT touch serve-queue.
set -euo pipefail
cd "$(dirname "$0")/.."
MODEL="${MODEL:-gpt-5.6-luna}"
YAML="${YAML:-models.yaml}"
K="${K:-2}"
J="${J:-2}"
PACKS="${PACKS:-tool_integrity,handoff_mini,mas_verify_mini,coord_tax_mini,overeager_mini,pii_safety,injection_mini,sycophancy_mini,eval_gaming_mini}"
OUT_DIR="reports/treatment"
WORK_ROOT="reports/work/treatment_luna"
LOG_DIR="logs/treatment"
mkdir -p "$OUT_DIR" "$WORK_ROOT" "$LOG_DIR"

# baseline + three treatments
ARMS=("" "prompt_reminder" "skill_scaffold" "expert_oversight")
NAMES=("baseline" "prompt_reminder" "skill_scaffold" "expert_oversight")

echo "TREATMENT_TRIAL_START model=$MODEL k=$K packs=$PACKS at=$(date -Is)" | tee "$LOG_DIR/luna_trial.log"

for i in "${!ARMS[@]}"; do
  arm="${ARMS[$i]}"
  name="${NAMES[$i]}"
  safe_name="${name//\//_}"
  out_md="$OUT_DIR/${MODEL//\//_}-${safe_name}.md"
  out_json="$OUT_DIR/${MODEL//\//_}-${safe_name}.json"
  work="$WORK_ROOT/${safe_name}"
  logf="$LOG_DIR/${safe_name}.log"
  echo "=== ARM $name start $(date -Is) ===" | tee -a "$LOG_DIR/luna_trial.log"
  args=(
    dsm-ae diagnose
    -m "$MODEL"
    --models-yaml "$YAML"
    -p "$PACKS"
    --k "$K"
    -j "$J"
    --work-dir "$work"
    -o "$out_md"
    --json "$out_json"
  )
  if [[ -n "$arm" ]]; then
    args+=(--treatment "$arm")
  fi
  # progress helper
  (
    set +e
    "${args[@]}" >"$logf" 2>&1
    ec=$?
    echo "=== ARM $name exit=$ec $(date -Is) ===" | tee -a "$LOG_DIR/luna_trial.log"
    if [[ $ec -ne 0 ]]; then
      echo "ARM_FAILED $name" | tee -a "$LOG_DIR/luna_trial.log"
      tail -40 "$logf" | tee -a "$LOG_DIR/luna_trial.log"
    else
      echo "ARM_OK $name -> $out_json" | tee -a "$LOG_DIR/luna_trial.log"
      python3 - << PY
import json
from pathlib import Path
p=Path("$out_json")
if p.is_file():
    d=json.loads(p.read_text())
    present=[f for f in d.get("findings") or [] if f.get("present")]
    fail=[g for g in d.get("gates") or [] if g.get("status") in ("FAIL","UNSTABLE") or g.get("disorder")]
    print(f"  findings_present={len(present)} disorder_gates={len(fail)}")
    for f in present[:8]:
        print(f"    FIND {f.get('code')} {f.get('severity')}")
PY
    fi
  )
done

echo "TREATMENT_TRIAL_DONE $(date -Is)" | tee -a "$LOG_DIR/luna_trial.log"

# Compare summary
python3 - << 'PY'
import json
from pathlib import Path
out = Path("reports/treatment")
model = "gpt-5.6-luna".replace("/", "_")
arms = ["baseline", "prompt_reminder", "skill_scaffold", "expert_oversight"]
rows = []
for arm in arms:
    p = out / f"{model}-{arm}.json"
    if not p.is_file():
        rows.append((arm, "MISSING", None, None))
        continue
    d = json.loads(p.read_text())
    present = sum(1 for f in d.get("findings") or [] if f.get("present"))
    disorder = sum(1 for g in d.get("gates") or [] if g.get("disorder"))
    pass_gates = sum(1 for g in d.get("gates") or [] if str(g.get("status")) == "PASS")
    rows.append((arm, "ok", present, disorder, pass_gates, len(d.get("gates") or [])))

lines = ["# Treatment trial summary (gpt-5.6-luna)", "", "| Arm | Status | Findings present | Disorder gates | PASS gates |", "|-----|--------|------------------|----------------|------------|"]
for r in rows:
    if r[1] == "MISSING":
        lines.append(f"| {r[0]} | MISSING | — | — | — |")
    else:
        lines.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]}/{r[5]} |")
Path("reports/treatment/SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
PY
