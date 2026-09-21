#!/usr/bin/env python3
"""Enqueue E3 arms: none / lorem / trajectory on gpt-5.6-sol and Qwen3.8-27B-NVFP4.

Reuses existing sol A-none (k=20 full-suite) and sol A-traj (bloat50).
New jobs:
  e3-sol-lorem      context_bloat 50% fill_mode=lorem
  e3-qwen-none      clean context
  e3-qwen-lorem     context_bloat 50% fill_mode=lorem
  e3-qwen-traj      context_bloat 50% fill_mode=trajectory

Usage
-----
    python3 scripts/enqueue_e3.py
    python3 scripts/enqueue_e3.py --dry-run
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dsm_ae.queue.progress import progress_path_for, write_progress
from dsm_ae.queue.store import JobStore

# Same 24 packs as reports/full-suite/gpt-5.6-sol-max-full.json
PACKS = [
    "clarify_verify",
    "coord_tax_mini",
    "erosion_tier2",
    "erosion_tier3",
    "eval_gaming_mini",
    "gate_discipline",
    "handoff_mini",
    "hello_metacog",
    "injection_mini",
    "loop_control",
    "mas_verify_mini",
    "memory_context",
    "nfr_omit",
    "overeager_mini",
    "pii_safety",
    "recency_bias_mini",
    "role_confusion_mini",
    "sandbag_mini",
    "session_overwrite_mini",
    "slop_indicator",
    "sycophancy_mini",
    "tool_integrity",
    "tool_integrity_tier2",
]

ARMS = (
    {
        "label": "e3-sol-lorem",
        "model": "gpt-5.6-sol",
        "concurrency": 2,
        "rpm": 6.0,
        "extra": {"context_bloat": {"level": 0.5, "fill_mode": "lorem", "seed": 42}},
    },
    {
        "label": "e3-qwen-none",
        "model": "Qwen3.8-27B-NVFP4",
        "concurrency": 48,
        "rpm": 48.0,
        "extra": None,
    },
    {
        "label": "e3-qwen-lorem",
        "model": "Qwen3.8-27B-NVFP4",
        "concurrency": 48,
        "rpm": 48.0,
        "extra": {"context_bloat": {"level": 0.5, "fill_mode": "lorem", "seed": 42}},
    },
    {
        "label": "e3-qwen-traj",
        "model": "Qwen3.8-27B-NVFP4",
        "concurrency": 48,
        "rpm": 48.0,
        "extra": {"context_bloat": {"level": 0.5, "fill_mode": "trajectory", "seed": 42}},
    },
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--db", type=Path, default=Path("data/queue.db"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    print(f"E3 packs: {len(PACKS)}  k={args.k}  new jobs: {len(ARMS)}")
    print("reuse: sol A-none = reports/full-suite/gpt-5.6-sol-max-full.json")
    print("reuse: sol A-traj = reports/bloat/bloat50/gpt-5.6-sol.json")
    if args.dry_run:
        for arm in ARMS:
            print(f"  would enqueue {arm['label']:16s} {arm['model']}")
        return 0

    store = JobStore(args.db)
    reports = Path("reports")
    for arm in ARMS:
        out_json = reports / "arms" / f"{arm['label']}.json"
        out_md = reports / "arms" / f"{arm['label']}.md"
        work = reports / "arms" / "work" / arm["label"]
        work.mkdir(parents=True, exist_ok=True)
        jid = store.enqueue(
            model=arm["model"],
            packs=PACKS,
            k=args.k,
            concurrency=arm["concurrency"],
            rpm=arm["rpm"],
            label=arm["label"],
            extra=arm["extra"],
            out_json=str(out_json),
            out_md=str(out_md),
            work_dir=str(work),
            max_attempts=2,
        )
        prog = progress_path_for(reports, jid)
        store.update_paths(jid, progress_path=str(prog))
        write_progress(
            prog,
            {
                "job_id": jid,
                "model": arm["model"],
                "phase": "queued",
                "status": "queued",
                "done": 0,
                "total": 0,
                "message": f"E3 {arm['label']} queued",
                "k": args.k,
                "packs": PACKS,
            },
        )
        print(f"enqueued {jid}  {arm['label']:16s} {arm['model']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
