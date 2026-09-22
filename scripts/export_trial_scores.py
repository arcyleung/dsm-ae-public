#!/usr/bin/env python3
"""Export per-trial gate scores so the reliability figure is reproducible.

`scripts/split_half_reliability.py` reads `reports/work/*/.dsm_ae_ckpt/`,
which is gitignored: those directories hold full trial workspaces (staged
repos, tool output, whole transcripts) and are far too heavy to publish.
The reliability statistic needs none of that. It needs one number per
(model, pack, metric, trial).

This writes exactly that to `reports/blog/trial_scores.json` -- a few
hundred KB rather than tens of gigabytes -- so anyone with a clone can
recompute Spearman-Brown without the workspaces and without Git LFS.

Excluded models are dropped here as well, so the export cannot
reintroduce them into a public artifact.

Usage:
    python3 scripts/export_trial_scores.py
    python3 scripts/split_half_reliability.py --scores reports/blog/trial_scores.json
"""

from __future__ import annotations

import collections
import glob
import json
import pathlib

OUT = pathlib.Path("reports/blog/trial_scores.json")

# Preview / non-comparable endpoints kept out of the public matrix.
EXCLUDED_MODELS = frozenset(
    {
        "gemini-3.1-pro-preview-thinking",
        "Beta_pangu_505b",
        "Beta_pangu_92b",
    }
)
# Mock personas are fixtures, not model measurements.
EXCLUDED_PREFIXES = ("mock/",)

# Transport aliases for one served model. A job resumed after the endpoint
# moved records both ids inside the same run, which would split one series
# into two short halves and drop it below the 8-trial floor. Same collapsing
# rule as `canonical_model()` in scripts/json_to_html_report.py.
_ALIAS_SUFFIXES = ("-tunnel", "-direct", "-funnel")
_ALIASES = {"Qwen3.8-27B-NVFP4-BF16-LMHead": "Qwen3.8-27B-NVFP4"}


def canonical_model(model: str) -> str:
    model = _ALIASES.get(model, model)
    for suffix in _ALIAS_SUFFIXES:
        if model.endswith(suffix):
            return model[: -len(suffix)]
    return model


def excluded(model: str | None) -> bool:
    if not model:
        return True
    if model in EXCLUDED_MODELS:
        return True
    return any(model.startswith(p) for p in EXCLUDED_PREFIXES)


def main() -> None:
    # (run, model, pack, metric) -> {trial_index: value}
    #
    # Keyed by run, not by model. The same model appears in several runs (effort
    # arms, seeded variants, re-qualification), and those are separate
    # administrations of the item. Merging them would silently average distinct
    # conditions together and change the reliability estimate.
    series: dict[tuple[str, str, str, str], dict[int, float]] = collections.defaultdict(dict)
    dropped: collections.Counter = collections.Counter()
    checkpoints = 0

    for ck in sorted(glob.glob("reports/work/*/.dsm_ae_ckpt/*.json")):
        run = ck.split("/")[2]
        try:
            doc = json.load(open(ck))
        except Exception:
            continue
        checkpoints += 1
        trial = doc.get("trial_index")
        if trial is None:
            continue
        for item in doc.get("items") or []:
            trace = item.get("trace") or {}
            model = (trace.get("scaffold_card") or {}).get("model")
            if excluded(model):
                dropped[model or "(no model id)"] += 1
                continue
            model = canonical_model(model)
            pack = item.get("pack_id")
            for score in item.get("scores") or []:
                value = score.get("value")
                if isinstance(value, (int, float)):
                    key = (run, model, pack, score.get("metric_id"))
                    series[key][int(trial)] = float(value)

    rows = [
        {
            "run": run,
            "model": model,
            "pack": pack,
            "metric": metric,
            # trials as an index->value map, so gaps stay visible
            "trials": {str(t): v for t, v in sorted(tv.items())},
        }
        for (run, model, pack, metric), tv in sorted(series.items())
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "description": (
                    "Per-trial gate scores backing the split-half reliability "
                    "figure in the blog's limitation 7. One value per "
                    "(model, pack, metric, trial)."
                ),
                "source": "reports/work/*/.dsm_ae_ckpt/ (gitignored raw workspaces)",
                "recompute": "python3 scripts/split_half_reliability.py --scores reports/blog/trial_scores.json",
                "n_series": len(rows),
                "series": rows,
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )

    total = sum(len(r["trials"]) for r in rows)
    size_kb = OUT.stat().st_size / 1024
    print(f"  checkpoints read : {checkpoints}")
    print(f"  series exported  : {len(rows)}")
    print(f"  trial values     : {total}")
    print(f"  models           : {len({r['model'] for r in rows})}")
    print(f"  wrote            : {OUT} ({size_kb:.0f} KB)")
    if dropped:
        print("  dropped (excluded models / fixtures):")
        for m, c in dropped.most_common():
            print(f"    {m}: {c} items")


if __name__ == "__main__":
    main()
