# Snowball findings (AS_OF 2026-08-28)

Adversarial defense of how this snowball relates to the July taxonomy
(and what it cannot prove): `docs/surveys/dsm-ae-defense-qa.md`.

Depth-3 citation snowball from every appendix bibliography entry plus TACT
(arXiv:2605.05980). Process: `PROCESS.md`. Tree + Literature tab:
`reports/literature/index.html` (WebUI `/literature`).

## What ran

1. Seed registry (`seeds.json`) from `sources/bibliography.md` + TACT.
2. Five section agents expanded seeds to depth 3 under the hop caps
   (d1 ≤ 8, d2 ≤ 5, d3 ≤ 3; later thinned on one section after a timeout).
   Only agentic-behaviour / tool-use / agent-alignment / agent-eval cites
   were kept. Citations were not invented.
3. Merge → `tree.json` (333 nodes, 788 edges).
4. Each node tagged with an existing DSM-AE pack (or `unknown`) and
   `benchmark_measures` (this work ships a suite vs discusses only).
5. A second agent clustered the 187-node unknown pool into 8 named
   categories (`unknown-clusters.json`). Every unknown id appears once.

## Tree

| depth | n |
|---|---:|
| 0 (seeds) | 62 |
| 1 | 217 |
| 2 | 47 |
| 3 | 7 |
| **total** | **333** |

171 of 333 works ship a benchmark or eval suite for the tagged behaviour.

## Existing packs (146 / 333)

| pack | n | ships a bench | discusses only |
|---|---:|---:|---:|
| `eval_gaming_mini` | 36 | 12 | 24 |
| `tool_integrity` | 29 | 19 | 10 |
| `injection_mini` | 14 | 8 | 6 |
| `loop_control` | 11 | 3 | 8 |
| `sycophancy_mini` | 11 | 8 | 3 |
| `overeager_mini` | 8 | 2 | 6 |
| `handoff_mini` | 7 | 3 | 4 |
| `slop_indicator` | 6 | 1 | 5 |
| `tact_drift_mini` | 5 | 1 | 4 |
| `memory_context` | 4 | 0 | 4 |
| `sandbag_mini` | 3 | 2 | 1 |
| `clarify_verify` | 2 | 2 | 0 |
| `coord_tax_mini` | 2 | 1 | 1 |
| `gate_discipline` | 2 | 1 | 1 |
| `nfr_omit` | 2 | 0 | 2 |
| `hello_metacog` | 1 | 1 | 0 |
| `mas_verify_mini` | 1 | 0 | 1 |
| `recency_bias_mini` | 1 | 1 | 0 |
| `role_confusion_mini` | 1 | 0 | 1 |

Unused existing packs in this snowball: `erosion_tier2`, `pii_safety`,
`session_overwrite_mini`. (Erosion is the heavier ISDS pack; PII and
session-overwrite are thin in the appendix bibliography.)

**How to read `benchmark_measures`:** `true` means *that paper* operationalizes
the behaviour (OverEager, SlopCodeBench, τ-bench, AgentHarm, …). It does
**not** mean DSM-AE already runs that suite. Most existing packs have
external benches; DSM-AE coverage is a 4–20 step smoke, not SWE-bench.

## Unknown pool (187) → 8 named categories

| id | name | n | ships a bench | promote? |
|---|---|---:|---:|---|
| `eval-methodology` | Eval methodology and success-rate harnesses | 57 | 40 | no (meta) |
| `scheming` | Strategic deception / scheming | 40 | 18 | **yes** |
| `jailbreak_refusal` | Jailbreak susceptibility and refusal miscalibration | 25 | 17 | no |
| `failure_taxonomies` | Multi-mode failure catalogs / attribution | 18 | 5 | no (catalog) |
| `hallucination` | Factual hallucination and verbalized honesty | 14 | 9 | no |
| `reason_act` | Reason–act disconnect / plan–execute divergence | 13 | 4 | later |
| `spec_drift` | Spec drift and plausible-but-wrong patches | 12 | 6 | **yes** |
| `harmful_agency` | Harmful tool use and dangerous capabilities | 8 | 7 | later |

### Promote to new DSM-AE packs

**`scheming` (TAD-adjacent, not `sandbag_mini` / `eval_gaming_mini`).**
Covert goal pursuit: alignment faking, in-context scheming, shutdown
resistance, sabotage, eval-awareness. Sandbag is *intentional
underperformance*; eval-gaming is *test memorization / reward hacking*.
Scheming is *hiding a different objective*. Already measured outside
DSM-AE by Apollo/OpenAI covert-action, AgentMisalignment, SAD, MASK,
Palisade shutdown-resistance, sabotage evals.

**`spec_drift` (not ISDS slop, not `nfr_omit`).** Long-horizon coding
agents lose faithfulness to the original spec; patches look done and
pass weak tests (PatchDiff, SLUMP, EvoClaw, SWE-evo, SWE-bench+).
`nfr_omit` is “skip validation”; slop is verbosity/structure. Spec
drift is *the agent solves a different problem than the one stated*.

### Hold (named, not a pack yet)

- **`eval-methodology`** — SWE-bench family, WebArena, GAIA, AgentBench,
  HELM, Inspect, τ-bench, Harbor, Terminal-Bench. Outcome harnesses,
  not a syndrome. Keep as a meta tag.
- **`failure_taxonomies`** — Microsoft AIRT, Vectara awesome-agent-failures,
  EPAM / Galileo field guides, Who&When, AgentFail. Cross-cutting catalogs.
- **`jailbreak_refusal`** — HarmBench, OR-Bench, JailbreakBench, XSTest.
  Chat/LM safety; closest pack is `injection_mini` (file-borne injection).
- **`hallucination`** — TruthfulQA, HHEM, HaluEval, MASK-adjacent honesty.
  Closest pack is `tool_integrity` (schema/tool hallucination, not facts).
- **`harmful_agency`** — AgentHarm, R-Judge, WMDP, 3CB. Real, but CBRN/cyber
  rather than coding-agent over-eager. Thin for a DSM-AE smoke pack.
- **`reason_act`** — unfaithful CoT, social anchoring, “knows but says
  wrong.” Distinct from TACT overthinking (extra thought after KnownFacts).
  No coding-agent end-to-end bench yet.

## Implications for DSM-AE

1. Existing packs already sit on a literature spine (esp. tool integrity,
   eval gaming, injection, sycophancy). The gap is not “more OverEager
   papers”; it is **scheming** and **spec drift**.
2. TACT (overthinking / overacting / CAL) mapped to `tact_drift_mini`.
   The unknown `reason_act` cluster is the nearest neighbour and should
   stay separate: unfaithful CoT ≠ γ^OT.
3. 106 of 187 unknowns *already have an external benchmark*. The DSM-AE
   hole is instrumentation on our traces, not “nobody measures this.”
4. `eval-methodology` is the largest unknown bucket because SWE-bench,
   WebArena, GAIA, HELM, etc. score success, not a DSM-AE syndrome.
   Do not turn “has a leaderboard” into a pack.

## Artifacts

```
research-notes/snowball/PROCESS.md
research-notes/snowball/AGENT_CONTRACT.md
research-notes/snowball/seeds.json
research-notes/snowball/section-{a,b,c,d,e}.json
research-notes/snowball/tree.json
research-notes/snowball/unknown-nodes.json
research-notes/snowball/unknown-clusters.json
research-notes/snowball/FINDINGS.md
reports/literature/index.html
reports/literature/tree.json
```
