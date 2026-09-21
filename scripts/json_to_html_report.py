#!/usr/bin/env python3
"""Build a cross-model HTML matrix from DSM-AE diagnosis JSON reports.

Includes clinical-style expandable diagnostic decision trees (FPG-like)
with per-model pathway tracing and trajectory evidence.

Usage:
  python3 scripts/json_to_html_report.py
  python3 scripts/json_to_html_report.py --input reports --out reports/index.html
  python3 scripts/json_to_html_report.py reports/**/*.json -o comparison.html

If models did not run the same packs/metrics, cells show NOT RUN.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from dsm_ae.criteria import evaluate_findings
    from dsm_ae.harbor.import_rewards import normalize_metric_id
    from dsm_ae.metric_citations import citations_for_metric, references_used
    from dsm_ae.decision_trees import (
        SYNDROME_TREES,
        PathwayResult,
        evaluate_tree,
        gates_from_report_acc,
        tree_to_mermaid,
    )
    from dsm_ae.metrics.bootstrap import classify_status
    from dsm_ae.models import BootstrapStats, GateStatus
    from dsm_ae.packs.smoke_metrics import is_smoke_metric
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from dsm_ae.criteria import evaluate_findings
    from dsm_ae.harbor.import_rewards import normalize_metric_id
    from dsm_ae.metric_citations import citations_for_metric, references_used
    from dsm_ae.decision_trees import (
        SYNDROME_TREES,
        PathwayResult,
        evaluate_tree,
        gates_from_report_acc,
        tree_to_mermaid,
    )
    from dsm_ae.metrics.bootstrap import classify_status
    from dsm_ae.models import BootstrapStats, GateStatus
    from dsm_ae.packs.smoke_metrics import is_smoke_metric


# Workspace / trajectory / progress trees are not diagnosis reports; scanning
# them is slow and can grow without bound under reports/work/.
_SKIP_DIR_NAMES = frozenset(
    {
        "work",
        "trajectories",
        ".dsm_ae_ckpt",
        "progress",
        "bloat",  # Axis V context-bloat runs — separate Comparison tab
        "__pycache__",
        ".git",
        "node_modules",
    }
)


def _is_noise_json(path: Path) -> bool:
    """True if path sits under a non-report directory."""
    return any(part in _SKIP_DIR_NAMES for part in path.parts)


def discover_jsons(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix == ".json":
            found.append(p)
        elif p.is_dir():
            for jp in sorted(p.rglob("*.json")):
                if _is_noise_json(jp.relative_to(p) if jp.is_relative_to(p) else jp):
                    continue
                found.append(jp)
    out: list[Path] = []
    seen: set[Path] = set()
    for p in found:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def load_report(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "gates" not in data and "findings" not in data:
        return None
    if "scaffold_card" not in data and "packs" not in data:
        return None
    data["_source_path"] = str(path)
    return data


# Transport aliases: several models.yaml entries point at the SAME backend model
# and differ only in how the request is routed (gateway vs SSH tunnel) or in a
# name the gateway has since retired. Reporting them as separate columns splits
# one model's evidence into fragments that each look sparse, and makes the
# ceiling audit read as "insufficient data" on packs that were in fact run.
# Suffixes are stripped so all routes collapse to the served model name.
_MODEL_ALIAS_SUFFIXES = ("-tunnel", "-direct", "-funnel")
# Not shown in the public blog/matrix (preview / non-comparable endpoints).
_EXCLUDED_MODELS = frozenset()
_MODEL_ALIASES = {
    # the gateway renamed this model on 2026-09-12; same weights, same backend
    "Qwen3.8-27B-NVFP4-BF16-LMHead": "Qwen3.8-27B-NVFP4",
}


def canonical_model(name: str) -> str:
    n = str(name or "unknown").strip()
    if n in _MODEL_ALIASES:
        return _MODEL_ALIASES[n]
    for suf in _MODEL_ALIAS_SUFFIXES:
        if n.endswith(suf):
            base = n[: -len(suf)]
            return _MODEL_ALIASES.get(base, base)
    return n


def model_id(report: dict[str, Any]) -> str:
    card = report.get("scaffold_card") or {}
    return canonical_model(str(card.get("model") or report.get("model") or "unknown"))


def _obs_from_bootstrap(b: dict[str, Any]) -> list[tuple[float, bool]]:
    """Extract (value, passed) observations from one bootstrap block."""
    out: list[tuple[float, bool]] = []
    pts = b.get("per_trial") or []
    if isinstance(pts, list) and pts:
        for pt in pts:
            if not isinstance(pt, dict):
                continue
            try:
                val = float(pt.get("value") if pt.get("value") is not None else 0.0)
            except Exception:
                val = 0.0
            if "passed" in pt:
                passed = bool(pt.get("passed"))
            else:
                passed = val >= 0.5
            out.append((val, passed))
        if out:
            return out

    values = b.get("values") or []
    if isinstance(values, list) and values:
        n = len(values)
        pr = b.get("pass_rate")
        if pr is not None:
            try:
                n_pass = int(round(float(pr) * n))
            except Exception:
                n_pass = sum(1 for v in values if float(v) >= 0.5)
        else:
            n_pass = sum(1 for v in values if float(v) >= 0.5)
        # Pair value with a reconstructed pass when per_trial missing.
        # Prefer binary pass flags matching pass_rate when values are continuous.
        for i, v in enumerate(values):
            try:
                fv = float(v)
            except Exception:
                fv = 0.0
            if all(float(x) in (0.0, 1.0) for x in values if x is not None):
                passed = fv >= 0.5
            else:
                passed = i < n_pass
            out.append((fv, passed))
        return out

    # Fall back to n × pass_rate expansion (historic gate-only records).
    try:
        n = int(b.get("n") or 0)
    except Exception:
        n = 0
    pr = b.get("pass_rate")
    if n > 0 and pr is not None:
        try:
            n_pass = int(round(float(pr) * n))
        except Exception:
            n_pass = 0
        for i in range(n):
            passed = i < n_pass
            out.append((1.0 if passed else 0.0, passed))
    return out


def _obs_from_gate(g: dict[str, Any]) -> list[tuple[float, bool]]:
    """Last-resort observations from a gate cell alone."""
    try:
        n = int(g.get("n") or 0)
    except Exception:
        n = 0
    # Parse n= from explanation when explicit n missing.
    if n <= 0:
        expl = str(g.get("explanation") or "")
        m = re.search(r"\bn=(\d+)\b", expl)
        if m:
            n = int(m.group(1))
    pr = g.get("pass_rate")
    mean = g.get("mean")
    if n <= 0 or pr is None:
        return []
    try:
        n_pass = int(round(float(pr) * n))
    except Exception:
        return []
    out: list[tuple[float, bool]] = []
    for i in range(n):
        passed = i < n_pass
        if mean is not None and n_pass == n:
            try:
                out.append((float(mean), True))
                continue
            except Exception:
                pass
        out.append((1.0 if passed else 0.0, passed))
    return out


def _finalize_metric(
    metric_id: str,
    *,
    dimension: str,
    values: list[float],
    passes: list[bool],
    notes: list[str],
    n_reports: int,
    threshold_pass: float = 0.8,
    threshold_std: float = 0.25,
) -> tuple[dict[str, Any], dict[str, Any], BootstrapStats]:
    """Build pooled gate + bootstrap dicts + BootstrapStats for criteria."""
    n = len(passes)
    pass_rate = statistics.fmean([1.0 if p else 0.0 for p in passes]) if n else 0.0
    mean = statistics.fmean(values) if values else 0.0
    # Prefer pass-series std for attunement variance (matches bootstrap_metric).
    series = [1.0 if p else 0.0 for p in passes]
    if values and not all(v in (0.0, 1.0) for v in values):
        series_for_std = values
    else:
        series_for_std = series
    std = statistics.pstdev(series_for_std) if n > 1 else 0.0
    status = classify_status(
        pass_rate, std, threshold_pass=threshold_pass, threshold_std=threshold_std
    )
    disorder = status in (GateStatus.FAIL, GateStatus.UNSTABLE)
    note = notes[0] if notes else ""
    if len(note) > 220:
        note = note[:217] + "…"
    summary = (
        f"n={n} mean={mean:.3f} std={std:.3f} pass_rate={pass_rate:.3f} → {status.value}"
        f"{' (DISORDER)' if disorder else ' (attuned)'}"
        f" [pooled from {n_reports} report(s)]"
        + (f". e.g. {note}" if note else "")
    )
    gate = {
        "metric_id": metric_id,
        "dimension": dimension,
        "pass_rate": pass_rate,
        "mean": mean,
        "std": std,
        "n": n,
        "status": status.value,
        "disorder": disorder,
        "explanation": summary,
        "n_reports": n_reports,
    }
    boot = {
        "metric_id": metric_id,
        "dimension": dimension,
        "n": n,
        "values": values,
        "mean": mean,
        "std": std,
        "pass_rate": pass_rate,
        "status": status.value,
        "disorder": disorder,
        "threshold_pass": threshold_pass,
        "threshold_std": threshold_std,
        "summary": summary,
        "n_reports": n_reports,
    }
    stats = BootstrapStats(
        metric_id=metric_id,
        dimension=dimension,
        n=n,
        values=values,
        mean=mean,
        std=std,
        pass_rate=pass_rate,
        status=status,
        disorder=disorder,
        threshold_pass=threshold_pass,
        threshold_std=threshold_std,
        per_trial=[],
        summary=summary,
    )
    return gate, boot, stats


def merge_reports(
    reports: list[dict[str, Any]],
    *,
    threshold_pass: float = 0.8,
    threshold_std: float = 0.25,
) -> dict[str, dict[str, Any]]:
    """Merge multiple JSON runs per model by **pooling trial observations**.

    Historic suite reports, queue jobs, and repro-shared ``trial_*.json`` (k=1)
    are concatenated per metric so tooltip ``n`` is total population size across
    all recent runs (last ~days of retests included). Variance is recomputed on
    the pooled series; retest-to-retest drift is intentionally de-emphasized.

    Packs are unioned. Findings are re-derived from pooled bootstraps via
    ``evaluate_findings`` when possible.
    """
    # model -> metric_id -> accumulator
    raw: dict[str, dict[str, Any]] = {}
    meta: dict[str, dict[str, Any]] = {}

    for rep in reports:
        mid = model_id(rep)
        if mid not in meta:
            meta[mid] = {
                "model": mid,
                "packs": set(),
                "sources": [],
                "k_trials": [],
                "run_ids": [],
            }
            raw[mid] = {}
        acc_m = meta[mid]
        packs = rep.get("packs") or []
        if isinstance(packs, list):
            acc_m["packs"].update(packs)
        acc_m["sources"].append(rep.get("_source_path", ""))
        if rep.get("run_id"):
            acc_m["run_ids"].append(rep["run_id"])
        if rep.get("k_trials") is not None:
            acc_m["k_trials"].append(rep["k_trials"])

        boots_by_id: dict[str, dict[str, Any]] = {}
        for b in rep.get("bootstraps") or []:
            bid = b.get("metric_id")
            if bid:
                # Collapse Harbor-broken dotted ids (acknowledges.sensitive) onto
                # canonical underscore ids so criteria + matrix rows match.
                boots_by_id[normalize_metric_id(str(bid))] = b

        seen_metrics: set[str] = set()
        for bid, b in boots_by_id.items():
            seen_metrics.add(bid)
            obs = _obs_from_bootstrap(b)
            if not obs:
                continue
            dim = normalize_metric_id(str(b.get("dimension") or bid))
            slot = raw[mid].setdefault(
                bid,
                {
                    "dimension": dim,
                    "values": [],
                    "passes": [],
                    "notes": [],
                    "n_reports": 0,
                },
            )
            if b.get("dimension"):
                slot["dimension"] = dim
            for val, passed in obs:
                slot["values"].append(val)
                slot["passes"].append(passed)
            slot["n_reports"] += 1
            note = b.get("summary") or ""
            if note:
                slot["notes"].append(str(note)[:240])

        for g in rep.get("gates") or []:
            raw_gid = g.get("metric_id") or g.get("dimension")
            if not raw_gid:
                continue
            gid = normalize_metric_id(str(raw_gid))
            if gid in seen_metrics:
                continue
            # Only use gate when no bootstrap for this metric in this report.
            obs = _obs_from_gate(g)
            if not obs:
                continue
            dim = normalize_metric_id(str(g.get("dimension") or gid))
            slot = raw[mid].setdefault(
                gid,
                {
                    "dimension": dim,
                    "values": [],
                    "passes": [],
                    "notes": [],
                    "n_reports": 0,
                },
            )
            for val, passed in obs:
                slot["values"].append(val)
                slot["passes"].append(passed)
            slot["n_reports"] += 1
            expl = g.get("explanation")
            if expl:
                slot["notes"].append(str(expl)[:240])

    by_model: dict[str, dict[str, Any]] = {}
    for mid, metrics in raw.items():
        m_meta = meta[mid]
        gates: dict[str, Any] = {}
        boots: dict[str, Any] = {}
        stats_list: list[BootstrapStats] = []
        for metric_id, slot in metrics.items():
            if not slot["passes"]:
                continue
            gate, boot, stats = _finalize_metric(
                metric_id,
                dimension=str(slot.get("dimension") or metric_id),
                values=list(slot["values"]),
                passes=list(slot["passes"]),
                notes=list(slot["notes"]),
                n_reports=int(slot.get("n_reports") or 0),
                threshold_pass=threshold_pass,
                threshold_std=threshold_std,
            )
            gates[metric_id] = gate
            boots[metric_id] = boot
            stats_list.append(stats)

        findings: dict[str, Any] = {}
        try:
            for f in evaluate_findings(stats_list):
                findings[f.code] = {
                    "code": f.code,
                    "name": f.name,
                    "present": f.present,
                    "severity": f.severity,
                    "rationale": f.rationale
                    + f" [pooled n across metrics; {len(m_meta['sources'])} report files]",
                    "linked_metrics": list(f.linked_metrics or []),
                }
        except Exception:
            # Fall back: leave findings empty if criteria cannot run.
            pass

        by_model[mid] = {
            "model": mid,
            "packs": m_meta["packs"],
            "gates": gates,
            "findings": findings,
            "bootstraps": boots,
            "sources": m_meta["sources"],
            "k_trials": m_meta["k_trials"],
            "run_ids": m_meta["run_ids"],
            "pooled": True,
            "n_reports": len(m_meta["sources"]),
        }
    return by_model


def collect_universe_fixed(by_model: dict[str, dict[str, Any]]):
    models = sorted(by_model.keys())
    metrics: set[str] = set()
    findings: set[str] = set()
    packs: set[str] = set()
    # Harbor reward rollup — not a pack syndrome metric
    _skip_metrics = frozenset({"primary_pass"})
    for acc in by_model.values():
        metrics.update(m for m in acc["gates"].keys() if m not in _skip_metrics)
        findings.update(acc["findings"].keys())
        packs.update(acc["packs"])
    # include catalogue syndrome codes even if no findings yet
    findings.update(SYNDROME_TREES.keys())
    return models, sorted(metrics), sorted(findings), sorted(packs)


# matplotlib RdYlGn stops (approx), t in [0,1] → (r,g,b) 0–255
_RDYLGN_STOPS: list[tuple[float, tuple[int, int, int]]] = [
    (0.0, (165, 0, 38)),
    (0.1, (215, 48, 39)),
    (0.2, (244, 109, 67)),
    (0.3, (253, 174, 97)),
    (0.4, (254, 224, 139)),
    (0.5, (255, 255, 191)),
    (0.6, (217, 239, 139)),
    (0.7, (166, 217, 106)),
    (0.8, (102, 189, 99)),
    (0.9, (26, 152, 80)),
    (1.0, (0, 104, 55)),
]


def rdylgn_rgb(t: float) -> tuple[int, int, int]:
    """RdYlGn colormap: 0 = red (fail), 0.5 = yellow, 1 = green (pass)."""
    t = max(0.0, min(1.0, float(t)))
    for i in range(len(_RDYLGN_STOPS) - 1):
        t0, c0 = _RDYLGN_STOPS[i]
        t1, c1 = _RDYLGN_STOPS[i + 1]
        if t <= t1 or i == len(_RDYLGN_STOPS) - 2:
            if t1 <= t0:
                return c1
            u = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            u = max(0.0, min(1.0, u))
            return (
                int(round(c0[0] + (c1[0] - c0[0]) * u)),
                int(round(c0[1] + (c1[1] - c0[1]) * u)),
                int(round(c0[2] + (c1[2] - c0[2]) * u)),
            )
    return _RDYLGN_STOPS[-1][1]


def pass_rate_style(pass_rate: float | None) -> str:
    """Inline style for continuous RdYlGn fill by pass_rate in [0,1]."""
    if pass_rate is None:
        return ""
    try:
        t = float(pass_rate)
    except Exception:
        return ""
    r, g, b = rdylgn_rgb(t)
    # Readable text: dark on yellow/light, light on deep red/green.
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    fg = "#111" if luminance >= 150 else "#fff"
    return f' style="background-color:rgb({r},{g},{b});color:{fg}"'


def status_class(status: str | None, not_run: bool = False) -> str:
    if not_run:
        return "not-run"
    s = (status or "").upper()
    if s == "PASS":
        return "pass"
    if s == "FAIL":
        return "fail"
    if s == "UNSTABLE":
        return "unstable"
    if s == "SKIP":
        return "skip"
    return "unknown"


def humanize_eval_text(text: str) -> str:
    """Soft-en user-facing evaluator dumps for tooltips and evidence lists."""
    if not text:
        return text
    s = str(text)
    # evidence[channel]: label → friendly channel label
    _channel_names = {
        "fs": "Filesystem",
        "derived": "Derived",
        "trace": "Trace",
        "text": "Text",
        "tool": "Tool",
    }

    def _channel(m: re.Match[str]) -> str:
        raw = m.group(1).strip()
        ch = _channel_names.get(raw.lower(), raw.replace("_", " ").strip().capitalize())
        return f"{ch}: "

    s = re.sub(r"evidence\[([^\]]+)\]:\s*", _channel, s)

    def _stats(m: re.Match[str]) -> str:
        n, mean, std, pr, status = m.group(1, 2, 3, 4, 5)
        status_label = {
            "PASS": "Pass",
            "FAIL": "Fail",
            "UNSTABLE": "Unstable",
            "SKIP": "Skipped",
        }.get(status.upper(), status)
        try:
            pr_s = f"{float(pr):.0%}"
        except Exception:
            pr_s = pr
        try:
            mean_s = f"{float(mean):.2f}"
        except Exception:
            mean_s = mean
        try:
            std_s = f"{float(std):.2f}"
        except Exception:
            std_s = std
        return (
            f"{n} trials · mean {mean_s} · σ={std_s} · "
            f"{pr_s} pass → {status_label}"
        )

    s = re.sub(
        r"n=(\d+)\s+mean=([-\d.]+)\s+std=([-\d.]+)\s+pass_rate=([-\d.]+)\s*→\s*(\w+)",
        _stats,
        s,
    )
    s = s.replace(" (DISORDER)", "").replace(" (ATTUNED)", " (attuned)")
    s = s.replace(" (disorder)", "")
    return s


def _fmt_pass_rate(pr: Any) -> str:
    try:
        return f"{float(pr):.0%}"
    except Exception:
        return "?"


def _fmt_std(std: Any) -> str:
    try:
        return f"{float(std):.2f}"
    except Exception:
        return "?"


def gate_trial_n(
    gate: dict[str, Any] | None,
    bootstrap: dict[str, Any] | None = None,
) -> int | None:
    """Best-effort trial / population size for a gate cell.

    Prefer explicit ``n`` on the gate or bootstrap, then list lengths
    (``values`` / ``scores`` / ``per_trial``), then ``n=…`` in explanation text.
    """
    for src in (gate, bootstrap):
        if not src:
            continue
        for key in ("n", "n_trials"):
            v = src.get(key)
            if isinstance(v, bool):
                continue
            if isinstance(v, int) and v > 0:
                return v
            if isinstance(v, float) and v == int(v) and v > 0:
                return int(v)
            if isinstance(v, str) and v.isdigit() and int(v) > 0:
                return int(v)
        trials = src.get("trials")
        if isinstance(trials, int) and trials > 0:
            return trials
        if isinstance(trials, (list, tuple)) and trials:
            return len(trials)
        for key in ("values", "scores", "per_trial"):
            vals = src.get(key)
            if isinstance(vals, (list, tuple)) and vals:
                return len(vals)
    for src in (gate, bootstrap):
        if not src:
            continue
        for key in ("explanation", "summary"):
            text = src.get(key)
            if not text:
                continue
            m = re.search(r"\bn=(\d+)\b", str(text))
            if m:
                n = int(m.group(1))
                if n > 0:
                    return n
    return None


def fmt_gate_cell(gate: dict[str, Any] | None) -> tuple[str, str]:
    if gate is None:
        return "Not run", "not-run"
    status = str(gate.get("status") or "?")
    pr_s = _fmt_pass_rate(gate.get("pass_rate"))
    std_s = _fmt_std(gate.get("std"))
    # Color encodes status; cell text is just pass rate + σ.
    text = f"{pr_s} pass · σ={std_s}"
    return text, status_class(status)


def fmt_gate_tooltip(
    gate: dict[str, Any] | None,
    bootstrap: dict[str, Any] | None = None,
) -> str:
    """Multi-line floating tooltip: pass %, n, σ, status (+ short note)."""
    if gate is None:
        return "Not run"
    pr_s = _fmt_pass_rate(gate.get("pass_rate"))
    std_s = _fmt_std(gate.get("std"))
    status = str(gate.get("status") or "?").upper()
    n = gate_trial_n(gate, bootstrap)
    n_s = str(n) if n is not None else "?"
    lines = [
        f"{pr_s} pass",
        f"n={n_s} trials",
        f"σ={std_s}",
        status,
    ]
    expl = gate.get("explanation") or (bootstrap or {}).get("summary")
    if expl:
        # Drop the leading stats line (already shown above); keep a short note.
        note = humanize_eval_text(str(expl))
        note = re.sub(
            r"^\d+\s+trials\s*·\s*mean\s+[-\d.]+\s*·\s*σ=[-\d.]+\s*·\s*"
            r"[\d.?%]+\s*pass\s*→\s*\w+(?:\s*\([^)]*\))?\s*\.?\s*",
            "",
            note,
            count=1,
        )
        # Also strip raw stats prefix if humanize didn't rewrite it.
        note = re.sub(
            r"^n=\d+\s+mean=[-\d.]+\s+std=[-\d.]+\s+pass_rate=[-\d.]+\s*→\s*\w+"
            r"(?:\s*\([^)]*\))?\s*\.?\s*",
            "",
            note,
            count=1,
        )
        note = re.sub(r"^\(attuned\)\s*\.?\s*", "", note, flags=re.I)
        note = note.strip(" .")
        if note:
            if len(note) > 160:
                note = note[:157] + "…"
            lines.append(note)
    return "\n".join(lines)


def gate_cell_attrs(
    gate: dict[str, Any] | None,
    bootstrap: dict[str, Any] | None = None,
) -> str:
    """HTML attributes for metric cells: data-* for JS floating tip only.

    Intentionally omits native ``title=`` so the browser does not show a second
    delayed tooltip on top of ``#cell-tip``.
    """
    if gate is None:
        tip = "Not run"
        tip_esc = html.escape(tip, quote=True)
        return (
            f' data-status="NOT_RUN" data-tip="{tip_esc}"'
            f' aria-label="{tip_esc}"'
        )
    pr = gate.get("pass_rate")
    try:
        pr_pct = f"{float(pr) * 100:.0f}"
    except Exception:
        pr_pct = ""
    std = gate.get("std")
    try:
        std_s = f"{float(std):.2f}"
    except Exception:
        std_s = ""
    status = str(gate.get("status") or "?").upper()
    n = gate_trial_n(gate, bootstrap)
    n_s = str(n) if n is not None else "?"
    tip = fmt_gate_tooltip(gate, bootstrap)
    tip_esc = html.escape(tip, quote=True)
    # Single-line aria-label for a11y (does not spawn a browser hover tooltip).
    aria = f"{_fmt_pass_rate(pr)} pass · n={n_s} · σ={_fmt_std(std)} · {status}"
    attrs = [
        f' data-pass="{html.escape(pr_pct, quote=True)}"' if pr_pct != "" else "",
        f' data-n="{html.escape(n_s, quote=True)}"',
        f' data-std="{html.escape(std_s, quote=True)}"' if std_s != "" else "",
        f' data-status="{html.escape(status, quote=True)}"',
        f' data-tip="{tip_esc}"',
        f' aria-label="{html.escape(aria, quote=True)}"',
    ]
    return "".join(attrs)


def finding_cell_attrs(
    tip: str | None,
    *,
    present: bool | None = None,
    severity: str | None = None,
) -> str:
    """Light tooltip attrs for syndrome matrix cells (no native title=)."""
    if not tip:
        return ""
    tip_s = str(tip).strip()
    if not tip_s:
        return ""
    if len(tip_s) > 400:
        tip_s = tip_s[:397] + "…"
    tip_esc = html.escape(tip_s, quote=True)
    parts = [f' data-tip="{tip_esc}"', f' aria-label="{tip_esc}"']
    if present is not None:
        parts.insert(0, f' data-status="{"PRESENT" if present else "ABSENT"}"')
    if severity:
        parts.insert(0, f' data-sev="{html.escape(str(severity), quote=True)}"')
    return "".join(parts)


def fmt_finding_cell(finding: dict[str, Any] | None) -> tuple[str, str]:
    # No finding and no tree verdict means the syndrome's packs were never run
    # for this model. That is not evidence of absence, so it must not render as
    # "Not present".
    if finding is None:
        return "Insufficient data", "not-run"
    present = finding.get("present")
    sev = finding.get("severity") or "none"
    if present:
        return f"Present · {sev}", "present"
    return f"Not present · {sev}", "absent"


# ---------------------------------------------------------------------------
# Decision tree HTML — Mermaid directed graphs (FPG-style)
# ---------------------------------------------------------------------------


def _esc(s: Any) -> str:
    return html.escape(str(s) if s is not None else "")


def render_mermaid_block(mermaid_src: str, caption: str = "") -> str:
    """Deferred Mermaid block — not rendered until the parent <details> opens.

    Source is stored in a non-executable script tag so mermaid.startOnLoad
    never walks hundreds of graphs on first paint.
    """
    cap = f'<div class="flow-title">{_esc(caption)}</div>' if caption else ""
    # Guard against accidental </script> in graph text; keep Mermaid syntax intact.
    safe = mermaid_src.replace("</script", "<\\/script")
    return (
        f'<div class="mermaid-wrap" data-lazy-mermaid="1">'
        f"{cap}"
        f'<div class="mermaid-host" hidden></div>'
        f'<script type="text/plain" class="mermaid-src">{safe}</script>'
        f'<noscript><p class="hint">Open this page with JavaScript enabled to view the decision tree.</p></noscript>'
        f"</div>"
    )


def render_reference_flowchart(tree) -> str:
    """Reference decision tree (lazy diagram)."""
    mm = tree_to_mermaid(tree, title=f"{tree.code} decision tree")
    bits = [
        f'<p class="flow-desc">{_esc(tree.description)}</p>',
        f'<p class="flow-metrics"><strong>Metrics:</strong> '
        + ", ".join(f"<code>{_esc(m)}</code>" for m in tree.linked_metrics)
        + "</p>",
        render_mermaid_block(mm, caption=f"Decision tree — {tree.code}"),
    ]
    return "\n".join(bits)


def render_model_pathway(
    tree,
    pathway: PathwayResult,
    model: str,
    gates: dict | None = None,
) -> str:
    """Per-model pathway as HTML step list only (no Mermaid — keeps matrix fast)."""
    badge = "neval"
    if pathway.not_evaluated:
        badge = "neval"
    elif pathway.present:
        badge = "present"
    else:
        badge = "absent"

    parts = [
        f'<div class="model-path" data-model="{_esc(model)}">',
        f'<div class="path-head">'
        f"<strong>{_esc(model)}</strong> "
        f'<span class="badge {badge}">{_esc(pathway.terminal_label)}</span>'
        f"</div>",
        '<details class="evidence-details"><summary>Evidence</summary>',
        '<ol class="path-steps">',
    ]

    for i, step in enumerate(pathway.steps, 1):
        cls = f"step {step.kind}"
        if step.branch == "yes":
            cls += " took-yes"
        elif step.branch == "no":
            cls += " took-no"
        if step.kind == "terminal":
            cls += " " + badge

        gate_html = ""
        # show all metrics touched at this step
        mids = []
        if step.metric_id:
            mids.append(step.metric_id)
        for snip in step.evidence_snippets:
            if ":" in snip and not snip.startswith(" "):
                mid = snip.split(":", 1)[0].strip()
                if mid and mid not in mids and " " not in mid:
                    mids.append(mid)
        if gates:
            chips = []
            for mid in mids:
                g = gates.get(mid)
                if not g:
                    continue
                pr = f"{g.pass_rate:.0%}" if g.pass_rate is not None else "?"
                st = f"{g.std:.2f}" if g.std is not None else "?"
                chips.append(
                    f'<div class="gate-chip {status_class(g.status)}">'
                    f"<code>{_esc(g.metric_id)}</code> "
                    f"{_esc(pr)} pass · σ={_esc(st)}"
                    f"</div>"
                )
            gate_html = "".join(chips)

        branch_html = ""
        if step.branch:
            ans = "YES" if step.branch == "yes" else "NO"
            branch_html = f' <span class="branch-taken {step.branch}">→ {ans}</span>'

        evid = ""
        if step.evidence_snippets:
            items = "".join(
                f"<li>{_esc(humanize_eval_text(s))}</li>"
                for s in step.evidence_snippets[:6]
            )
            evid = f'<ul class="evidence">{items}</ul>'

        parts.append(
            f'<li class="{cls}">'
            f'<div class="step-label"><span class="n">{i}.</span> '
            f"{_esc(step.label)}{branch_html}</div>"
            f"{gate_html}{evid}"
            f"</li>"
        )

    parts.append("</ol></details></div>")
    return "\n".join(parts)


def render_syndrome_section(
    code: str,
    models: list[str],
    by_model: dict[str, dict[str, Any]],
) -> str:
    tree = SYNDROME_TREES.get(code)
    if not tree:
        # finding without tree def
        name = code
        for m in models:
            f = by_model[m]["findings"].get(code)
            if f and f.get("name"):
                name = f"{code} — {f['name']}"
                break
        return (
            f'<details class="syndrome" id="syndrome-{_esc(code)}">'
            f"<summary><strong>{_esc(name)}</strong> "
            f"<em>(decision tree not defined yet)</em></summary>"
            f"<p>This finding appears in results, but no decision tree is defined yet.</p></details>"
        )

    # matrix row summary chips
    chips = []
    pathways: dict[str, PathwayResult] = {}
    for m in models:
        gates = gates_from_report_acc(by_model[m])
        pw = evaluate_tree(tree, gates)
        pathways[m] = pw
        dm = f' data-model="{_esc(m)}"'
        if pw.not_evaluated:
            chips.append(
                f'<span class="chip neval"{dm}>{_esc(m)}: insufficient data</span>'
            )
        elif pw.present:
            chips.append(
                f'<span class="chip present"{dm}>{_esc(m)}: present '
                f"({_esc(pw.severity)})</span>"
            )
        else:
            chips.append(
                f'<span class="chip absent"{dm}>{_esc(m)}: not present</span>'
            )

    body = [
        # Always collapsed by default (user expands as needed)
        f'<details class="syndrome" id="syndrome-{_esc(code)}">',
        f"<summary>"
        f"<strong>{_esc(tree.code)}</strong> — {_esc(tree.name)} "
        f'<span class="chips">{"".join(chips)}</span>'
        f"</summary>",
        '<div class="syndrome-body">',
        render_reference_flowchart(tree),
        "<h3>Models</h3>",
    ]
    for m in models:
        gates = gates_from_report_acc(by_model[m])
        body.append(render_model_pathway(tree, pathways[m], m, gates=gates))
    body.append("</div></details>")
    return "\n".join(body)



def _metric_algorithms_md_path() -> Path:
    """Repo path to docs/appendices/METRIC_ALGORITHMS.md."""
    return Path(__file__).resolve().parents[1] / "docs" / "appendices" / "METRIC_ALGORITHMS.md"


def _inline_md(text: str) -> str:
    """Escape then apply a small subset of inline Markdown (**bold**, `code`)."""
    s = html.escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _md_table_to_html(rows: list[str]) -> str:
    """Convert pipe-table lines (including separator) to an HTML table."""
    parsed: list[list[str]] = []
    for row in rows:
        line = row.strip().strip("|")
        cells = [c.strip() for c in line.split("|")]
        # Skip markdown separator rows (|---|---|)
        if cells and all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cells):
            continue
        parsed.append(cells)
    if not parsed:
        return ""
    head, *body = parsed
    thead = "<thead><tr>" + "".join(f"<th>{_inline_md(c)}</th>" for c in head) + "</tr></thead>"
    tbody_parts = []
    for r in body:
        # Pad/truncate to header width for ragged rows
        if len(r) < len(head):
            r = r + [""] * (len(head) - len(r))
        elif len(r) > len(head):
            r = r[: len(head)]
        tbody_parts.append(
            "<tr>" + "".join(f"<td>{_inline_md(c)}</td>" for c in r) + "</tr>"
        )
    tbody = "<tbody>" + "".join(tbody_parts) + "</tbody>"
    return f'<div class="panel appendix-table"><table>{thead}{tbody}</table></div>'


def md_to_appendix_html(md: str) -> str:
    """Render METRIC_ALGORITHMS.md subset → HTML (headers, tables, lists, fences)."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        # fenced code
        if line.startswith("```"):
            lang = line[3:].strip()
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1  # closing fence
            code = html.escape("\n".join(code_lines))
            cls = f' class="lang-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre{cls}><code>{code}</code></pre>")
            continue
        # table block
        if line.strip().startswith("|"):
            table_rows: list[str] = []
            while i < n and lines[i].strip().startswith("|"):
                table_rows.append(lines[i])
                i += 1
            out.append(_md_table_to_html(table_rows))
            continue
        # blank
        if not line.strip():
            i += 1
            continue
        # headings
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            # skip top-level H1 — details summary already titles the section
            if level == 1:
                i += 1
                continue
            tag = f"h{min(level + 1, 4)}"  # ## → h3 under appendix, etc.
            out.append(f"<{tag}>{_inline_md(m.group(2).strip())}</{tag}>")
            i += 1
            continue
        # unordered list block
        if re.match(r"^[-*]\s+", line):
            items: list[str] = []
            while i < n and re.match(r"^[-*]\s+", lines[i]):
                items.append(re.sub(r"^[-*]\s+", "", lines[i]))
                i += 1
            out.append(
                "<ul>"
                + "".join(f"<li>{_inline_md(it)}</li>" for it in items)
                + "</ul>"
            )
            continue
        # italic-only pack lines like *Primary pack(s):* `x`
        if line.strip().startswith("*") and line.strip().endswith("*") is False:
            # treat as paragraph (inline handles ** and `)
            out.append(f"<p>{_inline_md(line.strip())}</p>")
            i += 1
            continue
        # paragraph (merge consecutive non-blank non-special)
        para: list[str] = [line.strip()]
        i += 1
        while i < n:
            nxt = lines[i]
            if (
                not nxt.strip()
                or nxt.startswith("```")
                or nxt.strip().startswith("|")
                or re.match(r"^#{1,4}\s+", nxt)
                or re.match(r"^[-*]\s+", nxt)
            ):
                break
            para.append(nxt.strip())
            i += 1
        out.append(f"<p>{_inline_md(' '.join(para))}</p>")
    return "\n".join(out)


def render_metric_algorithms_appendix() -> str:
    """Collapsed <details> block with full metric algorithm appendix HTML.

    Returns empty string if the markdown source is missing (non-fatal).
    """
    md_path = _metric_algorithms_md_path()
    if not md_path.is_file():
        return (
            '<details class="appendix" id="metric-algorithms">\n'
            "  <summary>Appendix: Metric algorithms (source missing)</summary>\n"
            '  <div class="appendix-body">\n'
            "    <p class=\"meta\">Expected "
            f"<code>{html.escape(str(md_path))}</code>. "
            "Run <code>PYTHONPATH=src python scripts/generate_metric_appendix.py</code>.</p>\n"
            "  </div>\n"
            "</details>"
        )
    md = md_path.read_text(encoding="utf-8")
    body = md_to_appendix_html(md)
    # Count metrics for summary badge
    n_metrics = len(re.findall(r"^### `", md, flags=re.M))
    return (
        f'<details class="appendix" id="metric-algorithms">\n'
        f"  <summary>Appendix: Metric algorithms by syndrome"
        f" ({n_metrics} metrics · determinism tags)</summary>\n"
        f'  <div class="appendix-body appendix-md">\n'
        f'    <p class="meta">Source: <code>docs/appendices/METRIC_ALGORITHMS.md</code>'
        f" · regenerate with"
        f" <code>PYTHONPATH=src python scripts/generate_metric_appendix.py</code>."
        f" Tags: <code>DET_EXACT</code> exact match ·"
        f" <code>DET_REGEX</code> regex/numeric ·"
        f" <code>DET_SUBSTR</code> keyword ·"
        f" <code>DET_EXEC</code> execute agent code ·"
        f" <code>DET_STRUCT</code> static structure ·"
        f" <code>DET_TRACE</code> tool/FS sequence ·"
        f" <code>HYBRID</code> combined gates.</p>\n"
        f"{body}\n"
        f"  </div>\n"
        f"</details>"
    )


def build_html(
    by_model: dict[str, dict[str, Any]],
    title: str = "DSM-AE Multi-Model Report",
) -> str:
    models, metrics, finding_codes, packs = collect_universe_fixed(by_model)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def th_models() -> str:
        return "".join(
            f"<th class='model' data-model-col='{i}' data-model='{html.escape(m, quote=True)}'>"
            f"{html.escape(m)}</th>"
            for i, m in enumerate(models)
        )

    def td_model(i: int, m: str, inner: str, extra_attrs: str = "", cls: str = "") -> str:
        c = f" class='{cls}'" if cls else ""
        return (
            f"<td{c} data-model-col='{i}' data-model='{html.escape(m, quote=True)}'"
            f"{extra_attrs}>{inner}</td>"
        )

    # packs matrix
    pack_rows = []
    for pack in packs:
        cells = []
        for i, m in enumerate(models):
            ran = pack in by_model[m]["packs"]
            cells.append(
                td_model(
                    i,
                    m,
                    "Ran" if ran else "Not run",
                    cls="pass" if ran else "not-run",
                )
            )
        pack_rows.append(
            f"<tr><th class='row'>{html.escape(pack)}</th>{''.join(cells)}</tr>"
        )

    # gates matrix
    gate_rows = []
    for metric in metrics:
        cite_ids = citations_for_metric(metric)
        if cite_ids:
            cite_html = (
                '<sup class="cites">['
                + ",".join(
                    f'<a class="cite" href="#ref-{i}">{i}</a>'
                    for i in sorted(set(cite_ids))
                )
                + "]</sup>"
            )
            metric_label = f"<code>{html.escape(metric)}</code> {cite_html}"
        else:
            metric_label = f"<code>{html.escape(metric)}</code>"
        if is_smoke_metric(metric):
            metric_label += (
                ' <span class="badge smoke" title="Smoke/floor tier1 — not full '
                'disorder diagnostic">smoke</span>'
            )
            row_cls = "row metric smoke-metric"
        else:
            row_cls = "row metric"
        cells = []
        for i, m in enumerate(models):
            g = by_model[m]["gates"].get(metric)
            boot = by_model[m]["bootstraps"].get(metric)
            text, cls = fmt_gate_cell(g)
            attrs = gate_cell_attrs(g, boot)
            pr = g.get("pass_rate") if g else None
            style = pass_rate_style(pr if pr is not None else None)
            # Continuous RdYlGn by pass %; keep status class for semantics / chips.
            rate_cls = " rate-scale" if g is not None else ""
            cells.append(
                td_model(
                    i,
                    m,
                    html.escape(text),
                    extra_attrs=f"{attrs}{style}",
                    cls=f"{cls}{rate_cls}".strip(),
                )
            )
        gate_rows.append(
            f"<tr><th class='{row_cls}'>{metric_label}</th>{''.join(cells)}</tr>"
        )

    # findings matrix
    finding_rows = []
    for code in finding_codes:
        name = code
        tree = SYNDROME_TREES.get(code)
        if tree:
            name = f"{code} — {tree.name}"
        else:
            for m in models:
                f = by_model[m]["findings"].get(code)
                if f and f.get("name"):
                    name = f"{code} — {f['name']}"
                    break
        cells = []
        for i, m in enumerate(models):
            # prefer live finding; fall back to tree eval
            f = by_model[m]["findings"].get(code)
            if f is None and tree is not None:
                pw = evaluate_tree(tree, gates_from_report_acc(by_model[m]))
                if pw.not_evaluated:
                    text, cls = "Insufficient data", "not-run"
                    attrs = finding_cell_attrs(
                        "Insufficient data — the packs backing this syndrome "
                        "were not run for this model, so absence cannot be inferred."
                    )
                elif pw.present:
                    text, cls = f"Present · {pw.severity}", "present"
                    attrs = finding_cell_attrs(
                        pw.terminal_label, present=True, severity=pw.severity
                    )
                else:
                    text, cls = f"Not present · {pw.severity}", "absent"
                    attrs = finding_cell_attrs(
                        pw.terminal_label, present=False, severity=pw.severity
                    )
            else:
                text, cls = fmt_finding_cell(f)
                tip = None
                if f and f.get("rationale"):
                    tip = humanize_eval_text(str(f["rationale"]))[:400]
                elif f is None:
                    tip = (
                        "Insufficient data — the packs backing this syndrome "
                        "were not run for this model, so absence cannot be inferred."
                    )
                attrs = finding_cell_attrs(
                    tip,
                    present=bool(f.get("present")) if f else None,
                    severity=(f.get("severity") if f else None),
                )
            link = f"#syndrome-{html.escape(code)}"
            cells.append(
                td_model(
                    i,
                    m,
                    f"<a class='cell-link' href='{link}'>{html.escape(text)}</a>",
                    extra_attrs=attrs,
                    cls=cls,
                )
            )
        finding_rows.append(
            f"<tr><th class='row'><a href='#syndrome-{html.escape(code)}'>"
            f"{html.escape(name)}</a></th>{''.join(cells)}</tr>"
        )

    # expandable decision trees — catalogue order then any extras
    tree_order = list(SYNDROME_TREES.keys())
    for c in finding_codes:
        if c not in tree_order:
            tree_order.append(c)
    syndrome_sections = "\n".join(
        render_syndrome_section(code, models, by_model) for code in tree_order
    )

    # references
    refs_map = references_used(metrics)
    ref_items = []
    for num, meta in refs_map.items():
        url = meta.get("url") or ""
        text = meta.get("text") or meta.get("short") or str(num)
        if url:
            body = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{html.escape(text)}</a>'
        else:
            body = html.escape(text)
        ref_items.append(f'<li id="ref-{num}">[{num}] {body}</li>')
    refs_html = (
        "\n".join(ref_items)
        if ref_items
        else "<li>No survey citations mapped for these metrics.</li>"
    )

    source_blocks = []
    for m in models:
        acc = by_model[m]
        srcs = [s for s in acc["sources"] if s]
        packs_s = ", ".join(sorted(acc["packs"])) or "(none)"
        k_s = ", ".join(str(k) for k in acc["k_trials"]) or "?"
        source_blocks.append(
            f"<li data-model='{html.escape(m, quote=True)}'><strong>{html.escape(m)}</strong> — packs: "
            f"<code>{html.escape(packs_s)}</code>; trials: {html.escape(k_s)}; "
            f"sources: {html.escape('; '.join(srcs) if srcs else '—')}</li>"
        )

    # Model column filter controls (checkboxes; client-side hide/show)
    model_filter_items = []
    for i, m in enumerate(models):
        mid = html.escape(m, quote=True)
        model_filter_items.append(
            f'<label class="model-filter-item">'
            f'<input type="checkbox" class="model-col-toggle" data-model-col="{i}" '
            f'data-model="{mid}" checked/> '
            f"<code>{html.escape(m)}</code></label>"
        )
    model_filter_html = "\n".join(model_filter_items)

    metric_algorithms_html = render_metric_algorithms_appendix()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{html.escape(title)}</title>
<style>
  body {{
    margin: 0; padding: 10px 14px;
    font: 13px/1.35 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    background: #fff; color: #111;
  }}
  /* When embedded under the Comparison tab, drop outer padding so the report
     sits flush with the shell (parent page is the only vertical scroller). */
  html.embedded-in-shell body {{
    padding: 0 14px 8px;
  }}
  h1 {{ margin: 0 0 4px; font-size: 1.2rem; }}
  h2 {{ margin: 16px 0 6px; font-size: 1.05rem; }}
  h3 {{ margin: 12px 0 6px; font-size: 0.95rem; }}
  p, .meta {{ margin: 0 0 6px; color: #444; font-size: 12px; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 8px; font-size: 12px; }}
  .legend span {{ display: inline-flex; align-items: center; gap: 4px; }}
  .swatch {{ width: 10px; height: 10px; border: 1px solid #999; display: inline-block; }}
  .swatch.pass {{ background: #c8e6c9; }}
  .swatch.fail {{ background: #ffcdd2; }}
  .swatch.unstable {{ background: #fff3cd; }}
  /* Discrete classes still used by packs / syndromes / chips; metric cells use
     inline RdYlGn gradient via .rate-scale (inline style wins). */
  td.pass {{ background: #c8e6c9; }}
  td.fail {{ background: #ffcdd2; }}
  td.unstable {{ background: #fff3cd; }}
  td.rate-scale {{ /* fill set inline from pass_rate */ }}
  .swatch.not-run, td.not-run {{ background: #eee; color: #555; font-style: italic; }}
  .swatch.present, td.present {{ background: #ffcdd2; }}
  .swatch.absent, td.absent {{ background: #c8e6c9; }}
  .rate-legend {{
    display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
    margin: 0 0 8px; font-size: 12px; color: #444;
  }}
  .rate-bar {{
    display: inline-block; width: 180px; height: 12px; border: 1px solid #999;
    border-radius: 2px;
    background: linear-gradient(
      90deg,
      rgb(165,0,38) 0%,
      rgb(215,48,39) 10%,
      rgb(244,109,67) 20%,
      rgb(253,174,97) 30%,
      rgb(254,224,139) 40%,
      rgb(255,255,191) 50%,
      rgb(217,239,139) 60%,
      rgb(166,217,106) 70%,
      rgb(102,189,99) 80%,
      rgb(26,152,80) 90%,
      rgb(0,104,55) 100%
    );
  }}
  /* No nested vertical scroll: page (or parent shell) scrolls. Horizontal
     scroll only for wide multi-model tables. */
  .panel {{
    border: 1px solid #ccc; margin: 0 0 6px;
    max-height: none;
    overflow-x: auto;
    overflow-y: visible;
  }}
  /* separate + spacing 0: sticky is more reliable than border-collapse: collapse */
  table {{
    border-collapse: separate; border-spacing: 0;
    width: max-content; min-width: 100%; font-size: 12px;
  }}
  th, td {{
    border: 1px solid #ccc; padding: 2px 5px;
    text-align: center; vertical-align: middle;
    background-clip: padding-box;
  }}
  /* Column headers stick to the viewport when the document scrolls
     (full-page view). Inside a full-height iframe embed, the parent shell scrolls. */
  thead th {{
    position: sticky; top: 0; z-index: 3;
    background: #f5f5f5;
    box-shadow: 0 1px 0 #ccc;
  }}
  th.model, th.corner {{
    position: sticky; top: 0; background: #f5f5f5; z-index: 3;
  }}
  /* Top-left corner: stick both axes */
  th.corner {{
    left: 0; z-index: 5; text-align: left;
    box-shadow: 1px 0 0 #ccc, 0 1px 0 #ccc;
  }}
  /* Row labels: stick to left while scrolling horizontally within .panel */
  th.row {{
    position: sticky; left: 0; background: #fafafa; text-align: left;
    z-index: 2; font-weight: 600; max-width: 320px;
    box-shadow: 1px 0 0 #ccc;
  }}
  th.row.metric {{ font-size: 13px; background: #fafafa; }}
  th.row.metric code {{ font-size: 13px; }}
  td {{ font-variant-numeric: tabular-nums; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
  a {{ color: #0645ad; }}
  a:hover {{ text-decoration: underline; }}
  a.cell-link {{ color: inherit; text-decoration: none; }}
  a.cell-link:hover {{ text-decoration: underline; }}
  sup.cites {{ margin-left: 2px; white-space: nowrap; font-size: 0.9em; }}
  a.cite {{ color: #0645ad; text-decoration: none; }}
  .refs {{ margin: 0 0 6px; }}
  .refs ul {{ margin: 0; padding-left: 1.2em; list-style: disc; font-size: 12px; }}
  .refs li {{ margin: 0 0 2px; }}
  .refs li:target {{ background: #fff3cd; }}
  footer {{ margin-top: 12px; color: #666; font-size: 11px; }}
  ul.sources {{ margin: 0; padding-left: 1.2em; font-size: 12px; }}

  /* expandable syndromes */
  details.syndrome {{
    border: 1px solid #ccc; margin: 0 0 8px; padding: 0;
    background: #fff;
  }}
  details.syndrome > summary {{
    cursor: pointer; padding: 6px 8px; background: #f7f7f7;
    font-size: 13px; list-style: none;
  }}
  details.syndrome > summary::-webkit-details-marker {{ display: none; }}
  details.syndrome > summary::before {{
    content: "▸ "; color: #666; font-weight: 700;
  }}
  details.syndrome[open] > summary::before {{ content: "▾ "; }}
  details.syndrome[open] > summary {{ border-bottom: 1px solid #ddd; }}
  .syndrome-body {{ padding: 8px 10px 10px; }}
  .chips {{ display: inline-flex; flex-wrap: wrap; gap: 4px; margin-left: 8px; }}
  .chip {{
    font-size: 11px; font-weight: 500; padding: 1px 6px;
    border: 1px solid #bbb; border-radius: 3px; background: #fff;
  }}
  .chip.present {{ background: #ffcdd2; border-color: #e57373; }}
  .chip.absent {{ background: #c8e6c9; border-color: #81c784; }}
  .chip.neval {{ background: #eee; color: #555; }}

  .flow-title {{ font-weight: 700; margin: 0 0 4px; font-size: 12px; }}
  .flow-desc, .flow-metrics, .algo-note {{ font-size: 12px; color: #444; margin: 0 0 6px; }}
  .mermaid-wrap {{
    border: 1px solid #ccc; background: #fafafa; padding: 8px 10px;
    margin: 0 0 12px; overflow-x: auto; min-height: 0;
  }}
  .mermaid-host {{ text-align: center; }}
  .mermaid-host svg {{ max-width: 100%; height: auto; }}
  pre.mermaid-fallback {{
    margin: 0; background: transparent; border: none;
    font-size: 11px; text-align: left; white-space: pre-wrap;
  }}
  .mermaid-loading {{ font-size: 12px; color: #666; padding: 8px 0; }}
  /* per-model path */
  .model-path {{
    border: 1px solid #ddd; margin: 0 0 10px; padding: 6px 8px;
    background: #fff;
  }}
  .path-head {{ margin-bottom: 4px; font-size: 12px; }}
  .badge {{
    display: inline-block; padding: 1px 6px; border: 1px solid #999;
    border-radius: 3px; font-size: 11px; font-weight: 600;
  }}
  .badge.present {{ background: #ffcdd2; }}
  .badge.absent {{ background: #c8e6c9; }}
  .badge.neval {{ background: #eee; }}
  .badge.smoke {{
    background: #fff8e1; border-color: #ffb300; color: #6d4c00;
    font-size: 10px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.03em; margin-left: 4px; vertical-align: middle;
  }}
  th.row.smoke-metric {{ background: #fffde7; }}
  th.row.smoke-metric code {{ color: #5d4037; }}
  /* Keep smoke row sticky bg when scrolling */
  th.row.smoke-metric {{ z-index: 2; }}
  details.evidence-details {{ margin-top: 4px; font-size: 12px; }}
  details.evidence-details > summary {{ cursor: pointer; color: #0645ad; }}
  ol.path-steps {{ margin: 4px 0 0; padding-left: 18px; }}
  ol.path-steps li {{ margin: 0 0 6px; font-size: 12px; }}
  ol.path-steps li.took-yes {{ border-left: 3px solid #c62828; padding-left: 6px; }}
  ol.path-steps li.took-no {{ border-left: 3px solid #2e7d32; padding-left: 6px; }}
  ol.path-steps li.terminal {{ font-weight: 600; }}
  .step-label .n {{ color: #666; margin-right: 2px; }}
  .branch-taken {{ font-weight: 700; font-size: 11px; }}
  .branch-taken.yes {{ color: #b71c1c; }}
  .branch-taken.no {{ color: #1b5e20; }}
  .gate-chip {{
    display: inline-block; margin: 2px 0; padding: 1px 5px;
    border: 1px solid #ccc; font-size: 11px;
  }}
  .gate-chip.pass {{ background: #c8e6c9; }}
  .gate-chip.fail {{ background: #ffcdd2; }}
  .gate-chip.unstable {{ background: #fff3cd; }}
  ul.evidence {{
    margin: 2px 0 0 0; padding-left: 16px; color: #333; font-size: 11px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }}
  .toc {{ font-size: 12px; margin: 0 0 10px; }}
  .uc-banner {{ font-size: 12px; line-height: 1.45; margin: 0 0 10px;
    padding: 7px 9px; border: 1px solid #ccc; border-left: 3px solid #888;
    background: #f5f5f5; max-width: 860px; }}
  .toc a {{ margin-right: 8px; }}
  /* Anchor targets: leave room under sticky thead / shell chrome */
  details.syndrome,
  h2[id],
  li[id^="ref-"] {{
    scroll-margin-top: 12px;
  }}
  details.appendix {{
    border: 1px solid #ccc; margin: 12px 0 8px; padding: 0;
    background: #fff;
  }}
  details.appendix > summary {{
    cursor: pointer; padding: 6px 8px; background: #f7f7f7;
    font-size: 13px; font-weight: 600;
  }}
  details.appendix .appendix-body {{ padding: 8px 10px 10px; }}
  .appendix-md h3 {{ margin: 14px 0 6px; font-size: 0.95rem; border-top: 1px solid #e5e5e5; padding-top: 10px; }}
  .appendix-md h3:first-child {{ border-top: 0; padding-top: 0; }}
  .appendix-md h4 {{ margin: 10px 0 4px; font-size: 0.88rem; }}
  .appendix-md p {{ margin: 0 0 6px; color: #333; font-size: 12px; }}
  .appendix-md ul {{ margin: 2px 0 8px 0; padding-left: 18px; font-size: 12px; }}
  .appendix-md pre {{
    margin: 4px 0 10px; padding: 8px 10px; background: #f4f4f4;
    border: 1px solid #ddd; border-radius: 3px; overflow-x: auto;
    font: 11px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }}
  .appendix-md .appendix-table {{ margin: 6px 0 12px; }}
  .appendix-md .appendix-table table {{ font-size: 11px; }}
  .appendix-md .appendix-table th,
  .appendix-md .appendix-table td {{ vertical-align: top; }}
  a.cell-link, th.row a {{ cursor: pointer; }}
  /* Floating cell tooltip (fixed so it is not clipped by .panel overflow-x) */
  td[data-tip] {{ cursor: help; }}
  #cell-tip {{
    position: fixed;
    z-index: 10000;
    max-width: min(320px, calc(100vw - 16px));
    padding: 6px 8px;
    border: 1px solid #333;
    border-radius: 4px;
    background: #1e1e1e;
    color: #f5f5f5;
    font: 11px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    white-space: pre-line;
    pointer-events: none;
    box-shadow: 0 4px 14px rgba(0,0,0,0.28);
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.06s ease;
  }}
  #cell-tip.visible {{
    opacity: 1;
    visibility: visible;
  }}
  /* Model column filter */
  .model-filter {{
    border: 1px solid #ccc; background: #fafafa; margin: 0 0 10px; padding: 8px 10px;
    border-radius: 4px;
  }}
  .model-filter > summary {{
    cursor: pointer; font-weight: 600; font-size: 13px; list-style: none;
  }}
  .model-filter > summary::-webkit-details-marker {{ display: none; }}
  .model-filter > summary::before {{ content: "▸ "; color: #666; }}
  .model-filter[open] > summary::before {{ content: "▾ "; }}
  .model-filter-actions {{
    display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0 6px; align-items: center;
  }}
  .model-filter-actions button {{
    font: inherit; font-size: 12px; padding: 2px 8px; cursor: pointer;
    border: 1px solid #bbb; border-radius: 3px; background: #fff;
  }}
  .model-filter-actions button:hover {{ background: #f0f0f0; }}
  .model-filter-actions .hint {{ color: #666; font-size: 12px; margin-left: 4px; }}
  .model-filter-grid {{
    display: flex; flex-wrap: wrap; gap: 4px 12px; max-height: 180px; overflow-y: auto;
    padding: 4px 0 2px;
  }}
  .model-filter-item {{
    display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
    white-space: nowrap; cursor: pointer; user-select: none;
  }}
  .model-filter-item input {{ margin: 0; }}
  .model-filter-item code {{ font-size: 11px; }}
  /* Hidden model columns + matching pathway / chip blocks */
  th.model.col-hidden,
  td.col-hidden,
  .chip.col-hidden,
  .model-path.col-hidden,
  li[data-model].col-hidden {{
    display: none !important;
  }}
</style>
</head>
<body>
  <h1>{html.escape(title)}</h1>
  <p class="uc-banner"><strong>Under construction.</strong> Individual pack and
  syndrome scores below are <em>not yet model-discriminating</em>: 31% of gates
  return the same value for all {len(models)} models measured, and 81% cannot separate three
  gpt-5.6 variants at k=20. Treat this matrix as a development view, not a
  ranking. The evidenced results are in the
  <a href="blog/index.html" target="_blank" rel="noopener">blog</a>
  (&sect;2 structural split, &sect;3 layered measurement, &sect;4 smoke-test criteria).</p>
  <div class="meta">
    Generated {html.escape(generated)} ·
    {len(models)} model(s) ·
    {len(packs)} pack(s) ·
    {len(metrics)} metric(s) ·
    {len(finding_codes)} syndrome(s) ·
    {len(SYNDROME_TREES)} decision trees ·
    gates <strong>pooled</strong> across all historic diagnose JSONs (suite + queue + repro trials); tooltip <code>n</code> = total trial population
  </div>
  <div class="legend">
    <span><i class="swatch pass"></i> Pass / ran / not present</span>
    <span><i class="swatch fail"></i> Fail / present</span>
    <span><i class="swatch unstable"></i> Unstable</span>
    <span><i class="swatch not-run"></i> Not run / insufficient data</span>
  </div>
  <details class="model-filter" id="model-filter" open>
    <summary>Compare models — show / hide columns
      <span class="hint" id="model-filter-count">({len(models)}/{len(models)} visible)</span>
    </summary>
    <div class="model-filter-actions">
      <button type="button" id="model-filter-all" title="Show every model column">All</button>
      <button type="button" id="model-filter-none" title="Hide every model column">None</button>
      <button type="button" id="model-filter-invert" title="Invert current selection">Invert</button>
      <span class="hint">Uncheck models to hide their columns across syndrome, metric, and pack tables.</span>
    </div>
    <div class="model-filter-grid" role="group" aria-label="Visible model columns">
      {model_filter_html}
    </div>
  </details>
  <div class="toc meta">
    <a href="#syndrome-matrix">Syndromes</a>
    <a href="#decision-trees">Decision trees</a>
    <a href="#metric-results">Metrics</a>
    <a href="#references">References</a>
    <a href="#pack-coverage">Pack coverage</a>
    <a href="#source-files">Source files</a>
    <a href="#metric-algorithms">Metric algorithms</a>
    <a href="blog/index.html" target="_blank" rel="noopener">Blog: measuring agent capability</a>
  </div>

  <h2 id="syndrome-matrix">Syndrome matrix</h2>
  <p class="meta">Scoring algorithms &amp; determinism tags:
    see <code>docs/appendices/METRIC_ALGORITHMS.md</code>
    (<code>python scripts/generate_metric_appendix.py</code>).</p>
  <div class="panel">
    <table>
      <thead><tr><th class="corner">Syndrome</th>{th_models()}</tr></thead>
      <tbody>
        {''.join(finding_rows) if finding_rows else '<tr><td colspan="99">No findings found</td></tr>'}
      </tbody>
    </table>
  </div>

  <h2 id="decision-trees">Decision trees</h2>
  <div class="toc">
    {" ".join(f'<a href="#syndrome-{html.escape(c)}">{html.escape(c)}</a>' for c in tree_order)}
  </div>
  {syndrome_sections}

  <h2 id="metric-results">Metric results</h2>
  <div class="rate-legend" title="matplotlib RdYlGn-style scale on pooled pass rate">
    <span>Pass rate</span>
    <span>0%</span>
    <i class="rate-bar" aria-hidden="true"></i>
    <span>100%</span>
    <span class="hint">(RdYlGn · red=low · yellow=mid · green=high)</span>
  </div>
  <div class="panel">
    <table>
      <thead><tr><th class="corner">Metric</th>{th_models()}</tr></thead>
      <tbody>
        {''.join(gate_rows) if gate_rows else '<tr><td colspan="99">No gates found</td></tr>'}
      </tbody>
    </table>
  </div>

  <h2 id="references">References</h2>
  <div class="refs">
    <ul>
      {refs_html}
    </ul>
  </div>

  <details class="appendix" id="pack-coverage">
    <summary>Pack coverage</summary>
    <div class="appendix-body">
      <div class="panel">
        <table>
          <thead><tr><th class="corner">Pack</th>{th_models()}</tr></thead>
          <tbody>
            {''.join(pack_rows) if pack_rows else '<tr><td colspan="99">No packs found</td></tr>'}
          </tbody>
        </table>
      </div>
    </div>
  </details>

  <details class="appendix" id="source-files">
    <summary>Source files</summary>
    <div class="appendix-body">
      <ul class="sources">
        {''.join(source_blocks)}
      </ul>
    </div>
  </details>

  {metric_algorithms_html}

  <footer>DSM-AE comparison</footer>
  <div id="cell-tip" role="tooltip" hidden></div>
  <script>
  (function () {{
    // Floating tooltip for matrix cells (works inside sticky / overflow-x panels).
    // Cells use data-tip + aria-label only — no title= (avoids delayed browser tip).
    (function cellTip() {{
      const tip = document.getElementById("cell-tip");
      if (!tip) return;
      let active = null;
      const pad = 12;

      function hide() {{
        active = null;
        tip.classList.remove("visible");
        tip.hidden = true;
        tip.textContent = "";
      }}

      function place(clientX, clientY) {{
        tip.hidden = false;
        tip.classList.add("visible");
        const rect = tip.getBoundingClientRect();
        let x = clientX + pad;
        let y = clientY + pad;
        if (x + rect.width > window.innerWidth - 4) {{
          x = Math.max(4, clientX - rect.width - pad);
        }}
        if (y + rect.height > window.innerHeight - 4) {{
          y = Math.max(4, clientY - rect.height - pad);
        }}
        tip.style.left = x + "px";
        tip.style.top = y + "px";
      }}

      function showFor(el, clientX, clientY) {{
        const text = el.getAttribute("data-tip") || "";
        if (!text) {{
          hide();
          return;
        }}
        // Strip any accidental title so only one tip is ever shown.
        if (el.hasAttribute("title")) el.removeAttribute("title");
        active = el;
        tip.textContent = text;
        place(clientX, clientY);
      }}

      document.addEventListener("pointerover", (ev) => {{
        const el = ev.target && ev.target.closest
          ? ev.target.closest("td[data-tip]")
          : null;
        if (!el) return;
        showFor(el, ev.clientX, ev.clientY);
      }});
      document.addEventListener("pointermove", (ev) => {{
        if (!active) return;
        const el = ev.target && ev.target.closest
          ? ev.target.closest("td[data-tip]")
          : null;
        if (!el) {{
          hide();
          return;
        }}
        if (el !== active) {{
          showFor(el, ev.clientX, ev.clientY);
          return;
        }}
        place(ev.clientX, ev.clientY);
      }});
      document.addEventListener("pointerout", (ev) => {{
        if (!active) return;
        const to = ev.relatedTarget;
        if (to && active.contains && active.contains(to)) return;
        if (to && to.closest && to.closest("td[data-tip]") === active) return;
        hide();
      }});
      window.addEventListener("scroll", hide, true);
      window.addEventListener("blur", hide);
    }})();

    // --- Model column filter (show/hide comparison columns) -----------------
    (function modelColumnFilter() {{
      const STORAGE_KEY = "dsm-ae-matrix-visible-models";
      const boxes = Array.from(document.querySelectorAll("input.model-col-toggle"));
      if (!boxes.length) return;
      const countEl = document.getElementById("model-filter-count");

      function apply() {{
        const visible = new Set();
        boxes.forEach((cb) => {{
          const col = cb.getAttribute("data-model-col");
          const model = cb.getAttribute("data-model") || "";
          const on = !!cb.checked;
          if (on && model) visible.add(model);
          document.querySelectorAll(
            "th.model[data-model-col='" + col + "'], td[data-model-col='" + col + "']"
          ).forEach((el) => {{
            el.classList.toggle("col-hidden", !on);
          }});
          if (model) {{
            document.querySelectorAll(
              '.chip[data-model="' + CSS.escape(model) + '"],' +
              '.model-path[data-model="' + CSS.escape(model) + '"],' +
              'li[data-model="' + CSS.escape(model) + '"]'
            ).forEach((el) => {{
              el.classList.toggle("col-hidden", !on);
            }});
          }}
        }});
        const nOn = boxes.filter((b) => b.checked).length;
        if (countEl) {{
          countEl.textContent = "(" + nOn + "/" + boxes.length + " visible)";
        }}
        try {{
          localStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(visible)));
        }} catch (e) {{}}
        // Parent Comparison shell resizes iframe to content height
        try {{
          if (window.parent && window.parent !== window) {{
            window.parent.postMessage(
              {{ type: "dsm-ae-matrix-resize" }},
              window.location.origin
            );
          }}
        }} catch (e) {{}}
      }}

      // Restore last selection (by model id string)
      try {{
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {{
          const saved = JSON.parse(raw);
          if (Array.isArray(saved) && saved.length) {{
            const set = new Set(saved);
            const anyKnown = boxes.some((cb) =>
              set.has(cb.getAttribute("data-model") || "")
            );
            if (anyKnown) {{
              boxes.forEach((cb) => {{
                const model = cb.getAttribute("data-model") || "";
                // New models not in saved set stay visible (checked)
                if (model && set.has(model)) cb.checked = true;
                else if (model) cb.checked = false;
              }});
              // Ensure brand-new model ids remain on by default
              boxes.forEach((cb) => {{
                const model = cb.getAttribute("data-model") || "";
                if (model && !set.has(model)) cb.checked = true;
              }});
            }}
          }}
        }}
      }} catch (e) {{}}

      boxes.forEach((cb) => cb.addEventListener("change", apply));
      const allBtn = document.getElementById("model-filter-all");
      const noneBtn = document.getElementById("model-filter-none");
      const invBtn = document.getElementById("model-filter-invert");
      if (allBtn) allBtn.addEventListener("click", () => {{
        boxes.forEach((b) => {{ b.checked = true; }});
        apply();
      }});
      if (noneBtn) noneBtn.addEventListener("click", () => {{
        boxes.forEach((b) => {{ b.checked = false; }});
        apply();
      }});
      if (invBtn) invBtn.addEventListener("click", () => {{
        boxes.forEach((b) => {{ b.checked = !b.checked; }});
        apply();
      }});
      apply();
    }})();

    // Performance: do NOT load mermaid or render any SVG until a syndrome
    // section is opened. Sources live in <script type="text/plain"> so
    // startOnLoad cannot process hundreds of graphs on first paint.
    const MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js";
    let mermaidLoading = null;
    let mermaidReady = false;

    function loadMermaid() {{
      if (mermaidReady && window.mermaid) return Promise.resolve(window.mermaid);
      if (mermaidLoading) return mermaidLoading;
      mermaidLoading = new Promise((resolve, reject) => {{
        const s = document.createElement("script");
        s.src = MERMAID_CDN;
        s.async = true;
        s.onload = () => {{
          try {{
            window.mermaid.initialize({{
              startOnLoad: false,
              theme: "neutral",
              securityLevel: "loose",
              flowchart: {{ htmlLabels: true, curve: "basis", useMaxWidth: true }}
            }});
            mermaidReady = true;
            resolve(window.mermaid);
          }} catch (e) {{ reject(e); }}
        }};
        s.onerror = () => reject(new Error("Failed to load mermaid.js"));
        document.head.appendChild(s);
      }});
      return mermaidLoading;
    }}

    async function renderLazyIn(root) {{
      const wraps = root.querySelectorAll
        ? root.querySelectorAll("[data-lazy-mermaid]:not([data-rendered])")
        : [];
      if (!wraps.length) return;
      wraps.forEach((w) => {{
        const host = w.querySelector(".mermaid-host");
        if (host) {{
          host.hidden = false;
          host.innerHTML = '<div class="mermaid-loading">Loading decision tree…</div>';
        }}
      }});
      let m;
      try {{
        m = await loadMermaid();
      }} catch (e) {{
        wraps.forEach((w) => {{
          const host = w.querySelector(".mermaid-host");
          if (host) host.textContent = "Diagram library failed to load.";
        }});
        return;
      }}
      const nodes = [];
      wraps.forEach((w) => {{
        const srcEl = w.querySelector("script.mermaid-src");
        const host = w.querySelector(".mermaid-host");
        if (!srcEl || !host) return;
        const pre = document.createElement("pre");
        pre.className = "mermaid";
        pre.textContent = srcEl.textContent || "";
        host.innerHTML = "";
        host.appendChild(pre);
        nodes.push(pre);
        w.setAttribute("data-rendered", "1");
      }});
      if (nodes.length) {{
        try {{
          await m.run({{ nodes }});
        }} catch (e) {{
          console.warn("mermaid.run failed", e);
        }}
      }}
    }}

    document.querySelectorAll("details.syndrome").forEach((d) => {{
      d.addEventListener("toggle", () => {{
        if (d.open) renderLazyIn(d);
      }});
      if (d.open) renderLazyIn(d);
    }});

    /** Scroll target into view; when full-height iframe embed, also scroll parent. */
    function jumpTo(el) {{
      if (!el) return;
      el.scrollIntoView({{ behavior: "smooth", block: "start" }});
      try {{
        if (window.parent && window.parent !== window) {{
          const iframe = window.frameElement;
          if (iframe) {{
            const rect = el.getBoundingClientRect();
            const iframeRect = iframe.getBoundingClientRect();
            const parentDoc = window.parent.document.documentElement;
            const parentScroll =
              window.parent.pageYOffset || parentDoc.scrollTop || 0;
            const top = parentScroll + iframeRect.top + rect.top - 16;
            window.parent.scrollTo({{ top: Math.max(0, top), behavior: "smooth" }});
            // Notify shell to remeasure iframe height after open/expand.
            try {{
              window.parent.postMessage(
                {{ type: "dsm-ae-matrix-resize" }},
                window.location.origin
              );
            }} catch (e) {{}}
          }}
        }}
      }} catch (e) {{ /* cross-origin */ }}
    }}

    function openAndJump(el) {{
      if (!el) return;
      if (el.tagName === "DETAILS") {{
        const wasOpen = el.open;
        el.open = true;
        if (el.classList.contains("syndrome")) {{
          renderLazyIn(el);
        }}
        // Wait a frame (and a bit more if newly opened) so layout includes body.
        requestAnimationFrame(() => {{
          jumpTo(el);
          if (!wasOpen) {{
            setTimeout(() => jumpTo(el), 50);
            setTimeout(() => jumpTo(el), 250);
          }}
        }});
      }} else {{
        jumpTo(el);
      }}
    }}

    function resolveHash(hash) {{
      if (!hash || hash === "#") return null;
      const id = hash.startsWith("#") ? hash.slice(1) : hash;
      return document.getElementById(id);
    }}

    function openHash() {{
      const el = resolveHash(location.hash);
      if (el) openAndJump(el);
    }}

    // Intercept in-page anchors so we expand + jump even when hash is unchanged.
    document.addEventListener("click", (ev) => {{
      const a = ev.target.closest('a[href^="#"]');
      if (!a) return;
      const href = a.getAttribute("href") || "";
      if (href.length < 2) return;
      const el = resolveHash(href);
      if (!el) return;
      ev.preventDefault();
      if (location.hash !== href) {{
        history.pushState(null, "", href);
      }}
      openAndJump(el);
    }});

    window.addEventListener("hashchange", openHash);
    window.addEventListener("popstate", openHash);
    // Initial load with #syndrome-…
    if (document.readyState === "loading") {{
      document.addEventListener("DOMContentLoaded", openHash);
    }} else {{
      openHash();
    }}
  }})();
  </script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        default=[Path("reports")],
        help="JSON files or directories (default: reports/)",
    )
    ap.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("reports/dsm-ae-matrix.html"),
        help="Output HTML path",
    )
    ap.add_argument("--title", default="DSM-AE Multi-Model Report")
    ap.add_argument(
        "--include-mock",
        action="store_true",
        help="Include mock/* models (excluded by default)",
    )
    args = ap.parse_args(argv)

    paths = discover_jsons(list(args.inputs))
    reports: list[dict[str, Any]] = []
    for p in paths:
        rep = load_report(p)
        if not rep:
            continue
        mid = model_id(rep)
        if (not args.include_mock) and mid.startswith("mock/"):
            continue
        if mid in _EXCLUDED_MODELS:
            continue
        reports.append(rep)

    if not reports:
        print("No diagnosis JSON reports found.", file=sys.stderr)
        return 1

    by_model = merge_reports(reports)
    html_doc = build_html(by_model, title=args.title)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {args.out} ({len(by_model)} models, {len(reports)} json files)")
    models, metrics, findings, packs = collect_universe_fixed(by_model)
    print(f"  models: {', '.join(models)}")
    print(f"  packs: {len(packs)}, metrics: {len(metrics)}, syndromes: {len(findings)}")
    print(f"  decision trees: {len(SYNDROME_TREES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
