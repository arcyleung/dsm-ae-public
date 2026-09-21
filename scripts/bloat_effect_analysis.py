#!/usr/bin/env python3
"""Context-bloat effect analysis: clean k=10 vs bloat50 k=10, paired by pack.

Reads only checked-in artifacts:

  clean arm   reports/repro-shared/{model}/{PREFIX}_{pack}_n10/trial_*.json
  bloat arm   reports/bloat/bloat50/{model}.json      (assembled scores, per_trial kept)

Both arms are k=10 trials per pack under the same raw tool-loop scaffold
(temperature 0, max_turns 10). The bloat arm wraps that adapter in
``ContextBloatedAdapter`` (``src/dsm_ae/context_bloat.py``), which prepends
unrelated prior-session chat history until the prefix reaches ~50% of the
model's operational context window, then states the task.

Statistics
----------
**Pass semantics.** A metric's pass rate is the fraction of observations whose
scorer set ``passed`` — NOT ``value >= 1``. Several metrics are inverted
(``overeager_rate`` passes when the value is 0) or continuous with a scorer
threshold (``erosion_indicator.tier3``, ``god_function_mass``). Using the value
would silently invert them.

**Cluster unit = trial.** One trial is one LLM session on one fixture; packs
with several scenarios emit 2-4 observations from that single session, so
observations inside a trial are not independent. Every CI and p-value here
resamples or permutes *trials*, never observations. n is reported as both.

**Bloat arm reconstruction.** The assembled bloat report flattens per-trial
scores in pack-major, trial-minor order. We re-split that flat list using the
per-pack observation shape measured from the clean arm, and refuse to attribute
anything unless the arithmetic reconciles exactly against the reported n.

Usage
-----
    python3 scripts/bloat_effect_analysis.py
    python3 scripts/bloat_effect_analysis.py --json reports/bloat/bloat50/effects.json
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]

MODELS = [
    "gpt-5.5",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "qwen3.5-397b-a17b",
    "qwen3.6-plus",
]

GPT56 = ["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]

_PREFIXES = (
    "CSO_", "CTX_", "CVF_", "EGD_", "GDD_", "ISDS2_", "ISDS3_", "ISDS_",
    "MAH_", "MCD_", "MEM_", "MRC_", "MVF_", "NFR_", "OASD_", "PCD_", "PII_",
    "RSD_", "SBG_", "TID2_", "TID_", "XPI_",
)

BOOT_ITERS = 5000
PERM_ITERS = 20000
SEED = 20260910

# A "trial" key is (pack, trial_index). Values are the observations that trial
# produced for one metric, each already reduced to the scorer's pass flag.
TrialMap = dict[tuple[str, int], list[bool]]


def _pack_from_dirname(name: str) -> str:
    base = name.rsplit("_n", 1)[0] if "_n" in name else name
    for p in _PREFIXES:
        if base.startswith(p):
            return base[len(p):]
    return base


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load_clean(model: str) -> dict[str, TrialMap]:
    """metric_id -> {(pack, trial_index): [pass flags]} from clean k=10 runs."""
    root = _ROOT / "reports" / "repro-shared" / model
    out: dict[str, TrialMap] = defaultdict(dict)
    if not root.is_dir():
        return out
    for pack_dir in sorted(root.iterdir()):
        if not pack_dir.is_dir() or "_n10" not in pack_dir.name:
            continue
        pack = _pack_from_dirname(pack_dir.name)
        for tp in sorted(pack_dir.glob("trial_*.json")):
            try:
                idx = int(tp.stem.split("_")[-1])
            except ValueError:
                continue
            try:
                rep = json.loads(tp.read_text(encoding="utf-8"))
            except Exception:
                continue
            for b in rep.get("bootstraps") or []:
                flags = [bool(pt.get("passed")) for pt in b.get("per_trial") or []]
                if flags:
                    out[b["metric_id"]][(pack, idx)] = flags
    return out


def _obs_shape(model: str) -> dict[str, dict[str, int]]:
    """pack -> metric_id -> observations per trial (verified constant per pack)."""
    root = _ROOT / "reports" / "repro-shared" / model
    shape: dict[str, dict[str, int]] = {}
    if not root.is_dir():
        return shape
    for pack_dir in sorted(root.iterdir()):
        if not pack_dir.is_dir() or "_n10" not in pack_dir.name:
            continue
        trials = sorted(pack_dir.glob("trial_*.json"))
        if not trials:
            continue
        rep = json.loads(trials[0].read_text(encoding="utf-8"))
        shape[_pack_from_dirname(pack_dir.name)] = {
            b["metric_id"]: len(b.get("per_trial") or [])
            for b in rep.get("bootstraps") or []
        }
    return shape


def _global_obs_shape() -> dict[str, dict[str, int]]:
    merged: dict[str, dict[str, int]] = {}
    for m in MODELS:
        for pack, mm in _obs_shape(m).items():
            merged.setdefault(pack, {}).update(mm)
    return merged


def load_bloat(model: str, shape: dict[str, dict[str, int]]) -> tuple[dict[str, TrialMap], dict[str, Any]]:
    p = _ROOT / "reports" / "bloat" / "bloat50" / f"{model}.json"
    rep = json.loads(p.read_text(encoding="utf-8"))
    packs = list(rep["packs"])
    k = int(rep["k_trials"])

    out: dict[str, TrialMap] = defaultdict(dict)
    unreconciled: list[str] = []
    for b in rep.get("bootstraps") or []:
        mid = b["metric_id"]
        flags = [bool(pt.get("passed")) for pt in b.get("per_trial") or []]
        per_pack = [(pk, shape.get(pk, {}).get(mid, 0)) for pk in packs]
        if sum(k * n for _, n in per_pack) != len(flags):
            unreconciled.append(mid)
            continue
        i = 0
        for pk, n in per_pack:
            if n == 0:
                continue
            for t in range(k):
                out[mid][(pk, t)] = flags[i:i + n]
                i += n
    meta = {
        "packs": packs,
        "k": k,
        "context_bloat": (rep.get("scaffold_card") or {}).get("extra", {}).get("context_bloat"),
        "unreconciled_metrics": unreconciled,
        "notes": rep.get("notes"),
    }
    return out, meta


# --------------------------------------------------------------------------
# statistics (trial-clustered)
# --------------------------------------------------------------------------

def _rate(tm: TrialMap, keys: list[tuple[str, int]]) -> float:
    num = den = 0
    for kk in keys:
        fl = tm[kk]
        num += sum(1 for f in fl if f)
        den += len(fl)
    return num / den if den else float("nan")


def paired_rd(clean: TrialMap, bloat: TrialMap, *, iters: int = BOOT_ITERS,
              seed: int = SEED) -> dict[str, Any]:
    """Risk difference with a trial-clustered paired bootstrap.

    Trials are paired by (pack, trial_index): the two arms ran the same fixture
    with the same trial index, differing only in the stuffed prefix. Resampling
    the pair keeps the pairing and is the honest unit here.
    """
    keys = sorted(set(clean) & set(bloat))
    if not keys:
        return {"rd": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan"),
                "n_trials": 0, "n_obs_clean": 0, "n_obs_bloat": 0,
                "clean_pass": float("nan"), "bloat_pass": float("nan"), "p_perm": float("nan")}

    c_rate, b_rate = _rate(clean, keys), _rate(bloat, keys)
    point = b_rate - c_rate

    rng = random.Random(seed)
    draws = []
    for _ in range(iters):
        sel = [rng.choice(keys) for _ in keys]
        draws.append(_rate(bloat, sel) - _rate(clean, sel))
    draws.sort()
    lo = draws[int(0.025 * len(draws))]
    hi = draws[min(int(0.975 * len(draws)), len(draws) - 1)]

    # Paired permutation: swap arm labels within a trial pair at random.
    rng2 = random.Random(seed + 1)
    obs = abs(point)
    hits = 0
    for _ in range(PERM_ITERS):
        cn = cd = bn = bd = 0
        for kk in keys:
            a, b = clean[kk], bloat[kk]
            if rng2.random() < 0.5:
                a, b = b, a
            cn += sum(1 for f in a if f); cd += len(a)
            bn += sum(1 for f in b if f); bd += len(b)
        stat = (bn / bd if bd else 0.0) - (cn / cd if cd else 0.0)
        if abs(stat) >= obs - 1e-12:
            hits += 1
    p_perm = (hits + 1) / (PERM_ITERS + 1)

    return {
        "rd": point, "ci_lo": lo, "ci_hi": hi,
        "n_trials": len(keys),
        "n_obs_clean": sum(len(clean[k]) for k in keys),
        "n_obs_bloat": sum(len(bloat[k]) for k in keys),
        "clean_pass": c_rate, "bloat_pass": b_rate,
        "p_perm": p_perm,
        "packs": sorted({p for p, _ in keys}),
    }


def range_permutation(per_variant: dict[str, TrialMap], *, seed: int = SEED) -> dict[str, Any]:
    """Is the across-variant spread bigger than label noise at k=10?

    Pools trials from the three variants and permutes variant labels, keeping
    trial integrity. Returns the observed range and a permutation p-value for
    "the three variants have the same underlying rate".
    """
    names = sorted(per_variant)
    rates = {n: _rate(per_variant[n], sorted(per_variant[n])) for n in names}
    obs_range = max(rates.values()) - min(rates.values())

    pool: list[tuple[str, list[bool]]] = []
    sizes: dict[str, int] = {}
    for n in names:
        ks = sorted(per_variant[n])
        sizes[n] = len(ks)
        for kk in ks:
            pool.append((n, per_variant[n][kk]))

    rng = random.Random(seed + 7)
    hits = 0
    for _ in range(PERM_ITERS // 4):
        rng.shuffle(pool)
        i = 0
        rs = []
        for n in names:
            chunk = pool[i:i + sizes[n]]
            i += sizes[n]
            num = sum(1 for _, fl in chunk for f in fl if f)
            den = sum(len(fl) for _, fl in chunk)
            rs.append(num / den if den else 0.0)
        if (max(rs) - min(rs)) >= obs_range - 1e-12:
            hits += 1
    p = (hits + 1) / (PERM_ITERS // 4 + 1)
    return {"rates": rates, "range": obs_range, "p_perm": p}


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

def analyse() -> dict[str, Any]:
    shape = _global_obs_shape()
    clean_by: dict[str, dict[str, TrialMap]] = {}
    bloat_by: dict[str, dict[str, TrialMap]] = {}
    meta_by: dict[str, Any] = {}
    for m in MODELS:
        clean_by[m] = load_clean(m)
        bloat_by[m], meta_by[m] = load_bloat(m, shape)

    rows: list[dict[str, Any]] = []
    for m in MODELS:
        cl, bl = clean_by[m], bloat_by[m]
        for mid in sorted(set(cl) & set(bl)):
            r = paired_rd(cl[mid], bl[mid])
            if r["n_trials"] == 0:
                continue
            r.update({"model": m, "metric_id": mid})
            rows.append(r)

    # --- discrimination among the three gpt-5.6 variants -------------------
    disc: list[dict[str, Any]] = []
    metrics_all3 = set.intersection(*[
        set(clean_by[m]) & set(bloat_by[m]) for m in GPT56
    ])
    for mid in sorted(metrics_all3):
        c = range_permutation({m: clean_by[m][mid] for m in GPT56}, seed=SEED)
        b = range_permutation({m: bloat_by[m][mid] for m in GPT56}, seed=SEED + 3)
        disc.append({
            "metric_id": mid,
            "clean_rates": c["rates"], "clean_range": c["range"], "clean_p": c["p_perm"],
            "bloat_rates": b["rates"], "bloat_range": b["range"], "bloat_p": b["p_perm"],
            "clean_flat": c["range"] < 1e-9,
            "bloat_flat": b["range"] < 1e-9,
        })

    # --- aggregate discrimination test ------------------------------------
    # Per-gate permutation is hopeless at k=10 (the smallest attainable spread
    # is 0.05-0.10, and a 3-way label shuffle reproduces that constantly). The
    # question "does bloat increase discrimination ACROSS THE BATTERY" has far
    # more power: it is one statistic over 54 gates. We test it by permuting the
    # arm label (clean/bloat) within each gate and recomputing the mean spread.
    rng = random.Random(SEED + 11)
    obs_delta = (statistics.mean(d["bloat_range"] for d in disc)
                 - statistics.mean(d["clean_range"] for d in disc))
    hits = 0
    iters = PERM_ITERS // 2
    for _ in range(iters):
        cs = bs = 0.0
        for d in disc:
            a, b = d["clean_range"], d["bloat_range"]
            if rng.random() < 0.5:
                a, b = b, a
            cs += a
            bs += b
        if (bs - cs) / len(disc) >= obs_delta - 1e-12:
            hits += 1
    agg = {
        "mean_clean_range": statistics.mean(d["clean_range"] for d in disc),
        "mean_bloat_range": statistics.mean(d["bloat_range"] for d in disc),
        "delta": obs_delta,
        "p_one_sided": (hits + 1) / (iters + 1),
        "n_gates": len(disc),
        "n_woke": sum(1 for d in disc if d["clean_flat"] and not d["bloat_flat"]),
        "n_slept": sum(1 for d in disc if not d["clean_flat"] and d["bloat_flat"]),
        "n_clean_flat": sum(1 for d in disc if d["clean_flat"]),
        "n_bloat_flat": sum(1 for d in disc if d["bloat_flat"]),
    }
    # Sign test on the woke/slept asymmetry: of gates whose flatness changed at
    # all, how many changed in the "bloat separates" direction?
    changed = agg["n_woke"] + agg["n_slept"]
    if changed:
        # exact binomial tail, p=0.5 under the null
        from math import comb
        k = agg["n_woke"]
        agg["sign_test_p"] = sum(comb(changed, i) for i in range(k, changed + 1)) / 2 ** changed
    else:
        agg["sign_test_p"] = float("nan")

    # --- uniform vs model-specific ---------------------------------------
    per_metric: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        per_metric[r["metric_id"]].append(r)
    uni: list[dict[str, Any]] = []
    for mid, rs in sorted(per_metric.items()):
        rds = {r["model"]: r["rd"] for r in rs}
        moved = [m for m, v in rds.items() if abs(v) >= 0.10]
        sig = [r["model"] for r in rs if r["p_perm"] < 0.05]
        uni.append({
            "metric_id": mid,
            "n_models": len(rs),
            "rds": rds,
            "moved": moved,
            "significant": sig,
            "max_abs": max(abs(v) for v in rds.values()),
            "flat_everywhere": all(abs(v) < 1e-9 for v in rds.values()),
        })

    return {"rows": rows, "discrimination": disc, "aggregate_discrimination": agg,
            "uniformity": uni, "meta": meta_by}


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def report(res: dict[str, Any]) -> None:
    rows = res["rows"]
    models = sorted({r["model"] for r in rows})
    W = 82
    print("=" * W)
    print("CONTEXT BLOAT (50% window fill, unrelated prior sessions) vs CLEAN CONTEXT")
    print("=" * W)
    counts = defaultdict(int)
    for r in rows:
        counts[r["model"]] += 1
    print(f"models with both arms : {len(models)}")
    print("paired metrics/model  : " + ", ".join(f"{m}={counts[m]}" for m in models))
    print(f"model x metric cells  : {len(rows)}")
    ntr = sum(r["n_trials"] for r in rows)
    print(f"paired trial clusters : {ntr} across all cells "
          f"(each = one fixture x trial index run twice, once per arm)")
    cfg = res["meta"][models[0]]["context_bloat"]
    print(f"bloat config          : level={cfg.get('level')} token_method={cfg.get('token_method')} "
          f"seed={cfg.get('seed')} overflow_is_fail={cfg.get('overflow_is_fail')}")
    unrec = {m: v["unreconciled_metrics"] for m, v in res["meta"].items() if v["unreconciled_metrics"]}
    print(f"metrics dropped for un-reconcilable shape: {unrec or 'none'}")
    print()

    def line(r: dict[str, Any]) -> str:
        return (f"{r['model']:<19}{r['metric_id']:<30}{r['clean_pass']:>6.2f}{r['bloat_pass']:>7.2f}"
                f"{r['rd']:>+8.2f}  [{r['ci_lo']:+.2f},{r['ci_hi']:+.2f}]"
                f"  T={r['n_trials']:<3} p={r['p_perm']:.3f}")

    print("-" * W)
    print("1. DEGRADATIONS >= 10pp  (RD = bloat pass rate - clean pass rate)")
    print("-" * W)
    print(f"{'model':<19}{'metric':<30}{'clean':>6}{'bloat':>7}{'RD':>8}  95% CI (trial boot)   n  perm p")
    down = sorted([r for r in rows if r["rd"] <= -0.10], key=lambda r: r["rd"])
    for r in down:
        print(line(r))
    print(f"({len(down)} cells; {sum(1 for r in down if r['p_perm'] < 0.05)} with permutation p < 0.05)")
    print()

    print("-" * W)
    print("2. IMPROVEMENTS >= 10pp")
    print("-" * W)
    up = sorted([r for r in rows if r["rd"] >= 0.10], key=lambda r: -r["rd"])
    for r in up:
        print(line(r))
    print(f"({len(up)} cells; {sum(1 for r in up if r['p_perm'] < 0.05)} with permutation p < 0.05)")
    print()

    print("-" * W)
    print("3. ROBUSTNESS -- metrics unchanged in EVERY model that ran both arms")
    print("-" * W)
    flat = [u for u in res["uniformity"] if u["flat_everywhere"]]
    moved = [u for u in res["uniformity"] if not u["flat_everywhere"]]
    print(f"identical in every model : {len(flat)} / {len(res['uniformity'])}")
    print(f"moved in >= 1 model      : {len(moved)} / {len(res['uniformity'])}")
    print()
    print("  unchanged in all 6 models (the strongest robustness claim available):")
    for u in flat:
        if u["n_models"] == 6:
            print(f"    {u['metric_id']}")
    print()
    print("  unchanged, but only 1 model ran the pack (weak evidence):")
    thin = [u["metric_id"] for u in flat if u["n_models"] < 6]
    print("    " + ", ".join(thin) if thin else "    none")
    print()

    print("-" * W)
    print("4. UNIFORM (scaffold-shaped) vs MODEL-SPECIFIC (capability-shaped)")
    print("-" * W)
    big = [u for u in res["uniformity"] if u["max_abs"] >= 0.10 and u["n_models"] >= 5]
    uniform = [u for u in big if len(u["moved"]) == u["n_models"]]
    partial = [u for u in big if 0 < len(u["moved"]) < u["n_models"]]
    print("(restricted to metrics run by >= 5 models, so 'uniform' means something)")
    print(f"metrics moving >= 10pp somewhere : {len(big)}")
    print(f"  moved in EVERY model  (uniform)      : {len(uniform)}")
    print(f"  moved in SOME models  (model-specific): {len(partial)}")
    print()
    print("  UNIFORM -- every model degrades/improves; points at scaffold + context handling:")
    for u in sorted(uniform, key=lambda u: -u["max_abs"]):
        rds = "  ".join(f"{m}={v:+.2f}" for m, v in sorted(u["rds"].items()))
        print(f"    {u['metric_id']:<28} sig in {len(u['significant'])}/{u['n_models']}")
        print(f"        {rds}")
    print()
    print("  MODEL-SPECIFIC -- moved in a strict subset; points at model capability:")
    for u in sorted(partial, key=lambda u: -u["max_abs"]):
        rds = "  ".join(f"{m}={v:+.2f}" for m, v in sorted(u["rds"].items()))
        print(f"    {u['metric_id']:<28} moved in {len(u['moved'])}/{u['n_models']}, sig in {len(u['significant'])}")
        print(f"        {rds}")
    print()

    print("-" * W)
    print("5. DISCRIMINATION among gpt-5.6 {sol, terra, luna}: does bloat wake flat gates?")
    print("-" * W)
    disc = res["discrimination"]
    cflat = [d for d in disc if d["clean_flat"]]
    bflat = [d for d in disc if d["bloat_flat"]]
    woke = [d for d in disc if d["clean_flat"] and not d["bloat_flat"]]
    slept = [d for d in disc if not d["clean_flat"] and d["bloat_flat"]]
    n = len(disc)
    print(f"metrics run by all three variants in both arms : {n}")
    print(f"  identical for all 3 on CLEAN context : {len(cflat)}/{n} ({100*len(cflat)/n:.0f}%)")
    print(f"  identical for all 3 under BLOAT      : {len(bflat)}/{n} ({100*len(bflat)/n:.0f}%)")
    agg = res["aggregate_discrimination"]
    print(f"  mean across-variant spread : clean {agg['mean_clean_range']:.4f} -> "
          f"bloat {agg['mean_bloat_range']:.4f}  ({agg['mean_bloat_range']/agg['mean_clean_range']:.2f}x)")
    print()
    print("  BATTERY-LEVEL TEST (the powered one). Per-gate permutation at k=10 cannot")
    print("  resolve a 0.10 spread; the battery-level question can. Permuting the arm")
    print("  label within each of the 54 gates and recomputing mean spread:")
    print(f"    observed delta (bloat - clean mean spread) = {agg['delta']:+.4f}")
    print(f"    one-sided permutation p = {agg['p_one_sided']:.4f}   ({agg['n_gates']} gates)")
    print(f"    gates whose flatness changed: {agg['n_woke']} woke up vs {agg['n_slept']} went flat")
    print(f"    exact sign test on that {agg['n_woke']}/{agg['n_woke']+agg['n_slept']} split: "
          f"p = {agg['sign_test_p']:.4f}")
    print()
    print(f"  WOKE UP (flat on clean, separating under bloat): {len(woke)}")
    for d in sorted(woke, key=lambda d: -d["bloat_range"]):
        bs = " ".join(f"{m.split('-')[-1]}={d['bloat_rates'][m]:.2f}" for m in GPT56)
        print(f"    {d['metric_id']:<28} spread 0.00 -> {d['bloat_range']:.2f}"
              f"  perm p={d['bloat_p']:.3f}   bloat: {bs}")
    sig_woke = [d for d in woke if d["bloat_p"] < 0.05]
    print(f"    ...of which the spread beats a label permutation at p<0.05: {len(sig_woke)}")
    for d in sig_woke:
        print(f"      {d['metric_id']} (p={d['bloat_p']:.3f})")
    print()
    print(f"  WENT FLAT (separating on clean, identical under bloat): {len(slept)}")
    for d in sorted(slept, key=lambda d: -d["clean_range"]):
        cs = " ".join(f"{m.split('-')[-1]}={d['clean_rates'][m]:.2f}" for m in GPT56)
        print(f"    {d['metric_id']:<28} spread {d['clean_range']:.2f} -> 0.00"
              f"  clean perm p={d['clean_p']:.3f}   clean: {cs}")
    print()
    csig = sum(1 for d in disc if d["clean_p"] < 0.05)
    bsig = sum(1 for d in disc if d["bloat_p"] < 0.05)
    print(f"  gates whose 3-variant spread survives permutation at p<0.05:")
    print(f"    clean {csig}/{n}   bloat {bsig}/{n}")
    for d in disc:
        if d["bloat_p"] < 0.05 or d["clean_p"] < 0.05:
            print(f"      {d['metric_id']:<28} clean p={d['clean_p']:.3f} (range {d['clean_range']:.2f})"
                  f"  bloat p={d['bloat_p']:.3f} (range {d['bloat_range']:.2f})")
    print()

    print("-" * W)
    print("6. WHAT THE BIGGEST EFFECT ACTUALLY IS (tool_integrity_tier2 failure modes)")
    print("-" * W)
    print("The -1.00 cells all come from ONE pack. Before calling that 'context rot',")
    print("read the scorer's own failure modes for those trials:")
    combos: dict[frozenset[str], int] = defaultdict(int)
    by_variant: dict[tuple[str, str], int] = defaultdict(int)
    total = 0
    for m in MODELS:
        p = _ROOT / "reports" / "bloat" / "bloat50" / f"{m}.json"
        if not p.is_file():
            continue
        rep = json.loads(p.read_text(encoding="utf-8"))
        for b in rep.get("bootstraps") or []:
            if b.get("metric_id") != "answer_matches_tool_result":
                continue
            for pt in b.get("per_trial") or []:
                raw = pt.get("raw") or {}
                fm = frozenset(raw.get("failure_modes") or [])
                if not fm:
                    continue
                combos[fm] += 1
                total += 1
                v = str(raw.get("variant") or "?")
                by_variant[(v, "answer correct but not read from disk"
                            if fm == frozenset({"ungrounded_answer"})
                            else "read/retry actually broke")] += 1
    print(f"  bloat-arm observations with a failure mode: {total}")
    for fm, c in sorted(combos.items(), key=lambda kv: -kv[1])[:8]:
        print(f"    {c:>3}  {', '.join(sorted(fm))}")
    print()
    for (v, kind), c in sorted(by_variant.items()):
        print(f"    {v:<9} {kind:<38} {c}")
    print("  Reading: on the MODERATE arm the dominant single mode is the model emitting")
    print("  the exact gold string without a successful read. That is a real behavioural")
    print("  change (it stopped grounding), but it is NOT 'the model got the answer")
    print("  wrong', and a gate that scores it 0.00 conflates the two.")
    print()

    print("-" * W)
    print("7. COST")
    print("-" * W)
    tokens = []
    for m in MODELS:
        root = _ROOT / "reports" / "repro-shared" / m
        if not root.is_dir():
            continue
        for pack_dir in sorted(root.iterdir()):
            if not pack_dir.is_dir() or "_n10" not in pack_dir.name:
                continue
            for tp in sorted(pack_dir.glob("trial_*.json")):
                try:
                    rep = json.loads(tp.read_text(encoding="utf-8"))
                except Exception:
                    continue
                for tr in rep.get("traces") or []:
                    t = (tr.get("costs") or {}).get("tokens")
                    if isinstance(t, (int, float)) and t > 0:
                        tokens.append(float(t))
    if tokens:
        s = sorted(tokens)
        med = statistics.median(s)
        print(f"clean arm, measured prompt+completion tokens per trial (n={len(s)} traces):")
        print(f"  median {med:,.0f}   mean {statistics.mean(s):,.0f}   "
              f"p90 {s[int(0.9*len(s))]:,.0f}   max {max(s):,.0f}")
    print("bloat arm: assembly dropped traces (traces=[] in every bloat50/*.json), so NO")
    print("  per-trial token counts survive. Any 'bloat cost' figure must come from the")
    print("  design target, not from measurement:")
    print("    prefix target = level x operational window, level = 0.50")
    print("    windows (src/dsm_ae/context_bloat.py _DEFAULT_WINDOWS):")
    print("      gpt-5.5 272,000 | gpt-5.6-* 372,000 | qwen3.5-397b-a17b 262,144 | qwen3.6-plus 1,000,000")
    if tokens:
        print(f"  => ~136,000 prefix tokens on gpt-5.5 vs a measured clean median of {med:,.0f}:")
        print(f"     about {136000/med:.0f}x the clean prompt, per trial, before the task is stated.")
    print()
    print("STEP-COUNT PROXY (the one behavioural cost signal in the scores):")
    for m in MODELS:
        cv = _explain_ints(m, "clean", "low_coord_churn", "n_writes")
        bv = _explain_ints(m, "bloat", "low_coord_churn", "n_writes")
        if cv and bv:
            print(f"  {m:<20} coord_tax_mini writes/trial  clean mean {statistics.mean(cv):.1f} "
                  f"(n={len(cv)})  ->  bloat {statistics.mean(bv):.1f} (n={len(bv)})")
    print()

    print("-" * W)
    print("8. SAMPLE SIZE AND WHAT IS NOT TESTED")
    print("-" * W)
    print("  k = 10 trials per pack per arm, 2 arms, 6 models, 22 packs (15 for 5 of 6 models).")
    print("  Inference unit = trial. Per model x metric that is 10-40 paired trials.")
    print("  ONE fill level (50%). No 0.8 arm was ever run, so H3 (dose-response) is untested.")
    print("  ONE fill mode at scale (real prior trajectories). The lorem-vs-trajectory")
    print("  control is k=3, one pack, one model (reports/bloat/priming_control/).")
    print("  Baseline and bloat arms were run at different times on a live proxy; drift is")
    print("  not controlled for and there is no interleaved re-run.")


def _explain_ints(model: str, arm: str, metric: str, key: str) -> list[float]:
    import re
    pat = re.compile(rf"{key}=(\d+)")
    out: list[float] = []
    if arm == "bloat":
        p = _ROOT / "reports" / "bloat" / "bloat50" / f"{model}.json"
        if not p.is_file():
            return out
        rep = json.loads(p.read_text(encoding="utf-8"))
        for b in rep.get("bootstraps") or []:
            if b.get("metric_id") != metric:
                continue
            for pt in b.get("per_trial") or []:
                mt = pat.search(pt.get("explanation") or "")
                if mt:
                    out.append(float(mt.group(1)))
        return out
    root = _ROOT / "reports" / "repro-shared" / model
    if not root.is_dir():
        return out
    for pack_dir in sorted(root.iterdir()):
        if not pack_dir.is_dir() or "_n10" not in pack_dir.name:
            continue
        for tp in sorted(pack_dir.glob("trial_*.json")):
            try:
                rep = json.loads(tp.read_text(encoding="utf-8"))
            except Exception:
                continue
            for b in rep.get("bootstraps") or []:
                if b.get("metric_id") != metric:
                    continue
                for pt in b.get("per_trial") or []:
                    mt = pat.search(pt.get("explanation") or "")
                    if mt:
                        out.append(float(mt.group(1)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    res = analyse()
    report(res)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
