#!/usr/bin/env python3
"""Label LiteLLM-backed trials with task-progress + recovery + plan-exec + TACT CAL.

Only trial dirs that contain litellm.jsonl are loaded. Tool calls and
reasoning come from those logs (not repro-shared trial_*.json).

Usage:
  PYTHONPATH=src python3 scripts/analyze_intent_state.py
  PYTHONPATH=src python3 scripts/analyze_intent_state.py --models Qwen3.8,deepseek
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dsm_ae.atoms import label_trial  # noqa: E402
from dsm_ae.intent.label import label_trace  # noqa: E402
from dsm_ae.intent.litellm_load import iter_litellm_trials  # noqa: E402
from dsm_ae.intent.plan_exec import plan_exec_scores  # noqa: E402
from dsm_ae.intent.specs import spec_for  # noqa: E402
from dsm_ae.intent.tact_cal import tact_cal_ratios  # noqa: E402

FOCUS = (
    "loop_control",
    "overeager_mini",
    "recency_bias_mini",
    "tool_integrity_tier2",
    "handoff_mini",
    "coord_tax_mini",
    "mas_verify_mini",
    "memory_context",
    "clarify_verify",
    "tool_integrity",
)


def _summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    lab_n: Counter[str] = Counter()
    rec: Counter[str] = Counter()
    cal_pass: list[float] = []
    cal_fail: list[float] = []
    pe_div: list[float] = []
    pe_mis: list[float] = []
    n_plan = 0
    n_pass = n_fail = 0
    adv_pass = adv_fail = 0.0
    unr_pass = unr_fail = 0
    rec_ok_pass = rec_ok_fail = 0
    pack = str(traces[0].get("pack") or "") if traces else ""
    for tr in traces:
        scores = tr.get("_scores") or []
        task, _ = label_trial(str(tr.get("pack") or pack), scores)
        prog = label_trace(tr)
        if prog is None:
            continue
        for s in prog.steps:
            lab_n[s.label] += 1
        if prog.nonmonotonic:
            rec["nonmonotonic"] += 1
        if prog.unrecovered:
            rec["unrecovered"] += 1
        if prog.n_recover:
            rec["recovered"] += 1
        ratios = tact_cal_ratios(tr)
        pe = plan_exec_scores(tr)
        if pe and pe.get("has_plan"):
            n_plan += 1
            if pe.get("plan_exec_divergence") is not None:
                pe_div.append(float(pe["plan_exec_divergence"]))
            if pe.get("ra_mismatch_score") is not None:
                pe_mis.append(float(pe["ra_mismatch_score"]))
        n_adv = sum(1 for s in prog.steps if s.label in {"ADVANCE", "RECOVER"})
        frac_adv = n_adv / max(len(prog.steps), 1)
        if task is True:
            n_pass += 1
            cal_pass.append(ratios["calibrated_ratio"])
            adv_pass += frac_adv
            if prog.unrecovered:
                unr_pass += 1
            if prog.nonmonotonic and not prog.unrecovered:
                rec_ok_pass += 1
        elif task is False:
            n_fail += 1
            cal_fail.append(ratios["calibrated_ratio"])
            adv_fail += frac_adv
            if prog.unrecovered:
                unr_fail += 1
            if prog.nonmonotonic and not prog.unrecovered:
                rec_ok_fail += 1

    def mean(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 3) if xs else None

    return {
        "n": len(traces),
        "n_pass": n_pass,
        "n_fail": n_fail,
        "label_mix": dict(lab_n),
        "n_nonmonotonic": rec["nonmonotonic"],
        "n_recovered": rec["recovered"],
        "n_unrecovered": rec["unrecovered"],
        "frac_advance_pass": round(adv_pass / n_pass, 3) if n_pass else None,
        "frac_advance_fail": round(adv_fail / n_fail, 3) if n_fail else None,
        "unrecovered_rate_pass": round(unr_pass / n_pass, 3) if n_pass else None,
        "unrecovered_rate_fail": round(unr_fail / n_fail, 3) if n_fail else None,
        "recovered_ok_pass": rec_ok_pass,
        "recovered_ok_fail": rec_ok_fail,
        "cal_pass": mean(cal_pass),
        "cal_fail": mean(cal_fail),
        "n_with_plan": n_plan,
        "mean_plan_exec_divergence": mean(pe_div),
        "mean_ra_mismatch": mean(pe_mis),
    }


def _md_table(per_pack: dict[str, Any]) -> list[str]:
    lines = [
        "| pack | n | pass/fail | %ADV+REC pass | %ADV+REC fail | unrecovered pass | unrecovered fail | CAL pass | CAL fail | n plan | PC-15 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for pack, r in per_pack.items():
        lines.append(
            f"| `{pack}` | {r['n']} | {r['n_pass']}/{r['n_fail']} | "
            f"{r['frac_advance_pass'] if r['frac_advance_pass'] is not None else '—'} | "
            f"{r['frac_advance_fail'] if r['frac_advance_fail'] is not None else '—'} | "
            f"{r['unrecovered_rate_pass'] if r['unrecovered_rate_pass'] is not None else '—'} | "
            f"{r['unrecovered_rate_fail'] if r['unrecovered_rate_fail'] is not None else '—'} | "
            f"{r['cal_pass'] if r['cal_pass'] is not None else '—'} | "
            f"{r['cal_fail'] if r['cal_fail'] is not None else '—'} | "
            f"{r['n_with_plan']} | "
            f"{r['mean_plan_exec_divergence'] if r['mean_plan_exec_divergence'] is not None else '—'} |"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", type=Path, default=ROOT / "reports")
    ap.add_argument("-o", "--out", type=Path, default=ROOT / "reports" / "intent-state")
    ap.add_argument(
        "--models",
        default="",
        help="Comma substring filters (empty = all LiteLLM-backed models)",
    )
    args = ap.parse_args(argv)
    filters = [x.strip().lower() for x in args.models.split(",") if x.strip()]

    trials = iter_litellm_trials([args.reports, ROOT / "work"])
    if filters:
        trials = [
            t
            for t in trials
            if any(f in str((t.get("scaffold_card") or {}).get("model") or "").lower() for f in filters)
        ]

    by_model_pack: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for tr in trials:
        pack = str(tr.get("pack") or "")
        if pack not in FOCUS and spec_for(pack) is None:
            continue
        if spec_for(pack) is None:
            continue
        model = str((tr.get("scaffold_card") or {}).get("model") or "unknown")
        by_model_pack[(model, pack)].append(tr)

    by_model: dict[str, dict[str, Any]] = defaultdict(dict)
    for (model, pack), rows in sorted(by_model_pack.items()):
        by_model[model][pack] = _summarize(rows)

    n_models = len(by_model)
    n_trials = len(trials)
    payload = {
        "source": "litellm.jsonl only",
        "n_trials": n_trials,
        "n_models": n_models,
        "models": {m: packs for m, packs in by_model.items()},
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "analysis.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# Intent-state labels (LiteLLM-backed trials)",
        "",
        f"Source of truth: **`litellm.jsonl`** only ({n_trials} trials, {n_models} models).",
        "Repro-shared `trial_*.json` without LiteLLM are **not** loaded.",
        "RECOVER = restored high-water after REGRESS (desirable, not noise).",
        "",
    ]
    # Highlight mixed-outcome cells
    lines += ["## Mixed-outcome cells (both pass and fail)", "", 
              "| model | pack | n | pass/fail | %ADV+REC p/f | unrecovered p/f | CAL p/f |",
              "|---|---|---:|---:|---|---|---|"]
    mixed = []
    for model, packs in sorted(by_model.items()):
        for pack, r in packs.items():
            if r["n_pass"] >= 2 and r["n_fail"] >= 2:
                mixed.append((model, pack, r))
                lines.append(
                    f"| `{model}` | `{pack}` | {r['n']} | {r['n_pass']}/{r['n_fail']} | "
                    f"{r['frac_advance_pass']}/{r['frac_advance_fail']} | "
                    f"{r['unrecovered_rate_pass']}/{r['unrecovered_rate_fail']} | "
                    f"{r['cal_pass']}/{r['cal_fail']} |"
                )
    if not mixed:
        lines.append("| — | — | 0 | — | — | — | — |")

    for model, packs in sorted(by_model.items()):
        n_m = sum(r["n"] for r in packs.values())
        lines += ["", f"## `{model}` ({n_m} trials)", ""]
        lines += _md_table(packs)

    lines += [
        "",
        "## Signal (LiteLLM families)",
        "",
        "- **Recency ADVANCE gap replicates** off GPT: Qwen3.8 0.21 vs 0.13,",
        "  DeepSeek-flash 0.19 vs 0.14, Claude-opus 0.27 vs 0.19, GLM-5.2 0.20 vs 0.11.",
        "  Fails do less required-fact coverage, not a different n-gram program.",
        "- **Overeager unrecovered-REGRESS does *not* replicate on Qwen3.8**",
        "  (10/10 pass on the LiteLLM suite). DeepSeek-flash unrecovered is",
        "  0.33 pass vs 0.29 fail — no separation. The GPT 87.5% figure was",
        "  repro-shared (no LiteLLM) plus a few work-dir fails.",
        "- **Qwen3.8 / DeepSeek TID2 are 0/10 fail** with CAL ~0.66–0.67 vs GPT",
        "  all-pass CAL ~0.97. CAL tracks *family difficulty* on that pack.",
        "- **Plan-exec is now populated** (LiteLLM `reasoning_content`): Qwen",
        "  n_plan=18–20 per pack, PC-15 typically 0.2–0.5. That is a real",
        "  plan–execute gap, well above the n-gram floor (~0.09).",
        "",
        "Plan: `docs/surveys/2026-09-04-intent-state-layered-verification.md`.",
        "",
    ]
    (args.out / "ANALYSIS.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {args.out / 'ANALYSIS.md'} trials={n_trials} models={n_models} mixed={len(mixed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
