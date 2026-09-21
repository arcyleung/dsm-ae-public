#!/usr/bin/env python3
"""Enqueue bloated-context 50% jobs: 4 models × all packs, k=10, separate reports/bloat/."""
from __future__ import annotations

import argparse
from pathlib import Path

from dsm_ae.packs.registry import list_packs
from dsm_ae.queue.store import JobStore


MODELS = ["gpt-5.5", "gpt-5.6-sol", "qwen3.5-397b-a17b", "qwen3.6-plus"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("data/queue.db"))
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--level", type=float, default=0.5)
    ap.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Per-job pack×trial concurrency (default 8)",
    )
    ap.add_argument(
        "--models",
        default=None,
        help="Comma models (default: gpt-5.5,gpt-5.6-sol,qwen3.5-397b-a17b,qwen3.6-plus)",
    )
    ap.add_argument(
        "--label-suffix",
        default="",
        help="Optional label suffix e.g. -v2-codex-window",
    )
    ap.add_argument(
        "--packs",
        default=None,
        help="Comma packs (default: all registered)",
    )
    args = ap.parse_args()

    packs = (
        [p.strip() for p in args.packs.split(",") if p.strip()]
        if args.packs
        else list_packs()
    )
    models = (
        [m.strip() for m in args.models.split(",") if m.strip()]
        if args.models
        else list(MODELS)
    )
    store = JobStore(args.db)
    level = args.level
    tag = f"bloat{int(round(level * 100))}"
    bloat_root = args.reports_dir / "bloat" / tag
    bloat_root.mkdir(parents=True, exist_ok=True)
    (bloat_root / "work").mkdir(parents=True, exist_ok=True)
    suffix = args.label_suffix or ""

    ids = []
    for model in models:
        # One job per model with all packs (worker runs diagnose with full pack list)
        jid = store.enqueue(
            model=model,
            packs=packs,
            k=args.k,
            concurrency=args.concurrency,
            rpm=None,  # from models.yaml
            priority=10,
            label=f"{tag}-{model}{suffix}",
            out_md=str(bloat_root / f"{model}.md"),
            out_json=str(bloat_root / f"{model}.json"),
            work_dir=str(bloat_root / "work" / model.replace("/", "_")),
            extra={
                "context_bloat": {
                    "level": level,
                    "model": model,
                    "token_method": "char4",
                    "seed": 42,
                    "overflow_is_fail": True,
                    # Fill % of operational path window from models.yaml
                    # (Codex catalog for GPT via CLIProxy — not API 1.05M).
                }
            },
        )
        ids.append((model, jid))
        print(
            f"enqueued {model} -> {jid[:8]} packs={len(packs)} k={args.k} "
            f"level={level} concurrency={args.concurrency}"
        )

    print(f"Results under {bloat_root}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
