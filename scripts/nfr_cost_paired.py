#!/usr/bin/env python3
"""Non-functional cost of ill-behaviours, matched WITHIN instance_id.

`nfr_cost_analysis.py` pools every behaviour-present trial against every
behaviour-absent trial. Those two groups need not cover the same instances, so
the ratio it reports confounds "this behaviour is expensive" with "the subset of
instances where this behaviour appears is expensive".

This script removes that confound the only way the data allows: restrict to
instances that were solved BOTH with and without the behaviour, and compare
within each instance. Every comparison is then same-task, same-outcome, and the
difference is the behaviour plus whatever else varied between the two attempts.

Reports the paired median ratio (median over instances of the per-instance
ratio) with a bootstrap CI resampling instances, and dumps the instance_id list
so the blog can cite exactly which tasks the number rests on.
"""
import json
import random
import statistics
from collections import defaultdict
from pathlib import Path

from dsm_ae.harbor import iter_runs, scoreable_only
from dsm_ae.harbor.instruments import score_trajectory

random.seed(42)
KEYS = ("read_loop", "thrash_edit", "scope_creep", "destructive_command")

rows = []
for _r, ts in iter_runs(Path("evalhub-extract")):
    for t in scoreable_only(ts):
        if t.source != "swebenchpro" or t.completion_tokens <= 0:
            continue
        files = {
            (tc.get("arguments") or {}).get("filePath")
            or (tc.get("arguments") or {}).get("path")
            or ""
            for tc in t.tool_calls
        }
        rows.append(
            dict(
                ok=t.success,
                task=t.task_name,
                harness=t.harness,
                tok=t.completion_tokens,
                s=score_trajectory(t),
            )
        )

print(f"trials with token data: {len(rows)}")
print(f"harnesses: {sorted({r['harness'] for r in rows})}")

succ = [r for r in rows if r["ok"]]
print(f"successful trials: {len(succ)}")
print(f"distinct instances among successes: {len({r['task'] for r in succ})}")


def paired(key):
    """Instances solved both with and without the behaviour."""
    by = defaultdict(lambda: {"with": [], "without": []})
    for r in succ:
        by[r["task"]]["with" if r["s"][key] else "without"].append(r["tok"])
    both = {
        task: v for task, v in by.items() if v["with"] and v["without"]
    }
    return both


def boot_ci(ratios, B=5000):
    if len(ratios) < 3:
        return (None, None)
    out = []
    for _ in range(B):
        samp = [random.choice(ratios) for _ in ratios]
        out.append(statistics.median(samp))
    out.sort()
    return out[int(0.025 * B)], out[int(0.975 * B)]


summary = {}
print()
print("PAIRED WITHIN instance_id, successful trials only")
print(f"{'behaviour':22s}{'instances':>10}{'med ratio':>11}  95% CI")
for key in KEYS:
    both = paired(key)
    if not both:
        print(f"{key:22s}{0:>10}{'-':>11}")
        summary[key] = {"instances": 0, "instance_ids": []}
        continue
    ratios = []
    detail = []
    for task, v in sorted(both.items()):
        mw = statistics.median(v["with"])
        mo = statistics.median(v["without"])
        if mo > 0:
            ratios.append(mw / mo)
            detail.append(
                {
                    "instance_id": task,
                    "median_tokens_with": round(mw),
                    "median_tokens_without": round(mo),
                    "ratio": round(mw / mo, 3),
                }
            )
    med = statistics.median(ratios)
    lo, hi = boot_ci(ratios)
    ci = f"[{lo:.2f}, {hi:.2f}]" if lo else "-"
    print(f"{key:22s}{len(ratios):>10}{med:>11.2f}  {ci}")
    summary[key] = {
        "instances": len(ratios),
        "median_ratio": round(med, 3),
        "ci95": [round(lo, 3), round(hi, 3)] if lo else None,
        "n_with_behaviour_higher": sum(1 for r in ratios if r > 1.0),
        "instances_detail": detail,
    }

out = Path("reports/behaviour-task/nfr_cost_paired.json")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(f"\nwrote {out}")
