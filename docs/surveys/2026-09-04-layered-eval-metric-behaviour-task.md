# Layered eval: metric → behaviour → task

**Branch:** `intent-state`  
**AS_OF:** 2026-09-04  
**Depends on:** layered *verifier* (`2026-09-04-intent-state-layered-verification.md`)

The verifier labels *steps* on a trajectory. This note is the missing
**eval** stack: a task can require several behaviours, and we do not
yet know which ones matter. That is a mapping problem, not another
one-metric Harbor toy.

## The three layers

| Layer | Question | Oracle | What we have |
|---|---|---|---|
| **Metric** | Did this instrument fire? | Deterministic gate on a trace (`overeager_rate`, `read_grounded`, ADVANCE/REGRESS) | Packs + intent-state |
| **Behaviour** | Is this syndrome present? | Polythetic rule over metrics (OASD, TID, PCD, SPD) | `criteria.py` |
| **Task** | Did the agent finish the *job*? | External outcome: tests, gold, review accepted, ticket closed | Almost only the toy’s own gold |

Harbor packs today collapse all three: one fixture ≈ one metric ≈ one
behaviour ≈ the “task.” That is useful as a **closed-course exam**.
It cannot tell you whether OASD (or anything else) is load-bearing for
code review, incident response, or a SWE-bench instance.

Snowball already separated these: the `eval-methodology` cluster
(SWE-bench, Terminal-Bench, WebArena, GAIA, Harbor) is *task success*.
DSM-AE syndromes are *explanations*. Do not turn a leaderboard into a
pack (`FINDINGS.md`).

## Chicken and egg

Two bad shortcuts:

1. **Assume every ill-behaviour hurts every task.** False on our own
   data. N-grams did not separate overeager pass/fail (JSD 0.04).
   Qwen3.8 can be OASD-clean on the cleanup toy and still 0/10 on
   TID2. Recency ADVANCE predicts recency-task fail; it says nothing
   about cleanup. Behaviours are **conditionally** causal.
2. **Design the task suite from the taxonomy first.** Then we only
   rediscover the toys we planted. The mapping would be circular.

The honest order is **task-first, taxonomy-second**:

```text
  representative tasks
       ↓  (outer oracle: resolved / not)
  success trajs  ∪  fail trajs
       ↓  (intent-state + metrics, no new judge)
  failure-mode clusters
       ↓  (explain with existing codes; new code only if leftover)
  behaviour × task weight matrix
       ↓
  layered eval: P(task fail | behaviour) and P(behaviour | task fail)
```

You cannot know which behaviours matter until you have both a **task
oracle that is not a DSM-AE gate** and enough fail *and* success
trajectories on that task.

## What “representative” means here

Not “more k on `overeager_mini`.” A corpus is representative if:

- The **task** is an agentic job someone would pay for (fix a failing
  test, review a PR, restore a config after a regime change, implement
  a written spec).
- Success is an **external** oracle (tests, hidden tests, human
  accept), not `scope_safe`.
- Both classes exist (aim ≥30 fail and ≥30 success per task family
  before claiming a mapping). LiteLLM `litellm.jsonl` is required.
- Scaffold is locked and declared (Axis V). Mixing Claude Code vs raw
  loop will dominate the behaviour labels (OverEager’s own result).

In-repo we do **not** have that corpus. We have:

| Corpus | Task oracle? | Both classes? | Use |
|---|---|---|---|
| Pack work-dirs (Qwen/DeepSeek/Gemini/GPT max) | No — oracle *is* the behaviour | Sometimes | Dry-run the *pipeline*, not the mapping |
| Repro-shared `trial_*.json` | Same | Yes on some packs | No LiteLLM; do not ingest |
| Harbor `harbor_tasks/dsm-ae/*` | Same toys, different runner | Same | Still one-behaviour |
| SWE-bench / Terminal-Bench / live review | Yes | Need to run | **The actual mapping corpus** |

## Extracting failure modes without a circular taxonomy

On a task-labeled set `{(traj, y)}`, `y ∈ {success, fail}`:

1. **Progress skeleton** (already built): ADVANCE / REGRESS / RECOVER /
   NEUTRAL / OFF_TASK / ENABLE. Summarize each traj as
   `(coverage_final, unrecovered, recovery_rate, CAL, plan_exec_div)`.
2. **Metric vector**: existing pack gates *if* they can be scored
   off-policy on that traj (file-oracle metrics transfer; `2+2=5`
   does not). Off-policy score only instruments that do not assume
   the toy fixture.
3. **Failure-mode discovery** (fail trajs only):
   - Cluster progress skeletons (not raw n-grams first).
   - Discriminative procedures **conditioned on REGRESS vs RECOVER**
     (layer-1, now attached to intent).
   - Leftover clusters that no existing code explains → candidate
     new behaviour (same keep rule as snowball: ≥3 sources or 1
     named bench before promoting).
4. **Explain with the taxonomy** (not replace it):
   for each fail cluster, assign 0–N codes (OASD, TID, SPD, PCD, …)
   with evidence pointers. A fail may be **multi-label**. That is
   the point of a task layer.
5. **The mapping** is two numbers, not a story:

   - `P(y=fail | behaviour B)` — does B hurt *this* task?
   - `P(B | y=fail)` — when the task fails, how often is B present?

   A behaviour can be common in fails and still not causal (confound
   with length, scaffold, difficulty). Need at least a
   same-scaffold, difficulty-matched success baseline. The intent
   noise floor (same-condition JSD) is the analogue for *procedure*;
   here the analogue is **matched success trajectories**.

Who&When / AgentFail (snowball `failure_taxonomies`) are the
attribution literature for step (4). We do not re-derive a catalog;
we *bind* their modes and ours to an outer task oracle.

## Layered eval, once the matrix exists

For a new model on task family T:

```text
task score     = P(y=success | T)          # SWE-bench-like
behaviour card = {B: present/absent}       # DSM-AE + intent-state
metric card    = gate vector               # instruments
```

Certification language becomes:

> Model M on scaffold S: task-success 0.41 on T; when it fails, 60%
> of fails carry unrecovered REGRESS (OASD-like) and 25% carry SPD
> (held-out spec). Successes almost never show unrecovered REGRESS.

That is fitness-to-operate *on T*, not “OASD present on a cleanup
toy.” The toy remains the **elicitation / closed-course** for B
when T is too expensive.

## First empirical slice (do not wait for SWE-bench)

We can dry-run the *method* on LiteLLM suites we already have, with
the honest caveat that y is still a pack gold:

1. Per model × pack with both classes (already in
   `reports/intent-state/ANALYSIS.md`): treat pack gold as a fake T.
2. Emit `P(fail | unrecovered)`, `P(fail | low ADVANCE)`,
   `P(fail | high plan_exec_div)` vs matched successes.
3. That produces a **toy weight matrix** — useful to debug the
   pipeline, **not** to claim industrial mapping.

Then the real corpus, in order of leverage:

1. **Composite fixture** (still in-house, but multi-behaviour): one
   workspace that requires (a) read the new regime spec, (b) grounded
   tool use, (c) cleanup without touching secrets, (d) `add` only.
   Outer oracle = hidden tests + no `.env.old` delete + config not
   panic. Labels = existing metrics scored off the same traj.
2. **Import an existing agent-fail corpus** that already has y
   (SWE-bench trajectories, Terminal-Bench, Harbor non-DSM tasks)
   and run intent-state + off-policy metrics. Snowball
   `eval-methodology` is the shopping list.
3. **Only then** claim `P(fail_T | B)`.

## What we will not do

- Add more single-metric Harbor toys and call them tasks.
- Raise k to 20 on one toy and call that a behaviour×task map.
- Treat every leftover n-gram cluster as a new syndrome.
- Use LLM-as-judge “was this on-task?” as the outer oracle (MAST
  already did that; we want a test / gold / accept bit).

## Status

- Verifier layers 1–6: implemented on `intent-state`.
- Eval layers (this note): **plan only**. Next code is a
  `scripts/map_behaviour_to_task.py` dry-run on LiteLLM mixed cells,
  then a composite fixture pack if the dry-run’s schema holds.
