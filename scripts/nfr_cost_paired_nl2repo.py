#!/usr/bin/env python3
"""Paired within-instance cost of ill-behaviours on NL2Repo-Bench.

The SWE-bench-Pro version of this question (`nfr_cost_paired.py`) is
unanswerable: only one of the two archived harnesses records completion tokens,
and within that harness 654 of 661 instances were attempted exactly once, so
there is nothing to pair.

The NL2Repo corpus does support it. 109 instances carry token data across
multiple runs, giving 81-101 instances per behaviour that were attempted BOTH
with and without it. Comparing within an instance removes the "this behaviour
appears on harder tasks" confound that the pooled SWE-bench-Pro comparison
cannot address.

Two controls matter here and are reported separately:

1. **Harness.** Three harnesses are present (claude-code, opencode,
   openhands-sdk) and they differ in verbosity, which is an Axis V violation if
   pooled. `--same-harness` restricts every pair to one harness.

2. **Outcome.** NL2Repo reward is the *fraction* of oracle tests passing, so
   binarising at 1.0 keeps only 37 of 578 trials (blog section 2.8). Instead of
   conditioning on success, this bins by reward and reports the token ratio
   within reward-matched pairs, so "same outcome" means "comparable reward"
   rather than "both scored exactly 1.0".

Outputs the paired median ratio with a bootstrap CI resampling instances, plus
the instance_id list behind each number.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

from dsm_ae.harbor import iter_runs, scoreable_only
from dsm_ae.harbor.instruments import score_trajectory

KEYS = ("read_loop", "thrash_edit", "scope_creep", "destructive_command")


def load(root: Path) -> list[dict]:
    rows = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or "nl2repo" not in d.name:
            continue
        for _r, ts in iter_runs(d):
            for t in scoreable_only(ts):
                if t.completion_tokens <= 0 or t.reward is None:
                    continue
                rows.append(
                    dict(
                        task=t.task_name,
                        harness=t.harness,
                        tok=t.completion_tokens,
                        reward=float(t.reward),
                        run=d.name,
                        s=score_trajectory(t),
                    )
                )
    return rows


def boot_ci(vals: list[float], B: int = 5000, seed: int = 42):
    if len(vals) < 3:
        return None, None
    rng = random.Random(seed)
    out = []
    for _ in range(B):
        out.append(statistics.median([rng.choice(vals) for _ in vals]))
    out.sort()
    return out[int(0.025 * B)], out[int(0.975 * B)]


def analyse(rows, key, same_harness: bool, reward_tol: float):
    """Median within-instance token ratio (behaviour present / absent)."""
    by = defaultdict(list)
    for r in rows:
        by[r["task"]].append(r)

    ratios, detail = [], []
    for task, trials in sorted(by.items()):
        groups = defaultdict(lambda: {"w": [], "o": []})
        for r in trials:
            gk = r["harness"] if same_harness else "_all"
            groups[gk]["w" if r["s"][key] else "o"].append(r)

        for gk, g in groups.items():
            if not (g["w"] and g["o"]):
                continue
            # reward-matched: keep pairs whose reward is within tol
            pairs = [
                (a, b)
                for a in g["w"]
                for b in g["o"]
                if abs(a["reward"] - b["reward"]) <= reward_tol
            ]
            if not pairs:
                continue
            mw = statistics.median([a["tok"] for a, _ in pairs])
            mo = statistics.median([b["tok"] for _, b in pairs])
            if mo <= 0:
                continue
            ratios.append(mw / mo)
            detail.append(
                {
                    "instance_id": task,
                    "harness": gk,
                    "n_pairs": len(pairs),
                    "median_tokens_with": round(mw),
                    "median_tokens_without": round(mo),
                    "ratio": round(mw / mo, 3),
                }
            )
    return ratios, detail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("evalhub-extract"))
    ap.add_argument(
        "--reward-tol",
        type=float,
        default=0.10,
        help="max reward difference for a pair to count as same-outcome",
    )
    ap.add_argument("--out", type=Path,
                    default=Path("reports/behaviour-task/nfr_cost_paired_nl2repo.json"))
    args = ap.parse_args()

    rows = load(args.root)
    print(f"NL2Repo trials with token data : {len(rows)}")
    print(f"distinct instances             : {len({r['task'] for r in rows})}")
    print(f"harnesses                      : {sorted({r['harness'] for r in rows})}")
    print(f"reward-matched tolerance       : +/-{args.reward_tol}")

    summary = {
        "trials": len(rows),
        "instances": len({r["task"] for r in rows}),
        "harnesses": sorted({r["harness"] for r in rows}),
        "reward_tol": args.reward_tol,
        "behaviours": {},
    }

    for label, same in (("POOLED HARNESS", False), ("SAME HARNESS ONLY", True)):
        print(f"\n{label}  (paired within instance_id, reward-matched)")
        print(f"{'behaviour':22s}{'instances':>10}{'med ratio':>11}  95% CI")
        for key in KEYS:
            ratios, detail = analyse(rows, key, same, args.reward_tol)
            if not ratios:
                print(f"{key:22s}{0:>10}{'-':>11}")
                continue
            med = statistics.median(ratios)
            lo, hi = boot_ci(ratios)
            ci = f"[{lo:.2f}, {hi:.2f}]" if lo else "-"
            up = sum(1 for r in ratios if r > 1.0)
            print(f"{key:22s}{len(ratios):>10}{med:>11.2f}  {ci}"
                  f"   ({up}/{len(ratios)} instances costlier with)")
            summary["behaviours"].setdefault(key, {})[
                "same_harness" if same else "pooled"
            ] = {
                "instances": len(ratios),
                "median_ratio": round(med, 3),
                "ci95": [round(lo, 3), round(hi, 3)] if lo else None,
                "n_instances_costlier_with": up,
                "detail": detail,
            }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
