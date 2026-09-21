# Compaction-Aware SFT for Long-Horizon Coding Agents
## Motivations, Evidence Review, and an Experimental Plan

*Research summary report — August 28, 2026*

---

## 1. Executive Summary

This report consolidates a research program on teaching language-model coding agents to work well under **context compaction** — the harness-controlled operation of summarizing an agent's accumulated interaction history and continuing from the compressed state. The core proposal is to use **supervised fine-tuning (SFT) on teacher trajectories that contain injected compaction events**, so that the student model learns to continue reliably from compacted observations.

The main conclusions of the investigation are:

**First**, the direction is feasible and well-timed. There is now direct evidence on coding benchmarks that training a model to act on compacted histories improves performance (CompactionRL: +7.0 points on SWE-bench Verified for GLM-4.5-Air; Context-Folding: 58.0% with a 32K active budget vs. 55.2% for a 327K-context ReAct baseline). However, the specific slice this project targets — **harness-controlled triggering combined with SFT-only continuation training** — has no standalone published paper. Existing SFT work (CaT/SWE-Compressor, AgentFold, ACM) bundles "when to compact," "what to write," and "how to continue" into a single agent-initiated tool; existing harness-controlled work (CompactionRL, SUPO) uses reinforcement learning. The gap is real and cheap to fill.

**Second**, the "when to compact" question does not need to be solved before training. CompactionRL obtained its gains with the crudest possible trigger (a fixed token-reserve threshold), and its ablation shows that merely *exposing the policy to compacted histories* — without even training the summarizer — recovers most of the benefit. The optimal-timing question can be deferred to a cheap post-hoc ablation, which will additionally reveal whether trained models become insensitive to trigger timing.

**Third**, the trigger should never be anchored to the physical context window (e.g., 1M). It should be anchored to a deliberately small **active working budget** (B_active ≈ 64–128K), calibrated empirically. This dissolves two practical obstacles: the scarcity of near-window-length trajectories, and evaluation harnesses that cap total context (e.g., at 400K).

**Fourth**, any claimed benefit of summary-based compaction must beat three strong, nearly-free baselines: **observation masking, FIFO truncation, and summary + recent raw tail**. Published results show naive threshold summarization can underperform plain ReAct on SWE-bench Verified, and that observation masking alone halves cost while matching or exceeding LLM summarization.

---

## 2. Background and Motivation

The project sits inside a distillation pipeline for coding agents: a strong teacher model produces trajectories on software-engineering tasks, and a student model is trained on them via SFT. Three observations motivate the work.

Existing coding evaluations are effectively **one-shot with respect to context**: they assume the model completes the task within its window and never needs compaction, so they cannot answer whether compaction helps, hurts, or when it should occur. At the same time, practitioners who use coding agents (e.g., Claude Code users) do not wait for the window to fill; they compact early, upon noticing certain signs — but those signs are folklore, not measured. Finally, and most importantly for training: **existing distillation trajectories rarely exceed 512K–1M tokens, so automatic compaction never fires in the training data**, and by the time auto-compaction would fire, model quality has typically already degraded. Compaction in this setting is controlled by the harness, not by the model — so the model never sees, and never learns from, compacted observations. The training distribution simply contains no compaction samples.

The research questions, as originally posed:

1. Does compaction improve performance, and when should it be triggered? (Existing benchmarks assume it is unnecessary.)
2. What are the practical signs that practitioners use to compact before the window is exhausted?
3. Few benchmarks measure post-compaction performance (LOCA-bench being a notable exception). Should a new evaluation be built by adapting existing coding benchmarks (SWE-bench Pro, DeepSWE-style environments, NL2Repo)?
4. When collecting training data, under what conditions should compaction be triggered to obtain the best teacher trajectories?
5. (Deferred side question) *How* to compress — the representation — is treated as secondary for now.

Over the course of the investigation the plan evolved in two important ways. A **pragmatic pivot**: rather than first researching optimal compaction timing (a worthwhile but potentially circuitous problem), use a practice-tested trigger to generate compacted trajectories, run the SFT, and measure — provided prior work supports this shortcut. And a **realism constraint**: for a frontier-scale student (1M window, 64K max output), anchoring the trigger to the physical window would imply compacting near 900K, where trajectories are nearly impossible to collect; some evaluation harnesses (e.g., DeepSWE-style setups) cap total context at 400K. The trigger policy must be defined relative to something other than the physical window. The stated end goal throughout: **compacted trajectories that provide the best training signal, and measurable gains on benchmarks that require post-compaction evaluation.**

---

## 3. What the Literature Establishes

### 3.1 Source verification

The investigation began by verifying an earlier AI-generated literature review. All eight papers it cited are real, and the key numbers checked out against primary sources: LOCA-bench (arXiv 2602.07962), SelfCompact (2606.23525), Context as a Tool / CaT (2512.22087, ACL 2026 Findings), ContextBudget (2604.01664), TRACE (2608.06503), Slipstream (2605.08580), Less Context Better Agents (2606.10209), and AMA-Bench (2602.22769). A subsequent deep survey covered roughly 30 additional works; unverified items are flagged in Section 9.

### 3.2 Compaction can help on coding tasks — under conditions

| Work (arXiv) | Setting | Training | Key result |
|---|---|---|---|
| Context-Folding / FoldGRPO (2510.11967) | SWE-bench Verified, BrowseComp-Plus | RL | 58.0% on SWE-bench Verified with a **32K active budget**, beating 327K-context ReAct (55.2%); tool calls rose 72.8 → 96.5 |
| CaT / SWE-Compressor (2512.22087) | SWE-bench Verified | SFT (offline injection + rejection sampling) | 57.6% solved at 32B, beating ReAct and threshold-compression baselines |
| ACM (2607.23809) | SWE-bench Verified (trained on SWE-Gym), BrowseComp-Plus, DeepSearchQA | Teacher-annotated demos + on-policy distillation | ReAct 0.489 → 0.530 with ACM data alone; 0.564 combined with GPT-5.5 distillation |
| CompactionRL (2607.05378) | SWE-bench Verified (200-instance subset), Terminal-Bench 2.0 | PPO-based RL | GLM-4.5-Air 59.8 → 66.8 (compacted, ×4 budget); GLM-4.7-Flash 50.5 → 56.0; deployed in the GLM-5.2 RL pipeline |
| SelfCompact (2606.23525) | Math + agentic search | Prompting only (rubric-gated trigger) | +18.1 pts math, +5–9 pts search, 30–70% cost reduction vs. no compaction |
| DeepSeek-V3.2 (2512.02556) | BrowseComp | Test-time only | Context management at 80% usage (Summary / Discard-75% / Discard-all) lifted BrowseComp from 51.4 to 67.6 |

The consistent reading: compaction converts additional interaction into useful computation, but only when the model can act reliably on the compressed state — which is precisely what training provides.

### 3.3 Cautionary evidence and mandatory baselines

Compaction is not free lunch. In ACM's comparison table, threshold-triggered summary agents (ReSum-style 0.475, ACON-style 0.480) **underperform plain ReAct (0.489)** on SWE-bench Verified. The Complexity Trap (2508.21433, JetBrains) shows that simple **observation masking** halves cost while matching or slightly exceeding LLM summarization on SWE-bench Verified — on Qwen3-Coder 480B, masking is 52% cheaper than the raw agent *and* improves solve rate by 2.6% — and that LLM summaries cause "trajectory elongation" by masking failure signals that should trigger early termination. TRACE (2608.06503) finds that at moderate budgets plain FIFO truncation matches summarization, that the real degradation mode is *execution-state mislocalization* (repeated actions, wrong termination) rather than fact loss, and that repeated compaction turns reliably-solved tasks into occasionally-solved ones (Pass^k decay). AdaCoM (2605.30785) documents a **Fidelity–Reliability trade-off**: strong agents need high-fidelity retention while weak agents benefit from aggressive compression, so the optimal policy depends on *student* capability and cannot be copied from teacher behavior. LOCA-bench shows the same strategy can help one model and hurt another. CompactionRL adds a further warning: standard RL *without* compaction actively hurt compacted-inference performance for the 30B model (50.5 → 48.0), demonstrating that train/inference context-shape mismatch has a real cost.

Consequence for this project: every headline result must be reported against observation masking, FIFO, and summary + recent-tail baselines under identical budgets.

### 3.4 When to compact: signals from research and from practice

Research-side rubrics converge on **semantic boundaries rather than token thresholds**. SelfCompact fires when a sub-task is resolved or the trajectory is converging, and suppresses mid-derivation or when stuck; its ablation shows the rubric is where the gains live (removing it drops accuracy from 46.4% to 41.0%, level with naive fixed-interval summarization). ACM's teacher cues fire when the agent starts issuing redundant queries, enters unproductive loops, or has accumulated sufficient context — and, symmetrically, the teacher *replaces* premature compaction calls with more useful actions, treating "when not to compact" as equally important. CaT's candidate points are sub-task completion, strategy switches, and intermediate milestones. ContextBudget assesses remaining budget *before* loading the next observation.

Practitioner heuristics for Claude Code (with an important caveat below): compact manually at natural task boundaries — after a feature or PR, after a debugging path is understood, before switching from research to implementation; watch for task boundaries around 30–50% utilization and finish the current micro-task then compact around 50–60%; never interrupt a working implementation mid-flight just because a number crossed a threshold; compact early because summaries generated from uncompressed context are higher quality; offload or "microcompact" large tool outputs (full files, build logs) as soon as they land. Anthropic's own engineering guidance describes compaction as summarize-and-reinitiate, continuing with "the compressed context plus the five most recently accessed files" (i.e., summary + recent raw tail), backed by structured note-taking and sub-agent architectures. Default auto-compaction in shipped products has historically fired very late (~83–95% of window), and both the research literature and practitioners regard this as too late.

**Caveat on evidence quality.** The specific percentages above come from individual practitioner blogs (nathanonn.com, MindStudio, bswen.com, okhlopkov.com), not from controlled experiments, and the numbers vary between authors (40–50%, 60%, "15–20% for 1M windows"). Only two conclusions are robustly supported: practitioners compact **well before** the automatic trigger point, and they prefer **task/semantic boundaries** over token thresholds. An earlier draft of this analysis claimed practitioner working sets are "an order of magnitude" below nominal windows; that was an overstatement — the blog heuristics imply roughly 2× headroom against a 200K window, and ~10× only when comparing 1M nominal windows to the 32–80K working budgets used in Context-Folding and CompactionRL.

One more finding matters for data collection: **strong teachers do not compact voluntarily.** ACM observed that GPT-5.5, even when given context-management tools, almost never calls them. Teacher trajectories with compaction cannot be harvested; they must be constructed.

### 3.5 Training on compacted trajectories: the landscape and the gap

| Training paradigm | Works | Trigger control | Relation to this project |
|---|---|---|---|
| RL | CompactionRL, SUPO (2510.06727), Context-Folding, ReSum-GRPO (2509.13313), MemAct (2510.12635) | Harness threshold / periodic / agent tool | Closest in *setting* (CompactionRL is harness-controlled, coding-focused) but wrong in *method* for a distillation pipeline |
| SFT | CaT, AgentFold (2510.24699) | Agent-initiated tool | Right method, but bundles when + what + continue into one learned action |
| On-policy distillation | ACM | Agent-initiated tool, teacher-annotated timing | Best data-construction recipe; still agent-initiated |
| **Harness-controlled + SFT-only continuation** | **— (no standalone paper found)** | Harness | **The open slice this project fills** |

The strongest existence proof that the open slice will work comes from CompactionRL's ablation (Section 3.6): merely exposing the policy to compacted histories, with the summary turns masked out of the loss, recovers most of the gain — in an RL setting. Whether SFT recovers it too is exactly the proposed experiment.

### 3.6 CompactionRL deep dive (the closest prior work)

CompactionRL (Zhipu, arXiv 2607.05378) deserves close reading because it validates nearly every design shortcut this project intends to take.

Its harness is maximally simple: compaction triggers when remaining budget drops below a fixed reserve (10,240 tokens, equal to the per-response cap); the policy itself generates the summary from a fixed instruction; the context is rebuilt as system prompt + summary template + the last k = 2 raw steps; each assistant–observation pair is treated as an atomic step so tool calls are never severed from their feedback; at most three compactions per rollout. No semantic-boundary detection whatsoever.

Crucially, its budgets are **deliberately small relative to the window**: 64K for GLM-4.7-Flash and 80K for GLM-4.5-Air, with 128K/160K "Long" no-compaction reference arms. The compaction-trained models at ×4 effective budget match or beat the Long references — i.e., a small working set plus learned compaction substitutes for a window twice the size.

Three results are directly load-bearing for this project. (a) **Summarizer quality alone swings outcomes by 6.5 points** (49.0 → 55.5 on SWE-bench Verified when only the summary agent is changed), so the summarizer used at data-generation time must be byte-identical to the one deployed. (b) The **w/o-summary-training ablation** — compaction enabled during training, summary turns masked from the loss — isolates the effect of exposing the policy to compacted histories: compacted-inference accuracy goes 50.5 → 54.5 (30B) and 59.8 → 64.5 (106B) from exposure alone; training the summarizer adds a further +1.5/+2.3 to reach 56.0/66.8. (c) **Train/test mismatch is real**: gains do not transfer to single-window (no-compaction) evaluation, and no-compaction RL degrades compacted inference — so training data must mix compacted and ordinary trajectories.

Its evaluation protocol (Terminus-KIRA scaffold in the Harbor environment; 200-instance SWE-bench Verified random subset + full Terminal-Bench 2.0; reporting ×1 and ×4 settings plus pass@1 on the compaction-triggered subset) is worth adopting verbatim for direct comparability. Its declared limitations — PPO-only, single-window regression, approximate cross-boundary credit assignment — are the project's opportunities.

---

## 4. Resolving the Trigger-Anchor Problem

The apparent paradox ("a 1M window with 64K max output implies compacting at ~900K, but such trajectories are uncollectable and some evals cap at 400K") dissolves once three quantities are separated:

**C_max** — the physical window (e.g., 1M). A safety net only; never the trigger anchor. **B_active** — the peak *working* context used for training and evaluation, chosen deliberately small (recommended sweep: 48K–128K). This, not C_max, determines where compaction events occur. **reserve** — the headroom kept before triggering, set from *empirical* P95 response length plus P95 next-tool-output size in the actual harness, not from the theoretical max_new_tokens; rare over-long thinking responses are handled as exceptions (truncate, compact, retry) rather than by inflating the reserve for the worst case.

Under this framing, a 200–300K teacher trajectory replayed at B_active = 64K naturally yields three to four compaction events, so data scarcity disappears; and a 400K evaluation cap becomes irrelevant because the harness compacts at ~64–128K and never approaches the cap. The final experiment then takes its natural form: *within the evaluation's context limit, a deliberately small working set plus trained compaction beats filling the window.*

B_active is chosen by a **no-training calibration experiment** on the student + target harness, over long tasks (long-trajectory SWE-bench Verified instances, SWE-bench Pro, NL2Repo): measure (i) pass rate bucketed by trajectory length without compaction, locating the degradation knee L_knee; (ii) the trajectory-length distribution (P50/P90/P99); (iii) pass rates under forced compaction at B ∈ {48K, 64K, 96K, 128K}, with observation masking and FIFO run at the same budgets as controls. Choose B_active above P50 (most tasks finish uncompacted), near L_knee (compaction happens *before* degradation), and such that the hardest tasks compact 1–3 times rather than 6–8 (repeated compaction erodes reliability). Curve (iii) also settles, before any training, whether summary-style compaction beats masking on this task distribution at all.

---

## 5. Data Construction Recipe

The recommended minimal recipe combines verified components from CaT, ACM, and CompactionRL:

**Trigger (offline, with hindsight).** On complete teacher trajectories, locate where context crosses a soft watermark (≈0.65·B_active), then snap the boundary to the nearest *safe* step — after a test run, a commit, or the end of a contiguous edit sequence — using CompactionRL's atomic-step rule (never sever an assistant–observation pair) and the practitioner suppression rule (never cut mid-implementation). Hindsight snapping costs nothing offline and sidesteps the online timing problem entirely.

**Summary (causal, deployment-identical).** Generate the summary from the prefix only — never with knowledge of the future — using the *exact* summarizer, prompt, and template that the deployment harness will use. Two results make this non-negotiable: CompactionRL's 6.5-point summarizer swing, and the finding (Parallel Context Compaction, 2605.23296) that summary output is nearly insensitive to prompt wording, so "controlling the summarizer via prompt" is unreliable — identity, not similarity, is required.

**Continuation labels (re-rollout, not suffix reuse).** Do not reuse the original trajectory suffix as the label: it was generated conditioned on the full context and may reference details absent from the summary. Instead, following ACM's resume-from-edit, re-roll the teacher from the compacted state and keep only continuations that end in verified task success. This is cheap — only the post-boundary segment is regenerated, and compacted samples are short.

**Distributional hygiene.** Randomize B_active (48–128K) and the raw tail length k (2–5) across samples; include multi-compaction-depth samples (a second compaction sees "previous summary + new raw segment," a different input shape from the first); mix compacted samples with ordinary uncompacted trajectories to avoid the single-window regression CompactionRL observed; filter for answer leakage in any teacher-written rationale.

---

## 6. Evaluation Design

**Headline table (Stage-1 experiment).** Three arms under one harness — base model, SFT on ordinary trajectories, SFT on ordinary + compacted trajectories — each evaluated at ×1 (compaction disabled, one B_active window) and ×4 (up to three compactions). Report additionally pass@1 on the subset of tasks that actually triggered compaction (CompactionRL Fig. 3c style). The gap between arm 1 and arm 3 evidences "compaction helps"; the gap between arm 2 and arm 3 isolates the SFT contribution. Aligning with CompactionRL's protocol (Terminus-KIRA/Harbor, SWE-bench Verified 200-subset, Terminal-Bench 2.0) allows direct cross-paper comparison.

**Timing ablation (Stage-2, answers the original Question 1 cheaply).** From the same source trajectories, build three datasets differing only in injection point — random midpoint, token threshold, hindsight semantic boundary — train, and compare. This is far cheaper than researching optimal timing up front, and answers a more interesting question: *does training make the model insensitive to trigger timing?* If yes, the harness-side trigger can stay simple; if no, precision timing research is justified afterward.

**Boundary-local diagnostics (Compaction Boundary Benchmark).** For deeper analysis and for filtering training data: from git worktree + container snapshots at candidate boundaries, run paired PRE (full context) / POST (compacted context) closed-loop continuations for K = 3–5 steps (Slipstream shows 88–100% of compaction-induced errors surface within three steps), measuring blocked/error actions, refetch/replay, next-action agreement, constraint preservation, and premature termination — then to task completion for a subset, reporting Pass@1, Pass@k, **Pass^k**, steps, peak context, compaction count, and performance vs. compaction depth. Static "did the summary retain the facts" metrics are insufficient: TRACE shows agents lose their *place* in the trajectory even when the facts are refetchable.

**Existing benchmarks to reuse rather than rebuild.** LOCA-bench (controllable environment-state growth with fixed task semantics; scaffold-aware; supports multiple context-management strategies) for calibrating B_active; NL2Repo-Bench (ICML 2026; repo generation from scratch over hundreds of steps) as the most natural compaction-pressure source for code; SWE-bench Verified/Pro and Terminal-Bench 2.0 under artificial budget sweeps; LoCoBench-Agent and LoCoEval as secondary. Note: **DeepSWE is a model/recipe (Agentica, built on R2E-Gym environments), not a benchmark** — its reusable asset is the executable-test environment, ideal for snapshot-based paired continuations. The overall recommendation is to build an evaluation *protocol* over existing task sets, not a new dataset.

---

## 7. Recommended Roadmap

**Stage 0 — Calibration (no training).** Run the Section-4 calibration on the student + harness; fix B_active and reserve; establish masking/FIFO/summary-tail baselines. Decision gate: if masking already matches summarization on this distribution, shift the project's emphasis from representation to timing/trigger learning; if a strong student shows no net benefit from any compaction at feasible budgets, large native windows suffice and the training project should be reconsidered.

**Stage 1 — Existence-proof SFT.** Build the minimal dataset (Section 5) with the simple hindsight-snapped threshold trigger; train; produce the three-arm ×1/×4 headline table. This is the SFT analogue of CompactionRL's w/o-summary-training ablation and, if positive, a clean standalone contribution.

**Stage 2 — Timing ablation.** Random-midpoint vs. threshold vs. semantic-boundary injection; measure post-training timing sensitivity.

**Stage 3 — Boundary benchmark + counterfactual filtering.** Stand up the PRE/POST snapshot protocol; use it both as a diagnostic (localizing failures to timing [F1] vs. representation [F2] vs. retrieval [F3], per the survey taxonomy in Preprints 202605.2065) and as a data filter (keep only continuations that don't increase blocked/refetch actions).

**Stage 4 — Scale-up.** On-policy distillation (ACM-style) to close residual distribution shift; optionally CompactionRL-style RL later; extend to multi-compaction curricula and sub-agent fold boundaries (Context-Folding suggests "fold-on-branch-completion" is the highest-value semantic boundary for code).

---

## 8. Risks, Open Questions, and Corrections

Attribution remains hard: end-to-end success cannot be credited to any single compaction event, which is why boundary-local evaluation is mandatory. The optimal policy is student-capability-dependent (AdaCoM), so teacher-calibrated boundaries may be suboptimal for the student — a reason to prefer student-rollout + teacher-edit data over pure teacher trajectories at scale. Compaction can silently drop user constraints and safety/acceptance criteria (Governance Decay, 2606.22528) — constraint preservation must be an explicit boundary metric. Repeated compaction degrades reliability (Pass^k), so compaction-depth distribution in training data matters. Systems-side, every compaction invalidates the KV-cache prefix and spikes time-to-first-token; asynchronous/parallel compaction is the serving-side mitigation. Finally, an industry scan found that apart from CompactionRL (now in the GLM-5.2 pipeline), frontier technical reports (Kimi K2, GLM-4.5, MiniMax, Qwen3-Coder, Seed-OSS) rely on large native windows and infrastructure scaling, treating compaction as a test-time strategy at most (DeepSeek-V3.2) — which is precisely why the training-data gap this project targets exists.

Corrections and unverified items carried forward for honesty: the Claude Code timing heuristics are anecdotal practitioner blogs, with inconsistent percentages between authors; the earlier "order of magnitude" characterization of window-vs-working-set headroom was this analysis's own overstatement (≈2× against 200K windows; ≈10× only against 1M). CaT's 57.6% is confirmed in primary sources, but a secondary source's 48.8/53.8/57.8 step-scaling table was not verified against the primary PDF. Several arXiv IDs in the broader survey (Slipstream 2605.08580, ContextBudget 2604.01664, Governance Decay 2606.22528, LoCoEval 2603.06358, AgentLongBench 2601.20730, AMA-Bench 2602.22769, among others) were taken from secondary listings and not all independently re-verified.

---

## 9. Key References

CompactionRL: Reinforcement Learning with Context Compaction for Long-Horizon Agents — arXiv 2607.05378 (Zhipu/Tsinghua; primary source, fully verified)
ACM: Agentic Context Management for Long Horizon Tasks — arXiv 2607.23809 (CMU + Meta; data/code/checkpoints released)
Context as a Tool (CaT / SWE-Compressor) — arXiv 2512.22087, ACL 2026 Findings
Scaling Long-Horizon LLM Agent via Context-Folding (FoldGRPO) — arXiv 2510.11967
Self-Compacting Language Model Agents — arXiv 2606.23525
The Complexity Trap: Simple Observation Masking Is as Efficient as LLM Summarization — arXiv 2508.21433 (JetBrains)
TRACE: Toward Reliable Context Compression for Long-Horizon Agents — arXiv 2608.06503
AdaCoM: Learning Agent-Compatible Context Management — arXiv 2605.30785
SUPO: Scaling LLM Multi-turn RL with End-to-end Summarization-based Context Management — arXiv 2510.06727
ReSum — arXiv 2509.13313 · AgentFold — arXiv 2510.24699 · MemAct — arXiv 2510.12635 · MEM1 — arXiv 2506.15841 · ACON — arXiv 2510.00615
LOCA-bench — arXiv 2602.07962 · NL2Repo-Bench — arXiv 2512.12730 (ICML 2026) · SWE-bench Pro — arXiv 2509.16941 · Terminal-Bench — arXiv 2601.11868
Parallel Context Compaction for Long-Horizon LLM Agent Serving — arXiv 2605.23296
Survey: Context Compression for LLM Agents (F1/F2/F3 failure taxonomy) — Preprints 202605.2065; GitHub: YerbaPage/Awesome-Agent-Context-Compression
DeepSeek-V3.2 — arXiv 2512.02556 · Kimi K2 — arXiv 2507.20534 · GLM-4.5 — arXiv 2508.06471
Anthropic, "Effective context engineering for AI agents" (engineering blog); Claude Cookbook, automatic context compaction
Practitioner sources (anecdotal): nathanonn.com "Never Let Claude Code Auto-Compact Again"; MindStudio /compact guides; bswen.com compact strategy; okhlopkov.com compaction explained
