#!/usr/bin/env python3
"""E4 — how many gates separate Qwen3.8-27B from the gpt-5.6 centroid.

Uses already-run reports. No new model calls.

    python3 scripts/e4_qwen_anchor.py
"""

from __future__ import annotations

import json
from pathlib import Path

CEILING = 1.0 - 1e-3
GPT = [
    Path("reports/full-suite/gpt-5.6-terra-max-full.json"),
    Path("reports/full-suite/gpt-5.6-sol-max-full.json"),
    Path("reports/full-suite/gpt-5.6-luna-max-full.json"),
]
QWEN = Path("reports/queue/full-qwen38-27b-nvfp4-dd08460f.json")
REV2_QWEN = Path("reports/requalify/qwen27b_anchor.json")
REV2_ARMS = Path("reports/requalify/rev2_arms.json")


def rates(path: Path) -> dict[str, float]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return {b["metric_id"]: float(b.get("pass_rate", 0.0)) for b in d.get("bootstraps") or []}


def main() -> int:
    if not QWEN.is_file():
        print(f"missing Qwen suite: {QWEN}")
        return 1
    missing = [p for p in GPT if not p.is_file()]
    if missing:
        print(f"missing gpt-5.6 suites: {missing}")
        return 1

    gpt = [rates(p) for p in GPT]
    qwen = rates(QWEN)
    common = sorted(set(qwen) & set.intersection(*(set(g) for g in gpt)))
    centroid = {g: sum(arm[g] for arm in gpt) / 3.0 for g in common}

    sep = []
    for g in common:
        gpt_vals = [arm[g] for arm in gpt]
        gpt_flat = max(gpt_vals) - min(gpt_vals) < 1e-9
        delta = abs(qwen[g] - centroid[g])
        # "separates" = Qwen differs from the three-variant centroid by ≥0.10
        # or leaves a gpt-5.6 ceiling.
        left_ceiling = all(v >= CEILING for v in gpt_vals) and qwen[g] < CEILING
        moved = delta >= 0.10
        if left_ceiling or moved:
            sep.append({
                "gate": g,
                "qwen": round(qwen[g], 3),
                "gpt_centroid": round(centroid[g], 3),
                "gpt_vals": [round(v, 3) for v in gpt_vals],
                "delta": round(delta, 3),
                "left_gpt_ceiling": left_ceiling,
                "gpt_flat": gpt_flat,
            })

    print(f"Qwen suite: {QWEN}  ({len(qwen)} gates)")
    print(f"gpt-5.6 suites: {[p.name for p in GPT]}")
    print(f"common gates: {len(common)}  (E4 abandon trigger is <15 of 94)")
    print(f"gates that separate Qwen from gpt-5.6 centroid (|Δ|≥0.10 or left ceiling): {len(sep)}")
    for r in sorted(sep, key=lambda x: -x["delta"])[:40]:
        flag = " CEILING→live" if r["left_gpt_ceiling"] else ""
        print(f"  {r['delta']:.2f}  {r['gate']:36s} qwen={r['qwen']:.2f}  "
              f"gpt={r['gpt_centroid']:.2f} {r['gpt_vals']}{flag}")

    # rev2-only Qwen arm
    rev2_note = "no rev2 qwen file"
    if REV2_QWEN.is_file():
        d = json.loads(REV2_QWEN.read_text(encoding="utf-8"))
        qg = d.get("qwen_gates") or {}
        below = [k for k, v in qg.items() if float(v.get("pass_rate", 1.0)) < CEILING]
        at = [k for k, v in qg.items() if float(v.get("pass_rate", 1.0)) >= CEILING]
        rev2_note = (
            f"rev2 Qwen arm {d.get('qwen_arm')}: {len(qg)} gates, "
            f"{len(below)} below ceiling, {len(at)} at ceiling"
        )
        print(f"\n{rev2_note}")
        print(f"  below: {sorted(below)}")
        print(f"  at ceiling: {sorted(at)}")

    out = {
        "n_common": len(common),
        "n_separate": len(sep),
        "abandon_trigger": "<15 of 94",
        "trigger_fires": len(sep) < 15,
        "separating": sep,
        "rev2_qwen": rev2_note,
    }
    dest = Path("reports/requalify/e4_qwen_vs_gpt56.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {dest}")
    print(
        "E4 verdict: "
        + ("ABANDON trigger would fire" if out["trigger_fires"]
           else f"does not fire — {len(sep)} gates separate Qwen from the gpt-5.6 centroid")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
