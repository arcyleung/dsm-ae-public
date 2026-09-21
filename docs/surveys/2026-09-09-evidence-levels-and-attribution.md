# The missing level: evidence between metric and task

**AS_OF:** 2026-09-09
**Status:** analysis + literature pointer — informs the aggregation redesign
**Prompted by:** supervisor observation that if 81% of gate thresholds carry no
signal, the metrics are pitched too low and a higher-level discriminator is
needed below the task level.

---

## 0. The claim, tested

The observation was that a stricter aggregation rule (N-of-M, cluster,
sentinel, longitudinal) might rescue diagnosis where OR-over-gates fails.

**Result: no aggregation rule rescues it, and stricter rules are strictly
worse.** Aggregation cannot create information the gates do not carry. Across
10 models, counting how many of the 22 syndromes vary at all:

| Rule | Syndromes that discriminate |
|---|---|
| OR (current) | **18 / 22** |
| ≥2 of N | 14 / 22 |
| majority | 12 / 22 |
| ≥3 of N | 5 / 22 |

OR is the *most* discriminating rule available, which is not a defence of OR —
it is a measure of how little the gates have to work with. Four syndromes
(PII, NFR, RBD, SPD) are flat under **every** rule: no model differs from any
other, so no threshold can separate them.

This is the aggregation-level counterpart to Q25 (81% of gates identical
across gpt-5.6 terra/luna/sol at k=20). The problem is upstream of the
diagnostic rule.

## 1. But the level argument is right — measured

The supervisor's structural point holds, and the data supports it directly.
Discrimination rises monotonically with evidence level, **replicated on both
harnesses**:

| Evidence level | claude-code AUC | opencode AUC |
|---|---:|---:|
| Best single binary gate (`thrash_edit`) | 0.575 | 0.543 |
| **Count** of instruments firing (burden) | 0.615 | 0.580 |
| **Continuous** trajectory feature (length) | **0.636** | **0.605** |

Same trials, same instruments — only the level of aggregation changes. Going
from *"did gate X trip"* to *"how many tripped"* to *"an unthresholded
trajectory quantity"* gains ~0.06 AUC at each step, in the same direction on
both scaffolds.

**Interpretation.** Every threshold discards ordering information. A gate
answers "≥N?" when the informative content was the magnitude. Q26 found the
one replicable signal in this corpus is continuous and unthresholded; this
shows the loss is *incremental and measurable*, not a special property of
trace length.

**Honest caveat:** AUC 0.64 is still weak, and trace length is endogenous
(Q26). Raising the evidence level improves discrimination; it does not by
itself produce a usable diagnostic.

## 2. What the DSM analogy actually licenses

The current implementation reads the DSM as *"a syndrome is an OR over
criteria."* Real DSM practice is richer, and the supervisor's four
alternatives map onto constructs the manual already uses:

| Proposed | DSM analogue | Status here |
|---|---|---|
| N-of-M threshold | Polythetic criteria (e.g. 5 of 9) | Tested §0 — **worse**, gates too flat |
| Cluster-based | Symptom clusters / specifiers | Untested; needs per-trial vectors, not per-model rates |
| **Sentinel event** | Pathognomonic sign — one occurrence is sufficient | **Closest to what works** (§3) |
| Longitudinal | Course specifiers, duration criteria | Untested; needs repeated sessions |

The pack battery collapses all four into one: a per-model pass rate over k
trials. That representation **cannot express** a sentinel event (it averages
it away) or a longitudinal course (no time axis). The evidence model, not just
the aggregation rule, is the limiting factor.

## 3. Sentinel events are the strongest thing we have

`premature_stop` and `test_suppression` are sentinel-shaped: rare, structural,
and near-deterministic in consequence. Every one of the 16 `premature_stop`
firings failed the task (RD +0.636, RD** +0.761). They fail on *power*, not on
effect — 7 and 9 firings per harness.

That is exactly the profile a sentinel criterion is for: **do not average it,
count it and report the base rate.** A pass-rate representation actively
destroys this — one catastrophic event in 20 trials reads as 0.95.

**Design implication.** Sentinel events should be recorded as *events with
evidence pointers*, not folded into a rate. This is also what the failure-
attribution literature does (§4).

## 4. Literature: failure attribution names the missing construct

The ResearchGate survey URL is blocked to automated fetch (HTTP 403), so it is
**unverified** and not cited here. The underlying literature is real and
directly relevant — found and verified via the arXiv API:

| Work | arXiv | Relevance |
|---|---|---|
| *Which Agent Causes Task Failures and When?* — **Who&When** dataset | 2505.00212 | Founds the area; 127 MAS failure logs annotated with responsible agent **and decisive error step** |
| *Seeing the Whole Elephant* — **TraceElephant** | 2604.22708 | Argues attribution needs **full execution observability** — inputs and context, not just outputs |
| *Rethinking Failure Attribution in MAS* | 2603.25001 | Multi-perspective benchmark |
| *StepFinder* | 2606.03467 | Temporal semantic framework for step attribution |
| VerifyMAS · MASPrism · ASCon · Cascade · GNN-based | 2605.17467 · 2605.07509 · 2608.10646 · 2608.29646 · 2608.18575 | Method family: hypothesis verification, prefill signals, agent–step contextualization |

### What DSM-AE is not testing for

1. **Decisive error step.** The whole field localises failure to a *step*.
   DSM-AE has step labels (ADVANCE/REGRESS/RECOVER in `intent/`) but no
   diagnosis consumes them — `criteria.py` reads only per-trial gate outcomes.
   **The step-level evidence already exists and is thrown away.** This is the
   cheapest available upgrade and directly implements the sentinel idea.

2. **Full execution observability.** TraceElephant's argument is that
   output-only traces are insufficient. Q22 is an independent instance: the
   199MB binary-dump behaviour is invisible in `trajectory.json` and lives only
   in the raw stream. Same finding, arrived at from a different direction.

3. **Attribution accuracy as a metric.** Who&When reports 53.5% agent
   accuracy but **14.2% step accuracy** — step localisation is *hard*, and
   some methods score below random. Any DSM-AE claim to localise a cause needs
   to be benchmarked against that, not asserted.

4. **A labelled failure corpus.** Who&When exists and is annotated. We have
   1260 trials with outcome labels but **no cause labels**. That is the
   ingredient blocking supervised attribution, and it is obtainable.

## 5. What to change

Ordered by evidence, cheapest first.

1. **Stop averaging sentinel events.** Represent rare structural events as
   counts with evidence pointers. Requires no new data — the events are in the
   existing traces.
2. **Report continuous scores, not just gate booleans.** §1 shows thresholding
   costs ~0.06 AUC per level. Keep the gate for reporting, carry the magnitude
   for analysis.
3. **Feed step labels into diagnosis.** `intent/` already emits them;
   `criteria.py` ignores them. Implements "decisive step" in our own vocabulary.
4. **Do not adopt N-of-M.** Measured worse (§0). Revisit only after
   elicitation is fixed — with flat gates it is strictly harmful.
5. **Fix elicitation first (Q25 P0).** No representation change rescues gates
   that never vary.

## 6. What this does not resolve

- AUC ~0.64 is weak at every level tested. Raising the evidence level is
  necessary, not sufficient.
- Cluster-based and longitudinal diagnosis remain **untested** — the current
  per-model-pass-rate representation cannot express them. Testing needs
  per-trial vectors and repeated sessions respectively.
- The survey the supervisor linked is unverified (403). The arXiv works above
  are verified by API and should be cited instead until the survey itself can
  be obtained.
