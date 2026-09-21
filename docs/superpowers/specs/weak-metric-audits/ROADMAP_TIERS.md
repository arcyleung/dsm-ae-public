# Weak-metric roadmap (stakeholder-aligned)

**Date:** 2026-07-11  
**Updated:** 2026-07-11 (P0–P2 implementation pass)

## Erosion tiers

| Id | Status | Definition |
|----|--------|------------|
| `erosion_indicator.tier1` | **Done** — dual-emitted with legacy `erosion_indicator` | Current 2-ckpt absolute proxy (`analyze_code`, pass ≤0.5); smoke/floor badge |
| `erosion_indicator.tier2` | **Done** — pack `erosion_tier2` | Hot-seed + extend-without-extract; BMAD structural (god-mass, patch-into-hot, extract-refusal) |
| `erosion_indicator.tier3` | **Done** — pack `erosion_tier3` | Multi-checkpoint (≥4) erosion slope; fail if rising even when abs <0.5 |

## Tool integrity / task_tool_success tiers

| Id | Status | Definition |
|----|--------|------------|
| `task_tool_success` / `.tier1` | **Done** — smoke | String oracle on final_text / done message (pack `tool_integrity`) |
| `task_tool_success.tier2` | **Done** — pack `tool_integrity_tier2` | Moderate + hard grounded chain (list→read gold→done); hard injects one gold-read error; M∧H rollup; axes + failure modes |

## Priority board

### P0
- [x] Alias/rename matrix metric → `.tier1` + smoke badge
- [x] Smoke-label verbosity / critical_preserved / quality_stable
- [x] Draft tier2 erosion pack + BMAD structural criteria (**implemented**, not spec-only)

### P1
- [x] Batch audit remaining universal-PASS gates → `BATCH_WEAK_GATES.md` + `scripts/generate_batch_weak_gates.py`
- [x] Leakage/gaming catalog → `GAMING_AND_LEAKAGE.md`
- [x] gpt-5.6-sol calibration harness → `scripts/run_tier2_sol_calibration.sh` (DRY_RUN mock; parent starts live sol)
- [ ] Manual trajectory pass using TRAJECTORY_INSPECTION.md

### P2
- [x] `erosion_indicator.tier3` slope pack
- [x] Multi-scaffold stability harness → `scripts/run_tier2_multi_scaffold.sh`
- [ ] critical/verbosity tier2+ if not pulled into P1 (verbosity.tier2 prose/BMAD **deferred**; critical multi-channel **deferred**)

## Artifacts

- Executive summary: `EXECUTIVE_SUMMARY.md`
- Deep audits: `*-audit.md`
- Trajectories: `TRAJECTORY_INSPECTION.md`
- Batch weak gates: `BATCH_WEAK_GATES.md`
- Gaming/leakage: `GAMING_AND_LEAKAGE.md`

## Commands (sol tier2 calibration)

```bash
# Offline mock dry-run (no network)
DRY_RUN=1 bash scripts/run_tier2_sol_calibration.sh

# Live gpt-5.6-sol (does not touch serve-queue)
MODEL=gpt-5.6-sol K=2 J=2 bash scripts/run_tier2_sol_calibration.sh
# optional: INCLUDE_TIER3=1

# Multi-scaffold stability (baseline + 3 treatments)
DRY_RUN=1 bash scripts/run_tier2_multi_scaffold.sh
MODEL=gpt-5.6-sol K=2 bash scripts/run_tier2_multi_scaffold.sh

# Refresh batch weak-gate table
python3 scripts/generate_batch_weak_gates.py
```

Work: `reports/work/tier2_sol/` · Out: `reports/tier2/`
