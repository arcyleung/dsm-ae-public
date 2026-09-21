#!/usr/bin/env python3
"""Fingerprint TrialTraces and test whether procedures discriminate task outcome.

Loads work-dir trajectories that contain litellm.jsonl, maps tool calls
to procgrep-style atoms, then:

  1. per-pack pass/fail n-gram contrast (log-odds)
  2. AUC of a fail-score built from those n-grams
  3. same-condition JSD noise floor (Q5)

Usage:
  PYTHONPATH=src python3 scripts/analyze_trajectory_atoms.py
  PYTHONPATH=src python3 scripts/analyze_trajectory_atoms.py --reports reports -o reports/trajectory-atoms
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dsm_ae.atoms import (  # noqa: E402
    PROCESS_PACKS,
    LoadedTrial,
    atoms_from_trace,
    auc_roc,
    build_vocab,
    discriminative_procedures,
    fail_score,
    fingerprint,
    jsd,
    label_trial,
    match_patterns,
    mean_fingerprint,
    measure_floor,
    scores_from_bootstraps,
    seeds_needed,
    vocab_spec,
)


def _trace_model(tr: dict[str, Any]) -> str:
    card = tr.get("scaffold_card") or {}
    return str(card.get("model") or tr.get("model") or "unknown")


def load_work_dir_trials(reports: Path) -> list[LoadedTrial]:
    out: list[LoadedTrial] = []
    for root in reports.rglob("trajectories"):
        if "_request_logs" in root.parts or "experimental-ui" in root.parts:
            continue
        for d in root.iterdir():
            if not d.is_dir() or "__t" not in d.name:
                continue
            tj, sj = d / "traces.json", d / "scores.json"
            if not (d / "litellm.jsonl").is_file():
                continue
            if not tj.is_file():
                continue
            try:
                raw = json.loads(tj.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            traces = raw if isinstance(raw, list) else [raw]
            scores: list[dict[str, Any]] = []
            if sj.is_file():
                try:
                    sc = json.loads(sj.read_text(encoding="utf-8"))
                    if isinstance(sc, list):
                        scores = [s for s in sc if isinstance(s, dict)]
                except (OSError, json.JSONDecodeError):
                    scores = []
            pack = d.name.split("__t")[0]
            src = str(root.parent.relative_to(reports)) if root.is_relative_to(reports) else str(root)
            for tr in traces:
                if not isinstance(tr, dict):
                    continue
                atoms = atoms_from_trace(tr)
                task, all_ok = label_trial(pack, scores)
                tid = str(tr.get("trial_id") or f"{src}/{d.name}")
                out.append(
                    LoadedTrial(
                        trial_id=tid,
                        model=_trace_model(tr),
                        pack=pack,
                        source=src,
                        atoms=atoms,
                        scores=scores,
                        task_passed=task,
                        all_nonsmoke_passed=all_ok,
                    )
                )
    return out



    repro = reports / "repro-shared"
    if not repro.is_dir():
        return []
    out: list[LoadedTrial] = []
    for p in repro.rglob("trial_*.json"):
        if p.name.endswith(".err"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        traces = data.get("traces") or []
        if not traces or not isinstance(traces[0], dict):
            continue
        tr = traces[0]
        if not isinstance(tr.get("tool_calls"), list):
            continue
        scores = scores_from_bootstraps(data)
        packs = data.get("packs") or [tr.get("pack")]
        pack = str(packs[0] if packs else tr.get("pack") or "unknown")
        task, all_ok = label_trial(pack, scores)
        out.append(
            LoadedTrial(
                trial_id=str(tr.get("trial_id") or p),
                model=_trace_model(tr),
                pack=pack,
                source=f"repro-shared/{p.relative_to(repro).parts[0]}",
                atoms=atoms_from_trace(tr),
                scores=scores,
                task_passed=task,
                all_nonsmoke_passed=all_ok,
            )
        )
    return out


def dedupe(trials: Iterable[LoadedTrial]) -> list[LoadedTrial]:
    seen: set[str] = set()
    out: list[LoadedTrial] = []
    for t in trials:
        key = t.trial_id
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


def pack_report(trials: list[LoadedTrial], *, ngram_max: int) -> dict[str, Any]:
    labeled = [t for t in trials if t.task_passed is not None and t.atoms]
    n_pass = sum(1 for t in labeled if t.task_passed)
    n_fail = sum(1 for t in labeled if not t.task_passed)
    vocab = build_vocab(labeled, ngram_max=ngram_max, min_count=2)
    disc = discriminative_procedures(labeled, vocab, ngram_max=ngram_max, k=12)
    scores = [fail_score(t.atoms, disc) for t in labeled]
    labels = [0 if t.task_passed else 1 for t in labeled]
    auc = auc_roc(scores, labels)
    # majority baseline
    maj = max(n_pass, n_fail) / max(n_pass + n_fail, 1)
    # simple threshold at 0
    pred = [1 if s > 0 else 0 for s in scores]
    acc = sum(int(a == b) for a, b in zip(pred, labels)) / max(len(labels), 1)
    # pass vs fail JSD
    fps = [fingerprint(t.atoms, vocab, ngram_max=ngram_max) for t in labeled]
    pass_fp = mean_fingerprint([fp for fp, t in zip(fps, labeled) if t.task_passed])
    fail_fp = mean_fingerprint([fp for fp, t in zip(fps, labeled) if not t.task_passed])
    pf_jsd = jsd(pass_fp, fail_fp) if pass_fp and fail_fp else None
    pat = Counter()
    for t in labeled:
        for h in match_patterns(t.atoms):
            pat[(h, bool(t.task_passed))] += 1
    patterns = []
    for name in sorted({k[0] for k in pat}):
        np_ = pat[(name, True)]
        nf = pat[(name, False)]
        patterns.append(
            {
                "pattern": name,
                "n_pass": np_,
                "n_fail": nf,
                "rate_pass": np_ / max(n_pass, 1),
                "rate_fail": nf / max(n_fail, 1),
            }
        )
    return {
        "n": len(labeled),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "majority_acc": round(maj, 3),
        "fail_score_acc": round(acc, 3),
        "auc": None if auc is None else round(auc, 3),
        "pass_fail_jsd": None if pf_jsd is None else round(pf_jsd, 3),
        "vocab_size": len(vocab),
        "top_fail_procedures": [
            {
                "procedure": r.procedure,
                "log_odds": round(r.log_odds, 3),
                "p_pass": round(r.p_pass, 3),
                "p_fail": round(r.p_fail, 3),
                "n_pass": r.n_pass,
                "n_fail": r.n_fail,
            }
            for r in disc
            if r.log_odds > 0
        ][:8],
        "top_pass_procedures": [
            {
                "procedure": r.procedure,
                "log_odds": round(r.log_odds, 3),
                "p_pass": round(r.p_pass, 3),
                "p_fail": round(r.p_fail, 3),
                "n_pass": r.n_pass,
                "n_fail": r.n_fail,
            }
            for r in disc
            if r.log_odds < 0
        ][:8],
        "patterns": patterns,
    }


def floor_report(trials: list[LoadedTrial], *, ngram_max: int) -> dict[str, Any]:
    by_cond: dict[tuple[str, str], list[LoadedTrial]] = defaultdict(list)
    for t in trials:
        if t.atoms:
            by_cond[(t.model, t.pack)].append(t)
    # shared vocab across all trials so JSDs are comparable
    vocab = build_vocab(trials, ngram_max=ngram_max, min_count=3)
    spec = vocab_spec(vocab, ngram_max=ngram_max)
    conditions = []
    pooled: list[list[float]] = []
    for (model, pack), rows in sorted(by_cond.items()):
        if len(rows) < 10:
            continue
        fps = [fingerprint(t.atoms, vocab, ngram_max=ngram_max) for t in rows]
        pooled.extend(fps)
        pts = measure_floor(fps, sizes=(5,) if len(rows) < 20 else (5, 10), reps=60, seed=0)
        conditions.append(
            {
                "model": model,
                "pack": pack,
                "n": len(rows),
                "floor": [
                    {"n": p.n, "mean": round(p.mean, 3), "p2_5": round(p.p2_5, 3), "p97_5": round(p.p97_5, 3)}
                    for p in pts
                ],
                "seeds_needed": seeds_needed(pts),
            }
        )
    # also a global same-pack floor pooled across models? skip — not same condition
    # summary by group size
    by_n: dict[int, list[float]] = defaultdict(list)
    for c in conditions:
        for p in c["floor"]:
            by_n[p["n"]].append(p["mean"])
    summary = {
        str(n): {
            "n_conditions": len(vals),
            "mean_floor": round(sum(vals) / len(vals), 3),
            "max_floor": round(max(vals), 3),
        }
        for n, vals in sorted(by_n.items())
    }
    return {
        "vocab_spec": spec,
        "vocab_size": len(vocab),
        "n_conditions_ge10": len(conditions),
        "summary_by_n": summary,
        "conditions": conditions,
    }


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# Trajectory atom analysis",
        "",
        "procgrep-style atoms over DSM-AE `TrialTrace.tool_calls`. Procedures are",
        "n-grams (n≤3), not a large BPE vocab — mean trajectory length here is short.",
        "",
        f"- trials loaded: **{payload['n_trials']}** (after dedupe)",
        f"- with task label: **{payload['n_labeled']}**",
        f"- process packs analysed: `{', '.join(payload['packs'])}`",
        f"- vocab spec: `{payload['floor']['vocab_spec']}`",
        "",
        "## 1. Do procedures discriminate task pass/fail?",
        "",
        "| pack | n | pass | fail | majority | fail-score acc | AUC | pass↔fail JSD |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for pack, r in payload["per_pack"].items():
        auc = "—" if r["auc"] is None else f"{r['auc']:.2f}"
        j = "—" if r["pass_fail_jsd"] is None else f"{r['pass_fail_jsd']:.2f}"
        lines.append(
            f"| `{pack}` | {r['n']} | {r['n_pass']} | {r['n_fail']} | "
            f"{r['majority_acc']:.2f} | {r['fail_score_acc']:.2f} | {auc} | {j} |"
        )
    lines += [
        "",
        "AUC is fail-score (sum of fail-enriched log-odds of n-grams present) vs",
        "task outcome. Values near 0.5 mean the procedure bag does **not** beat a coin.",
        "Accuracy is a 0-threshold on that score; compare to the majority baseline.",
        "",
        "### Fail-enriched procedures (log-odds > 0)",
        "",
    ]
    for pack, r in payload["per_pack"].items():
        if r["n_fail"] < 3 or not r["top_fail_procedures"]:
            continue
        lines.append(f"**`{pack}`** (fail n={r['n_fail']})")
        lines.append("")
        lines.append("| procedure | log-odds | p(pass) | p(fail) |")
        lines.append("|---|---:|---:|---:|")
        for row in r["top_fail_procedures"][:6]:
            lines.append(
                f"| `{row['procedure']}` | {row['log_odds']:.2f} | "
                f"{row['p_pass']:.2f} | {row['p_fail']:.2f} |"
            )
        lines.append("")
    lines += [
        "### Hand pattern rates",
        "",
        "edit-before-read / delete-before-read / read-thrashing / no-submit, by pack.",
        "",
    ]
    for pack, r in payload["per_pack"].items():
        pats = [p for p in r["patterns"] if p["n_fail"] or p["n_pass"]]
        if not pats:
            continue
        interesting = [p for p in pats if abs(p["rate_fail"] - p["rate_pass"]) >= 0.15]
        if not interesting:
            continue
        lines.append(f"**`{pack}`**")
        for p in interesting:
            lines.append(
                f"- `{p['pattern']}`: fail {p['rate_fail']:.0%} ({p['n_fail']}) vs "
                f"pass {p['rate_pass']:.0%} ({p['n_pass']})"
            )
        lines.append("")
    sm = payload["floor"]["summary_by_n"]
    lines += [
        "## 2. Noise floor (Q5)",
        "",
        "Same model × pack, randomly split into two groups of n, JSD of mean",
        "fingerprints. This is the divergence you get when **nothing** differs.",
        "A pass↔fail JSD below the floor cannot be read as a real procedure shift.",
        "",
        "| group size n | conditions | mean floor | max floor |",
        "|---:|---:|---:|---:|",
    ]
    for n, row in sm.items():
        lines.append(
            f"| {n} | {row['n_conditions']} | {row['mean_floor']:.2f} | {row['max_floor']:.2f} |"
        )
    # how many pass-fail JSDs exceed floor at n=5
    floors5 = []
    for c in payload["floor"]["conditions"]:
        for p in c["floor"]:
            if p["n"] == 5:
                floors5.append(p["p97_5"])
    p97 = sorted(floors5)[len(floors5) // 2] if floors5 else None
    n_cond = len(payload["floor"]["conditions"])
    hit10 = sum(1 for c in payload["floor"]["conditions"] if any(x["delta"] == 0.1 and x["n"] for x in c["seeds_needed"]))
    hit20 = sum(1 for c in payload["floor"]["conditions"] if any(x["delta"] == 0.2 and x["n"] for x in c["seeds_needed"]))
    # pass-fail JSD vs floor
    lines += [
        "",
        f"Median 97.5th-percentile floor at n=5: **{p97 if p97 is None else f'{p97:.2f}'}** "
        f"({n_cond} model×pack conditions with n≥10).",
        f"{hit10}/{n_cond} conditions can resolve Δ=0.10; {hit20}/{n_cond} can resolve Δ=0.20 "
        "(smallest split whose floor p97.5 sits under that delta; `—` in JSON means even n=10 is not enough).",
        "",
        "Compare each pack's pass↔fail JSD to that floor:",
        "",
        "| pack | pass↔fail JSD | vs n=5 floor ~0.09 |",
        "|---|---:|---|",
    ]
    for pack, r in payload["per_pack"].items():
        j = r["pass_fail_jsd"]
        if j is None:
            flag = "—"
            js = "—"
        else:
            js = f"{j:.2f}"
            flag = "above (procedure shift)" if j >= 0.09 else "at/below floor (not identifiable)"
        lines.append(f"| `{pack}` | {js} | {flag} |")
    lines += [
        "",
        "Full per-condition floors live in `analysis.json` (`floor.conditions`).",
    ]
    lines += [
        "",
        "## 3. What this does and does not show",
        "",
        "- Useful discriminator: AUC ≳ 0.70 **and** pass↔fail JSD above the n=5 floor.",
        "- Pattern-only story (edit-before-read, etc.) can fire even when n-gram AUC is weak.",
        "- k=5 / k=10 repeats of one toy still measure **trial noise of one scenario**,",
        "  not prevalence. The floor numbers are the empirical version of defense Q5.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports", type=Path, default=ROOT / "reports")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "reports" / "trajectory-atoms")
    ap.add_argument("--ngram-max", type=int, default=3)
    args = ap.parse_args(argv)

    work = load_work_dir_trials(args.reports)
    # Repro-shared trial_*.json are not LiteLLM-sourced; skip.
    trials = dedupe(work)
    labeled = [t for t in trials if t.task_passed is not None]
    process = [t for t in labeled if t.pack in PROCESS_PACKS]

    per_pack: dict[str, Any] = {}
    for pack in sorted({t.pack for t in process}):
        rows = [t for t in process if t.pack == pack]
        n_fail = sum(1 for t in rows if t.task_passed is False)
        n_pass = sum(1 for t in rows if t.task_passed is True)
        if n_pass < 3 or n_fail < 3:
            continue
        per_pack[pack] = pack_report(rows, ngram_max=args.ngram_max)

    floor = floor_report(labeled, ngram_max=args.ngram_max)
    payload = {
        "n_trials": len(trials),
        "n_labeled": len(labeled),
        "n_work": len(work),
        "packs": sorted(per_pack),
        "per_pack": per_pack,
        "floor": floor,
        "atom_mix": dict(Counter(a for t in process for a in t.atoms).most_common()),
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "analysis.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = render_md(payload)
    (args.out / "ANALYSIS.md").write_text(md, encoding="utf-8")
    print(f"Wrote {args.out / 'ANALYSIS.md'} ({len(trials)} trials, {len(per_pack)} packs)")
    print(f"  labeled={len(labeled)} litellm_work={len(work)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
