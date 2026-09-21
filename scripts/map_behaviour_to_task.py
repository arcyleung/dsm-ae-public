#!/usr/bin/env python3
"""Behaviour -> task-outcome mapping over real Harbor/EvalHub trajectories.

This is the empirical slice the layered-eval note calls for: an outer task
oracle (verifier reward) that is **not** a DSM-AE gate, both outcome classes
present, and off-policy instruments scored on the same trajectories.

For every instrument B we report:

    P(fail | B)      does B hurt this task family?
    P(B | fail)      when the task fails, how often is B present?
    lift             P(fail | B) / P(fail | not B)
    risk difference  P(fail | B) - P(fail | not B)
    Fisher exact p   two-sided, plus Benjamini-Hochberg q
    stratified RD    language-adjusted (Mantel-Haenszel style pooling)

The **language-stratified** estimate is the confound control: a model that is
simply weak at Go will fail Go instances at a higher base rate, which would
make any instrument correlated with Go look causal. Pooling within-language
risk differences removes that. An instrument that survives stratification is
associated with failure *given the ecosystem*, which is the agentic-deficit
reading rather than the language-competence reading.

Two corrections are applied on top of the naive analysis (defense Q/A Q23):

**C4 — harness split.** The archived SWE-bench-Pro corpus pools two bundles
that ran *different agent harnesses* (opencode 1.18.18 on
`openai-compatible/proxy`, claude-code 2.1.207 on `hosted_vllm/0905_505B_v2_1`).
Pooling them is an Axis V (scaffold) violation, and it matters mechanically:
`read_loop` / `thrash_edit` / `scope_creep` are defined on tool-call counts,
and tool-call granularity differs between harnesses. `--split-by harness`
emits one block per harness alongside the pooled block.

**C3 — cluster-robust inference.** The pooled corpus covers far fewer distinct
upstream instances than trials, because the same instance is attempted once per
bundle. Fisher exact over the flat trial list treats those as independent. A
cluster bootstrap resamples *instances* with replacement and recomputes the risk
difference, giving a percentile CI and a bootstrap p that carry the clustering.
Within a single harness each instance appears once, so the correction is a
no-op there — which the report verifies rather than assumes.

Usage:
    python3 scripts/map_behaviour_to_task.py \
        --root evalhub-extract \
        --out reports/behaviour-task/mapping.json \
        --md reports/behaviour-task/MAPPING.md \
        --split-by harness --bootstrap 4000
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from dsm_ae.atoms import atom_from_tool
from dsm_ae.harbor import HarborTrial, iter_runs, score_trajectory
from dsm_ae.harbor.instruments import ANCHOR, INSTRUMENTS

# --------------------------------------------------------------- statistics


def _log_factorial_table(n: int) -> list[float]:
    tab = [0.0] * (n + 1)
    for i in range(2, n + 1):
        tab[i] = tab[i - 1] + math.log(i)
    return tab


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the 2x2 table [[a,b],[c,d]].

    Sums the hypergeometric probability of every table at least as extreme
    (<= observed probability) with the same margins.
    """
    n = a + b + c + d
    if n == 0:
        return 1.0
    lf = _log_factorial_table(n)
    r1, r2 = a + b, c + d
    c1, c2 = a + c, b + d

    def logp(x: int) -> float:
        # table [[x, r1-x], [c1-x, r2-c1+x]]
        y, z, w = r1 - x, c1 - x, r2 - c1 + x
        if min(x, y, z, w) < 0:
            return float("-inf")
        return (
            lf[r1] + lf[r2] + lf[c1] + lf[c2]
            - lf[n] - lf[x] - lf[y] - lf[z] - lf[w]
        )

    obs = logp(a)
    tol = 1e-9
    total = 0.0
    lo, hi = max(0, c1 - r2), min(r1, c1)
    for x in range(lo, hi + 1):
        lp = logp(x)
        if lp <= obs + tol:
            total += math.exp(lp)
    return min(1.0, total)


def benjamini_hochberg(pvals: Sequence[float]) -> list[float]:
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        i = m - rank
        val = pvals[idx] * m / (i + 1)
        prev = min(prev, val)
        q[idx] = min(1.0, prev)
    return q


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - half) / d), min(1.0, (c + half) / d))



# --------------------------------------------------------- cluster bootstrap


def _rd_from_counts(a: int, b: int, c: int, d: int) -> float | None:
    n1, n0 = a + b, c + d
    if n1 == 0 or n0 == 0:
        return None
    return a / n1 - c / n0


def cluster_bootstrap_rd(
    rows: Sequence[tuple[str, bool, bool]],
    *,
    n_boot: int = 2000,
    seed: int = 20260908,
    alpha: float = 0.05,
) -> tuple[float | None, float | None, float | None, int]:
    """Cluster bootstrap for the risk difference, clustering on instance id.

    `rows` is (cluster_id, behaviour_present, failed). Clusters — upstream
    instances — are resampled with replacement; every trial in a drawn cluster
    comes along. That preserves the within-instance correlation the naive
    Fisher test ignores.

    Returns (ci_lo, ci_hi, p, n_clusters). The p-value is the two-sided
    percentile-bootstrap p: 2 * min(P(RD* <= 0), P(RD* >= 0)), with the usual
    +1 continuity correction so it can never be exactly zero.
    """
    by: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for cid, present, failed in rows:
        by[cid].append((present, failed))
    keys = list(by.keys())
    k = len(keys)
    if k < 2:
        return None, None, None, k

    # Per-cluster 2x2 contributions, so a replicate is a few sums.
    cells: list[tuple[int, int, int, int]] = []
    for key in keys:
        a = b = c = d = 0
        for present, failed in by[key]:
            if present and failed:
                a += 1
            elif present:
                b += 1
            elif failed:
                c += 1
            else:
                d += 1
        cells.append((a, b, c, d))

    rng = random.Random(seed)
    reps: list[float] = []
    for _ in range(n_boot):
        A = B = C = D = 0
        for _ in range(k):
            a, b, c, d = cells[rng.randrange(k)]
            A += a
            B += b
            C += c
            D += d
        rd = _rd_from_counts(A, B, C, D)
        if rd is not None:
            reps.append(rd)
    if len(reps) < 50:
        return None, None, None, k

    reps.sort()
    n = len(reps)
    lo = reps[max(0, int(math.floor((alpha / 2) * n)))]
    hi = reps[min(n - 1, int(math.ceil((1 - alpha / 2) * n)) - 1)]
    n_le = sum(1 for r in reps if r <= 0.0)
    n_ge = sum(1 for r in reps if r >= 0.0)
    pval = min(1.0, 2.0 * (min(n_le, n_ge) + 1) / (n + 1))
    return lo, hi, pval, k


def cluster_profile(trials: Sequence[HarborTrial]) -> dict[str, object]:
    """How much clustering is actually present in a block.

    Reports the instance-repeat histogram and, for instances attempted more
    than once, the outcome-agreement rate -> an ICC proxy and design effect
    deff = 1 + (m_bar - 1) * ICC. A block whose instances all appear once has
    deff = 1 and needs no cluster correction; the report checks that rather
    than assuming it.
    """
    by: dict[str, list[bool]] = defaultdict(list)
    for t in trials:
        key = t.task_name or t.trial_name
        by[key].append(bool(t.success))
    sizes = Counter(len(v) for v in by.values())
    n_trials = sum(len(v) for v in by.values())
    k = len(by)
    m_bar = n_trials / k if k else 0.0

    paired = [v for v in by.values() if len(v) > 1]
    agree = 0
    total_pairs = 0
    for v in paired:
        for i in range(len(v)):
            for j in range(i + 1, len(v)):
                total_pairs += 1
                if v[i] == v[j]:
                    agree += 1
    agree_rate = agree / total_pairs if total_pairs else None

    # ICC via the standard one-way ANOVA identity on a binary outcome.
    icc = None
    if total_pairs and n_trials:
        p_bar = sum(sum(v) for v in by.values()) / n_trials
        var = p_bar * (1 - p_bar)
        if var > 0 and agree_rate is not None:
            # P(agree) = 1 - 2*p*(1-p)*(1-ICC)  for exchangeable binary pairs
            icc = max(0.0, min(1.0, 1.0 - (1.0 - agree_rate) / (2 * var)))
    deff = 1.0 + (m_bar - 1) * icc if icc is not None else 1.0
    return {
        "n_trials": n_trials,
        "n_instances": k,
        "attempts_per_instance": m_bar,
        "repeat_histogram": {str(a): b for a, b in sorted(sizes.items())},
        "paired_instances": len(paired),
        "outcome_agreement": agree_rate,
        "icc": icc,
        "design_effect": deff,
        "effective_n": n_trials / deff if deff else n_trials,
    }


def harness_profile(trials: Sequence[HarborTrial]) -> dict[str, object]:
    """Tool-call volume and atom mix, so the granularity claim is quantified.

    `read_loop`, `thrash_edit` and `scope_creep` are thresholds on tool-call
    counts. If one harness emits three times as many `read` calls for the same
    work, those instruments fire at different rates for reasons that have
    nothing to do with the model.
    """
    counts = sorted(len(t.tool_calls) for t in trials)
    tools: Counter = Counter()
    atoms: Counter = Counter()
    for t in trials:
        for tc in t.tool_calls:
            name = str(tc.get("name") or "")
            args = tc.get("arguments")
            tools[name or "<unnamed>"] += 1
            atoms[atom_from_tool(name, args if isinstance(args, dict) else {})] += 1
    total = sum(tools.values())

    def q(f: float) -> int:
        if not counts:
            return 0
        return counts[min(len(counts) - 1, int(len(counts) * f))]

    return {
        "n_trials": len(trials),
        "total_tool_calls": total,
        "tool_calls_mean": (total / len(trials)) if trials else 0.0,
        "tool_calls_p25": q(0.25),
        "tool_calls_median": q(0.5),
        "tool_calls_p75": q(0.75),
        "tool_calls_max": counts[-1] if counts else 0,
        "tool_names": dict(tools.most_common(15)),
        "atom_mix": {
            k: v / total for k, v in atoms.most_common(12)
        } if total else {},
        "atom_counts": dict(atoms.most_common(12)),
    }


# --------------------------------------------------------------- association


@dataclass
class Association:
    instrument: str
    anchor: str
    n: int
    n_present: int
    p_fail_given_b: float
    p_fail_given_not_b: float
    p_b_given_fail: float
    p_b_given_success: float
    lift: float
    risk_diff: float
    rd_ci_lo: float
    rd_ci_hi: float
    fisher_p: float
    fisher_q: float
    strat_risk_diff: float | None
    strat_strata: int
    lang_diff_risk_diff: float | None
    lang_diff_strata: int
    base_rate_fail: float
    verdict: str
    # Cluster-robust (C3): bootstrap over upstream instances, not trials.
    cl_ci_lo: float | None = None
    cl_ci_hi: float | None = None
    cl_p: float | None = None
    cl_q: float | None = None
    n_clusters: int = 0
    cluster_verdict: str = ""


def _rd_ci(a: int, b: int, c: int, d: int) -> tuple[float, float]:
    """Wald CI for the difference of two proportions."""
    n1, n2 = a + b, c + d
    if n1 == 0 or n2 == 0:
        return (0.0, 0.0)
    p1, p2 = a / n1, c / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    d0 = p1 - p2
    return (d0 - 1.96 * se, d0 + 1.96 * se)


def stratified_risk_difference(
    trials: Sequence[tuple[bool, bool, str]],
    min_per_stratum: int = 20,
) -> tuple[float | None, int]:
    """Cochran-Mantel-Haenszel style pooled risk difference across strata.

    `trials` is (behaviour_present, failed, stratum). Strata with too few
    observations, or with no variation in the behaviour, are dropped.
    """
    by: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for present, failed, stratum in trials:
        by[stratum].append((present, failed))

    num = 0.0
    den = 0.0
    used = 0
    for rows in by.values():
        n = len(rows)
        if n < min_per_stratum:
            continue
        n1 = sum(1 for p, _ in rows if p)
        n0 = n - n1
        if n1 == 0 or n0 == 0:
            continue
        f1 = sum(1 for p, f in rows if p and f)
        f0 = sum(1 for p, f in rows if not p and f)
        rd = f1 / n1 - f0 / n0
        w = n1 * n0 / n  # CMH weight
        num += w * rd
        den += w
        used += 1
    if den == 0:
        return None, 0
    return num / den, used


def difficulty_bucket(t: HarborTrial, edges: Sequence[int]) -> str:
    """Coarse difficulty proxy: trajectory length quartile.

    Longer runs mean the agent kept working, which tracks how hard the
    instance was. This is a proxy, not a difficulty label: it is endogenous
    (a thrashing agent also produces a long trace), so it is reported as a
    second stratification arm rather than as the headline estimate.
    """
    n = len(t.tool_calls)
    for i, e in enumerate(edges):
        if n <= e:
            return f"q{i + 1}"
    return f"q{len(edges) + 1}"


def _quartile_edges(trials: Sequence[HarborTrial]) -> list[int]:
    lens = sorted(len(t.tool_calls) for t in trials)
    if not lens:
        return [0, 0, 0]
    return [lens[int(len(lens) * f)] for f in (0.25, 0.5, 0.75)]


def associate(
    trials: Sequence[HarborTrial],
    scores: Sequence[dict[str, bool]],
    *,
    stratify_by: str = "language",
    n_boot: int = 0,
) -> list[Association]:
    labelled = [
        (t, s) for t, s in zip(trials, scores) if t.success is not None
    ]
    n_total = len(labelled)
    if n_total == 0:
        return []
    base_fail = sum(1 for t, _ in labelled if not t.success) / n_total
    edges = _quartile_edges([t for t, _ in labelled])

    raw: list[Association] = []
    for ins in INSTRUMENTS:
        a = b = c = d = 0  # a: B&fail, b: B&success, c: !B&fail, d: !B&success
        strat_rows: list[tuple[bool, bool, str]] = []
        joint_rows: list[tuple[bool, bool, str]] = []
        cluster_rows: list[tuple[str, bool, bool]] = []
        for t, s in labelled:
            present = s[ins.key]
            failed = not t.success
            lang = getattr(t, stratify_by, "unknown")
            strat_rows.append((present, failed, lang))
            joint_rows.append(
                (present, failed, f"{lang}|{difficulty_bucket(t, edges)}")
            )
            cluster_rows.append((t.task_name or t.trial_name, present, failed))
            if present and failed:
                a += 1
            elif present and not failed:
                b += 1
            elif not present and failed:
                c += 1
            else:
                d += 1

        n_present = a + b
        n_absent = c + d
        n_fail = a + c
        n_succ = b + d

        p_fail_b = a / n_present if n_present else 0.0
        p_fail_nb = c / n_absent if n_absent else 0.0
        lift = (p_fail_b / p_fail_nb) if p_fail_nb > 0 else float("inf") if p_fail_b else 1.0
        rd = p_fail_b - p_fail_nb
        lo, hi = _rd_ci(a, b, c, d)
        p = fisher_exact_two_sided(a, b, c, d)
        srd, nstrata = stratified_risk_difference(strat_rows)
        jrd, njstrata = stratified_risk_difference(joint_rows, min_per_stratum=15)
        if n_boot:
            cl_lo, cl_hi, cl_p, n_clusters = cluster_bootstrap_rd(
                cluster_rows, n_boot=n_boot
            )
        else:
            cl_lo = cl_hi = cl_p = None
            n_clusters = len({r[0] for r in cluster_rows})

        raw.append(
            Association(
                instrument=ins.key,
                anchor=ins.anchor,
                n=n_total,
                n_present=n_present,
                p_fail_given_b=p_fail_b,
                p_fail_given_not_b=p_fail_nb,
                p_b_given_fail=(a / n_fail if n_fail else 0.0),
                p_b_given_success=(b / n_succ if n_succ else 0.0),
                lift=lift,
                risk_diff=rd,
                rd_ci_lo=lo,
                rd_ci_hi=hi,
                fisher_p=p,
                fisher_q=1.0,
                strat_risk_diff=srd,
                strat_strata=nstrata,
                lang_diff_risk_diff=jrd,
                lang_diff_strata=njstrata,
                base_rate_fail=base_fail,
                verdict="",
                cl_ci_lo=cl_lo,
                cl_ci_hi=cl_hi,
                cl_p=cl_p,
                n_clusters=n_clusters,
            )
        )

    qs = benjamini_hochberg([r.fisher_p for r in raw])
    # BH over the cluster-robust p as well, so `cluster q` and `q` are
    # comparable: same family, same correction, different variance model.
    cl_ps = [1.0 if r.cl_p is None else r.cl_p for r in raw]
    cl_qs = benjamini_hochberg(cl_ps)
    for r, q, cq in zip(raw, qs, cl_qs):
        r.fisher_q = q
        r.cl_q = None if r.cl_p is None else cq
        r.verdict = _verdict(r)
        r.cluster_verdict = _cluster_verdict(r)
    raw.sort(key=lambda r: (-abs(r.risk_diff), r.fisher_q))
    return raw


def _verdict(r: Association) -> str:
    """Plain-language read of one association, confound-aware."""
    if r.n_present < 15:
        return "underpowered"
    if r.fisher_q >= 0.05:
        return "not significant"
    crosses_zero = r.rd_ci_lo <= 0 <= r.rd_ci_hi
    if crosses_zero:
        return "not significant"
    # Does the effect survive language stratification?
    if r.strat_risk_diff is not None and r.strat_strata >= 2:
        if r.risk_diff > 0 and r.strat_risk_diff < 0.5 * r.risk_diff:
            return "confounded by language"
        if r.risk_diff < 0 and r.strat_risk_diff > 0.5 * r.risk_diff:
            return "confounded by language"
    # And language x difficulty jointly? Difficulty is endogenous (a thrashing
    # agent also produces a long trace), so collapse here is reported as
    # "difficulty-entangled" rather than as a clean refutation.
    if r.lang_diff_risk_diff is not None and r.lang_diff_strata >= 3:
        if r.risk_diff > 0 and r.lang_diff_risk_diff < 0.5 * r.risk_diff:
            return "difficulty-entangled"
        if r.risk_diff < 0 and r.lang_diff_risk_diff > 0.5 * r.risk_diff:
            return "difficulty-entangled"
    if r.p_b_given_fail < 0.05:
        return "significant but rare"
    return "predicts failure" if r.risk_diff > 0 else "predicts success"


def _cluster_verdict(r: Association) -> str:
    """Does the naive verdict survive resampling instances instead of trials?

    Deliberately blunt: an instrument whose cluster-robust CI crosses zero is
    reported as no longer significant, whatever its naive q said.
    """
    if r.cl_ci_lo is None or r.cl_ci_hi is None:
        return "not computed"
    if r.n_present < 15:
        return "underpowered"
    robust_sig = (
        not (r.cl_ci_lo <= 0.0 <= r.cl_ci_hi)
        and r.cl_q is not None
        and r.cl_q < 0.05
    )
    naive_sig = r.fisher_q < 0.05 and not (r.rd_ci_lo <= 0 <= r.rd_ci_hi)
    if naive_sig and robust_sig:
        return "survives clustering"
    if naive_sig and not robust_sig:
        return "LOST under clustering"
    if robust_sig:
        return "significant only when clustered"
    return "not significant either way"


# --------------------------------------------------------------- reporting


@dataclass
class Block:
    title: str
    kind: str  # "pooled" | "harness"
    n_pass: int
    n_fail: int
    assocs: list[Association]
    cluster: dict[str, object] = field(default_factory=dict)
    harness: dict[str, object] = field(default_factory=dict)
    meta: dict[str, object] = field(default_factory=dict)


def _fmt_pct(x: float) -> str:
    return f"{x:.1%}"


def _fmt_ci(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return "—"
    return f"[{lo:+.3f}, {hi:+.3f}]"


def _fmt_p(p: float | None) -> str:
    return "—" if p is None else f"{p:.3g}"


def _instrument_table(assocs: Sequence[Association], *, clustered: bool) -> str:
    out = [
        "\n| Instrument | Anchor | n(B) | P(fail\\|B) | P(fail\\|¬B) | P(B\\|fail) "
        "| RD [95% CI] | RD* lang | RD** lang×diff | q |"
    ]
    if clustered:
        out.append(" cluster CI | cluster q | cluster verdict |")
    out.append(" Verdict |\n|---|---|---:|---:|---:|---:|---|---:|---:|---:|")
    if clustered:
        out.append("---|---:|---|")
    out.append("---|\n")
    for r in assocs:
        srd = "—" if r.strat_risk_diff is None else f"{r.strat_risk_diff:+.3f}"
        jrd = "—" if r.lang_diff_risk_diff is None else f"{r.lang_diff_risk_diff:+.3f}"
        row = (
            f"| `{r.instrument}` | {r.anchor} | {r.n_present} "
            f"| {_fmt_pct(r.p_fail_given_b)} | {_fmt_pct(r.p_fail_given_not_b)} "
            f"| {_fmt_pct(r.p_b_given_fail)} "
            f"| {r.risk_diff:+.3f} [{r.rd_ci_lo:+.3f}, {r.rd_ci_hi:+.3f}] "
            f"| {srd} | {jrd} | {r.fisher_q:.3g} |"
        )
        if clustered:
            row += (
                f" {_fmt_ci(r.cl_ci_lo, r.cl_ci_hi)} | {_fmt_p(r.cl_q)} "
                f"| {r.cluster_verdict} |"
            )
        row += f" {r.verdict} |\n"
        out.append(row)
    return "".join(out)


def _cluster_note(prof: dict[str, object]) -> str:
    if not prof:
        return ""
    n = prof["n_trials"]
    k = prof["n_instances"]
    m = prof["attempts_per_instance"]
    hist = ", ".join(f"{v} instance(s) × {a} attempt(s)" for a, v in prof["repeat_histogram"].items())  # type: ignore[union-attr]
    agree = prof["outcome_agreement"]
    icc = prof["icc"]
    deff = prof["design_effect"]
    eff = prof["effective_n"]
    lines = [
        f"\n> **Clustering.** {n} model-attempts over {k} distinct upstream "
        f"instances ({m:.2f} attempts each). Repeat histogram: {hist}.\n"
    ]
    if agree is not None:
        lines.append(
            f"> Repeated instances agree on outcome {agree:.1%} of the time "
            f"(ICC ≈ {icc:.2f}), design effect ≈ {deff:.2f}, "
            f"**effective n ≈ {eff:.0f}**. The `cluster CI` / `cluster p` "
            "columns come from a bootstrap that resamples *instances*, so they "
            "carry this correlation; the naive `q` does not.\n"
        )
    else:
        lines.append(
            "> No instance is attempted more than once in this block, so there "
            "is no clustering to correct: design effect = 1.00 and the cluster "
            "bootstrap reduces to an ordinary trial-level bootstrap. This is "
            "checked, not assumed.\n"
        )
    return "".join(lines)


def _harness_note(prof: dict[str, object]) -> str:
    if not prof:
        return ""
    tools = ", ".join(f"`{k}`×{v}" for k, v in list(prof["tool_names"].items())[:8])  # type: ignore[union-attr]
    atoms = ", ".join(
        f"{k} {v:.1%}" for k, v in list(prof["atom_mix"].items())[:8]  # type: ignore[union-attr]
    )
    return (
        f"\n> **Tool-call granularity.** {prof['total_tool_calls']} calls over "
        f"{prof['n_trials']} trials — mean {prof['tool_calls_mean']:.1f}, "
        f"quartiles {prof['tool_calls_p25']}/{prof['tool_calls_median']}/"
        f"{prof['tool_calls_p75']}, max {prof['tool_calls_max']}.\n"
        f"> Tools: {tools}.\n"
        f"> Atom mix: {atoms}.\n"
    )


def render_markdown(
    blocks: list[Block],
    lang_table: dict[str, dict[str, Counter]],
    excluded: Counter | None = None,
) -> str:
    out: list[str] = []
    out.append("# Behaviour → task-outcome mapping\n")
    out.append(
        "Off-policy DSM-AE instruments scored against real agentic task\n"
        "trajectories whose success oracle is the benchmark verifier, not a\n"
        "DSM-AE gate. This is the third layer of the metric → behaviour → task\n"
        "stack: it answers *which behaviours are load-bearing for which jobs*.\n"
    )
    out.append(
        "\n**Reading the table.** `P(fail|B)` is the failure rate among runs where\n"
        "the behaviour fired; `P(B|fail)` is how often failures carry it. `RD` is\n"
        "the risk difference with a 95% Wald interval, `q` is the\n"
        "Benjamini-Hochberg adjusted Fisher p.\n"
        "\n`RD*` is the **language-stratified** risk difference (CMH-pooled within\n"
        "ecosystem). An instrument whose plain RD is large but whose RD* collapses\n"
        "is tracking the ecosystem — the model is weak at Go — not an agentic\n"
        "deficit.\n"
        "\n`RD**` additionally stratifies on a **difficulty proxy** (trajectory-length\n"
        "quartile within language). Treat this column as a stress test, not as the\n"
        "headline: trace length is endogenous, since a thrashing agent produces a\n"
        "long trace for reasons that are themselves the behaviour under study.\n"
        "Conditioning on it can absorb genuine signal, so a shrunken `RD**` is\n"
        "flagged `difficulty-entangled` rather than treated as a refutation.\n"
        "\n`cluster CI` / `cluster q` are **cluster-robust**: a bootstrap that\n"
        "resamples upstream *instances* with replacement rather than trials, so\n"
        "repeated attempts on the same instance do not count as independent\n"
        "evidence. `q` is anti-conservative wherever an instance appears more\n"
        "than once; the cluster columns are the honest ones there. `cluster q`\n"
        "is BH-adjusted over the same instrument family as `q`, so the two are\n"
        "directly comparable. The bootstrap p has a resolution floor of\n"
        "1/(B+1), so a `cluster q` at that floor means \"smaller than the\n"
        "bootstrap can resolve\", not an exact value. Point\n"
        "estimates (`RD`, `RD*`, `RD**`) are unaffected by clustering.\n"
        "\n**Harness blocks.** Blocks labelled `<source> / <agent> <version>` are\n"
        "single-scaffold: one agent harness, one model. The pooled block above\n"
        "them mixes harnesses and is retained only for continuity with the\n"
        "earlier analysis — cross-scaffold claims are *not* supported by it\n"
        "(Axis V). Where a pooled and a per-harness result disagree, the\n"
        "per-harness result is the one to quote.\n"
    )

    for blk in blocks:
        out.append(f"\n## {blk.title}\n")
        out.append(f"n = {blk.n_pass + blk.n_fail} ({blk.n_pass} pass / {blk.n_fail} fail)\n")
        if blk.meta:
            bits = "; ".join(f"{k}: {v}" for k, v in blk.meta.items())
            out.append(f"\n_{bits}_\n")
        out.append(_cluster_note(blk.cluster))
        out.append(_harness_note(blk.harness))
        if not blk.assocs:
            out.append("\n_No labelled trials._\n")
            continue
        clustered = any(a.cl_ci_lo is not None for a in blk.assocs)
        out.append(_instrument_table(blk.assocs, clustered=clustered))

    if excluded:
        total_ex = sum(excluded.values())
        out.append("\n## Excluded: trials whose reward did not measure the model\n")
        out.append(
            f"\n{total_ex} trials carried a reward that is not a measurement of\n"
            "model behaviour, for one of two **structural** reasons:\n"
            "\n1. **Zero tests ran** — an empty `tests` list in\n"
            "   `verifier/output.json`: scored 0 without a single test executing.\n"
            "2. **The harness failed** — `result.json.exception_info` records a\n"
            "   trial-level failure (network, agent timeout, non-zero agent exit,\n"
            "   API/auth error). These are invisible in `trial.log`, which is why\n"
            "   an earlier pass reported \"zero errors\" while 119 reference trials\n"
            "   carried one.\n"
            "\nBoth mean the record shows the measurement *could not have happened*.\n"
            "A reward that merely disagrees with a partial success signal is **not**\n"
            "excluded — that case was adjudicated and rejected (defense Q/A Q18).\n"
            "\nThis matters because neither artifact is evenly distributed. Left in,\n"
            "they inflate the failure rate of whichever ecosystem they hit and\n"
            "manufacture precisely the language-deficit conclusion this study exists\n"
            "to rule out.\n"
        )
        out.append("\n| Language — reason | excluded |\n|---|---:|\n")
        for lang, n in sorted(excluded.items(), key=lambda kv: -kv[1]):
            out.append(f"| {lang} | {n} |\n")

    out.append("\n## Language base rates (the confound)\n")
    out.append(
        "\nIf failure rate varies sharply by ecosystem, any instrument correlated\n"
        "with ecosystem inherits that signal. These are the base rates the `RD*`\n"
        "column adjusts for.\n"
    )
    for run, langs in lang_table.items():
        out.append(f"\n**{run}**\n\n| Language | n | fail rate |\n|---|---:|---:|\n")
        for lang, c in sorted(langs.items(), key=lambda kv: -sum(kv[1].values())):
            n = c["pass"] + c["fail"]
            if not n:
                continue
            out.append(f"| {lang} | {n} | {c['fail'] / n:.1%} |\n")

    out.append("\n## What this does and does not establish\n")
    out.append(
        "\n- The oracle is external (verifier reward), so the association is not\n"
        "  circular with any DSM-AE gate.\n"
        "- Association is not causation. A surviving `RD*` means the behaviour\n"
        "  predicts failure *within* an ecosystem; it does not prove the\n"
        "  behaviour caused it. Difficulty is not matched.\n"
        "- Instruments are off-policy analogues of pack gates, not the gates\n"
        "  themselves. `edited_test_files` in particular has a high base rate on\n"
        "  SWE-bench-Pro, where touching tests is often legitimate.\n"
        "- Scaffold is fixed *within* a harness block (Axis V). The pooled block\n"
        "  mixes two harnesses and two models; any instrument defined on\n"
        "  tool-call counts (`read_loop`, `thrash_edit`, `scope_creep`) can move\n"
        "  there for granularity reasons alone. Quote the per-harness block.\n"
        "- Cluster-robust columns correct only the *precision* claim. They do not\n"
        "  address confounding, causality, or scaffold mixing.\n"
    )
    return "".join(out)


# --------------------------------------------------------------- main


def _build_block(
    title: str,
    kind: str,
    trials: Sequence[HarborTrial],
    *,
    n_boot: int,
) -> Block:
    scores = [score_trajectory(t) for t in trials]
    assocs = associate(trials, scores, n_boot=n_boot)
    n_pass = sum(1 for t in trials if t.success)
    meta: dict[str, object] = {}
    if kind == "harness":
        models = sorted({t.model_name for t in trials if t.model_name})
        runs = sorted({t.run for t in trials})
        meta = {"model(s)": ", ".join(models) or "unknown", "bundle(s)": ", ".join(runs)}
    else:
        harnesses = sorted({t.harness for t in trials})
        meta = {"harnesses pooled": ", ".join(harnesses)}
    return Block(
        title=title,
        kind=kind,
        n_pass=n_pass,
        n_fail=len(trials) - n_pass,
        assocs=assocs,
        cluster=cluster_profile(trials),
        harness=harness_profile(trials),
        meta=meta,
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("evalhub-extract"))
    ap.add_argument("--out", type=Path, default=Path("reports/behaviour-task/mapping.json"))
    ap.add_argument("--md", type=Path, default=Path("reports/behaviour-task/MAPPING.md"))
    ap.add_argument("--min-trials", type=int, default=40)
    ap.add_argument(
        "--split-by",
        choices=["none", "harness"],
        default="harness",
        help="emit an extra block per agent harness (Axis V scaffold split)",
    )
    ap.add_argument(
        "--bootstrap",
        type=int,
        default=4000,
        help="cluster-bootstrap replicates (0 disables cluster-robust columns)",
    )
    args = ap.parse_args(argv)

    by_source: dict[str, list[HarborTrial]] = defaultdict(list)
    lang_table: dict[str, dict[str, Counter]] = {}
    excluded: Counter = Counter()

    for run_name, trials in iter_runs(args.root):
        if not trials:
            continue
        langs: dict[str, Counter] = defaultdict(Counter)
        for t in trials:
            if t.reward is not None and not t.scoreable:
                reason = (
                    "zero tests ran"
                    if t.n_tests_run == 0
                    else f"harness: {t.exception_type}"
                )
                excluded[f"{t.language} — {reason}"] += 1
            if t.success is None:
                continue
            langs[t.language]["pass" if t.success else "fail"] += 1
        lang_table[run_name] = dict(langs)
        for t in trials:
            by_source[t.source].append(t)
        n_ex = sum(1 for t in trials if t.reward is not None and not t.scoreable)
        harnesses = Counter(t.harness for t in trials)
        print(
            f"loaded {run_name}: {len(trials)} trials ({n_ex} unscoreable) "
            f"harness={dict(harnesses)}"
        )

    if excluded:
        print("excluded (reward did not measure the model):")
        for k, v in sorted(excluded.items(), key=lambda kv: -kv[1]):
            print(f"   {v:5d}  {k}")

    blocks: list[Block] = []
    payload: dict[str, object] = {"sources": {}, "harnesses": {}}

    for source, trials in sorted(by_source.items()):
        labelled = [t for t in trials if t.success is not None]
        if len(labelled) < args.min_trials:
            print(f"skip {source}: only {len(labelled)} labelled trials")
            continue
        pooled = _build_block(source, "pooled", labelled, n_boot=args.bootstrap)
        blocks.append(pooled)
        payload["sources"][source] = {  # type: ignore[index]
            "n_pass": pooled.n_pass,
            "n_fail": pooled.n_fail,
            "n_instances": pooled.cluster["n_instances"],
            "cluster_profile": pooled.cluster,
            "harness_profile": pooled.harness,
            "harnesses_pooled": sorted({t.harness for t in labelled}),
            "associations": [asdict(a) for a in pooled.assocs],
        }
        print(
            f"{source}: n={len(labelled)} "
            f"instances={pooled.cluster['n_instances']} "
            f"deff={pooled.cluster['design_effect']:.2f}"
        )

        if args.split_by != "harness":
            continue
        by_harness: dict[str, list[HarborTrial]] = defaultdict(list)
        for t in labelled:
            by_harness[t.harness].append(t)
        if len(by_harness) < 2:
            continue
        for harness, hts in sorted(by_harness.items()):
            if len(hts) < args.min_trials:
                print(f"skip {source} / {harness}: only {len(hts)} labelled trials")
                continue
            # Within a harness every instance is attempted at most once, so the
            # cluster bootstrap is a no-op -- run it anyway and let the report
            # show that, rather than asserting it.
            blk = _build_block(
                f"{source} / {harness}", "harness", hts, n_boot=args.bootstrap
            )
            blocks.append(blk)
            payload["harnesses"][blk.title] = {  # type: ignore[index]
                "source": source,
                "harness": harness,
                "models": sorted({t.model_name for t in hts if t.model_name}),
                "bundles": sorted({t.run for t in hts}),
                "n_pass": blk.n_pass,
                "n_fail": blk.n_fail,
                "cluster_profile": blk.cluster,
                "harness_profile": blk.harness,
                "associations": [asdict(a) for a in blk.assocs],
            }
            print(
                f"  {blk.title}: n={len(hts)} "
                f"instances={blk.cluster['n_instances']} "
                f"deff={blk.cluster['design_effect']:.2f} "
                f"mean_calls={blk.harness['tool_calls_mean']:.1f}"
            )

    payload["language_base_rates"] = {
        run: {lang: dict(c) for lang, c in langs.items()}
        for run, langs in lang_table.items()
    }
    payload["excluded_zero_test_trials"] = dict(excluded)
    payload["instruments"] = {
        ins.key: {"anchor": ins.anchor, "det": ins.det, "doc": ins.doc}
        for ins in INSTRUMENTS
    }
    payload["config"] = {
        "split_by": args.split_by,
        "bootstrap_replicates": args.bootstrap,
        "cluster_unit": "task_name (upstream instance id)",
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))
    args.md.parent.mkdir(parents=True, exist_ok=True)
    args.md.write_text(render_markdown(blocks, lang_table, excluded))
    print(f"wrote {args.out} and {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
