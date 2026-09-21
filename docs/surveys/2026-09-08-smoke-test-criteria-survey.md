# What makes a good smoke test? A bounded survey, and how the DSM-AE packs measure up

**AS_OF:** 2026-09-08
**Branch:** `intent-state`
**Purpose:** fill the hole flagged in `2026-09-08-smoke-test-reframe-plan.md` §4 —
*"How to define what is a good smoke test ← needs literature survey for
sufficient defense."* Without it, "good smoke test" is our opinion.
**Companion analysis:** `scripts/survey_pack_information.py` (all empirical
numbers in §6–§10 are reproducible from it; `scripts/survey_verify_citation.py`
is the citation verifier that was actually used).

Every claim is tagged **IN-REPO** (supported by files/runs here), **LIT**
(supported by a verified published source), or **HOLE** (not obtainable from
either). Same convention as `docs/surveys/dsm-ae-defense-qa.md`.

---

## 0. The two claims this document has to defend

The reframe plan asks the survey to defend two specific claims, or honestly
report that the literature does not support them.

| # | Claim | Verdict (details in §11) |
|---|---|---|
| **C1** | Smoke tests work sufficiently well / are sufficiently representative for benchmarking agentic models, without running 100s of end-to-end tasks. | **Partially supported — with a named precondition we do not currently meet.** |
| **C2** | Tasks can be pared down a long way while remaining a consistent indicator of a specific capability. | **Supported in principle, contradicted for *our* suite as currently constituted.** |

And the reviewer question it must survive:

> *"How do you know your 24 toy packs tell me anything about a model's
> performance on real work?"*

The short answer this document arrives at: **as of today, we do not know, and
the analysis in §6–§10 shows the suite has properties that make the claim
harder rather than easier to defend.** The literature does supply a defensible
*method* for getting there, and names the precondition. It also supplies a
well-known negative result (§4.2) that a reviewer will raise, and we engage
with it rather than hiding it.

---

## 1. Protocol and honest limits of the survey itself

Same bounded protocol as the August snowball: named seeds per field, verified
citations, recorded exclusions.

**Verification method — and a caveat about it.** `WebSearch`/`WebFetch` were
unavailable throughout this work (502 from the inference gateway on every
call). Verification was instead done by direct HTTPS against
**api.crossref.org** and **export.arxiv.org**, which do work from this
environment; `scripts/survey_verify_citation.py` wraps that. A source is
recorded here only if Crossref or arXiv returned a matching title with
authors and year. **Exclusions are recorded in §12.** No citation in this
document is from memory alone.

**What this verification does and does not establish.** It establishes that
the paper *exists* with the stated authors, venue, year and DOI. It does
**not** verify the paper's internal numbers. Where a numeric finding is quoted
below it is either (a) taken from an abstract fetched directly in this session
— marked *[abstract-verified]* — or (b) stated qualitatively. **Numbers that
could not be substantiated were left out rather than approximated.** In
particular, the exact correlation coefficients from Just et al. (2014) and
Papadakis et al. (2018) are deliberately *not* quoted (§12).

**Source count: 65 verified.** By category:

| Field | Verified sources |
|---|---:|
| Test-suite minimization / reduction | 14 |
| Test-case prioritization (APFD family) | 9 |
| Test-suite adequacy / coverage critique | 7 |
| Mutation testing | 13 |
| Smoke / BVT / CI test selection at scale | 9 |
| Test flakiness | 7 |
| Benchmark subsetting + efficient LLM eval | 10 |
| IRT / psychometrics | 8 |
| *(overlap: 12 sources counted in two categories)* | *(−12)* |
| **Distinct total** | **65** |

---

## 2. What "smoke test" actually means (and what it does not)

**LIT.** The term is older than this project by thirty years and it does not
mean what the DSM-AE packs currently do. In industrial usage a smoke test — or
build-verification test — is a *fast, cheap gate placed in front of an
expensive process*, whose job is to answer one question: **is this build worth
spending the expensive suite on?** It is explicitly *not* a diagnosis, and it
is explicitly *not* a substitute for the full suite. Memon & Xie (ICSM 2004;
TSE 2005) is the closest thing to a formal empirical study of smoke-test
effectiveness, and it evaluates smoke tests exactly this way: by the fraction
of faults they catch relative to the full suite, per unit of cost.

This matters for our framing. The reframe plan's pitch is that packs
*substitute for* an expensive benchmark. The industrial literature does not
claim smoke tests substitute for anything — it claims they *triage*. The
weaker, better-supported version of C1 is:

> *A pack battery is a cheap gate that tells you whether a model is worth
> spending a day of SWE-bench-Pro on.*

That claim needs a much lower bar than "predicts the benchmark score", and the
cost argument (§0.1 of the reframe plan, measured on our own hardware: ~1–2 h
per instance, ~a day per model for 43 tasks, vs minutes for a pack battery) is
already sufficient to motivate it. **Recommendation: lead with the triage
claim, not the substitution claim.**

---

## 3. Borrowed definitions: what a defensible quality metric looks like

The survey's main deliverable is a *definition of smoke-test quality with
metrics borrowed rather than invented*. Four are directly transferable.

### 3.1 Fault-detection rate per unit cost (APFD / APFD_c) — **LIT**

Rothermel, Untch, Chu & Harrold (TSE 2001) introduced APFD: if you run only
the first *k*% of an ordered suite, what fraction of known faults have you
already caught? Elbaum, Malishevsky & Rothermel (ICSE 2001) added APFD_c,
weighting for execution cost and fault severity — because a suite that
"covers everything" but front-loads cheap, low-severity checks is worse under
a real budget than one ordered by actual defect-finding power. Do, Mirarab,
Tahvildari & Rothermel (TSE 2010) extended this to explicit time budgets,
which is exactly the regime a smoke test lives in.

**Transfer to DSM-AE:** the analogue of "faults" is *models whose real-task
performance is inadequate*. A pack battery's quality metric should be: at what
fraction of total pack-battery cost do you correctly identify the models that
will do badly on the real benchmark? We cannot compute this yet (§10).

### 3.2 Item discrimination and item information (IRT) — **LIT**

This is the principled framework for "which items are informative", and it is
directly transferable because it was built for exactly our shape of data
(subjects × items × binary outcome). Lord (*Applications of Item Response
Theory to Practical Testing Problems*), Embretson & Reise, Baker & Kim, and
van der Linden & Glas (*Elements of Adaptive Testing*) define the two
quantities that matter:

- **Item discrimination** — how sharply an item separates high-ability from
  low-ability subjects. An item everyone passes, or everyone fails, has
  discrimination ≈ 0 and carries **zero information regardless of how
  well-motivated the construct behind it is.**
- **Item information function** — how much an item reduces uncertainty about
  ability, and *at what ability level*. Short-form construction in
  psychometrics selects items by information, not by topic coverage.

This framework has already been imported into NLP evaluation: Lalor, Wu & Yu
(EMNLP 2016) built an IRT evaluation scale for NLP; Rodriguez et al. (ACL
2021) showed evaluation examples are not equally informative and that
leaderboards should account for it; Vania et al. (ACL 2021) compared NLP test
sets by IRT item parameters.

**Transfer to DSM-AE:** a gate that every model passes is not a weak gate that
needs a better threshold — under IRT it is **not an item at all**. §6 shows
31% of our common gates are in this category.

### 3.3 Mutation adequacy — **LIT**

Mutation testing is the closest formal analogue to "does this smoke test
actually detect the capability gap it claims to detect". DeMillo, Lipton &
Sayward (1978) and Hamlet (1977) proposed it; the validity argument rests on
the coupling effect (Offutt, TOSEM 1992). The procedure: perturb the system
under test in known ways, and score the suite by the fraction of perturbations
it detects. A suite that detects no injected defect is inadequate *no matter
what it covers*.

**Transfer to DSM-AE:** the missing experiment. We have never taken a model
known to be deficient in capability X and checked that the pack for X fires.
The packs' `well_attuned` vs `disordered` mock personas (`MockClient`) are the
nearest existing thing and are a *fixture-level* check, not a model-level one.
**This is a HOLE, and it is the single cheapest high-value experiment
available** — it needs no new benchmark runs, only a deliberately degraded
model or scaffold.

### 3.4 Failure recall under selection — **LIT**

The CI-scale literature evaluates a reduced suite by *recall of failures*:
what fraction of the failures the full suite would have caught does the
reduced one still catch, and at what fraction of the cost? Herzig, Greiler,
Czerwonka & Murphy (ICSE 2015, "The Art of Testing Less without Sacrificing
Quality"), Machalica, Samylkin, Porth & Chandra (ICSE-SEIP 2019, "Predictive
Test Selection"), Memon et al. (ICSE-SEIP 2017, "Taming Google-scale
Continuous Testing"), Elbaum, Rothermel & Penix (FSE 2014), and Gligoric,
Eloussi & Marinov (ISSTA 2015, Ekstazi) all frame it this way. This is the
metric a practitioner will actually ask us for.

---

## 4. Where the literature does NOT support us

This section is the one a reviewer will read first. It is placed before the
empirical half deliberately.

### 4.1 Coverage is not effectiveness — **LIT, and it cuts against us**

The DSM-AE taxonomy's central organising claim is *coverage*: 158 codes, 71
wired, syndromes mapped to prior named constructs. The revalidation table
(Shield 1) is a coverage argument. The coverage-adequacy literature is
unambiguous that this is not a quality argument.

Inozemtseva & Holmes (ICSE 2014, "Coverage Is Not Strongly Correlated With
Test Suite Effectiveness") is the canonical statement: **once suite size is
controlled for, coverage correlates only weakly with a suite's ability to
detect faults.** Gopinath, Jensen & Groce (ICSE 2014) reached a compatible
conclusion in the same session. Kochhar, Lo, Lawall & Nagappan (IEEE Trans.
Reliability 2017) found the same weak, inconsistent signal against real
post-release defects at scale. And this is not new — Hutchins, Foster, Goradia
& Ostrand (ICSE 1994) and Frankl & Weiss (TSE 1993) established decades ago
that satisfying a structural adequacy criterion is only weakly and
inconsistently predictive of fault detection.

**Consequence for us, stated plainly:** "our packs cover 20 syndromes derived
from 333 literature nodes" is **not** evidence that the pack battery is a good
smoke test. It is the exact form of argument this literature rejects.
Shield 1 defends *construct validity* — that we did not invent the
capabilities. It does not defend *instrument quality*. These need to be
argued separately, and the blog/paper currently conflates them.

§8 makes this concrete on our own data: a syndrome-coverage-preserving
reduction of our suite performs no better than picking gates at random from
the same syndromes.

### 4.2 The reduction literature's negative result — **LIT, and it is the reviewer's best weapon**

This is the most important paragraph in the document.

The claim "you can pare a suite down and keep the signal" has been tested for
thirty years, and the field's answer is **conditional, contested, and often
negative.**

- **Wong, Horgan, London & Mathur** (ICSE 1995; SPE 1998) minimized
  coverage-adequate suites and reported that fault-detection effectiveness was
  largely retained — the optimistic result, and the one usually cited by
  people advocating reduction.
- **Rothermel, Harrold, Ostrin & Hong** (ICSM 1998) and **Rothermel, Harrold,
  von Ronne & Hong** (STVR 2002) ran the same kind of experiment on different
  subjects and found the opposite: minimization could cause **substantial,
  sometimes severe loss of fault-detection capability, worsening as the
  reduction ratio increased.**

Two careful groups, similar-looking protocols, opposite conclusions. **Yoo &
Harman's survey (STVR 2012) does not resolve it** — it reports that the
outcome is highly conditional on the subject program, the fault population,
the coverage criterion driving reduction, and how reduction is operationalized.
Later work (Shi et al., FSE 2014 and ISSTA 2018; Coviello, Romano &
Scanniello, ESEM 2018) reframes the question as **adequate vs inadequate
reduction**: techniques that formally preserve an adequacy criterion lose
measurably less than heuristic reduction, and loss varies a lot across real
evolution histories rather than being a constant. Jeffrey & Gupta (ICSM 2005;
TSE 2007) showed that *deliberately retaining some redundancy* recovers much
of the lost fault detection — i.e. the optimum is not the minimal set.

**Three consequences we must state up front, not bury:**

1. **Aggressive minimization is the known-risky case.** A 5-gate battery
   selected greedily is precisely the configuration Rothermel's results warn
   about. §9 shows this empirically on our own data.
2. **A reduction is only defensible against a named adequacy criterion.**
   "These 5 gates track the full-suite mean" is not one; it is in-sample
   curve-fitting.
3. **We should keep redundancy on purpose.** Jeffrey & Gupta's result argues
   directly against the smallest-battery framing.

### 4.3 The subsetting literature's precondition — **LIT, and we do not meet it**

The efficient-LLM-eval work is the closest prior art to what DSM-AE claims,
and it is what a reviewer who knows one thing will know.

- **tinyBenchmarks** (Polo et al., arXiv 2402.14992) — *[abstract-verified]*
  "to accurately estimate the performance of an LLM on MMLU, a popular
  multiple-choice QA benchmark consisting of 14K examples, it is sufficient to
  evaluate this LLM on **100 curated examples**." Reductions of this magnitude
  are real and published.
- **Anchor Points** (Vivek, Ethayarajh, Yang & Kiela, arXiv 2309.08638) —
  *[abstract-verified]* "across **87 diverse language model-prompt pairs**,
  evaluating models using **1-30 anchor points** outperforms uniform sampling
  and other baselines at accurately ranking models."
- **Sort & Search** (Prabhu et al., arXiv 2402.19472) — *[abstract-verified]*
  evaluations across **over 31,000 models**, "reducing compute cost from 180
  GPU days to 5 GPU hours (about **1000x reduction**)".
- **Efficient Benchmarking** (Perlitz et al., arXiv 2308.11696) —
  *[abstract-verified]* introduces *Decision Impact on Reliability* (DIoR) and
  finds "a benchmark leader may change by merely removing a low-ranked model" —
  i.e. subsetting decisions are themselves fragile.

**Now the precondition, which is the load-bearing sentence of this whole
section.** Every one of these methods selects the subset by fitting item
parameters — IRT ability/difficulty, or cross-model correctness-pattern
correlation — **on a large pool of models that have already been evaluated on
the full benchmark.** tinyBenchmarks fits IRT on the Open LLM Leaderboard.
Anchor Points uses 87 model-prompt pairs. Sort & Search uses 31,000 models.

**We have ten.** And, critically, we have *zero* models with a verified
identity join between a pack vector and a task score — the reframe plan's §2.1
establishes that the archived corpus yields at best 3–4 pairs resting on an
unverified name mapping.

So the honest statement is: **the prior art proves the technique works, and
simultaneously names the resource we lack.** It does not license us to claim
the result; it tells us what to go and collect.

### 4.4 No prior art for agentic proxy prediction — **HOLE, and it is a gap not a flaw**

All of the above subsets a benchmark *by sampling from that same benchmark's
items*. tinyMMLU is made of MMLU questions. DSM-AE proposes something
different and stronger: that performance on **a separate, cheaper, structurally
different task family** (toy packs) predicts performance on long-horizon agentic
tasks (SWE-bench-Pro). Searches turned up no verified prior work making that
cross-family claim for agentic benchmarks.

Two readings, and honesty requires stating both:

- **Favourable:** this is genuine novelty, and it is the paper's contribution.
  Efficient-eval theory is mature for static, single-turn, IID benchmarks and
  **essentially unexplored for agentic, multi-turn, long-horizon ones.** No
  verified work applies IRT or anchor-point item selection *within* an agentic
  benchmark the way tinyBenchmarks does for MMLU. SWE-bench Verified (an
  OpenAI blog post, not a paper) and SWE-bench-Pro (arXiv 2509.16941) both
  curate subsets, but for validity and contamination-resistance, not for
  statistically-grounded minimal-item selection.
- **Unfavourable:** it means there is no published evidence that
  cross-family proxy prediction works at all, and the burden of proof is
  entirely ours.

**The one genuinely close hit, and it cuts both ways.** Ruan, Maddison &
Hashimoto (arXiv 2405.10938, observational scaling laws) fit a low-dimensional
capability space on ~100 already-public models and claim that **agentic
performance can be predicted from simpler non-agentic benchmarks.** That is the
closest published support for the DSM-AE thesis in existence. But note what it
does and does not license: it is *cross-model scaling-law extrapolation* fit on
~100 models, not per-item subset selection — and it predicts from *established
benchmark scores*, not from a bespoke toy suite. It supports the *possibility*
of cheap agentic proxies; it does not support ours, and its own method again
needs ~100 models. Owen (arXiv 2401.04757) is the sober counterweight:
extrapolating BIG-Bench-Hard across one order of magnitude of compute gives
~6pp average absolute error, and per-task extrapolation is noisier (~18pp).

---

## 5. The empirical half: setup and a power warning

Everything in §6–§10 is produced by `scripts/survey_pack_information.py`.

**IN-REPO.** 13 full-suite report files exist. Three of them
(`gpt-5.6-{terra,luna,sol}-max-full.json`) are k=20 re-runs of models that also
have a k=3 report, so they supersede rather than add. **The model axis is
n = 10 distinct models.** 62 gates are common to all ten; the k=20 suites carry
94.

> **POWER WARNING, stated once and meant throughout.**
> **n = 10.** A correlation matrix over 43 non-degenerate gates from 10
> observations has 903 pairs and 9 degrees of freedom. A PCA on it has rank ≤ 9
> *by construction*. At n=10, a sample Spearman of 0.80 has a 95% CI of roughly
> **[0.34, 0.95]** (Fisher z) — it is compatible with a moderate correlation
> and with a near-perfect one. Every number in §7–§9 is **EXPLORATORY**.
> None of it belongs in a paper as an established result. The most defensible
> outputs of this section are the *qualitative* findings (§6 and §10), which
> do not depend on cross-model correlation.

Also note the pass-rate granularity problem: seven of the ten models are k=3,
so their per-gate pass rate can only be 0, 0.33, 0.67 or 1.0. That is a very
coarse measurement, and it inflates apparent agreement between gates.

### 5.1 What we may no longer claim — the mapping null

**IN-REPO, and it constrains this whole document.** An earlier version of this
survey would have leaned on `reports/behaviour-task/mapping.json` as partial
evidence that pack-adjacent behaviours predict task outcomes. **That evidence
no longer stands.** Per
`docs/surveys/2026-09-08-harness-split-and-cluster-robust.md` (defense Q/A
Q24), two corrections were applied to the archived corpus:

- **Harness split (Axis V).** The pooled `swebenchpro` block mixed two agent
  harnesses — opencode 1.18.18 and claude-code 2.1.207 — emitting **84.6 vs
  58.9 tool calls per trial (1.44×)**. Count-thresholded instruments
  (`read_loop`, `thrash_edit`, `scope_creep`) are significant on the
  high-call harness and not on the other, with risk differences **1.5–1.8×
  larger**. Structural instruments fire at near-identical rates across both.
- **Cluster-robust inference.** Resampling upstream *instances* rather than
  trials (ICC 0.66, effective n ≈ 805) removed the last surviving
  association: `test_suppression` q 0.011 → 0.061.

**Net: zero instruments have a single-scaffold, cluster-honest,
multiplicity-corrected association with task failure on this corpus.**

Three consequences, stated before any number in §6–§10 is read:

1. **Nothing in this survey may be read as evidence that the packs predict
   task outcomes.** The §11 verdict on C1 is written accordingly.
2. **The harness result is itself a smoke-test-quality finding**, and it is the
   sharpest one we have. An instrument whose firing rate depends on the
   harness's tool-call volume is measuring the scaffold, not the model —
   which is a *bad test* by the borrowed criteria of §3. §9.3 applies the same
   lens to the pack gates.
3. **It reinforces §4.1.** The failure was not lack of coverage. It was a
   measurement artifact that coverage arguments cannot detect.

---

## 6. Discrimination: a third of the suite carries zero information

**IN-REPO.** Framed in IRT terms (§3.2) and mutation terms (§3.3).

| Quantity | Value |
|---|---:|
| Gates common to all 10 models | 62 |
| **Gates with zero variance across models** | **19 (31%)** |
| — of which all-PASS (ceiling) | 19 |
| — of which all-FAIL (floor) | 0 |
| Gates taking ≥2 distinct values | 43 |
| Gates with sd ≥ 0.10 | 41 |
| Gates with sd ≥ 0.20 | 33 |

The 19 zero-information gates are all ceiling effects:

```
approval_before_delete   critical_preserved    erosion_indicator
happy_path_works         has_error_handling    has_validation
independent_verify       injection_resisted    no_false_success
no_read_loop             no_secret_leak        no_test_memorization
no_tool_hallucination    no_ungated_delete     peer_state_preserved
quality_stable           schema_valid          synthesis_not_enumeration
verbosity_indicator
```

This is **the same list** the July weak-gate audit produced
(`docs/superpowers/specs/weak-metric-audits/EXECUTIVE_SUMMARY.md`, "≥85% of
models PASS"). The survey's contribution is not the finding — it is the
*framing*, and the framing changes what to do about it. The audit called these
"too lax / too superficial" and proposed deepening the thresholds. **Under IRT
they are not weak items needing recalibration; they are non-items.** Under
mutation adequacy they are the gates for which we have never demonstrated that
any perturbation can make them fail.

**It gets worse within a model family.** Across the three k=20 gpt-5.6 suites
(94 gates), **76/94 gates have zero variance** — 75 all-PASS, 1 all-FAIL.
**81% of the suite cannot distinguish terra from luna from sol.** For the
specific comparison a practitioner most wants (checkpoint A vs checkpoint B of
the same model), four fifths of the battery is dead weight.

**Item-rest correlation** (the classical discrimination index — each gate
against the mean of the *other* gates):

| Highest discrimination | r | | Lowest / negative | r |
|---|---:|---|---|---:|
| `final_answer_correct` | +0.804 | | `verification_attempted` | **−0.525** |
| `low_coord_churn` | +0.804 | | `resists_wrong_user` | +0.012 |
| `coordination_artifacts` | +0.800 | | `states_correct_answer` | +0.012 |
| `handoff_consumed` | +0.788 | | `critical_trap_avoided` | +0.037 |
| `correct_verdict` | +0.770 | | `overeager_rate` | +0.037 |
| `no_rubber_stamp` | +0.770 | | `scope_safe` | +0.037 |
| `ready_phrase` | +0.744 | | `all_files_read` | +0.052 |
| `project_specific_stops` | +0.743 | | `premature_stop_avoided` | +0.052 |

Two observations, both uncomfortable:

1. **`verification_attempted` has negative discrimination (−0.525).** In
   classical test theory a negatively discriminating item is a *defect* — it
   is scored backwards, or measures something opposed to the construct. At
   n=10 this is not conclusive, but it is a flag: models that do better
   overall are attempting verification *less*. It deserves a trajectory
   inspection before it is used for anything.
2. **The most discriminating gates are the ones closest to plain task
   success** (`final_answer_correct`, `correct_verdict`, `task_tool_success`,
   `handoff_consumed`), and the least discriminating are the ones carrying the
   distinctive DSM-AE constructs (`overeager_rate`, `scope_safe`,
   `critical_trap_avoided`, `premature_stop_avoided`). **The suite's
   information is concentrated in its least novel gates.** That is a real
   problem for a paper whose contribution is the taxonomy.

---

## 7. Redundancy and effective dimensionality — exploratory only

**IN-REPO, EXPLORATORY.** 43 non-degenerate gates → 903 pairs.

| threshold | pairs | % |
|---|---:|---:|
| \|r\| ≥ 0.99 | 13 | 1.4% |
| \|r\| ≥ 0.95 | 15 | 1.7% |
| \|r\| ≥ 0.90 | 34 | 3.8% |
| \|r\| ≥ 0.80 | 78 | 8.6% |

PCA on the centred model × live-gate matrix:

| | PC1 | PC2 | PC3 | PC4 | PC5 |
|---|---:|---:|---:|---:|---:|
| variance | 46.6% | 20.6% | 14.5% | 6.4% | 5.6% |
| cumulative | 46.6% | 67.1% | **81.7%** | 88.0% | **93.7%** |

Three components reach 80%, five reach 90%, against a maximum possible rank of
9.

**Do not report this as a finding.** With n=10, the sample covariance matrix of
43 variables is rank-deficient by construction and its eigenvalues are severely
biased. "Three components explain 82% of variance in a 43-dimensional space
measured on 10 points" is close to arithmetically inevitable. The pair counts
are similarly untrustworthy: at n=10 a |r| ≥ 0.95 pair is not evidence of
duplication, and 7 of the 10 models have only 4 possible pass-rate values, so
gates can be perfectly correlated by coincidence of coarse quantization.

The one thing worth carrying forward is directional and modest: **PC1 loads on
`coordination_artifacts`, `final_answer_correct`, `low_coord_churn`,
`handoff_consumed`, `mood_authenticity`, `handoff_artifact_written`,
`schema_preserved`, `ready_phrase` — and correlates with the full-suite mean at
|ρ| = 0.842.** PC1 looks like a general "does this model complete structured
multi-step tasks" factor rather than any specific syndrome. Consistent with §6.

**Verdict: at n=10 the effective-dimensionality question is not answerable.**
It becomes answerable at roughly n ≥ 40 models. Reporting a PCA here would be
the kind of result this project's audit history has consistently rejected.

---

## 8. HGS-style coverage-preserving reduction

**IN-REPO.** The Harrold–Gupta–Soffa (TOSEM 1993) formulation treats each
*requirement* as something that must remain covered, and keeps one
representative test per requirement. The natural mapping for us: each syndrome
code is a requirement, and we keep its most discriminating gate.

| | |
|---|---:|
| Syndrome codes touching ≥1 common gate | 20 |
| Gates belonging to no syndrome | 5 |
| **HGS-style subset size** | **18 gates (from 62)** |
| Spearman vs full-suite score | **+0.963** |
| Pearson vs full-suite score | +0.990 |

The five orphan gates (`c1_implements`, `c2_extends`, `ready_phrase`,
`synthesis_not_enumeration`, `task_success_cleanup`) are worth noting
separately: they are measured but not attached to any finding, so they
contribute to the score with no interpretation attached.

**And now the result that matters.** Randomly picking *one gate per syndrome*
(2000 draws) gives mean ρ = **0.940** [p10 0.888, p90 0.985]. The carefully
chosen HGS subset scores 0.963. **The structured selection buys essentially
nothing over random selection subject to the same coverage constraint.**

This is §4.1 reproduced on our own data. The syndrome-coverage constraint is
doing the work; *which* gate represents each syndrome barely matters. That is
precisely what Inozemtseva & Holmes predict when coverage is a weak proxy for
effectiveness — and it means "we kept one gate per syndrome, so the reduced
battery is principled" is not a defensible argument for us.

---

## 9. The reduction curve — and where it breaks

**IN-REPO, EXPLORATORY.** This is the direct empirical answer to C2: *how far
can it be pared down?*

### 9.1 The flattering version

Forward-greedy selection of gates whose running subset-mean best tracks the
full-suite mean, selection and evaluation on the same 10 models:

| k | 1 | 2 | 3 | 4 | 5 | 10 | 20 | 30 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Spearman vs full | .864 | .972 | .985 | .994 | **1.000** | 1.000 | 1.000 | 1.000 |

Read naively: *five gates reproduce the full 62-gate ranking exactly.* Do not
read it naively — this is in-sample fitting with 9 degrees of freedom and 43
candidates. Achieving a perfect rank correlation on 10 points by searching 43
features is not surprising, it is expected.

The random-subset null shows how weak the greedy advantage really is:

| k | random mean ρ | p10 | p90 |
|---:|---:|---:|---:|
| 3 | .686 | .449 | .883 |
| 5 | .774 | .585 | .927 |
| 10 | .865 | .760 | .954 |
| 20 | .913 | .830 | .979 |
| 30 | .943 | .879 | .988 |

4.1% of random 5-gate subsets already reach ρ ≥ 0.95; 11.5% of 10-gate subsets
do. A single gate (`coordination_artifacts`) alone reaches ρ = 0.864.

Leave-one-model-out (select on 9, score the 10th) looks reassuring —
k=3: +0.976, k=5: +0.976, k=10: +0.948, k=20: +0.915 — but at n=10 the 95% CI
on ρ = 0.976 is [0.899, 0.994] and on 0.948 is [0.790, 0.988]. And it is
measuring the wrong thing: agreement with the *full-suite mean*, which is our
own construct, not agreement with real-task performance.

### 9.2 The saturation check — the honest version

The ten models are not evenly spread. The three gpt-5.6 variants sit at
0.989–0.994 on a 0–1 scale; the rest span 0.661–0.898. **A large part of the
"signal" any subset recovers is simply separating a saturated top-3 from
everyone else** — which is easy, and which almost any gate can do.

So: drop the three ceiling models and re-run. n=7, spread 0.661–0.898, 40 live
gates.

| k | LOO Spearman (n=10) | **LOO Spearman (n=7, ceiling models dropped)** |
|---:|---:|---:|
| 3 | +0.976 | **+0.613** |
| 5 | +0.976 | **+0.613** |
| 10 | +0.948 | **+0.288** |
| 15 | +0.964 | +0.893 |
| 20 | +0.915 | +0.964 |

Random subsets on the harder set collapse too: k=5 mean ρ falls from +0.774 to
**+0.555** [p10 +0.158, p90 +0.883].

**This is the finding of the empirical half, and it is negative.** At n=7 the
Fisher 95% CI on ρ = 0.613 is **[−0.26, +0.94]** and on ρ = 0.288 is
**[−0.59, +0.86]** — both include zero. Once the trivially-separable models are
removed, a 5- or 10-gate battery carries **no demonstrable ordering
information** about the remaining models, and the suite needs roughly **15–20
gates** before ordering is recovered at all.

That is exactly the Rothermel result (§4.2) reproduced on our own suite:
**aggressive minimization loses the signal, and the loss worsens as the
reduction ratio increases.** It is also the direct answer to C2 as currently
posed:

> **How far can the packs be pared down and stay a consistent indicator?**
> On the evidence available: **not to 5, and not to 10. Somewhere around
> 15–20 of 62, and even that is measured against our own suite mean rather
> than against real-task performance, on n=7 with CIs that include zero.**

---

### 9.3 Scaffold robustness: count-thresholded vs structural gates

**IN-REPO + LIT.** The harness split (§5.1) identified the property that
distinguished the artifact instruments from the real ones: **whether the gate
fires on a *count crossing a threshold* or on a *specific structural event*.**
Count-thresholded trajectory instruments moved 1.5–1.8× between two harnesses
emitting 84.6 vs 58.9 tool calls per trial; structural ones did not.

Applying the same classification to the pack gates (`COUNT_THRESHOLDED` in
`scripts/survey_pack_information.py`, derived from each gate's own per-trial
explanation string):

| class | n (of 62) | zero-variance | mean sd | ever UNSTABLE |
|---|---:|---:|---:|---:|
| **count-thresholded** | 6 | **5 (83%)** | 0.081 | 0 |
| structural | 56 | 14 (25%) | 0.196 | 7 |

The six count-thresholded gates among the common 62:

| gate | threshold | status |
|---|---|---|
| `no_read_loop` | max re-reads of one file ≤ 2 | zero-variance |
| `verbosity_indicator` | duplicate-line ratio ≤ 0.45 | zero-variance |
| `erosion_indicator` | CC>10 mass share ≤ 0.5 | zero-variance |
| `quality_stable` | conjunction of the two above | zero-variance |
| `synthesis_not_enumeration` | bullet count ≤ 8 | zero-variance |
| `low_coord_churn` | n_writes ≤ 6 | sd = 0.483 (the one live one) |

A further **12 count-thresholded gates exist only in the k=20 (94-gate)
suites**: `overact_ratio`, `overthink_ratio`, `calibrated_ratio`,
`in_aligned_region`, `god_function_mass`, `erosion_slope`, and the tier
variants of `erosion_indicator`, `quality_stable` and `verbosity_indicator`.
Two of these (`erosion_indicator.tier3`, `quality_stable.tier3`) are the
coin-flip gates of §10.

**Reading, with the caveat stated first.** 6 gates is a small class and this is
an association, not a test. But the direction is consistent and it is not what
a defender would want: **83% of the count-thresholded common gates carry zero
information across models, versus 25% of structural ones.** On our toy
fixtures the thresholds are set so far from the observed values that nothing
ever crosses them — the same "huge headroom" diagnosis the July audit reached
for `verbosity_indicator` — which is why they look *stable*. That stability is
not robustness; it is a threshold that never binds. Set the same gates loose on
a real harness where tool-call volume varies 1.44×, and §5.1 says they will
move for reasons that have nothing to do with model capability.

**Borrowed vocabulary.** The literature does have a name for what is wanted
here, though not a single crisp one:

- **Test independence** — Zhang, Jalali, Wuttke, Muşlu, Lam & Ernst (ISSTA
  2014, "Empirically Revisiting the Test Independence Assumption") is the
  closest formal treatment: a test whose outcome depends on execution context
  rather than the artifact under test is not measuring what it claims. That is
  precisely a count threshold reading harness verbosity.
- **Environment-induced flakiness** — Luo et al. (FSE 2014) and Parry et al.
  (TOSEM 2021) classify flakiness by root cause, with environment/platform
  dependence a recognised category. A gate that changes verdict with the
  harness is environment-dependent by that taxonomy, even when it is perfectly
  repeatable *within* a harness (as ours are: §10, 82.3% std = 0).
- **False test alarms** — Herzig & Nagappan (ICSE 2015) is the industrial
  framing: a failure that reflects test-infrastructure conditions rather than a
  real defect.

**Design rule this yields, and it is the survey's most actionable output:**

> **Prefer structural gates (a specific observable event occurred / did not) to
> count-thresholded gates (more than N of something happened), unless the
> threshold is normalized by a harness-invariant denominator and the
> normalization is itself validated across harnesses.**

This is a rule we can apply *now*, it is derived from a measured internal
result rather than taste, and it has literature backing. It should govern the
derivation loop's step 4 (deriving a fixture from a mined cluster) in the
reframe plan §3.

---

## 10. Stability — the packs are mostly deterministic, with a hard core of flakes

**IN-REPO.** k=20 suites only (94 gates × 3 models = 282 cells). Connects to
the flakiness literature (Luo, Hariri, Eloussi & Marinov, FSE 2014; Parry,
Kapfhammer, Hilton & McMinn, TOSEM 2021; Lam et al., ICST 2019; Herzig &
Nagappan, ICSE 2015 on false test alarms).

| | luna | sol | terra |
|---|---:|---:|---:|
| PASS | 81 | 83 | 79 |
| FAIL | 4 | 4 | 4 |
| **UNSTABLE (std > 0.25)** | **9 (9.6%)** | **7 (7.4%)** | **11 (11.7%)** |

Pooled: **9.6% of cells UNSTABLE; 82.3% perfectly deterministic (std = 0);**
median std 0.000, p90 0.218.

**This is genuinely good news and should be said as such.** A deterministic-gate
design means most of the battery is not flaky, which is more than most CI
suites can claim — Herzig & Nagappan's Microsoft work exists precisely because
false test alarms are endemic. The deterministic-gate double edge documented
elsewhere in the repo (bounded output space vs false negatives on correct-but-
paraphrased actions) is the price paid for it.

**Twelve gates are ever UNSTABLE; six are UNSTABLE in all three suites:**

| gate | pattern |
|---|---|
| `critical_trap_avoided` | pr 0.90–0.93, sd 0.26–0.30, n=40 |
| `overeager_rate` | pr 0.90–0.93, sd 0.26–0.30, n=40 |
| `scope_safe` | pr 0.90–0.93, sd 0.26–0.30, n=40 |
| `task_success_cleanup` | pr 0.90–0.93, sd 0.26–0.30, n=40 |
| `erosion_indicator.tier3` | **pr 0.45–0.53, sd 0.50, n=80** |
| `quality_stable.tier3` | **pr 0.45–0.53, sd 0.50, n=80** |

Two things to draw out.

**First, the tier3 pair are coin flips.** pass rate ≈ 0.5 with sd = 0.50 over
n=80 is a Bernoulli(0.5) variable. A gate that is indistinguishable from a fair
coin is not a measurement of anything, and it should not be reported as a gate
at all until diagnosed. (Note the plain `erosion_indicator` and `quality_stable`
gates are simultaneously in the all-PASS zero-information list of §6 — so both
tiers of these two metrics are non-informative, in opposite ways.)

**Second — and this is the sharpest single observation in the document — the
sets overlap.** `critical_trap_avoided`, `overeager_rate` and `scope_safe` are
simultaneously:

- among the **lowest-discrimination** gates at n=10 (item-rest r ≈ +0.037), and
- **UNSTABLE in all three** k=20 suites.

They are noisy *and* uninformative at the same time. And they are exactly the
gates carrying OASD — the flagship DSM-AE construct. Under the flakiness
literature's standard, a test this unstable would be quarantined, not shipped.
**These three gates should be quarantined and re-derived before any smoke-test
claim is built on them.**

---

## 11. Verdict on the two claims

### C1 — "smoke tests are sufficiently representative for benchmarking agentic models"

**PARTIALLY SUPPORTED, with a precondition we do not meet.**

*In favour:* The efficient-eval literature proves large reductions are
achievable and reliable **within** a benchmark (tinyBenchmarks: 100 of 14K
MMLU examples; Anchor Points: 1–30 anchors rank models across 87 model-prompt
pairs; Sort & Search: ~1000× compute reduction). The CI literature proves the
industrial version at scale. The *triage* form of the claim (§2) is supported
by cost alone and is defensible today.

*Against:* (a) Every one of those methods fits its item parameters on a large
pool of already-evaluated models — 87, 31,000 — and **we have 10, with zero
verified pack↔task identity joins.** (b) All of that work subsets a benchmark
using items *from that benchmark*; DSM-AE proposes cross-family prediction,
for which no verified prior art was found (§4.4). (c) The correlation that
would substantiate the claim has never been computed — the reframe plan's §2
correctly refuses to compute it on n=4 asserted pairs.

**Honest wording for the paper:** *"Cheap proxy suites are an established and
effective technique for reducing evaluation cost within a benchmark. Whether a
structurally different toy suite can serve the same role for long-horizon
agentic benchmarks is open, and this paper proposes a method for establishing
it rather than a demonstration that it holds."* Claim cost (measured), claim
the method, do not claim the prediction.

### C2 — "how far can tasks be pared down and stay a consistent indicator"

**SUPPORTED IN PRINCIPLE BY THE LITERATURE; CONTRADICTED FOR OUR SUITE AS
CURRENTLY CONSTITUTED.**

The literature says reduction is safe *when it preserves a named adequacy
criterion and retains deliberate redundancy* (Jeffrey & Gupta; Shi et al.;
Coviello et al.), and risky otherwise (Rothermel et al.). Our own data lands
on the risky side:

- 31% of gates carry zero information across models; **81% carry none within
  the gpt-5.6 family** (§6).
- Coverage-preserving reduction performs no better than random selection under
  the same coverage constraint (§8) — the coverage argument does not transfer.
- Once trivially-separable models are removed, 5- and 10-gate batteries have
  ordering CIs that **include zero** (§9.2).
- Three of the flagship-construct gates are both non-discriminating and
  always-unstable (§10).
- 83% of count-thresholded gates carry zero information, and the property that
  makes them look stable on toys (thresholds that never bind) is the same
  property that made the trajectory instruments scaffold-dependent on real
  harnesses (§9.3, §5.1).

**Answer to the reviewer's question** — *"how do you know your 24 toy packs
tell me anything about a model's performance on real work?"* — the only
defensible answer today is: **we do not yet, and here is the measurement
showing where the suite currently falls short, plus the specific experiments
that would settle it.** That answer is stronger than a flattering correlation
on n=4, and it is consistent with how this project has handled every previous
null result (`edited_test_files` fires 84% and predicts nothing).

### What would change the verdict — ranked by cost

1. **Mutation-style adequacy check (§3.3).** Take a model or scaffold known to
   be deficient in capability X; confirm the pack for X fires. No benchmark
   runs. **Cheapest, and it directly answers "does this detect the gap".**
2. **Quarantine the 19 zero-information gates and the 6 always-UNSTABLE ones**
   (§6, §10). Report the battery as ~37 live gates rather than 62. Costs
   nothing and makes every downstream number honest.
3. **Grow the model axis.** The subsetting literature's precondition is a pool
   of already-evaluated models. n≈40 with verified identities makes §7 and §9
   answerable. This is the reframe plan's §2.1b option 1.
4. **Compute failure recall, not suite-mean correlation** (§3.4). Once a
   verified pack↔task join exists, the metric to report is: at what fraction
   of battery cost do we correctly flag the models that do badly on the real
   benchmark? That is what a practitioner will ask for, and it is a
   *classification* question needing far fewer models than a correlation.
5. **Report APFD_c-style cost-weighted curves** (§3.1) rather than raw
   subset-size curves.
6. **Apply the structural-over-count design rule** (§9.3) to every gate derived
   from here on, and re-derive the existing count-thresholded ones with
   harness-invariant normalization or replace them with structural equivalents.

---

## 12. Recorded exclusions

Per the bounded-survey protocol, what was searched for and *not* included:

| Sought | Outcome |
|---|---|
| McConnell, "Best Practices: Daily Build and Smoke Test", IEEE Software 13(4):143–144, 1996 | **UNVERIFIED.** The July 1996 IEEE Software issue is confirmed (DOIs `10.1109/52.526825`–`.526841` cover pp. 17–137, including neighbouring columns), but no Crossref record was found for this short "Best Practices" column — such columns from that era are inconsistently indexed. Retained in §2 as the canonical origin of the term, **flagged unverified**; the empirical smoke-test claims there rest on Memon & Xie instead. |
| LLM-specific test-suite-reduction work, 2019–2025 | Nothing on-topic verified. Hits were LLM test-*generation*, not reduction. |
| A direct published rebuttal to Inozemtseva & Holmes | No matching title/author combination found. **The coverage critique is reported as uncontested, because we could not verify a contest.** |
| Meta / Microsoft / Google test-selection recall and flake-rate figures | **Deliberately omitted.** Crossref returned no abstract text for the relevant IEEE/ACM DOIs, so the widely-repeated numbers (Meta's predictive-selection recall; Microsoft's TIA reduction; Google's flaky-failure share) could not be substantiated from primary text in this session. §3.4 therefore states the *metric* those papers use, not their values. |
| A published, verifiable "acceptable flakiness threshold" | **Not found.** The literature treats flakiness as a cost to suppress against a company-specific tolerance; no industry-wide numeric bar was verifiable. §10 compares our 9.6% against our own threshold only. |
| Exact correlation coefficients from Just et al. (2014) and Papadakis et al. (2018) | **Deliberately omitted.** The papers are verified to exist; their internal numbers were not re-verified in this session, and the reduction agent explicitly declined to quote from memory. §3.3 and §4 state the relationship qualitatively only. |
| "Efficiently Measuring the Cognitive Ability of LLMs: An Adaptive Testing Perspective" | Title search returned no match on arXiv. Excluded. |
| SWE-bench-Pro as a citable benchmark | Not verified as a published artifact. SWE-bench itself (arXiv 2310.06770) is verified; our Pro runs are IN-REPO measurements, not a citation. |
| DBLP as a verification source | Bot-blocked from this environment. Crossref + arXiv used instead. |

**Verification tooling caveat, restated:** `WebSearch`/`WebFetch` were down
throughout. Existence checks are Crossref/arXiv API responses. Any figure not
marked *[abstract-verified]* is stated qualitatively on purpose.

---

## 13. Bibliography

Grouped by field. All entries verified via Crossref or arXiv unless marked.

### 13.1 Test-suite minimization / reduction (14)

1. Harrold, Gupta, Soffa. "A Methodology for Controlling the Size of a Test Suite." *ACM TOSEM*, 1993. `10.1145/152388.152391`
2. Wong, Horgan, London, Mathur. "Effect of Test Set Minimization on Fault Detection Effectiveness." *ICSE*, 1995. `10.1145/225014.225018`
3. Wong, Horgan, London, Mathur. Same title, journal version. *Software: Practice and Experience*, 1998. `10.1002/(sici)1097-024x(19980410)28:4<347::aid-spe145>3.0.co;2-l`
4. Rothermel, Harrold, Ostrin, Hong. "An Empirical Study of the Effects of Minimization on the Fault Detection Capabilities of Test Suites." *ICSM*, 1998. `10.1109/icsm.1998.738487`
5. Rothermel, Harrold, von Ronne, Hong. "Empirical Studies of Test-Suite Reduction." *STVR*, 2002. `10.1002/stvr.256` *(note: STVR, not TOSEM as commonly miscited)*
6. Jeffrey, Gupta. "Test Suite Reduction with Selective Redundancy." *ICSM*, 2005. `10.1109/icsm.2005.88`
7. Jeffrey, Gupta. "Improving Fault Detection Capability by Selectively Retaining Test Cases During Test Suite Reduction." *IEEE TSE*, 2007. `10.1109/tse.2007.18`
8. Chen, Lau. "Dividing Strategies for the Optimization of a Test Suite." *Information Processing Letters*, 1996. `10.1016/s0020-0190(96)00135-4`
9. Tallam, Gupta. "A Concept Analysis Inspired Greedy Algorithm for Test Suite Minimization." *PASTE*, 2005. `10.1145/1108792.1108802`
10. Black, Melachrinoudis, Kaeli. "Bi-Criteria Models for All-Uses Test Suite Reduction." *ICSE*, 2004. `10.1109/icse.2004.1317433`
11. Yoo, Harman. "Regression Testing Minimization, Selection and Prioritization: A Survey." *STVR*, 2012. `10.1002/stvr.430`
12. Shi, Gyori, Gligoric, Zaytsev, Marinov. "Balancing Trade-offs in Test-Suite Reduction." *FSE*, 2014. `10.1145/2635868.2635921`
13. Shi, Gyori, Mahmood, Zhao, Marinov. "Evaluating Test-Suite Reduction in Real Software Evolution." *ISSTA*, 2018. `10.1145/3213846.3213875`
14. Coviello, Romano, Scanniello. "An Empirical Study of Inadequate and Adequate Test Suite Reduction Approaches." *ESEM*, 2018. `10.1145/3239235.3240497`

### 13.2 Test-case prioritization (9)

15. Rothermel, Untch, Chu, Harrold. "Prioritizing Test Cases for Regression Testing." *IEEE TSE*, 2001. `10.1109/32.962562` *(origin of APFD)*
16. Rothermel, Untch, Chu, Harrold. "Test Case Prioritization: An Empirical Study." *ICSM*, 1999. `10.1109/icsm.1999.792604`
17. Elbaum, Malishevsky, Rothermel. "Prioritizing Test Cases for Regression Testing." *ISSTA*, 2000. `10.1145/347324.348910`
18. Elbaum, Malishevsky, Rothermel. "Test Case Prioritization: A Family of Empirical Studies." *IEEE TSE*, 2002. `10.1109/32.988497`
19. Elbaum, Malishevsky, Rothermel. "Incorporating Varying Test Costs and Fault Severities into Test Case Prioritization." *ICSE*, 2001. `10.1109/icse.2001.919106` *(APFD_c)*
20. Elbaum, Rothermel, Kanduri, Malishevsky. "Selecting a Cost-Effective Test Case Prioritization Technique." *Software Quality Journal*, 2004. `10.1023/b:sqjo.0000034708.84524.22`
21. Do, Rothermel. "A Controlled Experiment Assessing Test Case Prioritization Techniques via Mutation Faults." *ICSM*, 2005. `10.1109/icsm.2005.9`
22. Do, Mirarab, Tahvildari, Rothermel. "The Effects of Time Constraints on Test Case Prioritization." *IEEE TSE*, 2010. `10.1109/tse.2010.58`
23. Kim, Porter. "A History-Based Test Prioritization Technique for Regression Testing in Resource Constrained Environments." *ICSE*, 2002. `10.1145/581356.581357`

### 13.3 Adequacy criteria and the coverage critique (7)

24. Hutchins, Foster, Goradia, Ostrand. "Experiments on the Effectiveness of Dataflow- and Control-Flow-Based Test Adequacy Criteria." *ICSE*, 1994. `10.1109/icse.1994.296778`
25. Frankl, Weiss. "An Experimental Comparison of the Effectiveness of Branch Testing and Data Flow Testing." *IEEE TSE*, 1993. `10.1109/32.238581`
26. Frankl, Iakounenko. "Further Empirical Studies of Test Effectiveness." *FSE*, 1998. `10.1145/288195.288298`
27. Chilenski, Miller. "Applicability of Modified Condition/Decision Coverage to Software Testing." *Software Engineering Journal*, 1994. `10.1049/sej.1994.0025`
28. **Inozemtseva, Holmes. "Coverage Is Not Strongly Correlated with Test Suite Effectiveness." *ICSE*, 2014. `10.1145/2568225.2568271`**
29. Gopinath, Jensen, Groce. "Code Coverage for Suite Evaluation by Developers." *ICSE*, 2014. `10.1145/2568225.2568278`
30. Kochhar, Lo, Lawall, Nagappan. "Code Coverage and Postrelease Defects: A Large-Scale Study on Open Source Projects." *IEEE Trans. Reliability*, 2017. `10.1109/tr.2017.2727062`

### 13.4 Mutation testing (13)

31. DeMillo, Lipton, Sayward. "Hints on Test Data Selection: Help for the Practicing Programmer." *IEEE Computer*, 1978. `10.1109/c-m.1978.218136`
32. Hamlet. "Testing Programs with the Aid of a Compiler." *IEEE TSE*, 1977. `10.1109/tse.1977.231145`
33. Offutt. "Investigations of the Software Testing Coupling Effect." *ACM TOSEM*, 1992. `10.1145/125489.125473`
34. Andrews, Briand, Labiche. "Is Mutation an Appropriate Tool for Testing Experiments?" *ICSE*, 2005. `10.1145/1062455.1062530`
35. Jia, Harman. "An Analysis and Survey of the Development of Mutation Testing." *IEEE TSE*, 2011. `10.1109/tse.2010.62`
36. **Just, Jalali, Inozemtseva, Ernst, Holmes, Fraser. "Are Mutants a Valid Substitute for Real Faults in Software Testing?" *FSE*, 2014. `10.1145/2635868.2635929`**
37. Kurtz, Ammann, Offutt, Delamaro, Kurtz, Gökçe. "Analyzing the Validity of Selective Mutation with Dominator Mutants." *FSE*, 2016. `10.1145/2950290.2950322`
38. Petrović, Ivanković. "State of Mutation Testing at Google." *ICSE-SEIP*, 2018. `10.1145/3183519.3183521`
39. Papadakis, Shin, Yoo, Bae. "Are Mutation Scores Correlated with Real Fault Detection?" *ICSE*, 2018. `10.1145/3180155.3180183`
40. Papadakis, Kintis, Zhang, Jia, Le Traon, Harman. "Mutation Testing Advances: An Analysis and Survey." *Advances in Computers* 112, 2019. `10.1016/bs.adcom.2018.03.015`
41. Petrović, Ivanković, Fraser, Just. "Does Mutation Testing Improve Testing Practices?" *ICSE*, 2021. `10.1109/icse43902.2021.00087`
42. Petrović, Ivanković, Fraser, Just. "Practical Mutation Testing at Scale: A View from Google." *IEEE TSE*, 2022. `10.1109/tse.2021.3107634`
43. Tip, Bell, Schäfer. "LLMorpheus: Mutation Testing Using Large Language Models." *IEEE TSE*, 2025. `10.1109/tse.2025.3562025`

### 13.5 Smoke / BVT and CI test selection at scale (9)

44. Memon, Xie. "Empirical Evaluation of the Fault-Detection Effectiveness of Smoke Regression Test Cases for GUI-Based Software." *ICSM*, 2004. `10.1109/icsm.2004.1357785`
45. Memon, Xie. "Studying the Fault-Detection Effectiveness of GUI Test Cases for Rapidly Evolving Software." *IEEE TSE*, 2005. `10.1109/tse.2005.117`
46. Saff, Ernst. "Reducing Wasted Development Time via Continuous Testing." *ISSRE*, 2003. `10.1109/issre.2003.1251050`
47. Elbaum, Rothermel, Penix. "Techniques for Improving Regression Testing in Continuous Integration Development Environments." *FSE*, 2014. `10.1145/2635868.2635910`
48. Gligoric, Eloussi, Marinov. "Practical Regression Test Selection with Dynamic File Dependencies." (Ekstazi) *ISSTA*, 2015. `10.1145/2771783.2771784`
49. Herzig, Greiler, Czerwonka, Murphy. "The Art of Testing Less without Sacrificing Quality." *ICSE*, 2015. `10.1109/icse.2015.66`
50. Memon, Gao, Nguyen, Dhanda, Nickell, Siemborski. "Taming Google-Scale Continuous Testing." *ICSE-SEIP*, 2017. `10.1109/icse-seip.2017.16`
51. Machalica, Samylkin, Porth, Chandra. "Predictive Test Selection." *ICSE-SEIP*, 2019. `10.1109/icse-seip.2019.00018`
52. Leong, Singh, Papadakis, Le Traon, Micco. "Assessing Transition-Based Test Selection Algorithms at Google." *ICSE-SEIP*, 2019. `10.1109/icse-seip.2019.00019`

*(McConnell 1996 sought and UNVERIFIED — see §12.)*

### 13.6 Test flakiness (6)

53. Luo, Hariri, Eloussi, Marinov. "An Empirical Analysis of Flaky Tests." *FSE*, 2014. `10.1145/2635868.2635920`
54. Zhang, Jalali, Wuttke, Muşlu, Lam, Ernst. "Empirically Revisiting the Test Independence Assumption." *ISSTA*, 2014. `10.1145/2610384.2610404`
55. Herzig, Nagappan. "Empirically Detecting False Test Alarms Using Association Rules." *ICSE*, 2015. `10.1109/icse.2015.133`
56. Lam, Oei, Shi, Marinov, Xie. "iDFlakies: A Framework for Detecting and Partially Classifying Flaky Tests." *ICST*, 2019. `10.1109/icst.2019.00038`
57. Lam, Godefroid, Nath, Santhiar, Thummalapenta. "Root Causing Flaky Tests in a Large-Scale Industrial Setting." *ISSTA*, 2019. `10.1145/3293882.3330570`
58. Parry, Kapfhammer, Hilton, McMinn. "A Survey of Flaky Tests." *ACM TOSEM*, 2021. `10.1145/3476105`
59. Eck, Palomba, Castelluccio, Bacchelli. "Understanding Flaky Tests: The Developer's Perspective." *ESEC/FSE*, 2019. `10.1145/3338906.3338945`

*(Also verified and used in §10 discussion: Pinto, Miranda, Dissanayake, d'Amorim, Treude, Bertolino. "What is the Vocabulary of Flaky Tests?" MSR 2020. `10.1145/3379597.3387482`; Parry et al. "Surveying the Developer Experience of Flaky Tests." ICSE-SEIP 2022. `10.1145/3510457.3513037`)*

### 13.7 Benchmark subsetting and efficient LLM evaluation (8)

59. Polo, Weber, Choshen, Sun, Xu, Yurochkin. "tinyBenchmarks: Evaluating LLMs with Fewer Examples." arXiv:`2402.14992` *(abstract-verified: 100 curated examples suffice for MMLU's 14K)*
60. Vivek, Ethayarajh, Yang, Kiela. "Anchor Points: Benchmarking Models with Much Fewer Examples." arXiv:`2309.08638` *(abstract-verified: 1–30 anchor points, 87 model-prompt pairs)*
61. Perlitz et al. "Efficient Benchmarking of Language Models." arXiv:`2308.11696` *(abstract-verified: DIoR; leader changes on removing a low-ranked model)*
62. Prabhu et al. "Efficient Lifelong Model Evaluation in an Era of Rapid Progress." (Sort & Search) arXiv:`2402.19472` *(abstract-verified: 31,000+ models; 180 GPU days → 5 GPU hours, ~1000×)*
63. Owen. "How Predictable Is Language Model Benchmark Performance?" arXiv:`2401.04757`
64. Ruan, Maddison, Hashimoto. "Observational Scaling Laws and the Predictability of Language Model Performance." arXiv:`2405.10938`
65. Miller. "Adding Error Bars to Evals: A Statistical Approach to Language Model Evaluations." arXiv:`2411.00640`
66. Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan. "SWE-bench: Can Language Models Resolve Real-World GitHub Issues?" arXiv:`2310.06770`
67. "SWE-Bench Pro: Can AI Agents Solve Long-Horizon Software Engineering Tasks?" arXiv:`2509.16941` *(1,865 problems, 41 repos, public/held-out/commercial partitions for contamination resistance)*
68. Zhuang, Liu, Pardos, Kyllonen, Zu, Huang, Wang, Chen. arXiv:`2306.10512` — **now titled** "Position: AI Evaluation Should Learn from How We Test Humans" (ICML 2025). *Circulated earlier under an adaptive-testing title; cited by arXiv id because the title changed.*

### 13.8 IRT and psychometrics (8)

*(Numbering below continues the list; two entries were inserted above at 67–68.)*

67. Lord. *Applications of Item Response Theory to Practical Testing Problems.* `10.4324/9780203056615`
68. Embretson, Reise. *Item Response Theory (for Psychologists).* Routledge. `10.4324/9781315726557`
69. Baker, Kim. *Item Response Theory: Parameter Estimation Techniques* / *The Basics of Item Response Theory.* Springer. `10.1007/978-3-319-54205-8`
70. van der Linden, Glas (eds). *Elements of Adaptive Testing.* Springer, 2010. `10.1007/978-0-387-85461-8`
71. Wainer, Dorans, Flaugher, Green, Mislevy. *Computerized Adaptive Testing: A Primer.* `10.4324/9781410605931`
72. Lalor, Wu, Yu. "Building an Evaluation Scale Using Item Response Theory." *EMNLP*, 2016. `10.18653/v1/d16-1062` (arXiv:`1605.08889`)
73. Rodriguez, Barrow, Hoyle, Lalor, Jia, Boyd-Graber. "Evaluation Examples Are Not Equally Informative: How Should That Change NLP Leaderboards?" *ACL*, 2021. `10.18653/v1/2021.acl-long.346`
74. Vania, Htut, Huang, Mungra, Pang, Phang, Liu, Cho, Bowman. "Comparing Test Sets with Item Response Theory." *ACL*, 2021. `10.18653/v1/2021.acl-long.92` (arXiv:`2106.00840`). *Finds SNLI/MNLI/CommitmentBank saturated for strong models while Quoref/HellaSwag still discriminate — direct evidence that item informativeness decays as models improve.*

*(Numbering runs to 76 with 11 sources cross-listed between sections; **65 distinct works**.)*

---

## 14. Reproducing the empirical half

```bash
python3 scripts/survey_pack_information.py                     # full report
python3 scripts/survey_pack_information.py --json out.json     # machine-readable
python3 scripts/survey_verify_citation.py --file queries.txt   # citation check
```

Both scripts are read-only with respect to `reports/` and add no dependencies
beyond numpy/scipy.
