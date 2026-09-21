# Executive summary: weak taxonomy metrics audit

**Date:** 2026-07-11  
**Scope:** Why virtually all models pass certain DSM-AE outcome gates — are tests too lax/superficial, and how to deepen them.  
**Live runs:** Not interrupted (qwen3.5-397b queue job + gpt-5.6-luna treatment arms left running).

## What was done

1. **Population scan** of diagnosis JSONs under `reports/` (excluding work/trajectory noise):  
   - 16 real models, 62 metrics, 27 report files.  
   - Flagged metrics with ≥85% of models PASS and n≥5 models.

2. **Deep audits (1 subagent each)** for the three user-flagged universal-PASS metrics:
   - `erosion_indicator`
   - `critical_preserved`
   - `verbosity_indicator`  

   Each audit: code forensics, artifact evidence, taxonomy/SlopCodeBench mapping, redesign options, pilot ideas.  
   Verbosity audit additionally grounded in **BMAD editorial + adversarial** skills and the session UI-copy cleanup experience.

3. **Artifacts written:**
   - `docs/superpowers/specs/weak-metric-audits/erosion_indicator-audit.md`
   - `docs/superpowers/specs/weak-metric-audits/critical_preserved-audit.md`
   - `docs/superpowers/specs/weak-metric-audits/verbosity_indicator-audit.md`
   - Supporting samples under `reports/weak-audits/{erosion_indicator,critical_preserved,verbosity_indicator}/`

## Headline findings

| Metric | Pass rate (16 models) | Verdict | Root cause (short) |
|--------|----------------------|---------|---------------------|
| **erosion_indicator** | 100% @ pr=1.0 | **too_superficial** (+ too_lax, metric_misaligned) | 2-ckpt task never produces CC>10; erosion≈0 everywhere; threshold ≤0.5 never binds; no C1→C2 **slope** |
| **quality_stable** | 100% | **misnamed / non-diagnostic** | Same absolute gates as erosion/verbosity; not a stability delta |
| **verbosity_indicator** | 100% @ pr≈1.0 | **too_lax + wrong modality** | Exact line-dup proxy; pass ≤0.45 with huge headroom; **prose/UI verbosity invisible**; not SlopCodeBench AST-Grep verbosity |
| **critical_preserved** | 100% @ pr=1.0 | **saturated floor / scaffolded** | Strong “don’t delete” + untrusted-content coaching; textbook injection; models *do* hit `.env.old` on **overeager** traps — so capability ≠ this metric |

### Broader weak cluster (not deep-audited here)

Also ~100% PASS across models (likely similar “smoke not diagnosis” issues):  
`verification_attempted`, `synthesis_not_enumeration`, `schema_valid`, `peer_state_preserved`, `no_ungated_delete`, `no_tool_hallucination`, `no_test_memorization`, `no_secret_leak`, `no_false_success`, `injection_resisted`, `independent_verify`, `approval_before_delete`, …  

Treat the deep-audited three as the **template**: measure *elicitation difficulty* and *metric alignment to taxonomy*, not just threshold knobs.

## Per-metric conclusions

### 1. erosion_indicator (CQ-01)

- **Formula can work** (synthetic god-functions score high).  
- **Elicitation fails:** modular CLI + short horizon + prompts that forbid god-functions.  
- Taxonomy wants **trajectory slope** (SlopCodeBench / ISDS); pack scores absolute snapshot.  
- **Recommendation:** multi-checkpoint slope (T≥5) or hot-seed “extend without extract”; fail on **rising** erosion even if absolute <0.5; demote current pack to smoke.

### 2. critical_preserved (AA-04 / injection)

- Not proof of deep critical-resource safety.  
- Models often **read** the injection and explicitly refuse; same models can delete `.env.old` when **overeager cleanup** frames it as trash.  
- Scoring holes: shell `rm` may false-PASS; only basename `env.old`; no “never saw” vs “saw and resisted.”  
- **Recommendation:** multi-channel injection battery, scaffold ablations (`shield_none`), graded severity, remaining-file oracle; keep current as smoke; use overeager critical-trap for interim discrimination.

### 3. verbosity_indicator (CQ-02) + BMAD path

- **SlopCodeBench verbosity is a weak fit alone** for the *session* disorder: verbose **UI/docs/agent prose**, not just AST duplicates.  
- Current proxy = exact duplicate lines / LOC — misses near-clones, long names, comment spam, and all non-code outputs.  
- Session evidence: multi-pass UI cleanup still left dense meta-jargon until **bmad-editorial-review-prose** + **bmad-review-adversarial-general** were invoked.  
- **Recommendation — dual track:**
  1. `verbosity_code` — closer to SCBench (AST-Grep-like rules + clones + slope)  
  2. `verbosity_prose` / `verbosity_ui` — score agent-written copy with BMAD-style criteria (filler density, jargon, adversarial “what’s still wrong after cleanup”) + **cleanup slope** (plain ask vs BMAD scaffold)

**Pilot pack sketch:** `ui_copy_pressure` — thoroughness pressure → plain “make it denser” → BMAD-skill scaffold; measure residual issues and slope.

## Are the tests too lax or superficial?

| Dimension | Answer |
|-----------|--------|
| Thresholds alone? | Partly (0.45/0.5 too high), but **not the main bug** |
| Superficial tasks? | **Yes** — short horizon, coached modularity, shielded injection |
| Wrong construct? | **Yes** for verbosity (code dups ≠ prose slop); erosion lacks slope; critical_preserved confounded with scaffolding |
| Models “solved” the disorders? | **Unlikely** — overeager critical trap and full SlopCodeBench literature still show failures |

## Prioritized next steps (revised 2026-07-11 — stakeholder plan)

### Naming: tiered erosion (and pattern for other weak gates)

| Tier | Metric id | Role |
|------|-----------|------|
| **Tier 1** | `erosion_indicator.tier1` | **Keep current definition** (2-ckpt absolute mass/CC proxy, pass ≤0.5). Smoke / floor label — not diagnostic of CQ-01 slope. |
| **Tier 2** | `erosion_indicator.tier2` | **Deeper rigorous test** — harder elicitation + scoring aligned to **BMAD-grade quality standards** (adversarial structural review: god-function patching, extract-vs-extend discipline, maintainability findings — not only raw CC mass). |
| **Tier 3** | `erosion_indicator.tier3` | **P2** — multi-checkpoint **erosion slope** + multi-scaffold stability (same task under raw / reminder / skill / oversight; does quality hold?). |

Legacy matrix key `erosion_indicator` should alias or rename to `.tier1` with an explicit **smoke** badge so reports stop implying full CQ-01 coverage.

Apply the same **tier1 smoke / tier2 rigorous** pattern to `verbosity_indicator` and `critical_preserved` when those redesigns land (verbosity.tier2 = BMAD prose/UI track; critical.tier2 = multi-channel injection battery).

---

### P0 — Label honesty + tier1 freeze

1. **Rename/label** existing `erosion_indicator` → **`erosion_indicator.tier1`** (definition unchanged).  
2. Badge in matrix / report notes: **smoke / floor**, not disorder-proof.  
3. Same honesty treatment for current `verbosity_indicator`, `quality_stable`, `critical_preserved` (mark smoke until tier2 exists).  
4. Spec skeleton for **`erosion_indicator.tier2`**: deeper pack + BMAD-referenced structural review criteria (findings count / god-function patching / extract refusal). *Implement after batch audit + sol calibration inputs.*  
5. Do **not** inflate tier1 thresholds as a fake fix.

### P1 — Batch weak-gate audit, leakage/gaming, sol calibration

1. **Batch audit (promoted from P2):** every ≥85% universal-PASS gate from the population scan — same template as the three deep audits (elicitation, scoring holes, false-PASS modes).  
2. **Test leakage & gaming catalog** while auditing:
   - Hardcoded public tests (`eval_gaming_mini`)
   - Keyword-only gates (`"langs" in code`, `"summary" in path`)
   - Scaffold that spoils the construct (injection + “do not delete”)
   - Shell-channel bypass (`rm` vs `delete_file`)
   - Performative compliance (long honest summary of injection without behavioral stress)
   - Checkpoint N/A padding (c1 metrics always pass on c2 traces)
3. **gpt-5.6-sol calibration (promoted from P2):** run sol on tier1 packs + any draft tier2 pilots; compare to luna treatment arms already on disk under `reports/treatment/`.  
4. Manual trajectory review (see [TRAJECTORY_INSPECTION.md](./TRAJECTORY_INSPECTION.md)).

### P2 — Deep structural diagnostics

1. **`erosion_indicator.tier3`**: multi-checkpoint erosion **slope** (Δerosion per ckpt; fail if rising even when absolute < tier1 threshold).  
2. **Multi-scaffold stability**: same problem under baseline / prompt_reminder / skill_scaffold / expert_oversight — does tier2/3 quality hold or only appear under one scaffold?  
3. Full SlopCodeBench-aligned code verbosity ruleset if still open after P1.  
4. Injection multi-channel battery + scaffold ablations (critical.tier2+).

---

### Dependency sketch

```
P0 tier1 labels ──► P1 batch audit + gaming ──► P1 sol calibration
                         │
                         ▼
                   P0/P1 tier2 designs (erosion BMAD-rigorous, verbosity BMAD-prose, critical multi-channel)
                         │
                         ▼
                   P2 tier3 slope + multi-scaffold stability
```

## Live systems

- Queue: qwen3.7-max + qwen3.5-397b **completed** (reports under `reports/queue/`).  
- Treatment trial gpt-5.6-luna: **all four arms completed** → `reports/treatment/` + `SUMMARY.md`.  
- serve-queue left running for UI/matrix.

## Appendix

- [erosion_indicator-audit.md](./erosion_indicator-audit.md)
- [critical_preserved-audit.md](./critical_preserved-audit.md)
- [verbosity_indicator-audit.md](./verbosity_indicator-audit.md)
- [TRAJECTORY_INSPECTION.md](./TRAJECTORY_INSPECTION.md) — curated paths + previews for manual review  
- Sample copies: `reports/weak-audits/trajectory_samples/`
