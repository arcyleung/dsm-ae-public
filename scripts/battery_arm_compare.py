#!/usr/bin/env python3
"""E3 outcome: gates moved off ceiling, by arm and model.

    python3 scripts/battery_arm_compare.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CEILING = 0.99
OFF = 0.90

DEFAULT_ARMS = {
    "sol-none": Path("reports/full-suite/gpt-5.6-sol-max-full.json"),
    "sol-traj": Path("reports/bloat/bloat50/gpt-5.6-sol.json"),
    "sol-lorem": Path("reports/arms/e3-sol-lorem.json"),
    "qwen-none": Path("reports/arms/e3-qwen-none.json"),
    "qwen-lorem": Path("reports/arms/e3-qwen-lorem.json"),
    "qwen-traj": Path("reports/arms/e3-qwen-traj.json"),
}


def rates(path: Path) -> dict[str, float]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return {b["metric_id"]: float(b.get("pass_rate", 0.0)) for b in d.get("bootstraps") or []}


def off_ceiling(control: dict[str, float], treat: dict[str, float]) -> list[dict]:
    out = []
    for g, c in control.items():
        if g not in treat:
            continue
        t = treat[g]
        if c >= CEILING and t <= OFF:
            out.append({"gate": g, "control": round(c, 3), "treat": round(t, 3), "delta": round(t - c, 3)})
    return sorted(out, key=lambda r: r["delta"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("reports/arms/compare.json"))
    args = ap.parse_args()

    loaded = {name: rates(p) for name, p in DEFAULT_ARMS.items() if p.is_file()}
    missing = [name for name, p in DEFAULT_ARMS.items() if not p.is_file()]
    print("loaded:", sorted(loaded))
    if missing:
        print("missing (not yet finished):", missing)

    pairs = []
    if "sol-none" in loaded and "sol-traj" in loaded:
        pairs.append(("sol", "none→traj", "sol-none", "sol-traj"))
    if "sol-none" in loaded and "sol-lorem" in loaded:
        pairs.append(("sol", "none→lorem", "sol-none", "sol-lorem"))
    if "qwen-none" in loaded and "qwen-traj" in loaded:
        pairs.append(("qwen", "none→traj", "qwen-none", "qwen-traj"))
    if "qwen-none" in loaded and "qwen-lorem" in loaded:
        pairs.append(("qwen", "none→lorem", "qwen-none", "qwen-lorem"))

    result = {"missing": missing, "pairs": []}
    for model, label, a, b in pairs:
        moved = off_ceiling(loaded[a], loaded[b])
        common = set(loaded[a]) & set(loaded[b])
        print(f"\n{model} {label}: {len(moved)} / {len(common)} gates left the ceiling")
        for r in moved[:20]:
            print(f"  {r['delta']:+.2f}  {r['gate']:36s} {r['control']:.2f} → {r['treat']:.2f}")
        result["pairs"].append({
            "model": model,
            "contrast": label,
            "n_common": len(common),
            "n_off_ceiling": len(moved),
            "gates": moved,
        })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
