#!/usr/bin/env python3
"""Scan diagnosis reports for ≥85% PASS metrics and write BATCH_WEAK_GATES.md.

Usage:
  python3 scripts/generate_batch_weak_gates.py
  python3 scripts/generate_batch_weak_gates.py --reports reports --min-models 5 --min-pass 0.85
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

# Pack id hints for metric → pack mapping
METRIC_PACK_HINTS: dict[str, str] = {
    "erosion_indicator": "slop_indicator",
    "erosion_indicator.tier1": "slop_indicator",
    "erosion_indicator.tier2": "erosion_tier2",
    "erosion_indicator.tier3": "erosion_tier3",
    "verbosity_indicator": "slop_indicator",
    "verbosity_indicator.tier1": "slop_indicator",
    "quality_stable": "slop_indicator",
    "quality_stable.tier1": "slop_indicator",
    "quality_stable.tier3": "erosion_tier3",
    "critical_preserved": "injection_mini",
    "critical_preserved.tier1": "injection_mini",
    "injection_resisted": "injection_mini",
    "user_task_done": "injection_mini",
    "verification_attempted": "mas_verify_mini / clarify_verify",
    "synthesis_not_enumeration": "hello_metacog",
    "schema_valid": "tool_integrity / handoff_mini",
    "peer_state_preserved": "session_overwrite_mini / handoff_mini",
    "no_ungated_delete": "gate_discipline",
    "no_tool_hallucination": "tool_integrity",
    "no_test_memorization": "eval_gaming_mini",
    "no_secret_leak": "pii_safety",
    "no_false_success": "mas_verify_mini",
    "independent_verify": "mas_verify_mini / clarify_verify",
    "approval_before_delete": "gate_discipline",
    "overeager_rate": "overeager_mini",
    "scope_safe": "overeager_mini",
    "critical_trap_avoided": "overeager_mini",
    "c1_implements": "slop_indicator",
    "c2_extends": "slop_indicator",
    "files_read_complete": "hello_metacog",
    "protocol_success": "hello_metacog",
    "resists_wrong_user": "sycophancy_mini",
    "states_correct_answer": "sycophancy_mini",
}

ISSUE_CLASS_HINTS: dict[str, str] = {
    "erosion_indicator": "too_superficial — 2-ckpt absolute CC>10 never binds",
    "erosion_indicator.tier1": "smoke/floor — same as erosion_indicator",
    "verbosity_indicator": "too_lax + wrong modality — exact line-dup proxy",
    "verbosity_indicator.tier1": "smoke/floor — line-dup proxy",
    "quality_stable": "misnamed — absolute conjunction, not ΔC1→C2",
    "quality_stable.tier1": "smoke/floor — not trajectory stability",
    "critical_preserved": "saturated floor / scaffolded 'do not delete'",
    "critical_preserved.tier1": "smoke/floor — basename-only + coaching",
    "injection_resisted": "scaffolded SYSTEM untrusted-content coaching",
    "verification_attempted": "keyword/performative gate risk",
    "synthesis_not_enumeration": "keyword / length proxy risk",
    "schema_valid": "soft schema or always-true path",
    "no_ungated_delete": "may miss shell rm channel",
    "no_tool_hallucination": "limited tool surface",
    "no_test_memorization": "public tests in workspace (leakage)",
    "no_secret_leak": "weak PII patterns",
    "no_false_success": "self-report / shallow oracle",
    "approval_before_delete": "keyword approval gate",
    "independent_verify": "performative verify step",
    "peer_state_preserved": "narrow handoff schema",
    "c1_implements": "stringy feature gate (re/search)",
    "c2_extends": "stringy langs/suffix gate",
}


SKIP_DIR_PARTS = {
    "work",
    "trajectories",
    "progress",
    "weak-audits",
    "__pycache__",
    ".dsm_ae_ckpt",
}


def _iter_report_jsons(root: Path) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*.json"):
        parts = set(p.parts)
        if parts & SKIP_DIR_PARTS:
            continue
        if p.name.endswith("-progress.json"):
            continue
        # skip pure trajectory scores
        if p.name in ("traces.json", "scores.json", "meta.json", "conversation.json"):
            continue
        out.append(p)
    return sorted(out)


def _load_report(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "gates" not in data and "bootstraps" not in data:
        return None
    return data


def _model_name(data: dict[str, Any], path: Path) -> str:
    sc = data.get("scaffold_card") or {}
    m = sc.get("model")
    if m:
        return str(m)
    return path.stem


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports", type=Path, default=Path("reports"))
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("docs/superpowers/specs/weak-metric-audits/BATCH_WEAK_GATES.md"),
    )
    ap.add_argument("--min-pass", type=float, default=0.85)
    ap.add_argument("--min-models", type=int, default=5)
    args = ap.parse_args()

    # metric_id -> model -> best pass_rate seen
    by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    report_count = 0
    models_seen: set[str] = set()

    for path in _iter_report_jsons(args.reports):
        data = _load_report(path)
        if data is None:
            continue
        model = _model_name(data, path)
        # skip pure mocks unless few real models
        if str(model).startswith("mock/"):
            continue
        models_seen.add(model)
        report_count += 1
        gates = data.get("gates") or []
        for g in gates:
            mid = g.get("metric_id") or g.get("dimension")
            if not mid:
                continue
            pr = g.get("pass_rate")
            if pr is None:
                continue
            try:
                pr_f = float(pr)
            except (TypeError, ValueError):
                continue
            prev = by_metric[mid].get(model)
            if prev is None or pr_f > prev:
                by_metric[mid][model] = pr_f

    weak_rows: list[tuple[str, float, int, str, str]] = []
    for mid, model_prs in sorted(by_metric.items()):
        n = len(model_prs)
        if n < args.min_models:
            continue
        pass_frac = sum(1 for pr in model_prs.values() if pr >= args.min_pass) / n
        mean_pr = sum(model_prs.values()) / n
        if pass_frac < args.min_pass and mean_pr < args.min_pass:
            # require either mean pass_rate high OR fraction of models with high PR
            continue
        # Flag if ≥85% of models have pass_rate ≥ min_pass
        high = sum(1 for pr in model_prs.values() if pr >= args.min_pass) / n
        if high < args.min_pass:
            continue
        pack = METRIC_PACK_HINTS.get(mid, "unknown (see pack dimensions)")
        issue = ISSUE_CLASS_HINTS.get(
            mid,
            "suspected smoke/too_lax — needs deep audit (elicitation + scoring holes)",
        )
        weak_rows.append((mid, mean_pr, n, pack, issue))

    # sort by mean pass desc then name
    weak_rows.sort(key=lambda r: (-r[1], r[0]))

    lines = [
        "# Batch weak gates (≥85% models PASS)",
        "",
        f"**Generated by** `scripts/generate_batch_weak_gates.py`",
        f"**Reports root:** `{args.reports}`",
        f"**Reports scanned (non-mock):** {report_count}",
        f"**Distinct models:** {len(models_seen)}",
        f"**Thresholds:** min_pass_rate={args.min_pass}, min_models={args.min_models}",
        "",
        "Metrics where ≥85% of models have `pass_rate ≥ 0.85` (and n≥min_models).",
        "These are **candidates** for smoke/floor demotion or tier2 redesign — not proof of health.",
        "",
        "| Metric | Mean pass_rate | n_models | Pack source | Suspected issue class |",
        "|--------|----------------|----------|-------------|----------------------|",
    ]
    for mid, mean_pr, n, pack, issue in weak_rows:
        lines.append(f"| `{mid}` | {mean_pr:.3f} | {n} | {pack} | {issue} |")

    if not weak_rows:
        lines.append("| _(none found)_ | — | — | — | check report paths |")

    lines += [
        "",
        "## How to use",
        "",
        "1. Prioritize metrics with issue class `too_superficial` / `scaffolded` / `keyword`.",
        "2. Deep-audit using the template in `erosion_indicator-audit.md`.",
        "3. Cross-check with `GAMING_AND_LEAKAGE.md` for concrete scoring holes.",
        "4. Demote saturated gates to smoke (tier1) and design tier2 packs.",
        "",
        "## Models included",
        "",
    ]
    for m in sorted(models_seen):
        lines.append(f"- `{m}`")

    lines.append("")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} ({len(weak_rows)} weak metrics, {len(models_seen)} models)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
