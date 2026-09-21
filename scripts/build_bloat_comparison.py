#!/usr/bin/env python3
"""Build Comparison tab: baseline vs context-bloat 50% (side-by-side metrics).

Writes:
  reports/bloat/bloat50/comparison.html
  reports/bloat/bloat50/{model}.json  (assembled from scores.json / checkpoints)
  reports/bloat/bloat50/baseline_k10/{model}.json  (clean k=10 repro-shared only)

**Baseline policy (v2 fair):** ONLY ``reports/repro-shared/{model}/**/trial_*.json``
(k=10 mini-testbeds). Does **not** pool suite/queue/root historic runs
(that dilution made bloat look better than it was).

Default models: work/* when present, else pre-assembled reports/bloat/bloat50/*.json
(after worktrees are purged). Default packs: only packs with full k checkpoints when
re-assembling from work; otherwise packs from each assembled JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "scripts"))

from dsm_ae.criteria import evaluate_findings  # noqa: E402
from dsm_ae.metrics.bootstrap import bootstrap_metric, build_gate_matrix  # noqa: E402
from dsm_ae.models import MetricResult  # noqa: E402
from dsm_ae.packs.registry import list_packs  # noqa: E402
from dsm_ae.report import render_markdown  # noqa: E402
from json_to_html_report import (  # noqa: E402
    build_html,
    discover_jsons,
    load_report,
    merge_reports,
    model_id,
)


def _ckpt_count(work: Path, pack: str, k: int) -> int:
    ck = work / ".dsm_ae_ckpt"
    if not ck.is_dir():
        return 0
    return sum(1 for t in range(k) if (ck / f"{pack}__t{t}.json").is_file())


def packs_complete_for_model(work: Path, packs: list[str], k: int) -> list[str]:
    return [p for p in packs if _ckpt_count(work, p, k) >= k]


def _load_scores_for_trial(work: Path, pack: str, trial: int) -> list[MetricResult]:
    """Load MetricResults from scores.json or lightweight checkpoint items."""
    scores_path = work / "trajectories" / f"{pack}__t{trial}" / "scores.json"
    if scores_path.is_file():
        try:
            raw = json.loads(scores_path.read_text(encoding="utf-8"))
            if isinstance(raw, list) and raw:
                return [MetricResult.model_validate(m) for m in raw]
        except Exception:
            pass
    # Fallback: checkpoint items (skip heavy Trace validation when possible)
    ck = work / ".dsm_ae_ckpt" / f"{pack}__t{trial}.json"
    if not ck.is_file():
        return []
    try:
        raw = json.loads(ck.read_text(encoding="utf-8"))
        items = raw.get("items") or []
        out: list[MetricResult] = []
        for it in items:
            for m in it.get("scores") or []:
                out.append(MetricResult.model_validate(m))
        return out
    except Exception:
        return []


def assemble_bloat_report(
    *,
    model: str,
    work: Path,
    packs: list[str],
    k: int,
    level: float,
) -> dict[str, Any] | None:
    """Assemble a DiagnosisReport-shaped dict from existing trial scores."""
    if not packs:
        return None
    bucket: dict[str, list[MetricResult]] = {}
    loaded = 0
    for pack in packs:
        for t in range(k):
            scores = _load_scores_for_trial(work, pack, t)
            if not scores:
                continue
            loaded += 1
            for m in scores:
                bucket.setdefault(m.metric_id, []).append(m)
    if not bucket:
        return None

    boots = [
        bootstrap_metric(
            mid,
            mid,
            results,
            threshold_pass=0.8,
            threshold_std=0.25,
        )
        for mid, results in bucket.items()
    ]
    boots.sort(key=lambda b: b.metric_id)
    gates = build_gate_matrix(boots)
    findings = evaluate_findings(boots)

    report = {
        "run_id": str(uuid.uuid4()),
        "scaffold_card": {
            "model": model,
            "scaffold": "raw",
            "permission_mode": "default",
            "k_trials": k,
            "max_turns": 10,
            "extra": {
                "context_bloat": {
                    "level": level,
                    "model": model,
                    "token_method": "char4",
                    "seed": 42,
                    "overflow_is_fail": True,
                },
                "assembled_from_scores": True,
            },
        },
        "packs": list(packs),
        "k_trials": k,
        "gates": [g.model_dump(mode="json") for g in gates],
        "findings": [f.model_dump(mode="json") for f in findings],
        "bootstraps": [b.model_dump(mode="json") for b in boots],
        "traces": [],
        "notes": [
            f"Assembled from scores under {work} (no re-LLM).",
            f"Packs ({len(packs)}): {', '.join(packs)}",
            f"Trials loaded: {loaded}/{len(packs) * k}",
            f"Context bloat level={level}",
        ],
    }
    return report


def _relabel(rep: dict[str, Any], label: str) -> dict[str, Any]:
    out = dict(rep)
    card = dict(out.get("scaffold_card") or {})
    card["model"] = label
    out["scaffold_card"] = card
    out["model"] = label
    return out


def _filter_metrics(rep: dict[str, Any], keep: set[str]) -> dict[str, Any]:
    if not keep:
        return rep
    out = dict(rep)
    out["gates"] = [g for g in (rep.get("gates") or []) if g.get("metric_id") in keep]
    out["bootstraps"] = [
        b for b in (rep.get("bootstraps") or []) if b.get("metric_id") in keep
    ]
    return out


def _metric_ids(rep: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for b in rep.get("bootstraps") or []:
        if b.get("metric_id"):
            ids.add(str(b["metric_id"]))
    for g in rep.get("gates") or []:
        mid = g.get("metric_id") or g.get("dimension")
        if mid:
            ids.add(str(mid))
    return ids



def _pack_from_repro_dirname(name: str) -> str | None:
    """Map RSD_sycophancy_mini_n10 → sycophancy_mini."""
    # strip trailing _n10 / _nN
    base = name
    if "_n" in base:
        base = base.rsplit("_n", 1)[0]
    # known prefixes from summarize_repro / run scripts
    prefixes = (
        "CSO_", "CTX_", "CVF_", "EGD_", "GDD_", "ISDS2_", "ISDS3_", "ISDS_",
        "MAH_", "MCD_", "MEM_", "MRC_", "MVF_", "NFR_", "OASD_", "PCD_", "PII_",
        "RSD_", "SBG_", "TID2_", "TID_", "XPI_",
    )
    for p in prefixes:
        if base.startswith(p):
            return base[len(p):]
    return base if base else None


def load_repro_shared_k10_reports(
    reports_dir: Path,
    models: list[str],
    *,
    k: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    """Load only clean k=10 repro-shared trial_*.json files per model.

    Does not include suite/queue/root diagnosis JSONs.
    """
    repro_root = reports_dir / "repro-shared"
    by_model: dict[str, list[dict[str, Any]]] = {}
    if not repro_root.is_dir():
        return by_model
    for model in models:
        mdir = repro_root / model
        if not mdir.is_dir():
            # try underscore variants
            alt = repro_root / model.replace(".", "_")
            mdir = alt if alt.is_dir() else mdir
        if not mdir.is_dir():
            continue
        for pack_dir in sorted(mdir.iterdir()):
            if not pack_dir.is_dir() or pack_dir.name.startswith("."):
                continue
            if f"_n{k}" not in pack_dir.name and not pack_dir.name.endswith(f"_n{k}"):
                # require n10 style dirs
                continue
            trials = sorted(pack_dir.glob("trial_*.json"))
            if len(trials) < k:
                # allow partial but prefer full k
                pass
            for tp in trials:
                rep = load_report(tp)
                if not rep:
                    continue
                mid = model_id(rep)
                # normalize to requested model name if scaffold missing
                if mid not in models and mid.replace("_", ".") not in models:
                    # force model label from directory
                    card = dict(rep.get("scaffold_card") or {})
                    card["model"] = model
                    rep["scaffold_card"] = card
                    mid = model
                if mid not in models:
                    # directory is source of truth for which model arm
                    card = dict(rep.get("scaffold_card") or {})
                    card["model"] = model
                    rep["scaffold_card"] = card
                    mid = model
                by_model.setdefault(model, []).append(rep)
    return by_model


def assemble_baseline_k10_report(
    model: str,
    trial_reports: list[dict[str, Any]],
    *,
    k: int = 10,
) -> dict[str, Any] | None:
    """Merge only k=10 repro trial reports into one DiagnosisReport-shaped dict."""
    if not trial_reports:
        return None
    # Use merge_reports then convert back to a single report-like dict for labeling
    labeled = []
    for r in trial_reports:
        card = dict(r.get("scaffold_card") or {})
        card["model"] = model
        r = dict(r)
        r["scaffold_card"] = card
        labeled.append(r)
    merged = merge_reports(labeled)
    acc = merged.get(model)
    if not acc:
        return None
    # gates may be dict after merge_reports path in by_model — rebuild list
    gates = acc.get("gates") or {}
    if isinstance(gates, dict):
        gate_list = list(gates.values())
    else:
        gate_list = gates
    boots = acc.get("bootstraps") or {}
    if isinstance(boots, dict):
        boot_list = list(boots.values())
    else:
        boot_list = boots
    findings = acc.get("findings") or {}
    if isinstance(findings, dict):
        find_list = list(findings.values())
    else:
        find_list = findings
    packs = sorted(acc.get("packs") or set())
    return {
        "run_id": str(uuid.uuid4()),
        "scaffold_card": {
            "model": model,
            "scaffold": "raw",
            "permission_mode": "default",
            "k_trials": k,
            "max_turns": 10,
            "extra": {
                "baseline_source": "repro-shared_k10_only",
                "n_trial_files": len(trial_reports),
            },
        },
        "packs": packs,
        "k_trials": k,
        "gates": gate_list,
        "findings": find_list,
        "bootstraps": boot_list,
        "traces": [],
        "notes": [
            f"Clean k={k} baseline assembled only from reports/repro-shared/{model}/**/trial_*.json",
            f"Trial files: {len(trial_reports)}",
            "Does NOT include suite/queue/root historic pooling.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports-dir", type=Path, default=Path("reports"))
    ap.add_argument("--level", type=float, default=0.5)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--models", default=None, help="Comma models (default: work/*)")
    ap.add_argument(
        "--include-incomplete-packs",
        action="store_true",
        help="Include packs without full k checkpoints",
    )
    ap.add_argument(
        "--baseline-mode",
        choices=("repro_k10", "all_reports"),
        default="repro_k10",
        help="Baseline source: clean repro-shared k=10 only (default) or legacy all reports/ pool",
    )
    args = ap.parse_args(argv)

    reports_dir = args.reports_dir.resolve()
    tag = f"bloat{int(round(args.level * 100))}"
    bloat_root = reports_dir / "bloat" / tag
    work_root = bloat_root / "work"
    has_work = work_root.is_dir()

    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    elif has_work:
        models = sorted(
            p.name
            for p in work_root.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )
    else:
        # Assembled JSON only (work trees purged after freeze)
        models = sorted(
            {
                p.stem
                for p in bloat_root.glob("*.json")
                if p.is_file() and not p.name.startswith(".")
            }
        )
        if not models:
            print(
                f"No bloat work dir at {work_root} and no assembled *.json under {bloat_root}",
                file=sys.stderr,
            )
            return 1
        print(
            f"No work tree; using pre-assembled {bloat_root}/*.json "
            f"({len(models)} models)",
            flush=True,
        )

    all_packs = list_packs()
    bloat_reports: list[dict[str, Any]] = []
    pack_union: set[str] = set()

    for model in models:
        work = work_root / model.replace("/", "_") if has_work else None
        out_json = bloat_root / f"{model}.json"
        rep: dict[str, Any] | None = None
        packs: list[str] = []

        if work is not None and work.is_dir():
            if args.include_incomplete_packs:
                packs = list(all_packs)
            else:
                packs = packs_complete_for_model(work, all_packs, args.k)
            pack_union.update(packs)
            rep = assemble_bloat_report(
                model=model, work=work, packs=packs, k=args.k, level=args.level
            )
            if rep:
                out_json.parent.mkdir(parents=True, exist_ok=True)
                out_json.write_text(json.dumps(rep, indent=2), encoding="utf-8")
                out_md = bloat_root / f"{model}.md"
                try:
                    from dsm_ae.models import DiagnosisReport

                    out_md.write_text(
                        render_markdown(DiagnosisReport.model_validate(rep)),
                        encoding="utf-8",
                    )
                except Exception:
                    out_md.write_text(
                        f"# {model} bloat{int(round(args.level * 100))}\n\n"
                        f"Packs: {', '.join(packs)}\n",
                        encoding="utf-8",
                    )
        elif out_json.is_file():
            try:
                rep = json.loads(out_json.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"  {model}: bad assembled json ({e})", file=sys.stderr)
                continue
            packs = list(rep.get("packs") or [])
            pack_union.update(packs)
            print(f"  {model}: loaded pre-assembled {out_json}", flush=True)
        else:
            print(f"  {model}: missing work dir and {out_json}", file=sys.stderr)
            continue

        if not rep:
            print(f"  {model}: no scores assembled", file=sys.stderr)
            continue
        rep["_source_path"] = str(out_json)
        bloat_reports.append(rep)
        print(
            f"  {model}: packs={len(packs)} gates={len(rep.get('gates') or [])} → {out_json}"
        )

    if not bloat_reports:
        print("No bloat reports to compare", file=sys.stderr)
        return 1

    bloat_metrics: set[str] = set()
    for rep in bloat_reports:
        bloat_metrics |= _metric_ids(rep)

    labeled: list[dict[str, Any]] = []
    pct = int(round(args.level * 100))
    baseline_mode = getattr(args, "baseline_mode", "repro_k10")

    if baseline_mode == "repro_k10":
        repro = load_repro_shared_k10_reports(reports_dir, models, k=args.k)
        baseline_root = bloat_root / "baseline_k10"
        baseline_root.mkdir(parents=True, exist_ok=True)
        for model in models:
            trials = repro.get(model) or []
            print(f"  {model}: clean k10 baseline trial files={len(trials)}")
            if not trials:
                print(f"  {model}: no repro-shared k10 baseline", file=sys.stderr)
            else:
                assembled = assemble_baseline_k10_report(model, trials, k=args.k)
                if assembled:
                    out_b = baseline_root / f"{model}.json"
                    out_b.write_text(json.dumps(assembled, indent=2), encoding="utf-8")
                    assembled["_source_path"] = str(out_b)
                    labeled.append(
                        _relabel(
                            _filter_metrics(assembled, bloat_metrics),
                            f"{model} · baseline k10",
                        )
                    )
                    print(f"  {model}: wrote clean baseline → {out_b}")
    else:
        # Legacy polluted pool (explicit opt-in only)
        baseline_paths = discover_jsons([reports_dir])
        baseline_by_model: dict[str, list[dict[str, Any]]] = {}
        for p in baseline_paths:
            rep = load_report(p)
            if not rep:
                continue
            mid = model_id(rep)
            if mid in models:
                baseline_by_model.setdefault(mid, []).append(rep)
        for model in models:
            for rep in baseline_by_model.get(model) or []:
                labeled.append(
                    _relabel(
                        _filter_metrics(rep, bloat_metrics),
                        f"{model} · baseline polluted",
                    )
                )
            if model not in baseline_by_model:
                print(f"  {model}: no baseline reports found", file=sys.stderr)

    for model in models:
        bloat_rep = next(
            (r for r in bloat_reports if model_id(r) == model),
            None,
        )
        if bloat_rep is None:
            for r in bloat_reports:
                src = r.get("_source_path") or ""
                if model in Path(src).name:
                    bloat_rep = r
                    break
        if bloat_rep is not None:
            labeled.append(
                _relabel(
                    _filter_metrics(bloat_rep, bloat_metrics),
                    f"{model} · bloat{pct}%",
                )
            )

    if not labeled:
        print("Nothing to merge", file=sys.stderr)
        return 1

    by_model = merge_reports(labeled)
    ordered: dict[str, dict[str, Any]] = {}
    for model in models:
        for suffix in (
            f"{model} · baseline k10",
            f"{model} · baseline polluted",
            f"{model} · baseline",
            f"{model} · bloat{pct}%",
        ):
            if suffix in by_model:
                ordered[suffix] = by_model[suffix]
    for mid, acc in by_model.items():
        if mid not in ordered:
            ordered[mid] = acc

    title = (
        f"Context Bloat — clean k10 baseline vs {pct}% "
        f"(packs: {len(pack_union)}; baseline={baseline_mode})"
    )
    html_doc = build_html(ordered, title=title)
    out_html = bloat_root / "comparison.html"
    out_html.write_text(html_doc, encoding="utf-8")
    print(
        f"Wrote {out_html} ({len(ordered)} columns, {len(bloat_metrics)} metrics, "
        f"{len(pack_union)} packs)"
    )
    print(f"  columns: {', '.join(ordered.keys())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
