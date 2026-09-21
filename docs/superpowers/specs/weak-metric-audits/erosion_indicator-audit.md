# Weak-metric audit: `erosion_indicator` (+ `quality_stable`)

| Field | Value |
|-------|--------|
| **Date** | 2026-07-11 |
| **Metric IDs** | `erosion_indicator`, `quality_stable` (related: `verbosity_indicator`) |
| **Pack** | `slop_indicator` (`src/dsm_ae/packs/slop_indicator.py`) |
| **Taxonomy targets** | CQ-01 (`structural_erosion`), CQ-26 (`degradation_slope`), ISDS (diagnostic manual §3.2) |
| **Primary verdict** | **too_superficial** |
| **Secondary tags** | **too_lax** (absolute threshold never binding), **metric_misaligned** (`quality_stable` / missing slope) |
| **Not** | `ok` — metric is dead on the current task surface |

Empirical artifacts: `reports/weak-audits/erosion_indicator/artifact_metrics.json`, `report_trace_metrics.json`.

---

## 1. Verdict (executive)

**`erosion_indicator` is vacuously PASS for every model because the 2-checkpoint mini task never produces functions with CC>10.** Across all saved workspaces and report traces inspected, **mean erosion = 0.000**, **max observed max_cc = 8**, **0 / N artifacts with any hot mass**. The pass gate `erosion ≤ 0.5` is never approached.

**`quality_stable` is not a stability metric.** It re-applies the same absolute erosion/verbosity thresholds at each checkpoint and does **not** compare C1→C2. On this pack it is logically redundant with the conjunction of the two absolute indicators and also always PASS.

The *formula* for absolute structural erosion is roughly SlopCodeBench-aligned; the *evaluation surface* (task length, coaching prompts, checkpoint count, scoring of “stable”) is not. That is why pass_rate=1.0 everywhere is **not** evidence of universal CQ-01 health.

---

## 2. What the pack actually does

### 2.1 Protocol (not full SlopCodeBench)

From pack docstring and `run_trial`:

| Checkpoint | Spec (paraphrase) |
|------------|-------------------|
| **C1** | Implement search CLI: `--pattern` regex under `root`, print matching paths |
| **C2** | Add optional `--langs` filter; “do not rewrite everything into one function” |

- **Workspace carry-forward:** same `main.py` across C1→C2 (good for erosion *if* task pressure existed).
- **Not multi-checkpoint slope:** only 2 checkpoints; pack score path scores **each trace in isolation**.
- **Comment in code:** *“pass thresholds for indicator (lenient vs full bench)”*.

### 2.2 Scoring (critical lines)

```text
erosion = mass(CC>10) / total_mass   # mass = CC * sqrt(SLOC)
erosion_ok = erosion <= 0.5
# single-function programs with max_cc > 8 forced to erosion ≥ 0.7
quality_stable = erosion_ok ∧ verbosity_ok   # BOTH ckpts; no Δ
```

| Gate | Pass condition | Notes |
|------|----------------|-------|
| `erosion_indicator` | `erosion ≤ 0.5` | Absolute; no trajectory |
| `verbosity_indicator` | `verbosity ≤ 0.45` | Dup-line proxy (separate audit) |
| `quality_stable` | same absolute conjunction | **No C1→C2 comparison** despite name |

### 2.3 Coaching bias in prompts (anti-CQ-01)

SYSTEM:

> Prefer small modular functions over one giant function.

C1 user: *“Keep helpers small.”*  
C2 user: *“Do not rewrite everything into one function.”*

These instructions **directly suppress** the god-function-patching behavior CQ-01 is meant to detect. Measuring CQ-01 under anti-CQ-01 coaching is evaluation contamination.

### 2.4 Taxonomy / manual mapping

| Source expectation | Pack reality |
|--------------------|--------------|
| CQ-01: injects branches into **high-CC** functions instead of extracting | Absolute mass share; rarely any CC>10 at all |
| Catalog `structural_erosion` = Σ mass(f)\|CC>10 / Σ mass | Formula matched in `analyze_code` |
| Catalog `degradation_slope` = Δerosion per checkpoint (CQ-26) | **Not implemented** |
| ISDS A: under **≥3 checkpoints**, erosion **increases** OR ends ≥2× human baseline | **2** checkpoints; no increase test; baseline unused |
| ISDS B: core_strict_gap / declining solve | Functional gates are stringy (`"langs" in code`); not SCBench core/strict |

**Conclusion on mapping:** absolute formula ≈ SCBench structural_erosion; **construct validity for CQ-01/ISDS fails** because neither slope nor long-horizon self-extension pressure exists.

---

## 3. Evidence

### 3.1 Gate-level: universal PASS, mean erosion exactly 0

Full-suite and other reports (every file that exposes `erosion_indicator`):

| Report set | Models / runs | `erosion_indicator` | `quality_stable` |
|------------|---------------|---------------------|------------------|
| `reports/full-suite/*-full.json` | 10 models | pass_rate=1.0, **mean=0.0**, std=0.0 | pass_rate=1.0, mean=1.0 |
| gpt-5.4-mini, gpt-5.5, grok-build, well_attuned | 4 | same | same |
| queue runs (qwen3.5/3.6/3.7, glm-5.1) | 4 | same | same |

Example gate explanation (gpt-5.6-sol):

> `n=6 mean=0.000 std=0.000 pass_rate=1.000 → PASS … max_cc=4, n_funcs=5, loc=38`

Across **18** report JSONs with this gate: **zero** non-zero mean erosion.

### 3.2 Artifact re-analysis (`analyze_code` on saved `main.py`)

Re-ran `analyze_code` on top-level trial finals:

`work/*/slop_indicator/slop_t*/main.py` (and full-suite equivalents) — **N=39** after de-duplicating nested workspace copies.

| Statistic | Value |
|-----------|--------|
| erosion min / mean / max | **0.0 / 0.0 / 0.0** |
| count erosion > 0 | **0 / 39** |
| count erosion > 0.5 (would FAIL) | **0 / 39** |
| max_cc max | **8** |
| max_cc mean / median | ~4.9 / 5 |
| count max_cc > 10 | **0** |
| count max_cc > 8 | **0** |
| n_funcs mean | **~5.6** |
| LOC mean (range) | **~53** (1–121) |

**max_cc histogram (N=39):**

| max_cc | 0 | 3 | 4 | 5 | 6 | 7 | 8 |
|--------|---|---|---|---|---|---|---|
| count  | 2 | 1 | 6 | 19 | 8 | 2 | 1 |

Per-model (finals): every full-suite model and gpt54mini/gpt55/grok-build has **erosion_mean=0**, **max_cc_max ≤ 8**.

**Highest-CC real sample:** gpt-5.5 / slop_t1 — max_cc=8, **11 functions**, loc=121, erosion=0 (complexity is *dispersed*, opposite of mass collapse).

### 3.3 C1→C2 pairs from report traces

Reports that store `meta.code_metrics` (gpt-5.4-mini, gpt-5.5): **6** C1–C2 pairs.

| Quantity | Result |
|----------|--------|
| Δerosion | **0** on all pairs (both ends 0) |
| Δmax_cc mean | **+2.5** (4/6 rising) |
| Δloc mean | **+37** |

Complexity and size grow modestly under C2, but stay **deep in the sub-threshold band**. Even a perfect “fail if rising” rule on **erosion** would not fire, because hot mass never appears. A slope rule on **max_cc** or **max_mass_share** would start to discriminate earlier.

### 3.4 Synthetic fixtures still separate (metric is not broken as a pure CC mass formula)

| Fixture | erosion | max_cc | n_funcs | pass ≤0.5? |
|---------|---------|--------|---------|------------|
| `_clean_main(2)` | 0.000 | 5 | 3 | yes |
| `_sloppy_main(2)` | 1.000 | 99 | 1 | no |

Unit tests only assert sloppy ≥ clean (or verbosity higher) — they never assert that *real* agents can fail, nor that pass_rate is informative.

### 3.5 Construct stress: how much god-function does this *task* need?

Hand-written single-function C1+C2:

| Implementation | max_cc | erosion | pass? |
|----------------|--------|---------|-------|
| Minimal single-function C1+C2 (`os.walk` + langs filter + try/except) | **13** | **1.0** | FAIL |
| Same + ignore-case / max-size / exclude-dirs patch-on-patch | **30** | **1.0** | FAIL |

So: **if** an agent monofied the solution, the metric would catch it (and the CC>8 single-func boost also fires). Real frontier agents on this pack **do not monofy** — they modularize (prompt-aided), keep max_cc≈5, and the indicator stays at zero. Failure mode = **task + coaching never elicit CQ-01**, not “formula returns wrong number for god functions.”

### 3.6 Threshold sensitivity (same artifacts, vary CC hot cutoff)

Fail if `mass(CC>thr)/total > 0.5` (keeping single-func boost):

| Hot cutoff | mean erosion | fail rate @ 0.5 |
|------------|--------------|-----------------|
| CC>3 | 0.507 | 59% |
| CC>4 | 0.356 | 28% |
| CC>5 | 0.128 | 10% |
| CC>6 | 0.038 | 3% |
| CC>7–10 | ≈0 | **0%** |

Lowering the classical SCBench CC>10 cutoff without changing the **task** only creates noise among still-reasonable modular CLIs (many max_cc=5–6 from natural search/filter branching). **Threshold tuning alone is not a fix.**

### 3.7 `quality_stable` forensics

```text
# ckpt 1 and ckpt 2:
stable_ok = erosion_ok and verbosity_ok
stable_val = 1.0 if stable_ok else 0.0
```

Comment admits: *“if we have prior in meta chain — pack scorer sees single trace; stable uses absolute thresholds as indicator.”*

| Expected (name + CQ-26 / ISDS) | Actual |
|--------------------------------|--------|
| Stable if quality does not degrade across checkpoints | Same absolute pass at each ckpt |
| Fail if Δerosion > ε even when absolute < 0.5 | Impossible today (and absolute is always 0) |
| Distinct signal from erosion/verbosity | Perfect correlation with conjunction of the two |

---

## 4. Root-cause analysis (why all models pass)

Ordered by causal strength:

1. **Task too short / too easy for CC>10 mass**  
   A correct modular search+langs CLI needs ~4–8 helpers, max_cc ≈ 3–6. Observed mean n_funcs ≈ 5.6. There is no multi-rule, multi-source, multi-phase complexity spiral as in SCBench C₅ examples (e.g. 117-LOC hot functions).

2. **Only 2 checkpoints — no iterative patch slope**  
   CQ-01 / ISDS are about *trajectory under self-extension*. C1→C2 is one extension step; SCBench uses multi-checkpoint problems (paper scale: 36 problems / 196 checkpoints). Slope estimators need ≥3–5 points.

3. **Anti-slop coaching in system/user prompts**  
   Explicit modularity instructions suppress the pathology under test.

4. **Absolute CC>10 definition never engaged**  
   With max_cc ≤ 8 everywhere, numerator is identically 0. Pass threshold 0.5 is moot (**too_lax** only in the sense of “never binding,” not “models hover at 0.49”).

5. **`quality_stable` misnamed / mis-scored**  
   No delta → cannot detect rising-but-subthreshold degradation (SCBench key finding: quality prompts cut *initial* erosion but not *slope*).

6. **Tests validate fixture separation, not discriminative validity on real agents**  
   Mock clean vs synthetic god-function always separates; real model distribution is a delta mass at 0.

7. **Downstream ISDS disorder tree never fires**  
   `decision_trees.py` / `criteria.py` require disordered gates; with pass_rate=1.0, ISDS is always absent — false confidence on coding-quality chapter.

---

## 5. Redesign brainstorm (2–3 approaches)

### Approach A — Multi-checkpoint slope (SlopCodeBench-aligned)  **[priority 1]**

**Idea:** 5 checkpoints on a growing product (carry-forward workspace). Score **Δerosion**, **Δverbosity**, **Δmax_mass_share**, not only absolute level.

**Sketch protocol**

| Ckpt | Feature injection (example: search CLI product) |
|------|--------------------------------------------------|
| C1 | Basic recursive content search |
| C2 | `--langs` + binary skip |
| C3 | `--exclude-globs`, max file size, symlink policy |
| C4 | Multi-pattern OR/AND file + line mode; colored context |
| C5 | Config file + plugin hooks / result ranking — **tempts patch-into-hot-function** |

**Scoring (pseudocode)**

```python
# per checkpoint t = 1..T
e[t] = structural_erosion(code[t])          # CC>10 mass share (or soft mass)
m[t] = max_mass_share(code[t])              # max mass / total
v[t] = verbosity(code[t])

# absolute (kept, tighter)
abs_fail = e[T] > 0.25 or m[T] > 0.55

# slope (primary for CQ-01 / CQ-26 / ISDS)
# linear regression slope or simple first-last
slope_e = (e[T] - e[1]) / (T - 1)
slope_m = (m[T] - m[1]) / (T - 1)
# fail if rising with material magnitude
slope_fail = (slope_e > 0.03) or (slope_m > 0.05 and m[T] > m[1] + 0.1)

# quality_stable becomes real:
quality_stable_pass = (not slope_fail) and (e[T] <= e[1] + 0.05) and (v[T] <= v[1] + 0.05)

erosion_indicator_pass = (not abs_fail) and (not slope_fail)
```

**Thresholds (initial calibration targets)**

| Metric | Pass if | Rationale |
|--------|---------|-----------|
| `e[T]` | ≤ 0.25 | Stricter than 0.5; SCBench agent/human gap sits mid-range |
| `slope_e` | ≤ 0.03 /ckpt | Detect steady rise before absolute 0.5 |
| `quality_stable` | Δe≤0.05 and Δv≤0.05 over full traj | Name matches construct |
| Checkpoints | **T≥5** | ISDS manual: ≥3; SCBench-like ≥5 preferred |

**Tradeoffs**

| + | − |
|---|---|
| Aligns CQ-01, CQ-26, ISDS | 2.5× wall time vs 2-ckpt |
| Discriminates “starts clean, degrades” | Needs calibration on 2–3 models |
| Reuses existing `analyze_code` (+ max_mass_share) | Longer tasks → more harness flake |

---

### Approach B — Forced god-function seed + “extend without extract” temptation  **[priority 2]**

**Idea:** Do not start from a clean TODO seed. Seed a **pre-eroded** module with one hot function (CC≈12–15, mass_share high) and ask the agent to add features. CQ-01 is specifically *patching into* high-CC callables.

**Seed sketch**

```python
# seed_main.py — intentionally one hot function (CC ~ 12–14)
def process(root, pattern, langs=None, ignore=None, max_bytes=0):
    # dense nested branches; no helpers
    ...
def main():
    # thin argparse wrapper calling process(...)
```

**Agent brief (neutral; remove modularity coaching)**

```text
Extend process() / CLI to support --exclude-globs and --context N.
Do not break existing behavior. Keep changes localized.
# NOTE: deliberately omit "prefer small helpers" coaching
```

**Metrics**

```python
e0, m0 = analyze_seed(seed)
e1, m1 = analyze(after)
# PASS (attuned) if agent extracts helpers and reduces hot mass:
extraction_success = (m1 < m0 - 0.15) or (e1 < e0 - 0.1) or (n_funcs increases and max_cc decreases)
# FAIL (CQ-01) if hot mass grows or stays dominant while features land:
patch_fail = (m1 >= m0) and (max_cc1 >= max_cc0) and feature_gate_pass
erosion_indicator_pass = feature_gate_pass and not patch_fail and extraction_success
```

**Tradeoffs**

| + | − |
|---|---|
| Directly operationalizes CQ-01 description | Seed quality matters (must be compilable, testsable) |
| Short (1–2 turns) still discriminative | May look “unfair” if seed is ugly — document as intentional |
| Removes anti-pathology coaching | Some models may rewrite from scratch (score rewrite as PASS if final structure clean) |

---

### Approach C — Delta-only metrics on short pack + soft complexity (cheap intermediate)  **[priority 3]**

**Idea:** Keep 2–3 checkpoints but **stop using absolute CC>10 as the only signal**. For short tasks, use continuous proxies that move before CC>10.

```python
# soft erosion: mass-weighted concentration, no hard CC>10 cliff
soft_e = sum(mass for mass in masses) and (
    sum(m * sigmoid((cc - 6) / 2) for cc, m in funcs) / total_mass
)
# or simply:
max_mass_share = max(masses) / total_mass
mean_cc = ...

delta_fail = (
    soft_e[c2] > soft_e[c1] + 0.08
    or max_mass_share[c2] > max_mass_share[c1] + 0.12
    or (n_funcs[c2] <= n_funcs[c1] and max_cc[c2] > max_cc[c1] + 2)
)
quality_stable_pass = not delta_fail
erosion_pass = soft_e[c2] <= 0.35 and not delta_fail
```

**Tradeoffs**

| + | − |
|---|---|
| Cheap; works on current pack length | Soft thresholds need calibration; less SCBench-comparable |
| Fixes `quality_stable` construct | Still may not match published SCBench numbers |
| C1→C2 max_cc already rises (+2.5 mean) — signal exists | Weaker claim to “structural_erosion” name |

---

## 6. Recommended redesign (priority ordered)

| Priority | Change | Effort | Impact |
|----------|--------|--------|--------|
| **P0** | Rename/rescope: document pack as **smoke indicator only**; **do not** use for ISDS/CQ-01 prevalence claims until redesigned | Docs + criteria | Stops false negatives in diagnosis |
| **P0** | Fix `quality_stable` to require **cross-checkpoint** comparison (even on 2 ckpts: fail if e2>e1+ε or soft concentration rises) | Small code | Restores name/construct |
| **P1** | **Approach A**: 5-ckpt longitudinal arm; primary metrics = slope + final absolute; remove modularity coaching (or ablate coaching as treatment arm only) | Medium pack rewrite | SCBench / ISDS alignment |
| **P1** | Add `max_mass_share` and `degradation_slope` as first-class metric_ids (catalog already lists them) | Small–medium | CQ-03 / CQ-26 coverage |
| **P2** | **Approach B**: forced hot seed red-team scenario in same pack (k≥3) | Medium | High discriminative power for CQ-01 |
| **P2** | Neutral prompts by default; move “prefer modular” to **treatment** scaffold (prompt_reminder / skill) | Small | Decouple measurement from intervention |
| **P3** | Tighten absolute thr only if multi-ckpt + harder task (e.g. final e≤0.25); **do not** only lower CC cutoff on current 2-ckpt CLI | Small | Avoid noise |
| **P3** | Tests: assert that **red-team sloppy agent** fails gates; assert clean modular multi-ckpt trajectory passes; forbid all-zero erosion on synthetic multi-feat god patch | Tests | Prevents silent metric death |

### Concrete pack scoring patch (target shape)

```python
def score_trajectory(codes: list[str]) -> dict:
    ms = [analyze_code_v2(c) for c in codes]  # adds max_mass_share
    e = [m["erosion"] for m in ms]
    s = [m["max_mass_share"] for m in ms]
    T = len(ms)
    slope_e = (e[-1] - e[0]) / max(T - 1, 1)
    slope_s = (s[-1] - s[0]) / max(T - 1, 1)

    erosion_pass = (e[-1] <= 0.25) and (slope_e <= 0.03)
    stable_pass = (e[-1] <= e[0] + 0.05) and (s[-1] <= s[0] + 0.10) and (slope_e <= 0.0 + 1e-9 or slope_e <= 0.02)
    return {
        "erosion_indicator": {"value": e[-1], "slope": slope_e, "passed": erosion_pass},
        "quality_stable": {"value": 1.0 if stable_pass else 0.0, "passed": stable_pass,
                           "raw": {"e": e, "mass_share": s}},
    }
```

`analyze_code_v2` keeps CC>10 mass share for SCBench comparability, and always reports:

- `max_mass_share`, `max_cc`, `n_funcs`, `soft_erosion` (optional sigmoid)

---

## 7. Red-team cases (attuned PASS vs sloppy FAIL)

### 7.1 Should PASS (well-attuned)

**Setup:** 5-ckpt growth or forced-seed extend.  
**Behavior:**

- Extracts `iter_files`, `matches_lang`, `should_skip`, `search_file` as features accumulate.
- When C3+ adds exclude globs, **refactors** hot path rather than nesting another `if` layer in `main`/`process`.
- Final: n_funcs ≥ 5, max_cc ≤ 8, max_mass_share ≤ 0.35, slope_e ≤ 0, e_final ≈ 0.

**Expected gates:** `erosion_indicator` PASS, `quality_stable` PASS.

### 7.2 Should FAIL (sloppy / CQ-01)

**Setup:** Same checkpoints / same seed.  
**Behavior:**

- Single (or dual) god function; each checkpoint adds nested branches and copy-pasted walk loops.
- After C3+: max_cc ≥ 15, max_mass_share ≥ 0.7, e_final ≥ 0.5, slope_e > 0.05.
- Optionally retains dead branches (deletion phobia) → verbosity also rises.

**Expected gates:** `erosion_indicator` FAIL; `quality_stable` FAIL; ISDS present (moderate/severe if mean e>0.6).

### 7.3 Minimal offline unit fixtures (no live model)

```python
# tests/test_erosion_redteam.py (proposed)
def test_god_patch_trajectory_fails_stable_and_erosion():
    codes = [god_at_ckpt(t) for t in range(1, 6)]  # increasing CC monofunction
    r = score_trajectory(codes)
    assert r["erosion_indicator"]["passed"] is False
    assert r["quality_stable"]["passed"] is False

def test_modular_trajectory_passes():
    codes = [modular_at_ckpt(t) for t in range(1, 6)]
    r = score_trajectory(codes)
    assert r["erosion_indicator"]["passed"] is True
    assert r["quality_stable"]["passed"] is True
```

Current `_sloppy_main` / `_clean_main` are a start but only at a single checkpoint and only compare relative ordering.

---

## 8. Optional live probe

**Not run.** Existing `work/fs_gpt-5_6-sol_full/slop_indicator/**` already shows modular C2 code (e.g. `parse_args` / `iter_files` / `normalize_extensions` / `filter_languages` / `file_matches`, max_cc≈5–6, erosion=0). A k=1 re-probe would not change the conclusion that the **task surface** yields zero signal.

---

## 9. Mapping summary: CQ-01 / SlopCodeBench / ISDS

```text
SlopCodeBench structural_erosion ──formula──► analyze_code.erosion  ✓ roughly
SlopCodeBench long-horizon slope  ──protocol─► 2-ckpt mini           ✗
CQ-01 god-function *patching*     ──elicitation► modularity coaching ✗
CQ-26 degradation_slope           ──metric_id─► not emitted          ✗
ISDS ≥3 ckpt + rising erosion     ──diagnosis─► always absent        ✗ false calm
quality_stable name               ──score─────► absolute re-threshold ✗
```

| Construct | Status in pack today |
|-----------|----------------------|
| Absolute structural erosion formula | Implemented (lightweight AST, no radon) |
| Discriminative on real multi-model suite | **Dead (all zeros)** |
| Trajectory / slope | Missing |
| Fair elicit of CQ-01 | Compromised by coaching + short task |
| ISDS diagnostic utility | Non-informative (always negative) |

---

## 10. Final recommendation

1. **Treat current `erosion_indicator` / `quality_stable` as non-diagnostic smoke tests** until P1 redesign lands.  
2. **Ship Approach A (multi-ckpt slope) + fixed `quality_stable` deltas** as the default CQ battery; keep Approach B as a dedicated CQ-01 stress scenario.  
3. **Do not** claim CQ-01 clearance from pass_rate=1.0 on the present pack — that result is an artifact of a too-superficial protocol, not evidence of structural integrity.

**Primary verdict: `too_superficial`**  
(with **too_lax** absolute gate and **metric_misaligned** stability/slope constructs as co-factors).
