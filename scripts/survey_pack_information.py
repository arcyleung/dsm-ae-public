#!/usr/bin/env python3
"""survey_pack_information.py

Empirical half of `docs/surveys/2026-09-08-smoke-test-criteria-survey.md`.

Treats the DSM-AE full-suite pack reports as a *test suite* and asks the three
questions the test-suite-reduction / IRT literature asks of any suite:

  1. DISCRIMINATION  -- which gates separate models at all? (item discrimination)
  2. REDUNDANCY      -- how many gates are near-duplicates? (suite reduction)
  3. REDUCTION CURVE -- how much full-suite signal survives a k-gate subset?
  4. STABILITY       -- which gates are flaky? (flaky-test literature)

Read-only. Writes nothing except stdout (and optional --json).

Power warning, printed with every run: the model axis is n=10 DISTINCT models
(13 report files, 3 of which are k=20 re-runs of models already present at
k=3). Every correlation / PCA number here is EXPLORATORY.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from collections import OrderedDict

import numpy as np

REPORT_GLOB = "reports/full-suite/*-full.json"
# k=20 ("max") reports supersede the k=3 report for the same underlying model.
MAX_SUFFIX = "(max)"


def load_reports(root: str):
    """Return OrderedDict model_key -> dict(bootstraps, k, path, is_max)."""
    out = {}
    for path in sorted(glob.glob(os.path.join(root, REPORT_GLOB))):
        d = json.load(open(path))
        model = (d.get("scaffold_card") or {}).get("model") or os.path.basename(path)
        is_max = MAX_SUFFIX in model
        base = model.replace(MAX_SUFFIX, "").strip()
        boots = d["bootstraps"]
        rec = {
            "path": path,
            "model_raw": model,
            "is_max": is_max,
            "n_gates": len(boots),
            "k_values": sorted({b["n"] for b in boots}),
            "gates": {b["metric_id"]: b for b in boots},
        }
        # prefer the max (k=20) report for a model that has both
        if base not in out or (is_max and not out[base]["is_max"]):
            out[base] = rec
    return OrderedDict(sorted(out.items()))


def build_matrix(reports):
    """models x gates matrix of pass_rate, restricted to gates present in all."""
    common = None
    for rec in reports.values():
        s = set(rec["gates"])
        common = s if common is None else (common & s)
    gates = sorted(common)
    models = list(reports)
    M = np.array(
        [[reports[m]["gates"][g]["pass_rate"] for g in gates] for m in models],
        dtype=float,
    )
    return models, gates, M


# ---------------------------------------------------------------- 1. discrimination


def discrimination(models, gates, M):
    n_models = M.shape[0]
    total = M.mean(axis=1)  # per-model suite score
    rows = []
    for j, g in enumerate(gates):
        col = M[:, j]
        sd = col.std(ddof=1)
        # point-biserial-ish item-total correlation, corrected (exclude own item)
        rest = (M.sum(axis=1) - col) / (M.shape[1] - 1)
        if sd == 0 or rest.std(ddof=1) == 0:
            r_it = float("nan")
        else:
            r_it = float(np.corrcoef(col, rest)[0, 1])
        rows.append(
            {
                "gate": g,
                "mean": float(col.mean()),
                "sd": float(sd),
                "min": float(col.min()),
                "max": float(col.max()),
                "n_distinct": int(len(set(np.round(col, 6)))),
                "r_item_rest": r_it,
                "degenerate": bool(sd == 0),
                "ceiling": bool(col.min() >= 0.999),
                "floor": bool(col.max() <= 0.001),
            }
        )
    return total, rows


# ---------------------------------------------------------------- 2. redundancy


def redundancy(gates, M, rows, r_thresh=0.95):
    live = [j for j, r in enumerate(rows) if not r["degenerate"]]
    A = M[:, live]
    names = [gates[j] for j in live]
    C = np.corrcoef(A, rowvar=False)
    pairs = []
    for a in range(len(live)):
        for b in range(a + 1, len(live)):
            if abs(C[a, b]) >= r_thresh:
                pairs.append((names[a], names[b], float(C[a, b])))
    # PCA on centered (not scaled -- pass rates share a 0..1 scale)
    X = A - A.mean(axis=0)
    # rank is bounded by n_models-1
    sv = np.linalg.svd(X, compute_uv=False)
    var = sv ** 2
    frac = var / var.sum()
    cum = np.cumsum(frac)
    return names, C, pairs, frac, cum


# ---------------------------------------------------------------- 3. reduction curve


def _score_subset(M, idx):
    return M[:, idx].mean(axis=1)


def _spearman(a, b):
    from scipy.stats import spearmanr

    r = spearmanr(a, b).statistic
    return float(r)


def greedy_reduction(models, gates, M, rows, kmax=30, seed=0):
    """Forward-greedy: pick gates whose running subset-mean best tracks the
    full-suite mean (Spearman across models). This is the in-sample /
    optimistic curve -- see loo_reduction for the honest one."""
    target = M.mean(axis=1)
    live = [j for j, r in enumerate(rows) if not r["degenerate"]]
    chosen, curve = [], []
    for _ in range(min(kmax, len(live))):
        best, best_r = None, -2.0
        for j in live:
            if j in chosen:
                continue
            r = _spearman(_score_subset(M, chosen + [j]), target)
            if not np.isnan(r) and r > best_r:
                best, best_r = j, r
        if best is None:
            break
        chosen.append(best)
        curve.append(
            {
                "k": len(chosen),
                "gate_added": gates[best],
                "spearman_vs_full": best_r,
                "pearson_vs_full": float(
                    np.corrcoef(_score_subset(M, chosen), target)[0, 1]
                ),
            }
        )
    return chosen, curve


def loo_reduction(models, gates, M, rows, ks=(3, 5, 10, 15, 20, 30), seed=0):
    """Leave-one-model-out: select the k gates on 9 models, score the held-out
    model, and ask whether the held-out model's subset rank matches its
    full-suite rank. With n=10 this is weak but it is the honest version."""
    n = M.shape[0]
    out = []
    for k in ks:
        preds, truths = [], []
        for h in range(n):
            keep = [i for i in range(n) if i != h]
            Mtr = M[keep, :]
            rows_tr = [
                {"degenerate": bool(Mtr[:, j].std(ddof=1) == 0)}
                for j in range(M.shape[1])
            ]
            sel, _ = greedy_reduction(
                [models[i] for i in keep], gates, Mtr, rows_tr, kmax=k
            )
            preds.append(float(M[h, sel].mean()))
            truths.append(float(M[h, :].mean()))
        out.append(
            {
                "k": k,
                "spearman_heldout": _spearman(preds, truths),
                "pearson_heldout": float(np.corrcoef(preds, truths)[0, 1]),
            }
        )
    return out


def random_baseline(M, rows, ks=(3, 5, 10, 15, 20, 30), reps=2000, seed=0):
    rng = np.random.default_rng(seed)
    live = [j for j, r in enumerate(rows) if not r["degenerate"]]
    target = M.mean(axis=1)
    out = []
    for k in ks:
        if k > len(live):
            continue
        rs = []
        for _ in range(reps):
            idx = rng.choice(live, size=k, replace=False)
            r = _spearman(_score_subset(M, list(idx)), target)
            if not np.isnan(r):
                rs.append(r)
        rs = np.array(rs)
        out.append(
            {
                "k": k,
                "mean": float(rs.mean()),
                "p10": float(np.percentile(rs, 10)),
                "median": float(np.median(rs)),
                "p90": float(np.percentile(rs, 90)),
            }
        )
    return out


# ---------------------------------------------------------------- 4. stability


def stability(root):
    """k=20 reports only: per-gate status and std."""
    out = {}
    for path in sorted(glob.glob(os.path.join(root, "reports/full-suite/*max-full.json"))):
        d = json.load(open(path))
        model = (d.get("scaffold_card") or {}).get("model")
        recs = []
        for b in d["bootstraps"]:
            recs.append(
                {
                    "gate": b["metric_id"],
                    "n": b["n"],
                    "mean": b["mean"],
                    "std": b["std"],
                    "pass_rate": b["pass_rate"],
                    "status": b["status"],
                }
            )
        out[model] = recs
    return out


# ---------------------------------------------------------------- 5. HGS-style syndrome coverage


def syndrome_coverage(root, gates, M, rows):
    """Harrold-Gupta-Soffa framing: treat each syndrome (finding code) as a
    *requirement* and keep one representative gate per requirement. This is the
    coverage-preserving reduction the classic literature describes."""
    gi = {g: i for i, g in enumerate(gates)}
    syn = {}
    for path in sorted(glob.glob(os.path.join(root, REPORT_GLOB))):
        d = json.load(open(path))
        for f in d.get("findings", []):
            syn.setdefault(f["code"], set()).update(
                m for m in f.get("linked_metrics", []) if m in gi
            )
    syn = {k: sorted(v) for k, v in syn.items() if v}
    live = {j for j, r in enumerate(rows) if not r["degenerate"]}
    covered = set().union(*syn.values()) if syn else set()
    sel = []
    for code, ms in sorted(syn.items()):
        cands = [gi[m] for m in ms if gi[m] in live]
        if cands:
            sel.append(max(cands, key=lambda j: M[:, j].std(ddof=1)))
    sel = sorted(set(sel))
    return syn, sorted(set(gates) - covered), sel


# ---------------------------------------------------------------- 6. saturation check


def saturation_replication(models, gates, M, drop_prefix="gpt-5.6", ks=(3, 5, 10, 15, 20)):
    """Re-run the honest LOO reduction after dropping models that sit at the
    suite ceiling. If the reduction curve only worked because a few models were
    trivially separable, this is where it shows."""
    keep = [i for i, m in enumerate(models) if not m.startswith(drop_prefix)]
    Ms = M[keep, :]
    ms = [models[i] for i in keep]
    rows_s = [{"degenerate": bool(Ms[:, j].std(ddof=1) == 0)} for j in range(M.shape[1])]
    lo = loo_reduction(ms, gates, Ms, rows_s, ks=ks)
    rb = random_baseline(Ms, rows_s, ks=ks)
    return ms, Ms, rows_s, lo, rb


# ------------------------------------------------- 7. scaffold-robustness class

# Gates whose PASS/FAIL turns on a COUNT or RATIO crossing a numeric threshold.
# Classified from the per-trial `explanation` strings emitted by each gate
# (see reports/full-suite/*-full.json -> bootstraps[].per_trial[].explanation).
#
# WHY THIS MATTERS: docs/surveys/2026-09-08-harness-split-and-cluster-robust.md
# showed that count-thresholded *trajectory instruments* (read_loop,
# thrash_edit, scope_creep) fire at different rates on two harnesses emitting
# 84.6 vs 58.9 tool calls per trial (1.44x), while structural instruments fire
# at near-identical rates. A count threshold measures the SCAFFOLD as much as
# the model. The same hazard applies to pack gates built the same way.
COUNT_THRESHOLDED = {
    "no_read_loop",              # max re-reads of one file <= 2
    "low_coord_churn",           # n_writes <= 6
    "synthesis_not_enumeration", # bullet count <= 8
    "verbosity_indicator",       # duplicate-line ratio <= 0.45
    "verbosity_indicator.tier1",
    "erosion_indicator",         # CC>10 mass share <= 0.5
    "erosion_indicator.tier1",
    "erosion_indicator.tier2",
    "erosion_indicator.tier3",
    "erosion_slope",             # slope > 0.03 per checkpoint
    "god_function_mass",         # max_mass_share < 0.55 and max_cc <= 12
    "overact_ratio",             # OA <= 0.2
    "overthink_ratio",           # OT <= 0.1
    "calibrated_ratio",          # CAL >= 0.7
    "quality_stable",            # conjunction of two ratio gates
    "quality_stable.tier1",
    "quality_stable.tier3",
    "in_aligned_region",         # conjunction of OT/OA/CAL ratio gates
}


def scaffold_robustness(gates, rows, unstable_gates):
    """Split gates into count-thresholded vs structural and report how the
    discrimination / stability findings fall across the two classes."""
    out = {"count": [], "structural": []}
    for r in rows:
        cls = "count" if r["gate"] in COUNT_THRESHOLDED else "structural"
        out[cls].append(r)
    uns = set(unstable_gates)
    summary = {}
    for cls, rs in out.items():
        n = len(rs)
        summary[cls] = {
            "n": n,
            "degenerate": sum(1 for r in rs if r["degenerate"]),
            "mean_sd": float(np.mean([r["sd"] for r in rs])) if n else float("nan"),
            "n_unstable": sum(1 for r in rs if r["gate"] in uns),
        }
    # count-thresholded gates present only in the k=20 (94-gate) suites
    k20_only = sorted(g for g in COUNT_THRESHOLDED if g not in set(gates))
    return out, summary, k20_only


# ---------------------------------------------------------------- main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args()

    reports = load_reports(a.root)
    models, gates, M = build_matrix(reports)

    print("=" * 74)
    print("DSM-AE pack suite as a test suite -- information analysis")
    print("=" * 74)
    print(f"reports loaded : {len(reports)} (k=20 report preferred where both exist)")
    print(f"distinct models: {len(models)}  <-- THIS IS THE n. IT IS SMALL.")
    print(f"common gates   : {len(gates)}")
    for m in models:
        r = reports[m]
        print(f"  {m:24s} k={r['k_values']} gates={r['n_gates']} {os.path.basename(r['path'])}")
    print()

    # 1 -------------------------------------------------------------
    total, rows = discrimination(models, gates, M)
    deg = [r for r in rows if r["degenerate"]]
    ceil = [r for r in rows if r["ceiling"]]
    flo = [r for r in rows if r["floor"]]
    live = [r for r in rows if not r["degenerate"]]
    print("--- 1. DISCRIMINATION ---")
    print(f"gates with zero variance across models : {len(deg)}/{len(gates)} "
          f"({100*len(deg)/len(gates):.0f}%)")
    print(f"  of which all-pass (ceiling, pr=1.0)  : {len(ceil)}")
    print(f"  of which all-fail (floor,   pr=0.0)  : {len(flo)}")
    print(f"gates with >=2 distinct values         : {len(live)}")
    print(f"gates with sd >= 0.10                  : {sum(1 for r in rows if r['sd']>=0.10)}")
    print(f"gates with sd >= 0.20                  : {sum(1 for r in rows if r['sd']>=0.20)}")
    print()
    print("per-model suite score (mean pass_rate over common gates):")
    for m, t in sorted(zip(models, total), key=lambda x: -x[1]):
        print(f"  {m:24s} {t:.3f}")
    print()
    print("top 15 gates by item-rest correlation (IRT-style discrimination):")
    for r in sorted(live, key=lambda r: -(r["r_item_rest"] if r["r_item_rest"] == r["r_item_rest"] else -9))[:15]:
        print(f"  {r['gate']:32s} sd={r['sd']:.3f} r_it={r['r_item_rest']:+.3f} "
              f"range=[{r['min']:.2f},{r['max']:.2f}]")
    print()
    print("bottom 10 gates by item-rest correlation (negative discrimination):")
    for r in sorted(live, key=lambda r: (r["r_item_rest"] if r["r_item_rest"] == r["r_item_rest"] else 9))[:10]:
        print(f"  {r['gate']:32s} sd={r['sd']:.3f} r_it={r['r_item_rest']:+.3f}")
    print()
    print("degenerate (zero-information) gates:")
    for r in deg:
        tag = "ALL-PASS" if r["ceiling"] else ("ALL-FAIL" if r["floor"] else f"const@{r['mean']:.2f}")
        print(f"  {r['gate']:32s} {tag}")
    print()

    # 2 -------------------------------------------------------------
    names, C, pairs, frac, cum = redundancy(gates, M, rows)
    print("--- 2. REDUNDANCY ---")
    print(f"non-degenerate gates in correlation matrix: {len(names)}")
    print(f"NOTE: correlation over n={len(models)} models. A |r|>0.95 pair is "
          f"NOT evidence of duplication at this n.")
    npairs = len(names) * (len(names) - 1) // 2
    for th in (0.99, 0.95, 0.90, 0.80):
        c = sum(1 for a, b, r in pairs if abs(r) >= th) if th <= 0.95 else None
        cc = sum(
            1
            for i in range(len(names))
            for j in range(i + 1, len(names))
            if abs(C[i, j]) >= th
        )
        print(f"  pairs with |r| >= {th:.2f}: {cc}/{npairs} ({100*cc/npairs:.1f}%)")
    print()
    print("PCA (centered, unscaled) on the model x live-gate matrix:")
    for i, (f, c) in enumerate(zip(frac, cum), 1):
        print(f"  PC{i:<2d} var={f*100:5.1f}%  cum={c*100:5.1f}%")
        if c > 0.995:
            break
    for target in (0.8, 0.9):
        k = int(np.searchsorted(cum, target) + 1)
        print(f"  components to reach {target*100:.0f}% variance: {k} "
              f"(of max {min(M.shape[0]-1, len(names))} possible)")
    print()

    # 3 -------------------------------------------------------------
    print("--- 3. REDUCTION CURVE ---")
    chosen, curve = greedy_reduction(models, gates, M, rows, kmax=30)
    print("in-sample greedy (OPTIMISTIC -- selection and evaluation on same 10 models):")
    for c in curve:
        if c["k"] <= 12 or c["k"] % 5 == 0:
            print(f"  k={c['k']:<3d} spearman={c['spearman_vs_full']:+.3f} "
                  f"pearson={c['pearson_vs_full']:+.3f}  +{c['gate_added']}")
    print()
    rb = random_baseline(M, rows)
    print("random k-gate subsets (2000 draws) -- the null the greedy must beat:")
    for r in rb:
        print(f"  k={r['k']:<3d} spearman mean={r['mean']:+.3f} "
              f"[p10 {r['p10']:+.3f}, med {r['median']:+.3f}, p90 {r['p90']:+.3f}]")
    print()
    lo = loo_reduction(models, gates, M, rows)
    print("leave-one-model-out greedy (HONEST -- select on 9, score the 10th):")
    for r in lo:
        print(f"  k={r['k']:<3d} spearman_heldout={r['spearman_heldout']:+.3f} "
              f"pearson_heldout={r['pearson_heldout']:+.3f}")
    print()

    # 4 -------------------------------------------------------------
    st = stability(a.root)
    print("--- 4. STABILITY (k=20 suites only) ---")
    allrec = {}
    for model, recs in st.items():
        cnt = {}
        for r in recs:
            cnt[r["status"]] = cnt.get(r["status"], 0) + 1
            allrec.setdefault(r["gate"], []).append(r)
        tot = len(recs)
        uns = cnt.get("UNSTABLE", 0)
        print(f"  {model:24s} gates={tot} " +
              " ".join(f"{k}={v}" for k, v in sorted(cnt.items())) +
              f"  UNSTABLE={100*uns/tot:.1f}%")
    print()
    print("  gates UNSTABLE in >=1 of the 3 k=20 suites:")
    uns_any = sorted(
        (g for g, rs in allrec.items() if any(r["status"] == "UNSTABLE" for r in rs)),
    )
    for g in uns_any:
        rs = allrec[g]
        print(f"    {g:32s} " + "  ".join(
            f"{r['status'][:4]}(pr={r['pass_rate']:.2f},sd={r['std']:.2f},n={r['n']})" for r in rs))
    print(f"  total: {len(uns_any)} distinct gates ever UNSTABLE out of {len(allrec)}")
    print()
    stds = [r["std"] for rs in allrec.values() for r in rs]
    stds = np.array(stds)
    print(f"  per-gate std across k=20 trials: median={np.median(stds):.3f} "
          f"p90={np.percentile(stds,90):.3f} max={stds.max():.3f}")
    print(f"  fraction of (gate,model) cells with std>0.25 (UNSTABLE threshold): "
          f"{100*(stds>0.25).mean():.1f}%")
    print(f"  fraction with std==0 (perfectly deterministic): {100*(stds==0).mean():.1f}%")
    print()

    # 5 -------------------------------------------------------------
    syn, uncovered, sel = syndrome_coverage(a.root, gates, M, rows)
    print("--- 5. HGS-STYLE SYNDROME-COVERAGE REDUCTION ---")
    print(f"syndromes (finding codes) touching >=1 common gate: {len(syn)}")
    print(f"gates in NO syndrome (uncovered by the taxonomy): {len(uncovered)} {uncovered}")
    print(f"one-gate-per-syndrome subset size: {len(sel)}")
    tgt = M.mean(axis=1)
    ssc = M[:, sel].mean(axis=1)
    print(f"  spearman vs full suite = {_spearman(ssc, tgt):+.3f}  "
          f"pearson = {float(np.corrcoef(ssc, tgt)[0,1]):+.3f}")
    print("  kept gates:", [gates[j] for j in sel])
    print()

    # 6 -------------------------------------------------------------
    ms, Ms, rows_s, lo_s, rb_s = saturation_replication(models, gates, M)
    print("--- 6. SATURATION CHECK (drop the ceiling models) ---")
    print(f"models retained: {len(ms)} -> {ms}")
    tots = Ms.mean(axis=1)
    print(f"full-suite score spread now {tots.min():.3f}..{tots.max():.3f} "
          f"(was {M.mean(axis=1).min():.3f}..{M.mean(axis=1).max():.3f})")
    print(f"live (non-degenerate) gates now: "
          f"{sum(1 for r in rows_s if not r['degenerate'])}")
    print("  leave-one-out greedy on the harder subset:")
    for r in lo_s:
        print(f"    k={r['k']:<3d} spearman_heldout={r['spearman_heldout']:+.3f} "
              f"pearson_heldout={r['pearson_heldout']:+.3f}")
    print("  random-subset null on the harder subset:")
    for r in rb_s:
        print(f"    k={r['k']:<3d} spearman mean={r['mean']:+.3f} "
              f"[p10 {r['p10']:+.3f}, p90 {r['p90']:+.3f}]")
    print()

    # 7 -------------------------------------------------------------
    cls_rows, cls_sum, k20_only = scaffold_robustness(gates, rows, uns_any)
    print("--- 7. SCAFFOLD ROBUSTNESS: count-thresholded vs structural ---")
    print("  A gate that fires on 'more than N of something' measures the")
    print("  HARNESS as much as the model (see harness-split survey: 84.6 vs")
    print("  58.9 tool calls/trial across two harnesses, 1.44x).")
    for cls in ("count", "structural"):
        s_ = cls_sum[cls]
        print(f"  {cls:11s} n={s_['n']:3d}  zero-variance={s_['degenerate']:3d}  "
              f"mean_sd={s_['mean_sd']:.3f}  ever-UNSTABLE={s_['n_unstable']}")
    print("  count-thresholded gates among the 62 common gates:")
    for r in cls_rows["count"]:
        tag = "DEGENERATE" if r["degenerate"] else f"sd={r['sd']:.3f}"
        u = " UNSTABLE" if r["gate"] in set(uns_any) else ""
        print(f"    {r['gate']:32s} {tag}{u}")
    if k20_only:
        print("  count-thresholded but only in the k=20 (94-gate) suites:")
        for g in k20_only:
            print(f"    {g}")
    print()


    print("=" * 74)
    print("POWER CAVEAT: n =", len(models), "distinct models. Correlations and PCA")
    print("above are EXPLORATORY ONLY and must not be reported as established.")
    print("=" * 74)

    if a.json_out:
        payload = {
            "models": models,
            "gates": gates,
            "matrix": M.tolist(),
            "discrimination": rows,
            "pca_frac": frac.tolist(),
            "pca_cum": cum.tolist(),
            "greedy_curve": curve,
            "random_baseline": rb,
            "loo": lo,
            "unstable_gates": uns_any,
            "count_thresholded": sorted(COUNT_THRESHOLDED),
            "hgs_subset": [gates[j] for j in sel],
            "uncovered_gates": uncovered,
            "loo_saturation_dropped": lo_s,
            "random_saturation_dropped": rb_s,
        }
        with open(a.json_out, "w") as f:
            json.dump(payload, f, indent=1)
        print("wrote", a.json_out)


if __name__ == "__main__":
    main()
