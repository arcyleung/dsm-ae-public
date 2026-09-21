# Reframe: from "diagnostic taxonomy" to "capability smoke tests"

**AS_OF:** 2026-09-08
**Source:** supervisor discussion 2026-09-08
**Status:** actionable plan — blog rewrite, then paper draft

---

## 0. What changed

The supervisor notes are not a polish pass on the existing framing. They
replace the *thesis*. Stating both plainly so the delta is visible:

| | Old framing (current blog) | New framing (these notes) |
|---|---|---|
| **Claim** | "Which behaviours break the job?" — a behaviour→task weight matrix | "Smoke tests substitute for expensive benchmarks" — a cheap capability indicator |
| **Unit of value** | Explanation of failure | *Prediction* of task performance at lower cost |
| **Packs are** | Elicitation instruments for a taxonomy | **The product** — minimized, prioritized test cases |
| **Taxonomy is** | The contribution | Scaffolding for deriving smoke tests |
| **Killer question** | "Is this association causal?" | "Why not just run SWE-bench?" |

The behaviour→task work is **not discarded** — it becomes the *derivation
method* for smoke tests (§3), and the honest-limits material carries over
almost unchanged. But the headline claim changes, and so does what counts as
evidence.

### 0.1 The economic argument is now the spine

> "Long-horizon tasks are expensive to evaluate, unlike previous 'easy'
> bugfix-scoped PRs like SWE-bench, feat-bench. Our proposal is these smoke
> tests can serve as a quick indicator substitute of performance."

We have a hard number for this from our own runs. SWE-bench-Pro on the DGX:
~2.1 trials/hour/job, ~1-2h per instance, and 43 tasks × 2 models is roughly
a day of wall-clock. A DSM-AE pack battery is minutes. **If a pack score
predicts a benchmark score, the cost ratio is the entire pitch.**

That prediction is the claim the paper must defend, and it is *not yet
tested*. See §2 — it is testable on data already on disk.

### 0.2 "A capability that did not help resolve a task is not a useful capability"

This is the sharpest line in the notes and it cuts against our own taxonomy:
**158 codes, of which only the ones that move task outcomes are worth
keeping.** It is also exactly what the existing mapping measures. Reframed:

- `test_suppression`, `premature_stop` → **useful** (survive both controls)
- `scope_creep`, `thrash_edit`, `read_loop` → **unresolved** (difficulty-entangled)
- `edited_test_files` → **not useful** (fires 84%, predicts nothing)

The existing null result becomes a *feature* of the new framing rather than a
caveat: it demonstrates the method can reject a capability.

**Caveat to keep:** functional vs non-functional is situational. A capability
with no signal on SWE-bench-Pro issue-resolution may matter for code review or
on-call. The 199MB binary-dump trial (Q22) is the standing counterexample —
real, costly, `reward=1`.

---

## 1. The two shields (defense structure)

The notes name two lines of defense. Both are already partly in the repo;
both need explicit statement.

### Shield 1 — "the world has decided these capabilities matter"

Construct validity does not rest on us. Every wired syndrome traces to a prior
named construct with a benchmark behind it (OverEager, SlopCodeBench, MAST,
SycEval, AIRT, Apollo). The August snowball quantifies this: 333 nodes, 171
shipping a benchmark, 146 mapped to an existing pack.

**Action:** promote the existing revalidation table
(`research-notes/snowball/REVALIDATION.md`, keep rule: ≥3 sources **or** ≥1
benchmark) from an appendix to a *first-class defense section*. A reviewer
asking "did you invent these?" gets a table, not an argument.

### Shield 2 — "failure does not imply the behaviour caused it"

We already say this, and now it is load-bearing rather than a hedge. The
mapping's difficulty-stratification result is the honest core: four
agency/control instruments survive language adjustment and collapse under
difficulty, and we report that rather than the flattering column.

**Action:** state the causal limit *up front* in both blog and paper, not in a
limitations section. The smoke-test claim is **predictive**, not causal — it
needs `pack_score` to correlate with `task_score`, which does not require
causation at all. This is a genuine strength of the reframe: it needs a weaker
claim than the old one.

---

## 2. THE decisive experiment (do this first)

**Question:** does a pack battery score predict task-level benchmark
performance?

This is the paper's central empirical claim and it is **testable today on
existing data, with no new model calls.**

### 2.1 The join is thinner than it first looks — checked, not assumed

13 full-suite pack reports exist; the archived corpus has 1260 scoreable
SWE-bench-Pro + 216 NL2Repo trials. But **one archived bundle = one model**,
so each bundle yields exactly *one* task-level datapoint:

| bundle | model in trajectories | task datapoints |
|---|---|---:|
| swebenchpro-0901 | `openai-compatible/proxy` (opaque) | 1 |
| swebenchpro-0905 | `hosted_vllm/0905_505B_v2_1` | 1 |
| nl2repo-0827 | `hosted_vllm/glm-5.2-npu` | 1 |
| nl2repo-0904a | `hosted_vllm/92b_lhz_sft` | 1 |
| nl2repo-0904b | `hosted_vllm/92B_stage2` | 1 |

**Consequence: n = 3-4 plausible pairs at best, resting on an unverified
name mapping.** That is not enough for a correlation, full stop. Reporting a
rank correlation on n=4 with asserted identities would be the kind of result
this project has spent its whole audit history rejecting.

### 2.1b What to do instead

Two honest options, in order of preference:

1. **Generate the join deliberately.** Pick 3-5 models we control
   (gpt-5.6-terra/luna/sol already have both k=3 and k=20 pack suites), run
   each on the *same* task subset, and record the model id in both artifacts.
   The DGX nogo runs are already doing exactly this for terra/luna — so this
   is mostly a matter of finishing them and adding 1-2 more models. This
   yields a small but *real* join with known identities.
2. **Report the archived pairs as anecdote, not correlation.** Show the
   pack profile beside the task score for whichever pairs we can defend, label
   them as illustrative, and make no statistical claim.

Do **not** compute a correlation coefficient over n=4 asserted pairs and put
it in a paper.

### 2.2 Protocol

1. `pack_vector` per model = per-gate pass rates from
   `reports/full-suite/<model>-full.json` (`bootstraps[]`, 62 gates, each with
   `metric_id` / `pass_rate` / `status`). This side is clean and ready.
2. `task_score` per model = mean reward over scoreable archived trials —
   but see §2.1, only one model per bundle and names do not match.
3. **Pre-register the target n before looking.** Below ~8 models with
   *verified* identities, report descriptively and make no correlation claim.
   Above it, rank correlation on the aggregate plus per-gate correlations to
   locate which gates carry signal, with CIs.

### 2.3 If the correlation is weak

Do not bury it. A weak correlation is itself the finding that motivates §3:
*the current packs were not selected to predict task outcomes, so we should
not expect them to.* That is precisely the argument for deriving smoke tests
from observed task failures instead of from a literature taxonomy.

---

## 3. The core methodological contribution (the loop)

From the notes:

> The agent runs until a failure is encountered at the task level; with enough
> runs we can mine and locate the core capability the model is missing, then
> derive micro-benchmarks to act as the smoke test.

This is the paper's method section and it is **new** — the current pipeline
runs the taxonomy *forward* (pack → syndrome), while this runs it *backward*
(task failure → mined capability → derived micro-benchmark).

```
run task suite  ->  collect fail trajectories
                        |
                        v
        cluster failures on progress skeletons + off-policy instruments
                        |
                        v
        explain with existing codes; mint a new one only if leftover
                        |
                        v
        derive a minimal fixture that elicits that failure  <- THE SMOKE TEST
                        |
                        v
        validate: does the micro-benchmark predict the task failure?
```

Steps 1-3 exist (`src/dsm_ae/intent/`, `src/dsm_ae/harbor/instruments.py`,
`scripts/map_behaviour_to_task.py`). **Steps 4-5 do not** — deriving a fixture
from a mined cluster, and validating it back against the task, is the unbuilt
core of the contribution.

The composite fixture (`fixtures/composite/`) is the closest existing
artifact and is a good template for what a derived smoke test looks like: real
repos, external oracle, multiple demands in one workspace.

---

## 4. The literature gap that must be filled

> "How to define what is a good smoke test **← needs literature survey for
> sufficient defense**"

This is correctly flagged as a hole. The relevant fields are mature and we
have not surveyed them:

| Field | What to take from it |
|---|---|
| **Test-case minimization** | Formal criteria for a reduced suite that preserves fault-detection |
| **Test-case prioritization** | APFD and related metrics — ordering tests by expected fault yield |
| **Test suite reduction** | Coverage-preserving reduction; the classic HGS heuristic |
| **Mutation testing** | Fault-detection *adequacy* — the closest analogue to "does this smoke test detect the capability gap" |
| **Adaptive/defect prediction** | Selecting tests by predicted defect location |

**Action:** a bounded survey (same protocol as the August snowball: seeds +
depth caps + recorded exclusions) producing a *definition* of smoke-test
quality we can defend, with metrics borrowed rather than invented. Without it,
"good smoke test" is our opinion.

---

## 5. Positioning: the scaffold finding and the trend context

### 5.1 The other team's scaffold result

> weaker models: task performance improves, **fewer** tokens
> stronger models: task performance improves, **more** tokens

This matters because it is the strongest external evidence for our Axis V
insistence, and it complicates the smoke-test pitch honestly: **if scaffold
changes both capability and cost non-monotonically, a smoke test measured
under scaffold A may not predict task performance under scaffold B.** Our own
pooling error (two harnesses in one block, Q23) is the same problem seen from
inside.

**Action:** state scaffold-conditionality as a scope condition of the smoke
test, not a limitation buried at the end. Cite OverEager's framework-gating
result (5.4-27.7% vs 0.2-4.5%) alongside the internal finding.

### 5.2 Trends to situate against

Databricks Omni and the OpenHands meta-harness are moving toward
harness-level abstraction. Position DSM-AE as complementary: they standardize
*how agents run*; we measure *what capability the agent has*, cheaply, under a
declared harness.

### 5.3 The value statement

> "Understand the wider capability of models, consistency, and not focused on
> benchmaxxing."

Consistency is measurable and already in the pipeline: the UNSTABLE gate
(std > 0.25) and the k-trial bootstrap. Benchmaxxing resistance is the
argument for *derived, personalized* smoke tests — a suite mined from your own
task failures cannot be trained against in the way a public leaderboard can.

---

## 6. Answering "why not just run the full benchmark?"

The notes pose this twice; it is the reviewer's first question. The answer has
three parts and only the first is currently defensible:

1. **Cost.** Measured, ours: ~1-2h/instance, ~a day per model for 43 tasks.
   Packs are minutes. **Defensible now.**
2. **Diagnosis.** A benchmark score says *whether*; a capability profile says
   *what to fix*. Partly defensible — the mapping shows some behaviours
   predict failure, none proven causal.
3. **Personalization.** Public benchmarks saturate and leak; a mined suite
   targets *your* failure modes. **Not yet demonstrated** — needs §3 steps 4-5.

Do not claim (2) or (3) as established. The paper can honestly claim (1) plus
"a method for (2) and (3) with a first empirical slice."

---

## 7. Work plan

### Phase A — blog wrap-up (days)

- [ ] **A1.** Rewrite the thesis around smoke-tests-as-substitute. Keep §3.4
      (the mapping) but reframe it as *evidence the derivation loop works*,
      not as the headline.
- [ ] **A2.** Add the two shields as explicit sections (§1 above).
- [ ] **A3.** Add the cost argument with our own measured numbers (§0.1).
- [ ] **A4.** Fold in "a capability that didn't help resolve a task isn't
      useful" (§0.2), using the `edited_test_files` null as the worked example.
- [ ] **A5.** State scaffold-conditionality as a scope condition (§5.1).
- [ ] **A6.** Regenerate `reports/blog/index.html`; verify nav + `/dsm-ae/`.

### Phase B — the decisive experiment (days)

- [ ] **B1.** `scripts/pack_vs_task.py` — extract `pack_vector` from the 13
      full-suite reports (clean side), and emit the *joinable* table with an
      explicit `identity_verified` column. Assert nothing.
- [ ] **B3.** Grow the join deliberately (§2.1b option 1): the DGX terra/luna
      nogo runs already produce both halves with known ids. Add 1-2 more
      models on the same 43-task subset.
- [ ] **B4.** Only once n is adequate: correlation + per-gate breakdown with
      CIs. Publish a negative result if that is what it is — it motivates §3.

### Phase C — paper draft (weeks)

- [ ] **C1.** Smoke-test-quality literature survey (§4), bounded protocol,
      recorded exclusions.
- [ ] **C2.** Implement derivation loop steps 4-5 (§3) — mine a cluster,
      derive a fixture, validate it predicts the task failure.
- [ ] **C3.** Cluster-robust inference on the mapping (Q23): paired test over
      instances, or cluster bootstrap. No model calls needed.
- [ ] **C4.** Split the archived mapping by agent harness (Q23) — fixes the
      Axis V violation and the clustering at once. **Highest-value unrun
      analysis; do this early, it is cheap.**
- [ ] **C5.** Paper skeleton: intro (cost) → shields → method (loop) →
      experiment (B) → derived-suite validation (C2) → limits.

### Ordering note

C4 and C3 are cheap, use existing data, and strengthen everything downstream —
run them alongside Phase A rather than waiting for Phase C.

---

## 7b. UPDATE 2026-09-08 (evening): what the survey and the corrections changed

Two workstreams landed after this plan was written and both cut against it.
Recording the delta rather than editing the plan silently.

### The literature verdict: triage, not substitute

The smoke-test survey (65 verified sources,
`2026-09-08-smoke-test-criteria-survey.md`) returns **partial support for the
weak claim, substantial damage to the strong one**:

- **The industrial literature says smoke tests *triage*, they do not
  substitute.** This is the single most important framing correction
  available, and it is good news: the triage claim is defensible *today* on
  cost alone and clears a far lower evidentiary bar than substitution. §6's
  three-part answer should lead with triage, not prediction.
- **Efficient-eval prior art proves the technique and names our missing
  precondition.** tinyBenchmarks (100 of 14K MMLU), Anchor Points, Sort &
  Search all fit item parameters on large pools of *already-evaluated models*
  — 87, ~100, 31,000 respectively. **We have 10 models and zero verified
  pack↔task identity joins.** The prior art tells us what to collect; it does
  not tell us we have it.
- **Rothermel's reduction negative result reproduces on our own suite.**
  Answer to "how far can it be pared down": **not to 5, not to 10; ~15-20 of
  62** — and that is measured against our own suite mean on n=7 with CIs
  including zero.
- **Ruan/Maddison/Hashimoto (arXiv 2405.10938)** is the closest external
  support: agentic performance *is* predictable from simpler non-agentic
  benchmarks. It also needs ~100 models and predicts from established
  benchmark scores, not a bespoke toy suite.
- **Shield 1 is narrower than §1 claims.** Coverage/revalidation defends
  *construct validity* — that these capabilities matter — not *instrument
  quality*. The blog currently conflates them. Separate them explicitly.

### The discrimination result changes the priority order

**81% of gates cannot separate terra from luna from sol at k=20** (Q25;
verified independently). The OASD gates are simultaneously lowest-
discrimination and UNSTABLE. 83% of count-thresholded gates carry zero
information versus 25% of structural ones.

Combined with Q24 (zero instruments survive scaffold + clustering), the
honest position is: **the current battery is not yet a smoke test, and the
blocking problem is elicitation, not analysis.** No amount of further
statistics on these gates will produce discrimination that the gates do not
have.

### Revised priorities

| Was | Now |
|---|---|
| B: pack↔task correlation | **Blocked** — n=10, no verified identity join. Do not attempt. |
| C1: literature survey | **Done** (65 sources) |
| C3/C4: statistics | **Done** — and they removed every finding |
| — | **NEW P0: fix elicitation.** Gates that never vary cannot be smoke tests. Target the 18 ceiling gates and the 76 flat gpt-5.6 gates. |
| — | **NEW P1: mutation-style adequacy check.** Take a model or scaffold known deficient in capability X; confirm the pack for X fires. No benchmark runs. Cheapest thing that moves the verdict. |
| — | **NEW P2: structural-gate rule.** Prefer structural; a count gate needs a harness-invariant denominator and cross-harness validation. |

P1 is the highest value-per-hour item in the whole plan: it directly answers
"does this detect the gap" and needs no new benchmark runs.

---

## 8. What this plan does not fix

- **Go/JavaScript are unmeasurable on the DGX** (QEMU). Reproducible on x86;
  the sample is seed-42 fixed.
- **gpt-5.6 has too few scoreable fails** (~16) for a per-model mapping. The
  archived corpus carries the finding.
- **The smoke-test→benchmark correlation may not exist.** §2 is a real
  experiment with a real chance of a negative result, and the plan commits to
  publishing it either way.
