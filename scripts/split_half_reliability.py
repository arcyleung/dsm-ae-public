#!/usr/bin/env python3
"""Split-half reliability of gate pass rates.

Limitation 7 used to say we had no reliability figure for syndrome PRESENT.
We do have the data: every trial checkpoint under
`reports/work/<run>/.dsm_ae_ckpt/<pack>__t<i>.json` stores the per-trial
`scores` list, so a gate's k trials can be split into two halves and
correlated without re-running anything.

Method
------
For each (run, pack, metric) series with >= 8 trials, split trials into
even- and odd-indexed halves, take each half's mean, then correlate the
halves across series and apply the Spearman-Brown correction for the fact
that each half is only k/2 long.

Reporting the headline number alone would overstate the result. Most gates
sit at ceiling (see 3.2), and a gate that reads 1.00 in both halves
correlates perfectly while carrying no information, so this also reports
the figure with degenerate (all-1.00 / all-0.00) series removed. That
restricted number is the one worth quoting.

Usage:
    python3 scripts/split_half_reliability.py
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import statistics


def pearson(xs: list[float], ys: list[float]) -> float:
    mx, my = statistics.mean(xs), statistics.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = sum((a - mx) ** 2 for a in xs) ** 0.5
    dy = sum((b - my) ** 2 for b in ys) ** 0.5
    return num / (dx * dy) if dx and dy else float("nan")


def collect_from_export(path: str) -> dict[tuple[str, str, str], dict[int, float]]:
    """Read the published excerpt (reports/blog/trial_scores.json)."""
    doc = json.load(open(path))
    data: dict[tuple[str, str, str], dict[int, float]] = {}
    for row in doc.get("series") or []:
        key = (row.get("run", ""), row["model"], row["pack"], row["metric"])
        data[key] = {int(t): float(v) for t, v in (row.get("trials") or {}).items()}
    return data


def collect() -> dict[tuple[str, str, str], dict[int, float]]:
    data: dict[tuple[str, str, str], dict[int, float]] = collections.defaultdict(dict)
    for ck in glob.glob("reports/work/*/.dsm_ae_ckpt/*.json"):
        run = ck.split("/")[2]
        try:
            d = json.load(open(ck))
        except Exception:
            continue
        trial = d.get("trial_index")
        for item in d.get("items") or []:
            pack = item.get("pack_id")
            for score in item.get("scores") or []:
                v = score.get("value")
                if isinstance(v, (int, float)):
                    data[(run, pack, score.get("metric_id"))][trial] = float(v)
    return data


def split_half(data, keep) -> tuple[int, float, float]:
    a: list[float] = []
    b: list[float] = []
    for _key, tv in data.items():
        if len(tv) < 8:
            continue
        if not keep(list(tv.values())):
            continue
        even = [v for t, v in sorted(tv.items()) if t % 2 == 0]
        odd = [v for t, v in sorted(tv.items()) if t % 2 == 1]
        if len(even) >= 3 and len(odd) >= 3:
            a.append(statistics.mean(even))
            b.append(statistics.mean(odd))
    if len(a) < 5:
        return len(a), float("nan"), float("nan")
    r = pearson(a, b)
    return len(a), r, 2 * r / (1 + r)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--scores",
        metavar="PATH",
        default=None,
        help="read the published excerpt instead of the raw checkpoints "
        "(default: reports/blog/trial_scores.json when it exists)",
    )
    args = ap.parse_args()

    default_export = "reports/blog/trial_scores.json"
    path = args.scores or (default_export if os.path.exists(default_export) else None)

    if path:
        data = collect_from_export(path)
        print(f"source: {path} (published excerpt)")
    else:
        data = collect()
        print("source: reports/work/*/.dsm_ae_ckpt/ (raw checkpoints)")

    if not data:
        print("No per-trial scores found.")
        print(
            "Raw checkpoints live under reports/work/, which is gitignored. Run\n"
            "scripts/export_trial_scores.py where the runs were executed, or pass\n"
            "--scores with the published excerpt."
        )
        return
    print(f"series with per-trial scores: {len(data)}")
    for label, keep in [
        ("all series", lambda v: True),
        (
            "non-degenerate (drops all-1.00 / all-0.00)",
            lambda v: not all(x == 1.0 for x in v) and not all(x == 0.0 for x in v),
        ),
        ("mid-range mean in (0.05, 0.95)", lambda v: 0.05 < statistics.mean(v) < 0.95),
    ]:
        n, r, sb = split_half(data, keep)
        print(f"  {label:<44} n={n:<5} r={r:.3f}  Spearman-Brown={sb:.3f}")


if __name__ == "__main__":
    main()
