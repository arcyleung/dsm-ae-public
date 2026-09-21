#!/usr/bin/env python3
"""Re-qualify ceiling-skipped packs against weaker conditions.

`scripts/ceiling_audit.py` found 75 of 94 gates at ceiling across the three
k=20 gpt-5.6 runs, and 18 packs ceilinged on every gate they own. Those packs
are skipped by default (`dsm_ae.packs.registry.CEILING_SKIPPED`).

A ceiling measured against one model family is not proof the item is trivial.
It may only be trivial *for that family at that reasoning effort*. This script
tests that directly by re-running the skipped packs under conditions where a
model has less capacity to spend:

  * a smaller model    -- Qwen3.8-27B-NVFP4-BF16-LMHead (27B, open weights)
  * lower effort       -- reasoning_effort none / low, against the medium default
  * standard mode      -- reasoning.mode=standard rather than extended thinking

A gate that still passes 20/20 for a 27B model at effort=none is genuinely
undemanding and should stay skipped. A gate that drops below ceiling was
measuring something real all along, and belongs back in the default battery.

The verdict is per gate, not per pack, because a pack can own one informative
gate and five saturated ones.

Usage
-----
    # what would run, and at what cost
    python3 scripts/requalify_ceiling_packs.py --plan

    # enqueue the arms (writes jobs; the queue worker executes them)
    python3 scripts/requalify_ceiling_packs.py --enqueue --k 10

    # once runs land, decide which gates leave the skip list
    python3 scripts/requalify_ceiling_packs.py --verdict \
        --baseline reports/full-suite/gpt-5.6-terra-max-full.json \
        --arms reports/requalify/*.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dsm_ae.packs.registry import CEILING_SKIPPED, PACKS

# Arms are (label, model, reasoning_effort, concurrency). `None` effort means
# "send no reasoning_effort at all", i.e. the deployment default.
#
# Concurrency differs by endpoint, not by arm: the gpt-5.6 models share one
# rate-limited deployment, Qwen has its own.
GPT_CONCURRENCY = 16
QWEN_CONCURRENCY = 32

ARMS: tuple[tuple[str, str, str | None, int], ...] = (
    ("qwen27b-default", "Qwen3.8-27B-NVFP4-BF16-LMHead", None, QWEN_CONCURRENCY),
    ("qwen27b-none", "Qwen3.8-27B-NVFP4-BF16-LMHead", "none", QWEN_CONCURRENCY),
    ("sol-none", "gpt-5.6-sol", "none", GPT_CONCURRENCY),
    ("sol-low", "gpt-5.6-sol", "low", GPT_CONCURRENCY),
)

CEILING = 1.0 - 1e-3


def skipped_packs() -> list[str]:
    return sorted(p for p in CEILING_SKIPPED if p in PACKS)


def rev2_packs() -> list[str]:
    """Seeded rev2 variants of packs whose rev1 gates saturate.

    A k=3 pilot on gpt-5.6-sol at reasoning_effort=none found rev1
    (recency_bias_mini, memory_context, gate_discipline) at 1.000 on all 14
    gates, while the rev2 variants put four gates below ceiling:
    all_deletes_gated 0.00, chose_validated_not_newest 0.00,
    recalled_without_reread 0.00, consulted_new_regime_docs 0.50.
    Seeding, not reasoning effort, is what makes these items bind.
    """
    return sorted(p for p in PACKS if p.endswith("_rev2"))


def cmd_plan(args: argparse.Namespace) -> int:
    packs = skipped_packs()
    print(f"ceiling-skipped packs: {len(packs)}")
    for p in packs:
        print(f"  {p:26s} {PACKS[p].name}")
    print(f"\narms ({len(ARMS)}):")
    for label, model, eff, conc in ARMS:
        print(f"  {label:18s} model={model:34s} "
              f"effort={(eff or '(deployment default)'):22s} concurrency={conc}")
    total = len(packs) * len(ARMS) * args.k
    print(f"\ntrials = {len(packs)} packs x {len(ARMS)} arms x k={args.k} = {total}")
    print(f"\ngpt-5.6 arms run at concurrency {GPT_CONCURRENCY} on the shared endpoint; "
          f"Qwen at {QWEN_CONCURRENCY} on its own, so the two families can overlap.")
    return 0


def cmd_enqueue(args: argparse.Namespace) -> int:
    from dsm_ae.queue.store import JobStore

    packs = skipped_packs()
    store = JobStore(args.db)
    ids = []
    for label, model, eff, conc in ARMS:
        # Whatever survives in `extra` is forwarded verbatim to LiteLLM as
        # client params (dsm_ae/queue/worker.py: `client_extra = extra or None`),
        # so only real API kwargs may go here. The arm name is carried by
        # `label` instead.
        extra: dict[str, object] = {}
        if eff is not None:
            extra["reasoning_effort"] = eff
        jid = store.enqueue(
            model=model,
            packs=packs,
            k=args.k,
            concurrency=args.concurrency or conc,
            rpm=None,
            priority=args.priority,
            label=f"requalify:{label}",
            extra=extra or None,
        )
        ids.append((label, jid))
        print(f"enqueued {jid}  arm={label} model={model} effort={eff} "
              f"packs={len(packs)} concurrency={args.concurrency or conc}")
    print(f"\n{len(ids)} jobs enqueued against {args.db}")
    print("Run the worker, then re-run this script with --verdict.")
    return 0


def _rates(path: Path) -> dict[str, float]:
    d = json.loads(path.read_text(encoding="utf-8"))
    return {b["metric_id"]: float(b.get("pass_rate", 0.0)) for b in d.get("bootstraps") or []}


def cmd_verdict(args: argparse.Namespace) -> int:
    if not args.baseline.is_file():
        print(f"missing baseline: {args.baseline}")
        return 1
    base = _rates(args.baseline)
    arms = {p.stem: _rates(p) for p in args.arms if p.is_file()}
    if not arms:
        print("no arm reports found")
        return 1

    print(f"baseline gates: {len(base)}   arms: {list(arms)}")
    # Only gates that were AT ceiling in the baseline are on trial here.
    on_trial = sorted(g for g, v in base.items() if v >= CEILING)
    print(f"gates at ceiling in baseline: {len(on_trial)}\n")

    rows = []
    for g in on_trial:
        vals = {a: r.get(g) for a, r in arms.items() if g in r}
        if not vals:
            continue
        lo = min(vals.values())
        left = lo < CEILING
        rows.append({
            "gate": g,
            "baseline": 1.0,
            "arms": {a: round(v, 4) for a, v in vals.items()},
            "min_arm": round(lo, 4),
            "left_ceiling": left,
        })

    freed = [r for r in rows if r["left_ceiling"]]
    stuck = [r for r in rows if not r["left_ceiling"]]
    print(f"LEFT CEILING (re-qualify, remove from skip list): {len(freed)}")
    for r in sorted(freed, key=lambda r: r["min_arm"])[:40]:
        detail = "  ".join(f"{a}={v}" for a, v in r["arms"].items())
        print(f"  {r['min_arm']:.3f}  {r['gate']:38s} {detail}")
    print(f"\nSTILL AT CEILING (genuinely undemanding, keep skipped): {len(stuck)}")

    out = {
        "baseline": str(args.baseline),
        "arms": sorted(arms),
        "n_on_trial": len(on_trial),
        "n_left_ceiling": len(freed),
        "n_still_ceiling": len(stuck),
        "gates": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")

    if freed:
        print("\nInterpretation: these gates were not trivial, only unchallenged by "
              "gpt-5.6. Remove them from CEILING_SKIPPED.")
    else:
        print("\nInterpretation: no skipped gate responded even to a 27B model at "
              "effort=none. The items are undemanding, not merely easy for one family.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true", help="show the run matrix and exit")
    ap.add_argument("--enqueue", action="store_true", help="enqueue the arms")
    ap.add_argument("--verdict", action="store_true", help="decide which gates re-qualify")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument(
        "--concurrency",
        type=int,
        default=0,
        help="Override per-arm concurrency (0 = per-endpoint default: "
        f"{GPT_CONCURRENCY} gpt-5.6, {QWEN_CONCURRENCY} Qwen)",
    )
    ap.add_argument("--priority", type=int, default=0)
    ap.add_argument("--db", type=Path, default=Path("data/queue.db"))
    ap.add_argument("--baseline", type=Path,
                    default=Path("reports/full-suite/gpt-5.6-terra-max-full.json"))
    ap.add_argument("--arms", nargs="*", type=Path, default=[])
    ap.add_argument("--out", type=Path, default=Path("reports/requalify/verdict.json"))
    args = ap.parse_args()

    if args.enqueue:
        return cmd_enqueue(args)
    if args.verdict:
        return cmd_verdict(args)
    return cmd_plan(args)


if __name__ == "__main__":
    raise SystemExit(main())
