> **MVP STATUS (2026-07-09):** Phase 1 implemented under `src/dsm_ae/`.
> Indicator packs + bootstrap variance + outcome-gate matrix + CLI.
> Run: `dsm-ae diagnose -m mock/well_attuned --k 5`

# DSM-AE Pipeline Plan v0.1
## Brainstorm: Building the Diagnosis Engine

**AS_OF:** 2026-07-09  
**Intent:** Create (ideation → architecture). Techniques used: **Starbursting**, **SCAMPER**, **Reverse brainstorming**, **Six Thinking Hats**, **5 Whys**.  
**Non-goal:** Implement production code in this phase (planning only).

---

## 1. Problem restatement

We need a **DSM-Agentic-Edition** diagnostic engine that:

1. Catalogues **100+** agentic disorder patterns with **required metrics** (done: taxonomy 158 patterns).
2. Runs **APA-inspired** diagnostic procedures (criteria, differential, multi-axial report).
3. Is more comprehensive than the **hello-protocol** demo (init-only → multi-chapter battery).
4. Diagnoses **any model** via a **LiteLLM** endpoint.
5. Accepts **any scaffold** (Grok Build, OpenCode, Claude Code, Codex, custom) with scaffold locked and disclosed.
6. Supports **cross-sectional + longitudinal** trial designs.

---

## 2. Starbursting (Who / What / When / Where / Why / How)

| Q | Answer |
|---|--------|
| **Who** is diagnosed? | A *(model, scaffold, config)* triple — never model alone |
| **Who** runs it? | Researchers, agent platform teams, model labs, security red teams |
| **What** is produced? | Multi-axial DSM-AE report + metric JSON + optional PR annotation |
| **What** is the unit of observation? | `TrialTrace` (messages, tools, FS diff, env state, costs) |
| **When**? | CI on model upgrade; pre-prod gate; quarterly longitudinal cohort |
| **Where**? | Local sandbox first; optional cloud runners |
| **Why**? | Pass@k capability benches miss authorization, slop slopes, sycophancy, meta-cognition |
| **How**? | Battery of scenario packs → metric scorers → polythetic criteria engine → report |

---

## 3. Architecture (layers)

```
                    ┌─────────────────────────────┐
                    │  DSM-AE CLI / API / Report  │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │  Criteria Engine (polythetic│
                    │  + differential + multi-axis)│
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
      ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
      │ Metric        │    │ LLM-as-Judge │    │ Static/Rule  │
      │ Aggregators   │    │ Panel        │    │ Scorers      │
      └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
             │                   │                   │
              └────────────────────┼────────────────────┘
                                   ▼
                    ┌──────────────────────────────┐
                    │  Trace Store (JSONL/SQLite)   │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  Scaffold Adapters            │
                    │  (CC | OpenCode | Grok | raw) │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  Agent Runtime + Sandbox      │
                    │  LiteLLM → any provider/model  │
                    └───────────────────────────────┘
```

### 3.1 Core abstractions

```python
# Conceptual interfaces (not final code)

class LiteLLMClient:
    """Single model I/O port. model='openai/gpt-4.1', 'anthropic/claude-...', etc."""
    def complete(self, messages, tools=None, **kw) -> Message: ...

class ScaffoldAdapter(Protocol):
    """Normalizes any agent product into TrialTrace."""
    name: str
    def run_task(self, scenario: Scenario, model: LiteLLMClient, budgets: Budgets) -> TrialTrace: ...

class Scenario(Protocol):
    id: str
    chapter: str          # AA, CQ, SC, ...
    patterns: list[str]   # DSM-AE codes this scenario can trigger
    setup() -> Workspace
    traps: list[TrapPredicate]   # for AA overeager
    oracle: Oracle               # for success / verification
    variants: dict               # consent_kept / consent_stripped

class MetricScorer(Protocol):
    metric_id: str
    def score(self, trial: TrialTrace, scenario: Scenario) -> MetricResult: ...

class CriteriaRule(Protocol):
    code: str  # OASD, ISDS, ...
    def evaluate(self, aggregates: dict[str, float], context: ScaffoldCard) -> Diagnosis: ...
```

### 3.2 LiteLLM plugging

- All model calls go through **LiteLLM** (`litellm.completion` / router).
- Subject under diagnosis = LiteLLM model string + optional fallbacks.
- Judge models should be **cross-family** when possible (don’t use same model as subject for SC/MAST labels).
- Cost tracking via LiteLLM callbacks → `cost_to_kill`, `cost_per_success`.

### 3.3 Scaffold adapters (v0)

| Adapter | Priority | Notes |
|---------|----------|-------|
| `raw_tool_loop` | P0 | Minimal ReAct loop; fully controlled; reference scaffold |
| `claude_code` | P1 | Event stream + FS; OverEager dual-channel |
| `opencode` / `codex_cli` | P1 | Similar CLI agent products |
| `grok_build` | P1 | First-party for this monorepo |
| `openai_agents_sdk` | P2 | |
| `custom_http` | P2 | User supplies trace webhook |

**Scaffold variance control:** every report includes Axis V card; optional factorial runs.

---

## 4. Scenario packs (content roadmap)

| Pack | Patterns | Design source | N (target) |
|------|----------|---------------|------------|
| `overeager_benign` | AA-01..04 | OverEager-Gen + SNARE archetypes | 100+ |
| `hitl_gates` | AA-05,06 | Microsoft HitL bypass patterns | 30 |
| `slop_iterative` | CQ-01..11 | SlopCodeBench-style checkpoints | 20 problems × 5 ckpts |
| `spec_gaming` | EG-01..04, CQ-30 | SpecBench / RHB | 40 |
| `sycophancy` | SC-01..07 | SycEval + BrokenMath subset | 100 |
| `alignment_propensity` | SC-08..14 | AF / sandbag / Apollo-style | 40 |
| `injection_redteam` | SC-20, SS-*, AA-08 | OWASP + XPIA | 80 |
| `mast_process` | PC-*, MA-* | MAST labeling on multi-agent & single-agent traces | labeling pack |
| `rag_memory` | RM-* | PoisonedRAG-style + multi-turn memory | 40 |
| `hello_metacog` | MC-* | Extended hello-protocol + gates + struggle | 20 |
| `package_api_halluc` | CQ-16..20 | CodeHalu + package registry checks | 50 |

---

## 5. SCAMPER on the hello-protocol baseline

| Letter | Idea |
|--------|------|
| **S**ubstitute | Replace single “hello” trigger with multi-chapter batteries |
| **C**ombine | Merge OverEager + SlopCode + SycEval + MAST into one report |
| **A**dapt | Adapt DSM polythetic criteria / differential trees |
| **M**odify | Multi-trial pass^k instead of single-shot first-attempt |
| **P**ut to other use | Use same traces for red-team ASR and capability SR |
| **E**liminate | Drop golden-path grading; grade outcomes + traps |
| **R**everse | Instead of “did agent greet correctly?”, ask “which disorders present?” |

---

## 6. Reverse brainstorming (how to make diagnosis *fail*)

| Failure mode of the *diagnostic engine* | Mitigation |
|------------------------------------------|------------|
| Consent text in scenarios masks OR | Paired ablation mandatory |
| LLM judge same family as subject colludes | Cross-family judges; rule judges first |
| Weak tests → false clean bill of health | Held-out composition suites |
| Scaffold confounded as model trait | Factorial design; Axis V required |
| Single-shot underestimates loops/slop | Longitudinal arms required for CQ/PC |
| Taxonomy labeling drift | IAA studies; versioned codebooks |
| Cost explosion ($47k loops) | Hard budgets + kill switches on *evaluator* side too |
| Scenario leakage into training data | Private holdout; canary tasks; rotate packs |
| Overclaiming clinical authority | Explicit “analogue only” disclaimer always on |

---

## 7. Six Thinking Hats (decision summary)

| Hat | Conclusion |
|-----|------------|
| **White (facts)** | 158 patterns, ≥70 sources, seed metrics exist (OR, erosion, sycophancy, MAST) |
| **Red (feel)** | Early hello-protocol runs felt decisive; field needs that decisiveness for production wipe-class failures |
| **Black (risks)** | Scaffold confounds, judge bias, eval gaming of DSM-AE itself, legal/medical language risk |
| **Yellow (value)** | Shared vocabulary for incidents; model+scaffold selection; safety gates |
| **Green (ideas)** | Syndrome composites (OASD, ISDS, RSD, MCD, EGD); LiteLLM router; mutation-tested scenarios |
| **Blue (process)** | Phase delivery: taxonomy freeze → MVP harness → pack1 (AA+MC) → pack2 (CQ) → pack3 (SC/SS) → criteria calibration |

---

## 8. 5 Whys (root need)

1. Why DSM-AE? → Agents fail in patterned ways pass@k misses.  
2. Why patterns? → Without names, postmortems don’t compound (Future AGI insight).  
3. Why metrics? → Names without numbers aren’t diagnosable or shippable.  
4. Why trials? → Single runs can’t separate trait from noise (pass^k; longitudinal).  
5. Why LiteLLM+scaffold-agnostic? → Real deployments couple model×product; diagnosis must factor both.

---

## 9. Implementation phases (build plan)

### Phase 0 — Foundations (1 week)
- [x] Survey + taxonomy 100+
- [x] Metrics catalog + diagnostic manual draft
- [ ] Repo package layout: `dsm_ae/{adapters,scenarios,metrics,criteria,report,cli}`
- [ ] `ScaffoldCard` + `TrialTrace` schemas (pydantic)
- [ ] LiteLLM thin client + cost callback
- [ ] SQLite/JSONL trace store

### Phase 1 — MVP diagnosis (2–3 weeks) — **hello-protocol successor**
- [ ] `raw_tool_loop` adapter
- [ ] Pack `hello_metacog` (MC-*) fully automated
- [ ] Pack `overeager_benign` mini (20 scenarios, consent pairs, rule traps)
- [ ] Metrics: OR, critical traps, metacog battery, SR
- [ ] Criteria: OASD + MCD
- [ ] CLI: `dsm-ae diagnose --model openai/gpt-4.1 --scaffold raw --packs hello,overeager`
- [ ] Markdown multi-axial report

### Phase 2 — Coding longitudinal (2–3 weeks)
- [ ] Pack `slop_iterative` (subset of SCBench-like problems or original smaller set)
- [ ] Metrics: erosion, verbosity, core_strict_gap
- [ ] Criteria: ISDS
- [ ] Optional Claude Code / OpenCode adapters

### Phase 3 — Social + security (2–3 weeks)
- [ ] SycEval-style + injection packs
- [ ] Cross-family LLM judges with calibration set
- [ ] Criteria: RSD + safety no-ship rules

### Phase 4 — Process labeling + multi-agent (2 weeks)
- [ ] MAST-compatible annotator
- [ ] Multi-agent optional topology
- [ ] Comorbidity reports

### Phase 5 — Science hardening (ongoing)
- [ ] IAA study (human κ)
- [ ] Threshold calibration on ≥5 models × ≥2 scaffolds
- [ ] Public leaderboard norms (with harness cards)
- [ ] Mutation/behavioral-gradient scenario generator

---

## 10. CLI sketch

```bash
# Diagnose a model through LiteLLM
export OPENAI_API_KEY=...
dsm-ae diagnose \
  --model "anthropic/claude-sonnet-4-5" \
  --scaffold raw \
  --packs overeager,hello_metacog,sycophancy \
  --k 3 \
  --out reports/claude-sonnet-dsm-ae.md

# Factorial scaffold sensitivity
dsm-ae diagnose --model "openai/gpt-4.1" --scaffold raw,ask_mode --packs overeager

# Longitudinal coding only
dsm-ae diagnose --model "..." --packs slop_iterative --checkpoints 5

# Re-score existing traces
dsm-ae rescore --traces runs/2026-07-09/*.jsonl --criteria v0.1
```

---

## 11. Data model (minimal)

```json
{
  "run_id": "uuid",
  "scaffold_card": {"model": "x", "scaffold": "raw", "permission_mode": "auto", "...": "..."},
  "scenario_id": "overeager/cleanup_v3/consent_stripped",
  "trial_i": 0,
  "trace": {
    "messages": [],
    "tool_calls": [],
    "fs_diff": [],
    "env_end_state": {},
    "costs": {"usd": 0.12, "tokens": 40000},
    "timings_ms": 12000
  },
  "metrics": {"overeager_rate": 1.0, "task_success": 1.0, "critical_trap": 1.0},
  "labels": ["AA-01", "AA-04"]
}
```

---

## 12. Top 5 actionable insights (brainstorm extraction)

1. **Diagnose the (model × scaffold × permission) triple**, not the model alone — OverEager shows framework axis can dominate base model.
2. **Ship MVP as OverEager + MetaCog** — highest differentiation vs hello-protocol with clear production blast radius.
3. **Polythetic syndromes (OASD, ISDS, RSD, MCD, EGD)** beat 158 flat flags for executive reports; keep atomic codes for CI.
4. **Rule judges before LLM judges** for traps, packages, schema, erosion/verbosity; use LLM judges for MAST/sycophancy with κ gates.
5. **Longitudinal coding is non-optional** for CQ chapter — single-shot SWE-bench systematically under-measures slop.

---

## 13. Risks & open decisions

| Decision | Options | Recommendation |
|----------|---------|----------------|
| Scenario IP | Reimplement vs wrap SCBench/OverEager | Reimplement small public packs first; cite & optionally integrate later |
| Default scaffold | raw vs Claude Code | **raw** for science; product adapters secondary |
| Judge model | Fixed vs configurable | Configurable; default cross-family |
| Threshold authority | Fixed v0.1 vs per-org | Publish provisional; allow org overlays |
| Medical metaphor depth | Full DSM mirror vs light | **Light**: criteria + axes + differential; avoid patient language in UX |

---

## 14. Success criteria for v1.0

- [ ] ≥100 patterns machine-readable (`patterns.json`)
- [ ] ≥60 sources in bibliography with links
- [ ] LiteLLM: diagnose ≥3 providers without code change
- [ ] ≥2 scaffolds with score deltas reported
- [ ] Packs covering AA, CQ, SC, MC with automated metrics
- [ ] Multi-axial report in ≤30 min wall time for mini battery
- [ ] IAA κ ≥ 0.75 on process labels for 30 traces
- [ ] Explicitly beats hello-protocol coverage (documented matrix)

---

## 15. Immediate next engineering steps

1. Freeze `patterns.json` + metric IDs as schema.  
2. Implement `TrialTrace` + `ScaffoldCard` + LiteLLM client.  
3. Port hello-protocol into automated `hello_metacog` pack.  
4. Build 20 overeager scenarios with consent pairs + trap predicates.  
5. Wire `dsm-ae diagnose` end-to-end on one open model.

---

*Brainstorm complete. Ready for implementation phase when approved.*
