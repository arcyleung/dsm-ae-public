# Compaction snowball findings (AS_OF 2026-09-01)

**PARKED 2026-09-01** — see `PARKED.md`. Resume there; do not expand this study until unparked.

Depth-3 snowball from `docs/surveys/compaction.md` §9 plus named
scaffolds and SFT trainers. Process: `PROCESS.md`. WebUI: `/compaction`.

Merged tree: **134 nodes, 180 edges** (d0=40, d1=80, d2=12, d3=2).
Five section agents: papers, evals, scaffolds, SFT-industry, SFT-academic.

## Q1 — When do coding-agent scaffolds compact?

Shipped products almost all fire on a **token / window / event-count
watermark**, plus a user `/compact` (or equivalent). Semantic-boundary
triggers live in papers and in practitioner folklore, not in default
product auto-compact.

| Product | Trigger | Published threshold | What is kept |
|---|---|---|---|
| **Grok Build** | threshold + `/compact [keep]` | **85%** of `context_window` (`[session] auto_compact_threshold_percent`) | Compressed history (summary / transcript / segments); last **3** tool-result turns full; memory flush+search; plan-mode kept |
| **Claude Code** | threshold + tool-output trim + `/compact` | Official: *approaches model limit* (no single %). Blogs: auto ~83–95%. Practitioners: **50–60%** at task boundaries | Structured summary; reload CLAUDE.md; re-read up to **5** recent files; older tool outputs cleared first |
| **Codex CLI / IDE** | threshold + `/compact` | `model_auto_compact_token_limit`; also clamped to **~90%** of window (staff 1M example: 900k) | Summary + recent user messages up to **20k** tokens |
| **GitHub Copilot CLI** | threshold + `/compact` | ~**80%** background, ~**95%** pause; tool I/O **>20 KiB** offloaded | Summary + user instructions + plans/todos |
| **Goose** | threshold + Compact | **80%** (`GOOSE_AUTO_COMPACT_THRESHOLD`; `0.0` disables) | Older-turn summary; recent tool calls fuller |
| **Gemini CLI** | threshold | source **0.5** of model limit | Compressed history (community: ~30% recent + snapshot) |
| **OpenHands** | event-count (+ overflow) | `max_size` **80–120**, `keep_first=4` | First N + recent tail + LLM middle |
| **SWE-agent** | tool_trim only | last **n=5** observations | Observation stubs — **not** an LLM summary |
| **mini-SWE-agent** | none | — | Linear append-only |
| **Cline** | threshold + `/smol` `/compact` | “approaching model limit”; % unpublished | LLM summary replaces history (else truncate) |
| **Roo** | threshold + Condense | slider default **100%** (example 80%); overflow −25% | Condensed earlier turns |
| **Cursor** | self-summarize + `/summarize` | research/evals **80k / 40k**; product % unpublished | ~1k self-summary + plan/todos |
| **Continue** | manual `compactConversation` | auto unpublished | Structured summary prepended |
| **Aider** | **none** | — | `/clear` `/drop`; repo-map ~1k tokens. No history compact |
| **Amp** | `/handoff` (replaced `/compact` Oct 2025) | later auto % unpublished | New thread: goal + files, not stacked summaries |
| **OpenCode** | threshold + `/compact` | used ≥ input_limit − min(20k, max_output) | LLM summary of older span |
| **Windsurf** | unknown | unpublished | Prior-chat summaries/checkpoints |

**Grok Build (first-party).** Auto-compact at **85%** of the model
`context_window` (default 200k if unset). `/compact` can take a keep-note.
`two_pass_compaction` defaults on. `/flush` is recommended *before*
compaction because compaction discards old turns. Memory is searched
again after auto-compact. Headless emits `compact_boundary`. Per-model
overrides: `auto_compact_threshold_percent`, `compaction_at_tokens`.

**Research / eval triggers (not product defaults).**

- Reserve: CompactionRL remaining budget < **10,240** tokens, last k=2
  atomic steps, ≤3 compactions; `B_active` 64–80k, not C_max.
- Percent: DeepSeek-V3.2 **80% of 128k** (Summary / Discard-75% /
  Discard-all). Discard-all lifted BrowseComp 51.4 → 67.6.
- Semantic: SelfCompact (sub-task resolved / converging; suppress when
  stuck); CaT / ACM / Context-Folding (milestone, strategy switch,
  branch completion).
- Observation masking: Complexity Trap M=10 (SWE-agent) / M=58
  (OpenHands). Often matches or beats LLM summary.
- Late is treated as too late: Terminus 2 summarizes only at the model
  limit; practitioner blogs and Slipstream say production should compact
  far earlier.

**Robust, multi-source conclusions (not blog percentages):**

1. Default product auto-compact is a **late watermark** (80–95% of the
   window, or “at the limit”).
2. Humans compact **earlier, at task boundaries**, and never mid-flight
   of a working implementation.
3. Almost every scaffold also **trims tool outputs** independently of
   full-history summarization (Claude microcompact, Copilot 20 KiB,
   Grok last-3-turns prune, SWE-agent LastN).
4. Strong teachers **do not compact voluntarily** (ACM: GPT-5.5 almost
   never calls `manage_context`). Training data with compaction must be
   constructed, not harvested.

## Q2 — Compressed trajectories in SFT

There is **no compact-aware industry filter**. LlamaFactory and peers
do role-based loss masking. Academic papers split: train the
summarizer vs train the continuer.

### Industry (LlamaFactory and peers)

| Trainer | Default loss | Compact-aware filter? | What happens to a compacted span |
|---|---|---|---|
| **LLaMA-Factory** | `train_on_prompt=False`, `mask_history=False`: IGNORE_INDEX on user / system / **observation**; loss on every `gpt` / `function` turn | **No** | Assistant-written summary → **preferred** (trained). Harness-injected summary as user/system/observation → **kept as context** (not discarded, not in loss). `mask_history=True` trains **last turn only** |
| Axolotl | `roles_to_train=['assistant']`, `train_on_inputs=false` | No | Same role mask |
| TRL SFTTrainer | `assistant_only_loss` (often off unless set) | No | Same |
| Unsloth | `train_on_responses_only` | No | Same |
| NeMo | `answer_only_loss` | No | Same |
| OpenAI SFT API | all assistant messages; `weight: 0` to skip a turn | No | Compaction is a Responses-API *inference* item, not an SFT type |
| Community SWE-agent / OpenHands / Claude-Code corpora | filter on **task success**, min turns, loop prune | **No mention of `/compact`** | Whole failed trajs discarded; compact spans not special-cased |

So the industry standard is: **do not discard compacted parts**. They
are either assistant targets (if the model wrote them) or context (if
the harness injected them). Quality filters drop *failed trajectories*,
not summaries.

### Academic literature

| Recipe | `compressed_in_loss` | Why |
|---|---|---|
| **CompactionRL** (PPO) | **preferred** in the full recipe; **masked** in the load-bearing ablation | w/o-summary-training: expose compacted histories, mask summary-response turns. Recovers most of the gain (30B 50.5→54.5 of 56.0; 106B 59.8→64.5 of 66.8). Training the summarizer adds +1.5 / +2.3 |
| **ACM** distill | **preferred** on assistant incl. `manage_context`; tool-output **masked** | Re-roll student from teacher-edited turn; do **not** reuse the original suffix |
| **CaT / SWE-Compressor** SFT | mixed / unknown on observation tokens; compact **Actions** are SFT targets | Offline injection + rejection sampling of successes |
| **AgentFold** | **preferred** | Folding-directive block is the SFT label (no RL) |
| **Context-Folding / FoldGRPO** | **preferred** | Fold / return(message) are policy actions |
| **SUPO** | **preferred** | Periodic summary is jointly optimized |
| **ReSum** | **split** | Compressor SFT on ⟨conversation, summary⟩ (summaries preferred). Explorer GRPO trains *after* the summary; observations masked. Authors warn explorer SFT on ReSum trajs can overwrite skills |
| **ACON** | compressor distilled; **agent frozen** | CE on (raw → compressed text) |
| **SWE-Gym / AgentTuning / FireAct / OpenHands-LM** | n/a | Success / rater filters; **no compact-span policy** |

**Practice that matches this project's SFT-only continuation slice:**

1. Inject compaction offline (threshold snapped to a safe step).
2. Put the summary in the observation / user channel.
3. **Mask** summary tokens (do not train the student to be the
   summarizer unless that is the goal).
4. **Re-roll** the continuation from the compacted state; keep only
   verified successes. Do not reuse the pre-compaction suffix.
5. Mix compacted and ordinary trajectories (train/test mismatch is
   real: no-compaction RL *hurt* compacted inference).
6. Use the **byte-identical** summarizer at data-gen and deploy
   (CompactionRL ±6.5 pts; Parallel Compaction: summaries are
   prompt-invariant).

That is the opposite of “discard compressed parts,” and it is **more
specific** than LlamaFactory’s default (which would train an
assistant-authored `/compact` transcript if you dumped the session
as-is).

## Q3 — Split compactor / continuer: generation, filtering, fidelity

The papers that actually *split* the two jobs are ACM, ReSum, ACON,
AdaCoM, CompactionRL’s w/o-summary-training ablation, and (partially)
CaT (summary is an Observation; the CM *call* is the Action). They do
not share one recipe. Two forks matter more than any single filter.

### Who writes the summary, who is trained

| Work | Compactor | Continuer | Train continuer on summary text? |
|---|---|---|---|
| ACM | external summarizer LLM (tool result) | same student policy | **No** (tool-output masked). Train *when* (`manage_context`) |
| ReSum | ReSumTool SFT on ⟨conversation, summary⟩ | explorer via GRPO, not SFT | **No** for explorer; **yes** for compressor. Authors **refuse explorer SFT** |
| ACON | distilled compressor | **frozen** agent | **Never** |
| AdaCoM | manager LLM (edit/delete/rewrite) | **frozen** agent | **Never** |
| CompactionRL w/o-sum | same policy, loss-masked | same policy | **No** (summary turns masked; histories still shown) |
| CompactionRL full | same policy, in the PPO loss | same policy | Yes — not a split |
| CaT | teacher LLM memory block as Observation | same policy (SFT on CM Action) | Unknown on Observation tokens; CM *call* is the target |

### Generating distillation trajectories

Special considerations that show up in more than one split paper:

1. **Construct compaction; do not harvest it.** ACM: GPT-5.5 almost
   never calls `manage_context`. Timing is teacher-annotated onto
   *student* rollouts (inject on H−, remove premature calls on H+).
2. **Decouple roles when collecting compressor data.** ReSum: WebSailor
   explores, GPT-OSS-120B summarizes → 9k ⟨Conversation, Summary⟩
   pairs. ACON/AdaCoM: teacher compressor/manager, frozen weaker agent.
3. **Resume-from-edit vs stitch (the live disagreement).**
   - ACM: replace `a_t` with teacher `a_t′` and **re-roll** the student
     from that point. Original suffix is discarded as a label.
   - CaT: **stitch** the original ReAct suffix (“without altering the
     original sequence of environment interactions”). No re-roll.
   Compaction.md §5 follows ACM, not CaT, because the original suffix
   was conditioned on the uncompressed prefix.
4. **Causal, deployment-identical summaries.** Prefix-only; same
   summarizer/prompt/template as deploy. CompactionRL summarizer swap
   is **+6.5** pass@1 with the executor frozen. Parallel Compaction:
   wording barely moves summary volume (48× input → ~3× output).
5. **Atomic (action, observation) steps.** CompactionRL never severs a
   tool call from its feedback. Keep a raw tail (k=2 there).
6. **Do not SFT the explorer on compacted expert traces** (ReSum):
   “risks overwriting general capabilities and demands costly expert
   trajectories.” They use GRPO on post-summary segments instead,
   broadcasting the *final-answer* advantage to every segment.
7. **Mix ordinary and compacted / unedited student rollouts.** ACM
   resamples original student trajs (self-distill) to stabilize.
   CompactionRL: no-compaction RL *hurt* compacted inference.

### Selecting / filtering

There is **no compact-span discard**. Filters are about *which
rollouts* and *which teacher edits* to keep.

| Filter | Used by | Keep | Drop |
|---|---|---|---|
| Student fails all trials | ACM | hard cases for teacher edits | easy student successes |
| Answer-leakage in teacher rationale | ACM | justifications that cite loops / redundancy only | traces that reveal A* |
| Task success / unrecoverable error | CaT, ACON distill, SWE-Gym | completed trajs | failures (CaT); failed-*compressed* teacher (ACON CE) |
| Contrastive succeed-full / fail-compressed | ACON guidelines (ut) | D_cont for prompt search | uncompressed failures |
| Succeed-compressed only | ACON co + distill | D_succ / D_train⁺ | failed compressed teacher summaries |
| Unreasonable CM | CaT | — | too-frequent / no-gain / **semantic drift** / state inconsistency |
| Format / JSON / −20% modify | AdaCoM SFT, ReSum format-check | parseable manager/summary | invalid JSON, too-long, near-dups |
| Easy-task cap | SWE-Gym | per-instance cap | flood of short successes |
| Summary-quality score | **none of the split trainers** | — | CompactionRL *refuses* a hand-designed summary reward |

ACON’s 95% “teacher accuracy” is **frozen-agent task accuracy** with
the student compressor vs gpt-4.1, not token-level summary match.

### How compression → continuation fidelity is measured

Nobody in this set uses ROUGE as the agent-compaction score. Static
“did the summary keep the facts” is treated as the *wrong* target
(TRACE: agents lose their *place* even when facts are refetchable).

**Usable as a data filter (boundary-local, next-k steps):**

| Metric | Paper | Protocol | Headline number | Filter? |
|---|---|---|---|---|
| PRE/POST ΔG | TRACE 2608.06503 | Same AppWorld state; full-context PRE vs compacted POST; K=5; Q=−ΔG (extra blocked/error + refetch/replay) | 590 boundaries / 4640 rollouts; POST−PRE blocked **+0.108** at step 1 | **yes** |
| Terminate-form | TRACE | Hold the decision point; 10 next actions | 2K: summary 44.6% vs FIFO 77.2% vs full 66.6% | yes |
| Next-action TV | TRACE | Open-loop 24 samples vs full-history API-call dist. | retain 0.149 / compress **0.233** / omit 0.289 | yes |
| Next-k error locality | Slipstream 2605.08580 | First CM error within k steps | **88–100%** within 3 steps | yes |
| Plan + statement judge | Slipstream | Independent next-k vs summary; accept ≥7/10 | ~**90%** of failures are *omissions* | **yes** |
| Constraint survival | Governance Decay 2606.22528 | Does the summary still entail the pinned policy? | survive → **0%** violate (n=90); drop → **38%** (n=315) | **yes** |
| Pin constraints | Governance Decay | Re-inject ~47 tokens after every compact | restores 0% violation | yes |

**End-task / diagnostic only (not a per-boundary filter):**

- CompactionRL: pass@1 on the compaction-triggered subset; summarizer
  swap 49.0→55.5. **No local fidelity metric.**
- TRACE Pass^k vs Pass@k: repeated compact turns reliably-solved tasks
  into occasional ones (TRACE Acc / Pass² / Pass@2 = 77.1 / 67.3 / 86.9).
- AdaCoM “fidelity” = **post-management token volume** (1.9k–7.0k),
  not a summary-quality score. Stronger ReAct agents keep more raw
  context; weaker ones need more compression.
- AMA-Bench: QA over stored trajs (Recall / Causal / Update /
  Abstraction). NL summaries fail because tool traces are causal and
  machine-dense (GPT-5.2 72% vs AMA-Agent 57%).
- LOCA-bench: same CM helps Gemini/GPT and **hurts** DeepSeek. No
  separate fidelity axis.
- Parallel Compaction: prompt-invariance is a *negative*
  controllability result — you cannot steer retained content by
  wording.
- Complexity Trap: LLM summaries can *elongate* trajectories by
  masking failure signals (Gemini 52 vs 44 mask turns). Diagnostic,
  not a scored fidelity.

Survey taxonomy (YerbaPage / Preprints 202605.2065): **F1** timing,
**F2** in-compress loss, **F3** post-compress access. TRACE ΔG and
Slipstream next-3-step sit on F3; CaT “semantic drift” is F2.

**Practical filter for this project’s SFT-only continuation slice:**
at each candidate boundary, snapshot the env, run paired PRE/POST
continuations for **K=3–5** steps, and keep the sample only if POST
does not raise blocked/refetch vs PRE and the Slipstream-style judge
does not flag an omitted constraint. That is the literature’s actual
compression→continuation fidelity test. Fact-retention / ROUGE is not.

## Controversies / limits

- Practitioner 50–60% / 83–95% numbers are blogs, not controlled
  experiments. Only “earlier than auto, at a task boundary” is robust.
- CaT’s PDF does not state whether summary *Observation* tokens enter
  the SFT loss — do not treat 57.6% as proof of a particular mask.
- Several 2026 arXiv IDs in the parent survey were re-fetched; hops
  that 404’d are in each section’s `gaps`.
- Depth 3 is thin (2 nodes) because most product docs and trainer
  READMEs have no bibliography.

## Artifacts

```
research-notes/compaction/PROCESS.md
research-notes/compaction/seeds.json
research-notes/compaction/section-{papers,evals,scaffolds,sft-industry,sft-academic,split-recipes,fidelity}.json
research-notes/compaction/tree.json
research-notes/compaction/FINDINGS.md
reports/compaction/index.html
```
