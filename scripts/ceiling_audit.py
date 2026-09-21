#!/usr/bin/env python3
"""Classify every gate as ceiling / floor / live across a set of full-suite runs.

Blog §4.4 reports that 81% of gates return an identical value for the three
gpt-5.6 variants at k=20. That number is true but ambiguous: a gate can be flat
because it cannot resolve a real difference, or because every model passes it.
Those are different defects with different fixes.

This script separates them. A gate is:

  ceiling   every run scores >= 1 - eps   (the item is too easy to fail)
  floor     every run scores <= eps       (the item is too hard to pass)
  flat      identical but not at a bound  (genuinely unable to resolve)
  live      the gate takes different values across runs

The distinction matters because a ceilinged gate is flat with probability ~1
whether or not the models differ, so counting it as evidence of poor resolution
is a category error — and any statistic that rewards "gate moved off 1.00"
(see the §2.3 sign test) is measuring difficulty, not discrimination.

Usage
-----
    python3 scripts/ceiling_audit.py \
        --runs reports/full-suite/gpt-5.6-terra-max-full.json \
               reports/full-suite/gpt-5.6-sol-max-full.json \
               reports/full-suite/gpt-5.6-luna-max-full.json \
        --out reports/ceiling/audit.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

EPS = 1e-3


def gate_to_pack() -> dict[str, str]:
    """Map metric_id -> pack_id from the live registry.

    The full-suite JSON records a flat `bootstraps` list and a bare `packs`
    name list, with no join between them, so the association is recovered from
    each pack's declared `dimensions`.
    """
    try:
        from dsm_ae.packs.registry import get_pack, list_packs
    except Exception:  # registry unavailable -> degrade to unattributed
        return {}
    out: dict[str, str] = {}
    for name in list_packs():
        try:
            pack = get_pack(name) if isinstance(name, str) else name
            for dim in getattr(pack, "dimensions", []) or []:
                key = getattr(dim, "metric_id", None) or getattr(dim, "id", None) or dim
                if isinstance(key, str):
                    out.setdefault(key, getattr(pack, "id", str(name)))
        except Exception:
            continue
    return out


def load_run(path: Path) -> tuple[str, dict[str, float], int]:
    """Return (model, {gate: pass_rate}, k)."""
    d = json.loads(path.read_text(encoding="utf-8"))
    model = (d.get("scaffold_card") or {}).get("model") or path.stem
    rates = {}
    for b in d.get("bootstraps") or []:
        mid = b.get("metric_id")
        if mid is None:
            continue
        rates[mid] = float(b.get("pass_rate", 0.0))
    return model, rates, int(d.get("k_trials") or 0)


def classify(vals: list[float]) -> str:
    spread = max(vals) - min(vals)
    if spread > EPS:
        return "live"
    if min(vals) >= 1.0 - EPS:
        return "ceiling"
    if max(vals) <= EPS:
        return "floor"
    return "flat"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", nargs="+", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("reports/ceiling/audit.json"))
    args = ap.parse_args()

    runs, ks = {}, {}
    packs_by_gate = gate_to_pack()
    for p in args.runs:
        if not p.is_file():
            print(f"missing run: {p}")
            return 1
        model, rates, k = load_run(p)
        runs[model] = rates
        ks[model] = k
        print(f"{p.name}: model={model} gates={len(rates)} k={k}")
    if not packs_by_gate:
        print("warning: pack registry unavailable; pack attribution skipped")

    if len(runs) < 2:
        print("need at least two runs to classify")
        return 1

    common = sorted(set.intersection(*[set(v) for v in runs.values()]))
    print(f"\ncommon gates: {len(common)}  (k: {sorted(set(ks.values()))})")

    states: dict[str, str] = {}
    detail = []
    for g in common:
        vals = [runs[m][g] for m in runs]
        st = classify(vals)
        states[g] = st
        detail.append(
            {
                "gate": g,
                "pack": packs_by_gate.get(g, ""),
                "state": st,
                "spread": round(max(vals) - min(vals), 4),
                "values": {m: round(runs[m][g], 4) for m in runs},
            }
        )

    counts = Counter(states.values())
    n = len(common)
    flat_total = n - counts["live"]
    print(f"\nceiling={counts['ceiling']}  floor={counts['floor']}  "
          f"flat(other)={counts['flat']}  LIVE={counts['live']}")
    print(f"flat = {flat_total}/{n} = {100 * flat_total / n:.1f}%")
    if flat_total:
        print(f"of the flat gates, {100 * counts['ceiling'] / flat_total:.1f}% "
              f"are at CEILING (every model passes)")

    live = sorted(
        (d for d in detail if d["state"] == "live"),
        key=lambda d: -d["spread"],
    )
    print("\nlive gates by spread:")
    for d in live[:15]:
        print(f"  {d['spread']:.3f}  {d['gate']}")

    by_pack = defaultdict(Counter)
    for d in detail:
        by_pack[d["pack"] or "?"][d["state"]] += 1
    live_packs = [p for p, c in by_pack.items() if c["live"]]
    print(f"\npacks containing >=1 live gate: {len(live_packs)} of {len(by_pack)}")

    out = {
        "runs": {m: {"k": ks[m]} for m in runs},
        "n_common_gates": n,
        "counts": dict(counts),
        "flat_total": flat_total,
        "flat_pct": round(100 * flat_total / n, 2),
        "ceiling_share_of_flat": (
            round(100 * counts["ceiling"] / flat_total, 2) if flat_total else None
        ),
        "live_packs": sorted(live_packs),
        "n_packs": len(by_pack),
        "gates": detail,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")

    # The §4.2 abandon trigger, evaluated rather than asserted.
    if counts["live"] < 10 and len(live_packs) < 4:
        print("\nABANDON TRIGGER MET: fewer than 10 live gates across fewer than "
              "4 packs. The battery is a narrow instrument at this difficulty.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
