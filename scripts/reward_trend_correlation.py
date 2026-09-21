#!/usr/bin/env python3
"""Continuous-reward trend analysis for reward-shaped task families.

WHY THIS EXISTS
---------------
Two task families need different analyses, and conflating them was an error in
the earlier mapping work:

**Workflow-structured** (SWE-bench-Pro, feat-bench). A canonical sequence
exists — plan -> explore -> implement -> verify — so phases are meaningful,
sentinel events can be localized to a step, and the oracle is binary
(resolved / not). `map_behaviour_to_task.py` handles this family.

**Reward-shaped** (NL2Repo-Bench, DenovoSWE). No canonical workflow, so
"ill-behaviour" may not even be definable — but the oracle is *continuous*
(fraction of the oracle repo's unit tests passing). This module handles that
family.

The binarisation `success = reward >= 1.0` is actively wrong here. On the
archived NL2Repo corpus: 216 scoreable trials, **162 strictly between 0 and 1**,
154 distinct reward values, and only 14 at exactly 1.0. Thresholding turns a
0.98 into a "failure" indistinguishable from a 0.0 and discards nearly all the
variance. That also explains the >93% "failure rate" earlier attributed to task
difficulty — it was largely a measurement artifact.

WHAT IS MEASURED
----------------
Spearman rank correlation of continuous trajectory trends against the
continuous reward, plus an efficiency view (reward per 1k completion tokens).
Rank correlation because the reward scale is not linear-meaningful — it is the
fraction of a particular repo's tests, and repos differ.

Inference clusters on `task_name`: the same instance is attempted by several
models, so trials are not independent (the design-effect problem recorded in
defense Q/A Q23). CIs come from a cluster bootstrap resampling *instances*.

Everything here is continuous and unthresholded by design: the evidence-level
analysis (docs/surveys/2026-09-09-evidence-levels-and-attribution.md) measured
that each thresholding step costs ~0.06 AUC. Reward-shaped families are exactly
where that loss is avoidable.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dsm_ae.harbor import iter_runs, scoreable_only  # noqa: E402
from dsm_ae.harbor.steps import sentinels, trends  # noqa: E402

BOOT = 4000
SEED = 42


# ----------------------------------------------------------------- statistics

def _ranks(xs: Sequence[float]) -> list[float]:
    """Average ranks, ties shared."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    out = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return None if dx == 0 or dy == 0 else num / (dx * dy)


def cluster_bootstrap_rho(
    rows: Sequence[dict], feat: str, cluster_key: str = "task_name", b: int = BOOT
) -> tuple[float | None, float | None, float | None]:
    """Point estimate + percentile CI, resampling whole instances."""
    rho = spearman([r[feat] for r in rows], [r["reward"] for r in rows])
    if rho is None:
        return None, None, None
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[r[cluster_key]].append(r)
    keys = list(by)
    rng = random.Random(SEED)
    out: list[float] = []
    for _ in range(b):
        samp: list[dict] = []
        for _ in keys:
            samp.extend(by[rng.choice(keys)])
        v = spearman([r[feat] for r in samp], [r["reward"] for r in samp])
        if v is not None:
            out.append(v)
    if not out:
        return rho, None, None
    out.sort()
    return rho, out[int(0.025 * len(out))], out[int(0.975 * len(out))]


def benjamini_hochberg(ps: Sequence[float]) -> list[float]:
    m = len(ps)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: ps[i])
    q = [0.0] * m
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        i = m - rank
        prev = min(prev, ps[idx] * m / (i + 1))
        q[idx] = min(1.0, prev)
    return q


def boot_p(lo: float | None, hi: float | None) -> float:
    """Crude two-sided p from whether the CI excludes zero."""
    if lo is None or hi is None:
        return 1.0
    return 0.04 if (lo > 0 or hi < 0) else 1.0


# ----------------------------------------------------------------- features

FEATURES: dict[str, Callable[[Any], float]] = {
    "n_calls": lambda tr, t: float(tr.n_calls),
    "search_share": lambda tr, t: tr.search_share,
    "edit_share": lambda tr, t: tr.edit_share,
    "test_share": lambda tr, t: tr.test_share,
    "error_share": lambda tr, t: tr.error_share,
    "repeat_read_ratio": lambda tr, t: tr.repeat_read_ratio,
    "late_edit_share": lambda tr, t: tr.late_edit_share,
    "distinct_files": lambda tr, t: float(tr.distinct_files),
    "first_edit_frac": lambda tr, t: (
        tr.first_edit_frac if tr.first_edit_frac is not None else 1.0
    ),
    "first_test_frac": lambda tr, t: (
        tr.first_test_frac if tr.first_test_frac is not None else 1.0
    ),
    "n_sentinels": lambda tr, t: float(len(sentinels(t))),
    "completion_tokens": lambda tr, t: float(t.completion_tokens),
    "n_steps": lambda tr, t: float(t.n_steps),
}


def build_rows(root: Path, source_match: str) -> list[dict]:
    rows: list[dict] = []
    for _run, ts in iter_runs(root):
        for t in scoreable_only(ts):
            if source_match not in t.source:
                continue
            if t.reward is None:
                continue
            tr = trends(t)
            if tr.n_calls == 0:
                continue
            row = {
                "trial_name": t.trial_name,
                "task_name": t.task_name,
                "harness": t.harness,
                "model": t.model_name,
                "reward": float(t.reward),
            }
            for k, fn in FEATURES.items():
                row[k] = float(fn(tr, t))
            # efficiency: reward per 1k completion tokens
            row["reward_per_1k_tok"] = (
                t.reward / (t.completion_tokens / 1000.0)
                if t.completion_tokens
                else 0.0
            )
            rows.append(row)
    return rows


# ----------------------------------------------------------------- reporting

def analyse(rows: list[dict], label: str) -> dict[str, Any]:
    res = []
    for f in FEATURES:
        vals = [r[f] for r in rows]
        if len(set(vals)) < 3:
            continue
        rho, lo, hi = cluster_bootstrap_rho(rows, f)
        if rho is None:
            continue
        res.append(
            {
                "feature": f,
                "rho": rho,
                "ci_lo": lo,
                "ci_hi": hi,
                "p": boot_p(lo, hi),
                "n": len(rows),
            }
        )
    qs = benjamini_hochberg([r["p"] for r in res])
    for r, q in zip(res, qs):
        r["q"] = q
        r["verdict"] = (
            "excludes zero" if (r["ci_lo"] is not None and (r["ci_lo"] > 0 or r["ci_hi"] < 0))
            else "not significant"
        )
    res.sort(key=lambda r: -abs(r["rho"]))
    return {
        "label": label,
        "n_trials": len(rows),
        "n_instances": len({r["task_name"] for r in rows}),
        "features": res,
    }


def render(blocks: list[dict]) -> str:
    out = ["# Continuous-reward trend correlation (reward-shaped task family)\n"]
    out.append(
        "\nSpearman rank correlation of continuous trajectory trends against the\n"
        "**continuous** task reward, for families where the oracle is graded rather\n"
        "than binary. CIs are cluster bootstraps resampling *instances*, since the\n"
        "same instance is attempted by several models.\n"
        "\n**Why not binarise.** On this corpus 162 of 216 scoreable trials fall\n"
        "strictly between 0 and 1, across 154 distinct reward values, with only 14\n"
        "at exactly 1.0. `success = reward >= 1.0` would score a 0.98 identically to\n"
        "a 0.0 and discard almost all the variance — and would report a >93%\n"
        "failure rate that is mostly a measurement artifact.\n"
    )
    for b in blocks:
        out.append(f"\n## {b['label']}\n")
        out.append(
            f"\nn = {b['n_trials']} trials over {b['n_instances']} distinct instances\n"
        )
        if not b["features"]:
            out.append("\n_No feature with enough variation._\n")
            continue
        out.append(
            "\n| Feature | Spearman ρ | 95% CI (cluster) | q | Verdict |\n"
            "|---|---:|---|---:|---|\n"
        )
        for r in b["features"]:
            ci = (
                f"[{r['ci_lo']:+.3f}, {r['ci_hi']:+.3f}]"
                if r["ci_lo"] is not None
                else "—"
            )
            out.append(
                f"| `{r['feature']}` | {r['rho']:+.3f} | {ci} | {r['q']:.3g} | {r['verdict']} |\n"
            )
    out.append("\n## Interpretation limits\n")
    out.append(
        "\n- Rank correlation, not causation. A trend that tracks reward may be\n"
        "  downstream of instance difficulty rather than of agent behaviour.\n"
        "- `n_calls` and `completion_tokens` are **endogenous**: an agent that is\n"
        "  doing badly keeps working, so length partly reflects difficulty. The same\n"
        "  over-adjustment trap recorded in defense Q/A Q16 and Q26.\n"
        "- Reward is the fraction of a *particular* repo's tests. Cross-instance\n"
        "  comparability is why this uses rank rather than linear correlation.\n"
        "- No workflow phases are used here. For families without a canonical\n"
        "  sequence, phase labels and step attribution are not defined; only\n"
        "  aggregate trends and efficiency are.\n"
    )
    return "".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("evalhub-extract"))
    ap.add_argument("--source", default="nl2repo")
    ap.add_argument("--out", type=Path, default=Path("reports/behaviour-task/REWARD_TRENDS.md"))
    ap.add_argument("--json", type=Path, default=Path("reports/behaviour-task/reward_trends.json"))
    args = ap.parse_args(argv)

    rows = build_rows(args.root, args.source)
    print(f"loaded {len(rows)} trials from source~{args.source}")
    if not rows:
        print("nothing to analyse")
        return 1

    blocks = [analyse(rows, f"{args.source} (all models pooled)")]
    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)
    for m, rs in sorted(by_model.items()):
        if len(rs) >= 40:
            blocks.append(analyse(rs, f"{args.source} / model {m[:44]}"))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(blocks))
    args.json.write_text(json.dumps(blocks, indent=2))
    print(f"wrote {args.out} and {args.json}")

    top = blocks[0]["features"][:6]
    print("\ntop features (pooled):")
    for r in top:
        ci = f"[{r['ci_lo']:+.3f},{r['ci_hi']:+.3f}]" if r["ci_lo"] is not None else "-"
        print(f"  {r['feature']:20s} rho={r['rho']:+.3f}  {ci}  {r['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
