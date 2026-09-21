"""Import Harbor reward.json(s) under a harbor_runs job (or reward dir) into DSM-AE DiagnosisReport-shaped dict.

Task 5.
- reward floats (0/1 primary + metric values) are turned into synthetic MetricResult rows.
- Uses bootstrap + gate + findings logic so the result is compatible with json_to_html_report / Comparison.
- k_trials inferred from number of per-trial rewards or passed explicitly.
- Offline only; no harbor CLI.

Functions:
  reward_dir_to_report(reward_dir: Path, *, model: str, pack_id: str | None = None, k: int | None = None) -> dict
  import_harbor_run(job_id: str, *, reports_dir: Path | None = None, model: str | None = None) -> dict

CLI:
  python -m dsm_ae.harbor.import_rewards --job-id <jid> [--model M] [--out path.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import uuid4

# make importable as module or -m
if __name__ == "__main__" or "dsm_ae" not in str(Path(__file__)):
    _root = Path(__file__).resolve().parents[3]
    if str(_root / "src") not in sys.path:
        sys.path.insert(0, str(_root / "src"))

from dsm_ae.criteria import evaluate_findings
from dsm_ae.harbor.run_layout import harbor_run_dir
from dsm_ae.metrics.bootstrap import bootstrap_metric, build_gate_matrix
from dsm_ae.models import MetricResult
from dsm_ae.packs.registry import list_packs

# Tier suffixes written by pack_bridge.write_reward as "_" (metric dots → underscores).
_TIER_SUFFIXES = ("tier1", "tier2", "tier3")


def reward_key_to_metric_id(key: str) -> str:
    """Inverse of ``write_reward``'s ``metric_id.replace(".", "_")``.

    Only the *tier* segment uses a dot in canonical DSM-AE ids
    (``task_tool_success.tier2``, ``erosion_indicator.tier1``). Everything else
    keeps underscores (``acknowledges_sensitive``, ``files_read_complete``).

    The previous importer naively did ``key.replace("_", ".")``, which produced
    ghost metrics (``acknowledges.sensitive``) that broke criteria matching and
    duplicated matrix rows next to the real underscore ids.
    """
    k = (key or "").strip()
    if not k or k == "primary_pass":
        return k
    for tier in _TIER_SUFFIXES:
        suffix = f"_{tier}"
        if k.endswith(suffix):
            return f"{k[: -len(suffix)]}.{tier}"
    return k


def normalize_metric_id(mid: str) -> str:
    """Repair already-imported dotted ids and pass through canonical ones.

    - ``acknowledges.sensitive`` → ``acknowledges_sensitive``
    - ``critical.preserved.tier1`` → ``critical_preserved.tier1``
    - ``task_tool_success.tier2`` → unchanged
    - ``files_read_complete`` → unchanged
    """
    m = (mid or "").strip()
    if not m or m == "primary_pass" or "." not in m:
        return m
    for tier in _TIER_SUFFIXES:
        suffix = f".{tier}"
        if m.endswith(suffix):
            base = m[: -len(suffix)].replace(".", "_")
            return f"{base}.{tier}"
    return m.replace(".", "_")


def _reward_to_metric_results(reward: dict[str, Any], pack_hint: str | None = None) -> list[MetricResult]:
    """Turn a single harbor reward dict (floats) into list of synthetic MetricResult.

    primary_pass is used to influence overall but per-metric we use the value.
    Reward keys use underscores (see write_reward); restore only ``.tierN`` dots.
    passed heuristic: for [0,1] values use >= 0.5; for other floats use value > 0.
    """
    results: list[MetricResult] = []

    for key, val in reward.items():
        # primary_pass stays in reward.json for Harbor verifiers only — do not
        # promote it into the diagnosis gate matrix (not a pack metric).
        if key == "primary_pass":
            continue
        if not isinstance(val, (int, float)):
            continue
        v = float(val)
        mid = reward_key_to_metric_id(str(key))
        if mid == "primary_pass":
            continue
        passed = bool(v >= 0.5) if v in (0.0, 1.0) or (0.0 <= v <= 1.0) else (v > 0.0)
        results.append(
            MetricResult(
                metric_id=mid,
                value=v,
                passed=passed,
                explanation=f"harbor import value={v} (from reward key {key})",
            )
        )
    return results


def _infer_pack_from_filename(fn: str) -> str | None:
    # filename like hello_metacog__t0.json or tool_integrity_tier2__t1.json
    base = fn.rsplit(".", 1)[0]
    if "__t" in base:
        return base.split("__t", 1)[0]
    return None


def reward_dir_to_report(
    path: Path,
    *,
    model: str,
    pack_id: str | None = None,
    k: int | None = None,
    threshold_pass: float = 0.8,
    threshold_std: float = 0.25,
) -> dict[str, Any]:
    """Build DiagnosisReport-shaped dict from a dir containing reward json files (or a single reward.json).

    Scans *.json under path (or uses path if file). Groups metrics.
    If pack_id given, only include matching; else aggregate all found.
    """
    p = Path(path)
    rewards: list[tuple[str, dict[str, Any]]] = []

    if p.is_file() and p.suffix == ".json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            pk = pack_id or _infer_pack_from_filename(p.name) or "unknown"
            rewards.append((pk, data))
        except Exception:
            pass
    elif p.is_dir():
        # Prefer rewards/ subdir (canonical harbor_runs layout)
        candidates = []
        rewdir = p / "rewards"
        if rewdir.is_dir():
            candidates = sorted(rewdir.glob("*.json"))
        else:
            candidates = sorted(p.glob("*.json"))
        for jf in candidates:
            if not jf.name.endswith(".json"):
                continue
            # skip meta / other non-reward jsons by name heuristic
            if jf.name in ("meta.json", "docker_cleanup.json", "reward.json"):
                # still allow top-level reward.json as fallback
                if jf.name == "reward.json" and not rewdir.is_dir():
                    pass
                else:
                    if rewdir.is_dir():
                        continue
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                pk = pack_id or _infer_pack_from_filename(jf.name) or "unknown"
                if pack_id and pk != pack_id:
                    continue
                rewards.append((pk, data))
            except Exception:
                continue
    else:
        # fallback (should not reach for normal paths)
        rewdir = p / "rewards"
        if rewdir.is_dir():
            for jf in sorted(rewdir.glob("*.json")):
                try:
                    data = json.loads(jf.read_text(encoding="utf-8"))
                    pk = pack_id or _infer_pack_from_filename(jf.name) or "unknown"
                    if pack_id and pk != pack_id:
                        continue
                    rewards.append((pk, data))
                except Exception:
                    continue

    if not rewards:
        # return minimal empty shaped report
        card = {"model": model, "k_trials": k or 1, "scaffold": "raw"}
        return {
            "run_id": str(uuid4()),
            "scaffold_card": card,
            "packs": [pack_id] if pack_id else [],
            "k_trials": k or 0,
            "gates": [],
            "findings": [],
            "bootstraps": [],
            "traces": [],
            "notes": ["no rewards found under " + str(path)],
        }

    # group by metric
    bucket: dict[str, list[MetricResult]] = defaultdict(list)
    seen_packs: set[str] = set()
    for pk, rew in rewards:
        seen_packs.add(pk)
        for mr in _reward_to_metric_results(rew, pack_hint=pk):
            bucket[mr.metric_id].append(mr)

    n_trials = len(rewards) if k is None else k
    packs_list = sorted(seen_packs) if seen_packs else ([pack_id] if pack_id else list(list_packs())[:1])

    boots = [
        bootstrap_metric(
            mid,
            mid,  # dimension == metric for imported (no pack dimension map here)
            results,
            threshold_pass=threshold_pass,
            threshold_std=threshold_std,
        )
        for mid, results in sorted(bucket.items())
    ]
    gates = build_gate_matrix(boots)
    findings = evaluate_findings(boots)

    card = {
        "model": model,
        "scaffold": "raw",
        "permission_mode": "auto",
        "k_trials": n_trials,
        "max_turns": 10,
        "extra": {"imported_from_harbor": True},
    }

    report = {
        "run_id": str(uuid4()),
        "scaffold_card": card,
        "packs": packs_list,
        "k_trials": n_trials,
        "gates": [g.model_dump(mode="json") for g in gates],
        "findings": [f.model_dump(mode="json") for f in findings],
        "bootstraps": [b.model_dump(mode="json") for b in boots],
        "traces": [],
        "notes": [
            f"Imported from Harbor rewards under {path}",
            f"model={model}",
            f"trials_aggregated={len(rewards)}",
        ],
    }
    return report


def import_harbor_run(
    job_id: str,
    *,
    reports_dir: Path | None = None,
    model: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience: load the full harbor_runs/{job_id} tree and build report dict.

    Uses meta.json for model/packs/k if present.
    """
    root = harbor_run_dir(job_id, reports_dir=reports_dir)
    meta_path = root / "meta.json"
    meta_model = None
    meta_packs = None
    meta_k = None
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta_model = meta.get("model")
            meta_packs = meta.get("packs")
            meta_k = meta.get("k_trials")
        except Exception:
            pass

    m = model or meta_model or "mock/unknown"
    packs = meta_packs or []

    # Prefer scanning the job root (reward_dir_to_report will look in rewards/)
    rep = reward_dir_to_report(
        root,
        model=m,
        pack_id=None,  # aggregate all packs in the run
        k=meta_k,
        **{k: v for k, v in kwargs.items() if k in ("threshold_pass", "threshold_std")},
    )
    # enrich with packs from meta if better
    if packs and not rep.get("packs"):
        rep["packs"] = packs
    if meta_k is not None:
        rep["k_trials"] = meta_k
        if isinstance(rep.get("scaffold_card"), dict):
            rep["scaffold_card"]["k_trials"] = meta_k
    rep.setdefault("notes", []).append(f"job_id={job_id}")
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import Harbor run rewards into DSM-AE report JSON (Task 5)")
    ap.add_argument("--job-id", required=True, help="job id under reports/harbor_runs/")
    ap.add_argument("--model", default=None, help="override model in scaffold_card (else from meta)")
    ap.add_argument("--reports-dir", type=Path, default=None, help="base reports/ (default ./reports)")
    ap.add_argument("--out", type=Path, default=None, help="write the report json here")
    ap.add_argument("--print", action="store_true", help="also print to stdout")
    args = ap.parse_args(argv)

    try:
        rep = import_harbor_run(job_id=args.job_id, reports_dir=args.reports_dir, model=args.model)
    except Exception as e:
        print(f"import failed: {e}", file=sys.stderr)
        return 2

    text = json.dumps(rep, indent=2, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")

    if args.print or not args.out:
        print(text)

    # quick validation note
    if rep.get("gates") or rep.get("bootstraps"):
        print(f"\n# summary: packs={rep.get('packs')} gates={len(rep.get('gates', []))} bootstraps={len(rep.get('bootstraps', []))}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
