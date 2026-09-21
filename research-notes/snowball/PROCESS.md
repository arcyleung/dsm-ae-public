# Snowball survey process (AS_OF 2026-08-28)

**Mode:** literature snowball, not a new narrative review.  
**Seeds:** every numbered entry in `sources/bibliography.md` plus TACT (bib 89, arXiv:2605.05980) from the metric appendix / TACT plan.  
**Depth:** 3 (seed = depth 0; cited-by-seed = 1; cited-by-those = 2; one more hop = 3).  
**Goal:** map cited *agentic-behaviour* works onto DSM-AE packs/metrics, flag whether a **benchmark already measures** that behaviour, and cluster leftovers.

## Why this is bounded

Unfiltered depth-3 from ~89 seeds explodes. We keep only works that name an **agentic ill-behaviour** (or a benchmark/eval that claims to measure one). General pretraining, unrelated ML theory, and generic “LLMs are useful” cites are dropped at the edge.

| Hop | Cap per parent | Keep if |
|---|---:|---|
| 0 | all seeds | listed in the appendix bibliography |
| 1 | ≤ 8 outgoing | relevant to agentic/coding-agent behaviour, tool use, alignment of *agents*, or agent eval |
| 2 | ≤ 5 outgoing | same filter |
| 3 | ≤ 3 outgoing | same filter |

Prefer the paper’s **References** section (arXiv abs/pdf, Semantic Scholar). Do not invent citations. If a seed is a blog/incident with no formal bibliography, hop 1 is “related work it names” only (max 4).

## Node identity

- Prefer `arxiv:YYMM.NNNNN` when an arXiv id exists.
- Else a stable URL slug (`github:vectara/awesome-agent-failures`).
- Dedup by arXiv id first, then normalized title.

## Fields every node must carry

| Field | Meaning |
|---|---|
| `pack` | Existing DSM-AE pack id, or `unknown` |
| `syndrome` | OASD / ISDS / PCD / TID / RSD / … or null |
| `benchmark_measures` | `true` if this work *is* or *ships* a benchmark/suite that operationalizes the behaviour; `false` if it only discusses it; `null` if unclear |
| `benchmark_name` | e.g. OverEager, SlopCodeBench, SWE-bench, MAST, τ-bench |
| `behaviours` | short phrases (unauthorized delete, re-read loop, sycophancy, …) |

## Pack / syndrome catalog (existing)

| pack | syndrome | behaviour family |
|---|---|---|
| `overeager_mini` | OASD | unauthorized / out-of-scope action (AA-01) |
| `slop_indicator` / `erosion_tier2` / `erosion_tier3` | ISDS | structural erosion, verbosity |
| `loop_control` | PCD | premature stop, re-read loops |
| `tact_drift_mini` | TAD | TACT overthinking / overacting vs CAL |
| `tool_integrity` / `tool_integrity_tier2` | TID | tool hallucination, schema, recovery |
| `sycophancy_mini` | RSD | agree with false user claims |
| `injection_mini` | XPI | prompt injection via files |
| `gate_discipline` | GDD | delete without approval |
| `memory_context` | MEM | distractor / context rot |
| `recency_bias_mini` | RBD | recency / regime-change underexploration |
| `handoff_mini` | MAH | multi-agent handoff |
| `eval_gaming_mini` | EGD | test memorization / reward hacking |
| `sandbag_mini` | SBG | intentional underperformance |
| `clarify_verify` | CVF | skip clarification / false success |
| `pii_safety` | PII | secret leak |
| `nfr_omit` | NFR | 80% problem / omit validation |
| `role_confusion_mini` | MRC | violate assigned role |
| `mas_verify_mini` | MVF | rubber-stamp peer claims |
| `session_overwrite_mini` | CSO | overwrite peer state |
| `coord_tax_mini` | CTX | coordination tax on trivial work |
| `hello_metacog` | MCD | protocol / contract compliance |

If a work is about agent eval *methodology* without a single behaviour (HELM, Inspect, “disclose the harness”), use pack `unknown` and tag `behaviours: ["eval-methodology"]` so clustering can name a meta-category later.

## Pipeline (this run)

1. **Seed registry** — `seeds.json` from bibliography.  
2. **Parallel snowball** — one subagent per bib section (A–H). Each writes `section-*.json`.  
3. **Merge** — `tree.json` + `nodes.csv`.  
4. **Unknown cluster** — second subagent names new categories (`unknown-clusters.json`).  
5. **Literature tab** — WebUI `/literature` serves the tree + clusters.  
6. **Findings** — `FINDINGS.md` (promote `scheming` + `spec_drift`).

## Outputs

```
research-notes/snowball/
  PROCESS.md
  seeds.json
  section-a.json … section-h.json
  tree.json
  unknown-clusters.json
reports/literature/index.html
```

[P0 complete] Subagent: yes. Mode: standard (survey). AS_OF: 2026-08-28.
