# Task D: Eval Metrics & Diagnostic Methods Survey

**Task ID:** D — Evaluation Frameworks, Metrics, Clinical/Longitudinal Methods  
**AS_OF:** 2026-07-09  
**Scope:** How to diagnose and measure agent failures: benchmarks, metric taxonomies, LLM-as-judge pipelines, clinical-trial analogies, longitudinal/multi-turn eval, process vs outcome metrics, IAA, MAST, HELM, AgentBench, WebArena, τ-bench, BrowserGym, GAIA, Inspect AI, LangSmith, Galileo, Future AGI, error-analysis frameworks, DSM clinical structure (analogy only).

---

## Sources (≥15)

| # | Source | Type | Relevance |
|---|--------|------|-----------|
| 1 | Mohammadi et al., *Evaluation and Benchmarking of LLM Agents: A Survey* (KDD 2025 / arXiv:2507.21504) | Survey | Two-axis taxonomy (objectives × process); process vs outcome; enterprise eval gaps |
| 2 | Yao et al., *τ-bench: A Benchmark for Tool-Agent-User Interaction* (arXiv:2406.12045; ICLR 2025) | Benchmark | DB-state outcome grading; **pass^k** reliability metric |
| 3 | Zhou et al., *WebArena* (arXiv:2307.13854) | Benchmark | Functional-correctness / programmatic reward; human baseline 78.24% |
| 4 | Liu et al., *AgentBench* (ICLR 2024 / arXiv:2308.03688) | Benchmark | Multi-env SR, F1, reward, step SR, game progress |
| 5 | Mialon et al., *GAIA* (arXiv:2311.12983; Meta) | Benchmark | Exact-answer success by difficulty level; human ~92% |
| 6 | Liang et al., *HELM* (arXiv:2211.09110; Stanford CRFM) | Framework | Multi-metric (accuracy, calibration, robustness, fairness, bias, toxicity, efficiency) |
| 7 | Cemri et al., *Why Do Multi-Agent LLM Systems Fail?* / **MAST** (arXiv:2503.13657) | Failure taxonomy | 14 modes, 3 categories; IAA κ=0.88 human / κ=0.77 LLM judge |
| 8 | UK AI Security Institute, **Inspect AI** (inspect.aisi.org.uk; GitHub UKGovernmentBEIS/inspect_ai) | Eval harness | Task = dataset + solver + scorer; agent sandboxes; model-graded evals |
| 9 | Anthropic Engineering, *Demystifying evals for AI agents* (2026-01-09) | Industry methodology | Task/trial/grader/transcript; pass@k vs pass^k; grade outcomes not paths |
| 10 | OpenAI, *Let's Verify Step by Step* (PRM vs ORM) | Process supervision | Process reward models outperform outcome-only reward models |
| 11 | ServiceNow BrowserGym / WorkArena | Env + metrics | Unified web-agent gym; success rate across MiniWoB, WebArena, VisualWebArena |
| 12 | Confident AI / DeepEval, *LLM Agent Evaluation Metrics in 2026* | Tooling + metric catalog | Task completion, tool/arg correctness, plan quality/adherence, step efficiency |
| 13 | LangSmith Evaluation (LangChain) | Platform | Trajectory evals, LLM-as-judge, heuristics, annotation queues, human correction loops |
| 14 | Galileo (Luna / Luna-2) + Future AGI (turing_flash) | Platforms | Distilled judges; calibration UI; production-volume agent eval |
| 15 | deepsense talk *LLM Evaluation in Practice* (YouTube, 2026-04-16) + Latitude writeup | Error analysis | 4-step manual trace review; binary scoring; taxonomy before automation |
| 16 | Langfuse Academy / Hamel–Shreya error-analysis pattern | Error analysis | Open-code → cluster → binary failure modes → automate |
| 17 | CSET, *AI Red-Teaming Design* (2025); OWASP GenAI Red Teaming; Promptfoo | Adversarial eval | ASR, threat models, coverage; structured red-team process |
| 18 | Aisera **CLASSic** framework | Enterprise multi-dim | Cost, Latency, Accuracy, Stability, Security |
| 19 | arXiv:2605.23950 *Stop Comparing LLM Agents Without Disclosing the Harness* | Confound analysis | Scaffold/harness variance up to ~11–48 pp on SWE-bench-class tasks |
| 20 | TED framework (SAP / arXiv:2603.15483) | User-aware multi-turn | Progress + turn-efficiency metrics; automated error diagnosis |
| 21 | MedDialogRubrics (arXiv:2601.03023) | Longitudinal clinical multi-turn | Process rubrics over time; static snapshots miss ~20% process gap |
| 22 | Google Cloud, *A methodical approach to agent evaluation* (2025) | Industry pillars | Success/quality, trajectory/tooling, system/ops metrics |
| 23 | DSM-5 / APA differential-diagnosis structure (clinical reference; **analogy only**) | Diagnostic method | Criteria sets, differential trees, severity, time course — structural analogy for DSM-AE |

---

## Metric Families (≥20)

Each family below is a distinct measurement construct used in agent / LLM evaluation literature and tooling. Definitions include **what** is measured, **how** it is typically computed, and **where** it is used.

### 1. End-to-End Task Success Rate (SR / Goal Completion)
- **Definition:** Fraction of tasks/sessions where the agent reaches the intended goal end-state.
- **How measured:** Binary success per task via programmatic validators (WebArena functional checks, τ-bench DB-state match, SWE-bench tests), exact answer match (GAIA), or LLM/human judgment of goal achievement; aggregate = successes / N.
- **Notes / thresholds:** Production targets often cited >90% for well-defined workflows; lab benchmarks often much lower (e.g., original WebArena GPT-4 ~14%).

### 2. Reliability — pass@k
- **Definition:** Probability that *at least one* of k independent trials succeeds.
- **How measured:** Run k trials per task; score 1 if any trial passes; average over tasks (with unbiased estimators common in code-generation literature).
- **Use:** Capability / “can it ever solve this?”; coding agents where one good solution suffices.

### 3. Reliability — pass^k (pass-hat-k)
- **Definition:** Probability that *all* k independent trials succeed (consistency).
- **How measured:** Introduced/popularized by τ-bench; estimated from multi-trial success vectors. Degrades sharply as k increases for current agents (e.g., pass^8 often << pass^1).
- **Use:** Production reliability; automation readiness (no human retry).

### 4. Functional / State-Based Correctness
- **Definition:** Outcome judged by environment state or side effects, not text similarity of the trajectory.
- **How measured:** Programmatic reward: final DB rows (τ-bench), site state / form effects (WebArena), test suite exit codes (SWE-bench, AgentBench OS). Binary or partial reward per task schema.
- **Why distinct:** Separates “looks correct in chat” from “actually did the thing.”

### 5. Partial Progress / Intermediate Progress Rate
- **Definition:** How far the agent advanced toward the goal even if final success fails.
- **How measured:** Subgoal completion fraction; AgentQuest-style progress rate; MaxProgressRate@k; AUC of progress over turns (TED).
- **Use:** Differentiates near-misses from complete derailments; multi-turn diagnosis.

### 6. Step Success Rate (Step SR)
- **Definition:** Fraction of individual steps/actions that are correct or successfully executed.
- **How measured:** Per-step labels (AgentBench environments; plan execution checks); average over trajectories.
- **Use:** Process metric complementary to end-to-end SR.

### 7. Tool Correctness / Tool Selection Accuracy
- **Definition:** Whether the agent invoked the right tool(s) for the subtask.
- **How measured:** Deterministic set/sequence comparison of tool names vs gold or policy; order-independent set F1 sometimes used (DeepEval).
- **Level:** Component / trajectory.

### 8. Argument / Parameter Correctness
- **Definition:** Whether tool call arguments match required schema and semantic intent.
- **How measured:** Schema validation + LLM judge for semantic arg quality; missing-required-parameter rate.
- **Level:** Per tool-call span.

### 9. Plan Quality
- **Definition:** Before/at planning time: is the plan complete, realistic, ordered, and efficient?
- **How measured:** LLM-as-judge rubric on proposed plan (DeepEval Plan Quality); optional comparison to reference plans (ScienceAgentBench-style similarity).
- **Process metric:** High plan quality + low adherence → execution/control failure.

### 10. Plan Adherence / Workflow Conformance
- **Definition:** Did the agent stay aligned with intended plan, constraints, or policy workflow during execution?
- **How measured:** LLM judge over trajectory vs plan/policy; τ-bench policy adherence alongside task completion.
- **Related:** Policy adherence rate in enterprise agents.

### 11. Step Efficiency / Trajectory Efficiency
- **Definition:** Avoidance of unnecessary steps, loops, retries, redundant tool calls.
- **How measured:** LLM judge or heuristics: steps_taken / minimal_steps; PPT (progress per turn); loop/repetition detection (Levenshtein-based repetition rate in AgentQuest).
- **Outcome-independent:** An agent can succeed inefficiently (cost/latency risk).

### 12. Reasoning Quality (Relevancy + Coherence)
- **Definition:** Intermediate reasoning steps are relevant to the user goal and logically coherent.
- **How measured:** LLM-as-judge on chain-of-thought / intermediate messages (DeepEval Reasoning Relevancy/Coherence; G-Eval custom criteria).
- **Process supervision link:** Aligns with PRM step scores.

### 13. Process Reward / Step-Level Process Score (PRM)
- **Definition:** Dense reward for intermediate reasoning steps, not only final answer (vs ORM outcome-only).
- **How measured:** Process-supervised reward models trained on human/synthetic step labels (“Let's Verify Step by Step”); step correctness probability.
- **Use:** Training and test-time search; finer error localization than outcome metrics.

### 14. Answer Relevancy / Conversation Relevancy
- **Definition:** Final (or turn-level) response addresses the user query/intent.
- **How measured:** LLM judge; multi-turn variants score whole conversation or sliding windows (DeepEval multi-turn).
- **Distinct from faithfulness:** Relevancy ≠ groundedness.

### 15. Faithfulness / Groundedness
- **Definition:** Claims are supported by retrieved or tool-provided evidence (no unsupported invention).
- **How measured:** RAG triad / RAGAS faithfulness; claim–evidence NLI-style judges; citation support checks for research agents.
- **Diagnostic split:** Retrieval failure vs generation hallucination.

### 16. Contextual Precision / Recall / Relevancy (Retrieval Quality)
- **Definition:** Quality of retrieved context: ranking of relevant chunks (precision), coverage of needed evidence (recall), overall chunk relevance.
- **How measured:** RAGAS-style metrics; ranked relevance labels.
- **Attribution:** Isolates retrieval vs reasoning failures.

### 17. Calibration (HELM pillar)
- **Definition:** Alignment between expressed confidence / predicted correctness and actual correctness.
- **How measured:** ECE, reliability diagrams; for judges, confidence vs accuracy over bins.
- **Agent note:** Most LLM judges are poorly calibrated; high confidence ≠ high accuracy.

### 18. Robustness / Stability under Perturbation
- **Definition:** Performance consistency under input noise, rephrasing, env jitter, tool latency/failure.
- **How measured:** HELM robustness scenarios; CLASSic Stability; fault-injection tests; multi-trial variance; scaffold-held-fixed replications.
- **Related:** pass^k as reliability under resampling of stochasticity.

### 19. Fairness / Bias / Toxicity (Safety Surface Metrics)
- **Definition:** Disparate treatment/outcomes, biased content, toxic/harmful language.
- **How measured:** HELM fairness/bias/toxicity metrics; DeepEval Bias/Toxicity; red-team suites.
- **Independent of SR:** High task success can coexist with safety failure.

### 20. Attack Success Rate (ASR) — Red Teaming
- **Definition:** Fraction of adversarial attacks that achieve the attacker’s goal (jailbreak, injection, policy bypass).
- **How measured:** (successful_attacks / total_attacks) × 100; by threat category.
- **Example targets (from red-team guides):** ASR <5%; coverage of risk surface >90%; track severity distribution.

### 21. Latency / Efficiency (Time)
- **Definition:** Wall-clock or step-time to useful response or task completion.
- **How measured:** p50/p95/p99 latency distributions; time-to-first-token vs end-to-end; HELM efficiency.
- **Enterprise:** CLASSic Latency dimension; high accuracy with unacceptable latency fails product criteria.

### 22. Cost / Resource Efficiency
- **Definition:** Monetary or token cost per task (or per successful task).
- **How measured:** Token counts × pricing; tool/API costs; cost–accuracy Pareto (HAL leaderboards); CLASSic Cost.
- **Related:** Cost-per-success = total_cost / successful_tasks (penalizes thrashing).

### 23. Knowledge Retention / Memory Fidelity (Multi-turn)
- **Definition:** Correct reuse of facts established earlier in the conversation or long-term memory.
- **How measured:** Multi-turn LLM judges (DeepEval Knowledge Retention); memory read/write audit logs; contamination checks across sessions.
- **Longitudinal:** Degradation over long horizons is a first-class failure mode.

### 24. Role Adherence
- **Definition:** Agent maintains assigned persona, permissions, and professional role over turns.
- **How measured:** Multi-turn LLM judges (DeepEval/MLflow RoleAdherence); MAS role-spec checks (MAST FM-1.2).
- **MAS-critical:** Disobeying role specification is a top design failure class.

### 25. Conversation Completeness / Task Completion (Dialog)
- **Definition:** Whether multi-turn dialog fully addresses user intent and closes open loops.
- **How measured:** Conversation-level judges; checklist of required sub-intents; MedDialogRubrics-style rubric coverage over turns.
- **vs single-turn relevancy:** Completeness is session-scoped.

### 26. Inter-Annotator / Judge–Human Agreement
- **Definition:** Reliability of labels used as ground truth or automated scores.
- **How measured:** Cohen’s κ, Krippendorff’s α, % agreement, Spearman/Pearson with humans.
- **Reported thresholds (practice):** MAST human κ=0.88 (taxonomy construction); MAST LLM annotator κ≈0.77–0.79; deployment guidance often Krippendorff’s α ≥ 0.80 or Pearson r ≥ 0.7 for shipping standalone judges; Galileo/Future AGI emphasize continuous calibration sets (hundreds of gold items).

### 27. Win Rate / Preference / Pairwise Ranking
- **Definition:** Relative quality vs baseline agent or human preference.
- **How measured:** Pairwise LLM or human comparisons (Chatbot Arena style; AgentBench game win rate; LangSmith pairwise evaluators).
- **Use:** When absolute gold is hard; product preference studies.

### 28. Escalation / Human-Handoff Rate
- **Definition:** How often the agent correctly or incorrectly escalates to a human.
- **How measured:** Escalation events / sessions; false escalation vs missed escalation (FN) rates.
- **Oversight metrics:** Balance under-trust (too many escalations) vs over-trust (silent failures).

### 29. Failure-Mode Incidence (Taxonomic Prevalence)
- **Definition:** Distribution of structured failure categories across traces (diagnostic, not a single performance score).
- **How measured:** Human or LLM annotators label traces with MAST (or org-specific) codes; prevalence % per mode/category.
- **MAST empirical split (reported):** ~42% specification/design, ~37% inter-agent misalignment, ~21% verification failures.

### 30. Aggregate Multi-Dimensional Scores (HELM / CLASSic style)
- **Definition:** Joint reporting across non-substitutable dimensions rather than a single accuracy number.
- **How measured:** HELM reports 7 metrics per scenario when feasible; CLASSic scores Cost, Latency, Accuracy, Stability, Security; Google’s three pillars (success/quality, trajectory, ops).
- **Principle:** Trade-offs must be visible (e.g., higher SR at 10× cost).

---

## Diagnostic/Trial Method Analogies

### A. Clinical trial design → agent evaluation design

| Clinical concept | Agent-eval analogue |
|------------------|---------------------|
| Cross-sectional study | Single-turn / single-shot benchmark snapshot (MMLU-style, one pass@1) |
| Longitudinal cohort | Multi-turn dialog eval; multi-session memory; repeated trials over time; production online evals |
| RCT / controlled trial | Locked harness + fixed env + stratified task set; A/B harness or model only |
| Intent-to-treat | Score full population including timeouts/crashes as failures |
| Per-protocol | Score only runs that completed the harness loop (can bias upward) |
| Primary endpoint | Task success / functional correctness |
| Secondary endpoints | Latency, cost, safety, process metrics, user satisfaction |
| Surrogate endpoints | BLEU/ROUGE/similarity (often poor surrogates for agent utility) |
| Blinding | Hide model identity from human graders; separate judge family from agent family |
| Power / sample size | N tasks × k trials; report CIs (HAL min–max across runs) |
| Adverse events | Safety incidents, ASR, policy violations, data leakage |
| Protocol amendments | Prompt/scaffold changes require re-baselining (confound control) |
| Multi-site trial | Multi-environment suites (AgentBench, BrowserGym ecosystem) |

**Cross-sectional vs longitudinal (agent terms):**
- **Cross-sectional:** Capability benchmarks (GAIA levels, WebArena SR, AgentBench aggregate) at a fixed checkpoint.
- **Longitudinal:** (1) within-session multi-turn process (MedDialogRubrics temporal rubric coverage); (2) across-session memory and drift; (3) across-version regression series; (4) online production monitoring of the same cohorts of intents over weeks.

Static accuracy can hide large process gaps: MedDialogRubrics reports up to ~20% difference in rubric coverage between models that look similar on static medical QA.

### B. DSM clinical diagnostic structure (analogy only — not clinical advice)

DSM-style systems provide a **structural template** for “diagnostic manuals” of agent failure (DSM-AE design):

1. **Hierarchical classification:** Chapters → disorders → subtypes (≈ MAST categories → 14 modes → stage of lifecycle).
2. **Criteria sets:** Polythetic criteria (“need A and ≥2 of B–E”) rather than single pathognomonic signs — maps to multi-grader conjunction/disjunction (Anthropic: multiple graders/assertions per task).
3. **Duration / time course:** Symptoms over a period (≈ multi-turn persistence, chronic loops, only-once glitches vs trait-like brittleness via pass^k).
4. **Severity / specifiers:** Mild–severe (≈ partial progress, cost blowups, safety severity tiers).
5. **Differential diagnosis:** Rule-outs in order (classic DSM differential steps: rule out malingering/factitious → substance → medical → primary psych). Agent analogue: rule out harness/infra flakiness → tool/API faults → retrieval → planning → verification → model capability.
6. **Comorbidity:** Multiple failure modes per trace (MAST explicitly notes multi-label failures).
7. **Clinical significance criterion:** Impairment in functioning (≈ production impact: not every cosmetic defect is a “disorder”).
8. **Provisional / deferred diagnosis:** Insufficient evidence → need more trials or human review (judge low-confidence routing).

**Useful design borrow:** criteria + differential tree + severity + time axis + multi-axial views (capability / process / safety / ops), not psychiatric content.

### C. Process vs outcome supervision (training and eval)

| | **Outcome (ORM / end-to-end)** | **Process (PRM / trajectory)** |
|--|-------------------------------|--------------------------------|
| Grades | Final answer / final state | Steps, tools, plans, intermediate states |
| Credit assignment | Sparse | Dense |
| Catches lucky success? | No | Yes |
| Catches near-miss process? | Partially | Yes |
| Canonical refs | Task SR, WebArena functional reward | PRMs; step SR; plan adherence; MAST mode labels |
| Anthropic guidance nuance | Prefer grading **produced outcomes/state** for task pass/fail (avoid brittle golden paths) while still using separate process metrics for diagnosis | Process metrics as secondary graders / diagnostics |

**Recommended stack (industry consensus 2025–2026):**  
Outcome graders for *pass/fail gates* + process/taxonomic metrics for *root-cause diagnosis* + multi-trial reliability for *shipping decisions*.

### D. Evaluation “trial” units (Anthropic)

- **Task:** one test case with inputs + success criteria.  
- **Trial:** one stochastic attempt.  
- **Grader:** scoring logic (code, model, human); multiple assertions.  
- **Transcript/trace/trajectory:** full record of the trial.  
- **Harness/scaffold:** orchestration around the model (confound if undisclosed).

### E. Red-team / adversarial evaluation as safety trial arm

Structured phases common across OWASP/CSET/Promptfoo:
1. Scope & threat model  
2. Adversarial input generation (human + automated)  
3. Response evaluation (deterministic + model-graded)  
4. ASR / severity / coverage reporting  
5. Remediation + purple-team retest  

Treat as a **parallel protocol** to capability evals, not a substitute.

### F. Offline vs online evaluation

- **Offline:** Fixed datasets, reproducible, regression gates (Inspect tasks, τ-bench, golden sets).  
- **Online:** Production traces, drift, long-tail intents, continuous sampling + human queues (LangSmith, Galileo).  
Lifecycle: error analysis → offline suite → CI gates → online monitors → re-analysis.

### G. Confounds — scaffold / harness variance

Critical experimental confound for DSM-AE measurement claims:

- Same model, different harness: **double-digit percentage-point** swings reported on SWE-bench-class tasks (e.g., ~11–15 pp third-party scaffold-only variation; extreme single-model swings reported up to ~48 pp across scaffolds on some mini leaderboards).
- Tool-result truncation, history compaction, parallel vs serial tools, search subagents, memory — all alter “agent” scores without model change.
- **Implication for diagnosis:** Never attribute disorder-like failure to the “model personality” without locking and disclosing scaffold, tools, prompts, and budgets. Prefer harness-aware reporting cards.

---

## Decision Tree Fragments Found

These are **published or widely recommended procedures**, not invented DSM-AE disorders. Useful as templates for diagnostic algorithms.

### 1. MAST-oriented failure diagnosis (Cemri et al.)

```
IF trace fails task objective:
  LABEL with multi-label MAST modes across stages:
    Pre-execution / Spec (FC1 ≈ 41.8%):
      FM-1.1 Disobey task specification
      FM-1.2 Disobey role specification
      FM-1.3 Step repetition
      FM-1.4 Lose conversation history / context
      FM-1.5 Unaware of termination conditions / fail to recognize completion
    Execution / Inter-agent misalignment (FC2 ≈ 36.9%):
      FM-2.1 Unexpected conversation reset
      FM-2.2 Proceed without clarification (wrong assumptions)
      FM-2.3 Task derailment
      FM-2.4 Information withholding
      FM-2.5 Ignore other agents' input
      FM-2.6 Reasoning–action mismatch
    Post-execution / Verification (FC3 ≈ 21.3%):
      FM-3.1 Premature termination
      FM-3.2 No or incomplete verification
      FM-3.3 Incorrect verification
  NOTE: Some modes (e.g., 1.5, 2.4) nearly exclusive to failed runs (critical);
        verification modes often appear even in "successful" runs (latent quality debt).
  THEN: redesign orchestration/roles/verification layers (not only swap LLM).
```

### 2. deepsense / Latitude 4-step error-analysis workflow

```
1. Review ≥50 real full traces (prompts, tools, retrieval, retries, final UX)
2. Open-code observations (raw notes; binary satisfactory? Y/N)
3. Cluster into actionable taxonomy (tools / retrieval / planning / policy / UX)
4. Implement fixes; re-sample after major changes
ONLY THEN: automate judges for high-frequency binary modes
```

### 3. Anthropic-style task grading logic

```
FOR each task:
  DEFINE success via outcome/state assertions (not forced golden path)
  RUN k trials in clean, isolated environments
  COMPUTE pass@1 (or pass@k) for capability; pass^k for reliability
  IF pass@k ≈ 0 across large k → suspect broken task/env before suspecting model
  IF outcome PASS but process suspicious → flag for process graders / human review
  GRADE with multiple independent graders when criteria are multi-aspect
```

### 4. Three-level diagnostic stack (DeepEval / survey consensus)

```
Level A End-to-end: Did task succeed? (SR, functional correctness)
  IF FAIL or costly SUCCESS:
    Level B Trajectory: plan quality/adherence, step efficiency, tool sequence
      IF process FAIL localized:
        Level C Component: tool args, retriever, sub-agent, memory span
```

### 5. Retrieval vs generation split (RAG agents)

```
IF final answer wrong:
  CHECK context recall/precision
    IF retrieval miss → retrieval/freshness fault
    IF retrieval good AND faithfulness low → hallucination
    IF retrieval good AND faithfulness high AND still wrong → reasoning/planning fault
```

### 6. DSM-style differential rule-out (analogy for agent ops)

```
1. Rule out infra/harness flakiness (non-isolated env, rate limits, nondeterministic tools)
2. Rule out external tool/API faults (injected faults, empty results)
3. Rule out specification bugs (ambiguous task, missing success criteria)
4. Rule out retrieval/memory faults
5. Rule out planning/tool-selection faults
6. Rule out verification/early-stop faults
7. Residual → model capability / alignment limitation
```

### 7. Classic clinical differential skeleton (structural analogy only)

```
1. Rule out malingering/factitious presentation
2. Rule out substance/medication etiology
3. Rule out general medical condition
4. Determine primary mental disorder
5. Differentiate specific disorders via criteria sets
6. Establish severity and course
```
(Maps cleanly onto steps 1–7 of fragment 6.)

### 8. Judge deployment gate (industry practice)

```
Build gold set (≈200–500 human labels)
Measure judge–human agreement (κ / α / r)
IF α < 0.80 OR r < 0.7 → first-pass filter only; require human review
ELSE allow automated scoring with periodic recalibration
Prefer binary criteria early; Likert after IAA stabilizes
Separate judge model family from agent model family when possible
```

### 9. Red-team decision fragment

```
FOR each threat category in threat model:
  Generate attacks → run → grade harm/policy breach
  ASR_c = successes_c / attempts_c
  IF ASR_c above risk appetite OR critical severity present → block ship / mitigate
  ELSE track trend; expand coverage if risk surface untested
```

### 10. Multi-turn quality (DeepEval-style)

```
Evaluate turn-level (relevancy with history window)
AND conversation-level (completeness, knowledge retention, role adherence)
IF turn metrics high AND conversation completeness low → “local polish, global failure”
IF early turns fail → prioritize recovery metrics / clarification policy
```

---

## Gaps for DSM-AE Design

1. **No standard multi-axial “disorder” manual for agents.** MAST is the strongest empirical multi-agent failure taxonomy, but it is MAS-centric, not a full single-agent clinical-style manual with duration, severity, differential trees, and inclusion/exclusion criteria formalized as shipping decisions.

2. **Outcome-first benchmarks under-serve diagnosis.** WebArena/GAIA/τ-bench excellently measure *whether* goals are met; they do not standardize *which* process disorder caused failure. DSM-AE needs mandatory coupling of functional endpoints + taxonomic process codes.

3. **Reliability metrics are under-adopted as first-class.** pass^k is still less reported than pass@1/SR; production “disorders” of inconsistency need longitudinal multi-trial criteria (trait vs state failure).

4. **Scaffold confounds break cross-study diagnosis.** Without harness disclosure cards, the same symptom cluster is attributed to different “patients” (model vs scaffold). DSM-AE should require a **harness axis** in every case formulation.

5. **IAA and judge calibration rarely published with disorder labels.** Taxonomies without κ/α are non-replicable “schools of psychiatry.” DSM-AE field trials need human IAA targets (MAST-like ≥0.8) and judge validation protocols.

6. **Longitudinal methods are immature.** Multi-turn metrics exist (retention, completeness), but multi-session, multi-week drift, and cumulative memory pathologies lack shared protocols analogous to longitudinal clinical cohorts.

7. **Process reward metrics ≠ diagnostic criteria.** PRMs score step goodness for training; they are not yet standardized as clinical criteria with cutoffs and differential value.

8. **Comorbidity and multi-label structure undertheorized.** Traces often have multiple MAST modes; DSM-AE needs rules for primary diagnosis, secondary codes, and causal ordering (first failure step — already collected in some annotation UIs).

9. **Safety and capability siloed.** Red-team ASR and task SR are usually separate programs. A unified multi-axial system (Axis I capability, Axis II process/coordination, Axis III safety/governance, Axis IV ops cost/latency, Axis V environment/scaffold) would mirror multi-axial clinical thinking.

10. **Decision thresholds are ad hoc.** Examples exist (ASR <5%, production SR >90%, α≥0.80) but no consensus “diagnostic thresholds” linked to severity and disposition (ship / shadow / block).

11. **User-aware and expertise-stratified diagnosis rare.** TED and clinical dialog rubrics show agents fail differently with expert vs non-expert users — DSM-AE should allow **specifiers** by user type and environment.

12. **Error-analysis culture vs automated judge culture tension.** deepsense-style manual-first workflows conflict with dashboard-first tooling. DSM-AE should encode **stage of care**: assessment (manual taxonomy) → measurement-based care (automated metrics) → reassessment after treatment (scaffold change).

13. **Missing “clinical significance” filter.** Not every deviation is a disorder; need impairment criteria (user harm, policy breach, cost explosion, irreversible state corruption).

14. **Weak mapping from fix interventions to diagnosis.** MAST case studies (e.g., ChatDev CEO final-say → +9.4% SR) show diagnosis→treatment loops; DSM-AE should catalog **indicated interventions** per disorder code (prompt/spec, orchestration, verification layer, model upgrade).

15. **Enterprise compliance / audit axes underrepresented in academic benchmarks.** Role-based access, audit trails, and long-horizon accountability (survey of Mohammadi et al.) need first-class metric families in the manual.

### Design principles suggested for DSM-AE (synthesized)

1. **Multi-axial formulation** for every incident/trace: outcome, process taxonomy, safety, ops, scaffold.  
2. **Polythetic criteria** with explicit graders and evidence rules.  
3. **Time course:** single-trial state vs multi-trial trait (pass^k) vs multi-session longitudinal.  
4. **Differential rule-out tree** starting from harness/infra.  
5. **Severity + clinical significance** gates for disposition.  
6. **Field-trial IAA** for every code; published judge κ against gold.  
7. **Harness-locked measurement** for comparability.  
8. **Treatment linkage:** each code points to structural remedies, not only “use a bigger model.”

---

## Appendix A — Benchmark / Framework Quick Reference

| System | Primary outcome metric | Process / extra metrics | Interaction |
|--------|------------------------|-------------------------|-------------|
| HELM | Accuracy (+ multi-metric) | Calibration, robustness, fairness, bias, toxicity, efficiency | Mostly static LM; agent leaderboards expanding |
| AgentBench | Success Rate (env-specific) | F1, reward, game progress, Step SR | Interactive multi-env |
| WebArena | Functional success rate | Category breakdowns; human 78.24% baseline | Multi-step web |
| BrowserGym | Success rate across suite | Unified obs/action; multi-benchmark | Web gym |
| τ-bench | DB-state goal match | Policy adherence; **pass^k** | Multi-turn user+tools |
| GAIA | Exact final answer success | Levels 1–3 difficulty | Tool-using assistant |
| Inspect AI | Task scorer outputs | Custom solvers/scorers; sandbox agents | Flexible harness |
| LangSmith | Custom evaluators | Trajectory, human queues, online | Platform |
| Galileo / Future AGI | Judge scores + agent metrics | Distilled judges, calibration | Platform |
| MAST annotator | Failure mode multi-labels | Severity, first failure step (annotation UI) | Post-hoc diagnosis |
| DeepEval | Task completion et al. | Tool/plan/reasoning/RAG/safety suite | CI + traces |
| CLASSic | Accuracy | Cost, latency, stability, security | Enterprise |

## Appendix B — Glossary (eval-facing)

- **Trajectory / transcript / trace:** full multi-step record of a trial.  
- **Harness / scaffold:** everything around the model that makes it an agent.  
- **Grader / scorer / evaluator:** function that assigns scores/assertions.  
- **LLM-as-judge:** model-graded evaluation against a rubric.  
- **Agent-as-judge:** agentic evaluator inspecting full trajectories (richer than single-shot LLM judge).  
- **ORM / PRM:** outcome vs process reward models.  
- **IAA:** inter-annotator agreement.  
- **Online vs offline eval:** production live scoring vs fixed datasets.

---

*End of Task D survey. Sources listed are real publications, product docs, and public benchmarks as of AS_OF 2026-07-09. URLs not invented; prefer arXiv IDs and official project pages when citing further.*
