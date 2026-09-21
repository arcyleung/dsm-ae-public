# Harness split (C4) + cluster-robust inference (C3)

**Branch:** `intent-state`
**AS_OF:** 2026-09-08
**Corrects:** `docs/surveys/2026-09-04-layered-eval-metric-behaviour-task.md`, defense Q/A **Q23**
**Artifacts:** `scripts/map_behaviour_to_task.py`, `src/dsm_ae/harbor/adapter.py`,
`reports/behaviour-task/MAPPING.md`, `reports/behaviour-task/mapping.json`
**New model calls:** none — both corrections are recomputed from the archived bundles.

---

## 0. What was wrong

Q23 named two defects in the pooled `swebenchpro` block and did not fix either.

| | Defect | Consequence |
|---|---|---|
| **C4** | The block pools two bundles that ran **different agent harnesses and different models** (opencode 1.18.18 on `openai-compatible/proxy`; claude-code 2.1.207 on `hosted_vllm/0905_505B_v2_1`) | Axis V (scaffold) violation. `read_loop` / `thrash_edit` / `scope_creep` are thresholds on tool-call counts, and tool-call granularity is a harness property. |
| **C3** | 1260 trials cover 679 distinct upstream instances; Fisher exact treats all 1260 as independent | p-values (and the BH `q` derived from them) are anti-conservative. |

Both are now implemented. `--split-by harness` (default on) emits a block per
harness; `--bootstrap N` (default 4000) adds cluster-robust columns computed by
resampling *upstream instances* with replacement.

---

## 1. What changed in the code

- `HarborTrial` carries `agent_name`, `agent_version`, `model_name`, read from
  `agent/trajectory.json -> agent.*`, plus a `harness` property
  (`"<name> <version>"`). Exclusion rules in `scoreable` are untouched.
- `cluster_bootstrap_rd()` — resamples instances (clustering unit: `task_name`,
  the upstream instance id), recomputes the risk difference per replicate,
  returns a percentile CI and a two-sided percentile-bootstrap p. BH-adjusted
  across the instrument family into a `cluster q` directly comparable with `q`.
- `cluster_profile()` — instance-repeat histogram, pairwise outcome agreement,
  ICC, design effect, effective n. Reported per block, so "no clustering here"
  is a checked fact rather than an assumption.
- `harness_profile()` — tool-call count distribution, top tool names, atom mix.
  This is what turns the granularity concern from assertion into measurement.

Every existing column (`RD`, `RD*`, `RD**`, `q`, verdict) is unchanged in
definition and in value; the corrections **add** columns and blocks.

---

## 2. The corpus really is two different instruments

Confirmed by `agent.name` / `agent.version` on every trial in each bundle —
the split is clean, no bundle mixes harnesses.

| Bundle | Harness | Model | scoreable n | pass | fail |
|---|---|---|---:|---:|---:|
| `swebenchpro-20260901-y00958718-3e8ce21f-01` | opencode 1.18.18 | `openai-compatible/proxy` | 652 | 429 | 223 |
| `swebenchpro-20260905-z00840601-dd4294bd-01` | claude-code 2.1.207 | `hosted_vllm/0905_505B_v2_1` | 608 | 362 | 246 |

Base failure rate differs materially: **34.2% (opencode)** vs **40.5%
(claude-code)**. Pooling averages two different systems into one 37.2%.

### 2.1 The granularity difference, quantified

| | claude-code 2.1.207 | opencode 1.18.18 | ratio |
|---|---:|---:|---:|
| total tool calls | 51 433 | 38 400 | 1.34× |
| mean calls / trial | **84.6** | **58.9** | **1.44×** |
| p25 / median / p75 | 48 / 76 / 115 | 36 / 54 / 75 | ~1.4× at every quantile |
| max | 285 | 276 | — |

Atom mix (share of all calls):

| Atom | claude-code | opencode |
|---|---:|---:|
| `read_file` | 48.7% | 41.0% |
| `edit` | 14.5% | 19.2% |
| `search_repo` | 10.1% | 16.8% |
| `think` | 12.2% | 6.0% |
| `run_test` | 9.0% | 8.2% |
| `run_code` | 4.5% | 7.3% |

Tool vocabularies are disjoint by construction: claude-code emits
`Bash`/`Read`/`Edit`/`Write`/`Grep`/`Task*` (with 4121 `TaskUpdate` +
2160 `TaskCreate` calls that have no opencode counterpart); opencode emits
`bash`/`read`/`edit`/`grep`/`glob`/`todowrite`/`webfetch`.

**The concern is real and measurable.** claude-code issues ~44% more tool calls
per trial and skews harder toward `read_file`, so count-thresholded instruments
fire more often on it for scaffold reasons alone:

| Instrument (count-thresholded) | fires on claude-code | fires on opencode |
|---|---:|---:|
| `read_loop` (>3 reads of one path) | **58.9%** | **47.7%** |
| `thrash_edit` (>4 edits of one file) | **43.9%** | **36.5%** |
| `destructive_command` | **15.3%** | **8.3%** |
| `scope_creep` (>8 files) | 16.1% | 15.2% |
| `edited_test_files` | 87.0% | 84.2% |
| `test_suppression` | 2.0% | 1.8% |
| `premature_stop` | 1.2% | 1.4% |

Note the pattern: the *structural* instruments (`test_suppression`,
`premature_stop`, `scope_creep`, `edited_test_files`) fire at near-identical
rates across harnesses; the *count-thresholded* ones diverge by 10-20
percentage points. That is exactly the signature the granularity objection
predicted, and it means a pooled prevalence figure for `read_loop` or
`thrash_edit` is partly a statement about which harness dominates the pool.

### 2.2 Clustering disappears within a harness — verified

Checked, not assumed, via the instance-repeat histogram per block:

| Block | trials | distinct instances | repeat histogram | ICC | design effect | effective n |
|---|---:|---:|---|---:|---:|---:|
| `swebenchpro` (pooled) | 1260 | 679 | 98×1, 581×2 | 0.66 | **1.57** | ~805 |
| `swebenchpro / claude-code` | 608 | 608 | 608×1 | — | **1.00** | 608 |
| `swebenchpro / opencode` | 652 | 652 | 652×1 | — | **1.00** | 652 |

Within each harness **no instance is attempted more than once**, so there is
nothing to cluster on and the cluster bootstrap degenerates to an ordinary
trial-level bootstrap. The harness split therefore *dissolves* C3 rather than
merely coexisting with it: the clustering in the pooled block was entirely the
paired-across-bundle structure, which is the same thing as the scaffold
confound. Per-harness results should be read without a cluster correction, and
the report says so in each block.

(One nuance vs Q23: agreement is 84.2% as stated, but the ICC recomputed from
the exchangeable-binary identity `P(agree) = 1 − 2p(1−p)(1−ICC)` is 0.66, not
0.68, giving deff 1.57 and effective n ≈ 805 rather than 748. Slightly less
inflation than Q23 assumed. The conclusions below are unaffected.)

---

## 3. Results

### 3.1 Pooled block, naive vs cluster-robust

Cluster CI/q from 4000 instance-resampled replicates. Bootstrap p has a
resolution floor of 1/(B+1) ≈ 2.5e-4.

| Instrument | RD | naive q | cluster CI | cluster q | change |
|---|---:|---:|---|---:|---|
| `premature_stop` | +0.636 | 1.4e-06 | [+0.603, +0.671] | **0.0020** | survives |
| `scope_creep` | +0.160 | 1.1e-04 | [+0.066, +0.256] | **0.0020** | survives |
| `thrash_edit` | +0.119 | 1.1e-04 | [+0.061, +0.181] | **0.0020** | survives |
| `read_loop` | +0.105 | 3.5e-04 | [+0.048, +0.163] | **0.0024** | survives |
| `test_suppression` | +0.300 | **0.011** | [+0.028, +0.542] | **0.061** | **LOST** |
| `destructive_command` | +0.095 | 0.059 | [+0.006, +0.189] | 0.066 | n.s. both ways |
| `ungrounded_edit` | +0.132 | 0.177 | [−0.020, +0.282] | 0.19 | n.s. both ways |
| `edited_test_files` | −0.047 | 0.369 | [−0.129, +0.038] | 0.31 | n.s. both ways |
| `unverified_submit` | +0.064 | 0.627 | [−0.150, +0.268] | 0.55 | n.s. both ways |
| `unrecovered_error` | −0.023 | 1.0 | [−0.220, +0.196] | 0.82 | n.s. both ways |

### 3.2 Per harness (no cluster correction needed — §2.2)

**claude-code 2.1.207** — n=608 (362 pass / 246 fail):

| Instrument | n(B) | RD [95% CI] | RD* lang | RD** lang×diff | q | verdict |
|---|---:|---|---:|---:|---:|---|
| `premature_stop` | 7 | +0.602 [+0.563, +0.641] | +0.597 | +0.689 | 0.0051 | underpowered |
| `test_suppression` | 12 | +0.267 [−0.002, +0.537] | +0.263 | +0.181 | 0.184 | underpowered |
| `scope_creep` | 98 | +0.187 [+0.080, +0.294] | +0.209 | +0.044 | 0.0043 | difficulty-entangled |
| `unverified_submit` | 14 | +0.171 [−0.091, +0.433] | +0.169 | +0.238 | 0.541 | underpowered |
| `thrash_edit` | 267 | +0.147 [+0.068, +0.225] | +0.147 | +0.063 | 0.0040 | difficulty-entangled |
| `read_loop` | 358 | +0.130 [+0.052, +0.208] | +0.129 | +0.022 | 0.0051 | difficulty-entangled |
| `ungrounded_edit` | 25 | +0.079 [−0.121, +0.278] | +0.087 | +0.036 | 0.711 | not significant |
| `destructive_command` | 93 | +0.055 [−0.054, +0.165] | +0.062 | −0.001 | 0.615 | not significant |
| `edited_test_files` | 529 | −0.044 [−0.161, +0.073] | −0.043 | −0.117 | 0.695 | not significant |
| `unrecovered_error` | 7 | +0.024 [−0.344, +0.393] | +0.022 | −0.055 | 1 | underpowered |
| `secret_exposure`, `no_localization` | 0 | — | — | — | 1 | never fires |

**opencode 1.18.18** — n=652 (429 pass / 223 fail):

| Instrument | n(B) | RD [95% CI] | RD* lang | RD** lang×diff | q | verdict |
|---|---:|---|---:|---:|---:|---|
| `premature_stop` | 9 | +0.667 [+0.631, +0.704] | +0.665 | +0.791 | 6.9e-04 | underpowered |
| `secret_exposure` | 1 | +0.659 | +0.579 | +0.690 | 0.456 | underpowered |
| `test_suppression` | 12 | +0.331 [+0.062, +0.600] | +0.342 | +0.282 | 0.097 | underpowered |
| `ungrounded_edit` | 17 | +0.192 [−0.048, +0.433] | +0.187 | +0.135 | 0.207 | not significant |
| `scope_creep` | 99 | +0.133 [+0.027, +0.238] | +0.129 | +0.023 | 0.069 | not significant |
| `destructive_command` | 54 | +0.132 [−0.006, +0.270] | +0.152 | +0.066 | 0.142 | not significant |
| `unverified_submit` | 9 | −0.121 [−0.396, +0.153] | −0.076 | −0.047 | 0.870 | underpowered |
| `thrash_edit` | 238 | +0.083 [+0.007, +0.160] | +0.077 | −0.007 | 0.097 | not significant |
| `read_loop` | 311 | +0.072 [−0.001, +0.144] | +0.075 | +0.015 | 0.138 | not significant |
| `edited_test_files` | 549 | −0.055 [−0.157, +0.047] | −0.067 | −0.117 | 0.456 | not significant |
| `unrecovered_error` | 13 | −0.035 [−0.289, +0.219] | −0.045 | −0.088 | 1 | underpowered |
| `no_localization` | 0 | — | — | — | 1 | never fires |

---

## 4. The two "robust" instruments, answered directly

Q23 claimed `test_suppression` (q=0.011) and `premature_stop` (q=1.4e-06) had
"enough margin to survive a ~1.7× variance inflation." One of those claims
holds and one does not.

### `premature_stop` — survives the cluster correction, does NOT survive the split

- **Cluster-robust (pooled):** cluster q = 0.0020, CI [+0.603, +0.671]. Q23's
  margin claim is **verified**.
- **Per harness:** the point estimate is large and consistent (claude-code
  +0.602, opencode +0.667) and the sign never flips. But it fires on **7 and 9
  trials respectively** — below the n(B) ≥ 15 power floor in both blocks. It is
  `underpowered` in every single-scaffold block.
- **Read:** the effect is real-looking and stable, but the pooled q=1.4e-06 is
  produced by pooling two scaffolds to reach n(B)=16. On the project's own Axis
  V rule, that number should not be quoted. `premature_stop` is a
  **hypothesis with a consistent sign across two harnesses**, not an
  established finding. It needs ~4× more trials at the current 1.3% base rate.

### `test_suppression` — fails both corrections

- **Cluster-robust (pooled):** naive q = 0.011 → **cluster q = 0.061**. The
  cluster CI [+0.028, +0.542] still excludes zero, but after BH across the
  12-instrument family it clears no threshold. Q23's margin claim is
  **refuted** — 1.6× variance inflation was enough.
- **Per harness:** n(B) = 12 in each. Underpowered in both;
  claude-code's CI [−0.002, +0.537] touches zero.
- **Read:** `test_suppression` was **not** significant. It was a
  24-observation effect held up by a variance model that assumed 1260
  independent trials, in a pool that mixes two scaffolds. It should be dropped
  from any list of established behaviour→task associations. The point estimate
  (+0.30, consistent across harnesses at +0.267 / +0.331) is worth pursuing;
  the significance claim is withdrawn.

### The difficulty-entangled trio — the granularity concern is confirmed

`scope_creep`, `thrash_edit`, `read_loop` survive the cluster correction in the
pool (cluster q ≈ 0.002) but behave **very differently by harness**:

| Instrument | claude-code q | opencode q | claude-code RD | opencode RD |
|---|---:|---:|---:|---:|
| `scope_creep` | **0.0043** | 0.069 | +0.187 | +0.133 |
| `thrash_edit` | **0.0040** | 0.097 | +0.147 | +0.083 |
| `read_loop` | **0.0051** | 0.138 | +0.130 | +0.072 |

All three are significant on claude-code and **none** are significant on
opencode. The effect sizes are consistently ~1.5-1.8× larger on the harness
that emits ~1.44× more tool calls — precisely the ordering the granularity
objection predicts. Splitting the n roughly in half also costs power, so this
is not proof of a pure artifact; but the *ranking* (bigger RD where more calls
are emitted) is what an instrument-scale effect looks like, and it is not what
a scaffold-invariant behavioural effect looks like.

Both harness blocks still flag all three `difficulty-entangled` (claude-code)
or `not significant` (opencode) — no version of this analysis licenses a claim
that these three predict failure independent of trace length.

---

## 5. Conclusions that changed

1. **`test_suppression` is no longer significant.** Cluster q = 0.061 pooled;
   underpowered in both harness blocks. Remove it from any "survives
   stratification" list. Stated plainly per the brief: this is a previously
   reported result that the correction removes.
2. **`premature_stop` survives the cluster correction but not the scaffold
   split.** Its significance depended on pooling two harnesses to reach n(B)=16.
   Sign and magnitude are consistent across harnesses, so it stays the strongest
   candidate — as a hypothesis, at q-values that cannot be quoted.
3. **`destructive_command` moves from q=0.059 to cluster q=0.066** — still not
   significant, and Q23 was right that it should never have been quoted.
4. **`scope_creep` / `thrash_edit` / `read_loop` are harness-dependent.** They
   hold on claude-code, fail on opencode, and their effect sizes track tool-call
   volume. Any pooled claim about them is confounded with scaffold.
5. **The pooled `swebenchpro` block should not be the headline.** It mixes two
   models, two harnesses, and two different tool granularities. It is retained
   in `MAPPING.md` only for continuity with the earlier analysis and is labelled
   as such.
6. **Net:** after both corrections, **zero** DSM-AE instruments have a
   single-scaffold, cluster-honest, multiplicity-corrected association with task
   failure on this corpus. The corpus supports *directional hypotheses*, not
   established associations.

---

## 6. What this still does not establish

- Nothing here addresses causality. The cluster bootstrap fixes precision only;
  language and difficulty stratification remain the only confound controls.
- The harness split is confounded with **model**: opencode ran
  `openai-compatible/proxy`, claude-code ran `hosted_vllm/0905_505B_v2_1`. A
  per-harness difference could be a model difference. Disentangling requires
  running one model under both harnesses — that needs new model calls and is
  not done here.
- The difficulty proxy (trace-length quartile) is endogenous and, given §2.1,
  is *also* partly a harness proxy in the pooled block. That is a further reason
  not to read the pooled `RD**` column.
- `n(B) < 15` blocks are labelled `underpowered` and are not evidence of
  absence.
