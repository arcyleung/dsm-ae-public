#!/usr/bin/env python3
"""
Harbor job runner for DSM-AE packs (Task 4).

Orchestrates k trials (outer loop) over packs for a single job_id.

- Writes artifacts to reports/harbor_runs/{job_id}/rewards/{pack}__t{i}.json
  and trajectories/{pack}__t{i}/...
- Uses run_harbor_task wrapper (guarantees cleanup_docker_for_job in finally)
- Offline mock supported: task_fn that calls pack_bridge.prepare_workspace + score_workspace
  (no harbor CLI, no docker required). Uses MockClient via bridge.
- For real harbor runs: pass a task_fn that invokes `harbor run` (the fn receives the job run_dir).
- Docker containers (when used) must be started with:
    --label dsm-ae.harbor.job={job_id}
  (or harbor equivalent). Cleanup always happens.

CLI:
  python scripts/harbor_run_job.py --job-id abc12def --model mock/well_attuned \
      --packs hello_metacog,tool_integrity_tier2 --k 3
  # or with --base /tmp/harbor_test for sandbox

Returns the job root path on success. Exits non-zero on failure (but cleanup ran).

See:
- harbor_tasks/dsm-ae/README.md
- src/dsm_ae/harbor/runner.py
- .superpowers/sdd/task-4-brief.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ensure src importable when run as script
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from dsm_ae.harbor.pack_bridge import prepare_workspace, score_workspace, write_reward
from dsm_ae.harbor.run_layout import init_run, finalize_meta
from dsm_ae.harbor.runner import run_harbor_task
from dsm_ae.queue.progress import write_progress


def _infer_persona(model: str) -> str:
    if model.startswith("mock/"):
        p = model.split("/", 1)[1] or "well_attuned"
        return p
    # For live models, default well_attuned for mock scoring in offline paths;
    # real agent phase will not use this persona.
    return "well_attuned"


def _trial_task_fn(
    pack_id: str,
    trial_index: int,
    model: str,
    *,
    models_yaml: Path | None = None,
    force_rerun: bool = False,
):
    """Return a task_fn for run_harbor_task: mock or live LLM trial + reward.

    - model starting with ``mock/`` → offline MockClient
    - otherwise → live LiteLLM via models.yaml (trajectories + litellm under
      harbor_runs/{job_id}/trajectories/{pack}__t{i}/)
    """
    persona = _infer_persona(model)
    live = not model.startswith("mock/")

    def task_fn(run_dir: Path) -> dict[str, Any]:
        (run_dir / "rewards").mkdir(parents=True, exist_ok=True)
        (run_dir / "trajectories").mkdir(parents=True, exist_ok=True)

        prepare_workspace(pack_id, run_dir, trial_index, mock_persona=persona)
        metrics = score_workspace(
            pack_id,
            run_dir,
            trial_index,
            model=model if live else None,
            models_yaml=models_yaml,
            force_rerun=force_rerun,
        )

        tmp_rew = run_dir / f".tmp_reward_{pack_id}__t{trial_index}.json"
        write_reward(metrics, tmp_rew)
        reward = json.loads(tmp_rew.read_text(encoding="utf-8"))
        try:
            tmp_rew.unlink()
        except Exception:
            pass
        return reward

    return task_fn


def run_harbor_job(
    *,
    job_id: str,
    model: str,
    packs: list[str],
    k: int = 1,
    run_dir_base: Path | None = None,
    reports_dir: Path | None = None,
    models_yaml: Path | None = None,
    force_rerun: bool = False,
    progress_path: Path | None = None,
    progress_paths: list[Path] | None = None,
    on_progress: Any | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> Path:
    """Run k outer-loop trials for the given packs under one job_id.

    Always ensures cleanup (via runner). Returns the harbor_runs/{job_id} root.
    - mock/* models: offline MockClient
    - other models: live LiteLLM via models.yaml

    Progress is written in the same shape as the queue UI indicator
    (``done`` / ``total`` / ``percent`` / ``message`` / ``phase`` / ``status``)
    via :func:`dsm_ae.queue.progress.write_progress`. Optionally dual-write to
    several paths (queue progress + harbor_runs/.../progress.json) and/or call
    ``on_progress(payload)``.
    """
    if not job_id or not packs:
        raise ValueError("job_id and packs required")
    k = max(1, int(k))
    total = len(packs) * k
    done = 0
    paths: list[Path] = []
    if progress_path is not None:
        paths.append(Path(progress_path))
    if progress_paths:
        paths.extend(Path(p) for p in progress_paths)

    def _progress(msg: str, **extra: Any) -> None:
        payload: dict[str, Any] = {
            "job_id": job_id,
            "model": model,
            "runner": "harbor",
            "done": done,
            "total": total,
            "message": msg,
            "packs": packs,
            "k": k,
            **extra,
        }
        # drop None so JSON stays clean for UI
        payload = {kk: vv for kk, vv in payload.items() if vv is not None}
        print(f"[harbor_run_job] {msg} ({done}/{total})", flush=True)
        for p in paths:
            try:
                write_progress(p, payload)
            except Exception as e:
                print(f"[harbor_run_job] progress write failed {p}: {e}", flush=True)
        if on_progress is not None:
            try:
                on_progress(payload)
            except Exception as e:
                print(f"[harbor_run_job] on_progress failed: {e}", flush=True)

    # Initialize once (records full context); subsequent runner calls will update meta/status
    root = init_run(
        job_id,
        reports_dir=reports_dir,
        base=run_dir_base,
        model=model,
        packs=packs,
        k_trials=k,
        live=not model.startswith("mock/"),
        models_yaml=str(models_yaml) if models_yaml else None,
        **(extra_meta or {}),
    )
    _progress("starting", status="running", phase="start")

    overall_status = "succeeded"
    errors: list[str] = []

    try:
        for pack_id in packs:
            for ti in range(k):
                _progress(
                    f"pack={pack_id} trial={ti + 1}/{k} model={model}",
                    status="running",
                    phase="running",
                    current_pack=pack_id,
                    current_trial=ti,
                )
                tf = _trial_task_fn(
                    pack_id,
                    ti,
                    model,
                    models_yaml=models_yaml,
                    force_rerun=force_rerun,
                )
                try:
                    run_harbor_task(
                        job_id=job_id,
                        model=model,
                        packs=packs,
                        run_dir_base=run_dir_base,
                        reports_dir=reports_dir,
                        task_fn=tf,
                        pack_id=pack_id,
                        trial_i=ti,
                    )
                except Exception as e:
                    errors.append(f"{pack_id}__t{ti}: {e}")
                    overall_status = "partial"
                done += 1
                _progress(
                    f"finished {pack_id} t{ti}",
                    status="running",
                    phase="running",
                    current_pack=pack_id,
                    current_trial=ti,
                    errors=errors[-5:] if errors else None,
                )

        finalize_meta(
            root,
            {
                "status": overall_status if not errors else "partial",
                "k_trials": k,
                "errors": errors if errors else None,
            },
        )
        _progress(
            f"complete status={overall_status} errors={len(errors)}",
            status=overall_status if not errors else "partial",
            phase="done",
            errors=errors if errors else None,
        )
        if errors:
            print(f"[harbor_run_job] completed with {len(errors)} trial errors", flush=True)
    finally:
        pass

    return root


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Run DSM-AE packs as Harbor job (k trials; mock or live LLM)"
    )
    p.add_argument("--job-id", required=True, help="Job id for reports/harbor_runs/{job_id}")
    p.add_argument(
        "--model",
        required=True,
        help="mock/well_attuned or live model id from models.yaml",
    )
    p.add_argument(
        "--packs",
        default="all",
        help="Comma pack ids, or 'all' for list_packs()",
    )
    p.add_argument("--k", type=int, default=1, help="Number of trials (outer loop)")
    p.add_argument("--base", type=Path, default=None, help="Override base dir (tests)")
    p.add_argument("--reports-dir", type=Path, default=None, help="reports dir (default ./reports)")
    p.add_argument(
        "--models-yaml",
        type=Path,
        default=Path("models.yaml"),
        help="models.yaml for live LiteLLM routing",
    )
    p.add_argument(
        "--force-rerun",
        action="store_true",
        help="Ignore existing scores.json and re-run trials",
    )
    p.add_argument(
        "--progress",
        type=Path,
        default=None,
        help="Write progress JSON here (default: reports/harbor_runs/{job_id}/progress.json)",
    )
    p.add_argument("--extra-meta", type=str, default=None, help="JSON extra meta")
    args = p.parse_args(argv)

    if args.packs.strip().lower() == "all":
        from dsm_ae.packs.registry import list_packs

        packs = list_packs()
    else:
        packs = [x.strip() for x in args.packs.split(",") if x.strip()]
    extra = None
    if args.extra_meta:
        try:
            extra = json.loads(args.extra_meta)
        except Exception as e:
            print(f"WARNING: bad --extra-meta JSON ignored: {e}")

    prog = args.progress
    if prog is None:
        rd = args.reports_dir or Path("reports")
        prog = rd / "harbor_runs" / args.job_id / "progress.json"

    try:
        root = run_harbor_job(
            job_id=args.job_id,
            model=args.model,
            packs=packs,
            k=args.k,
            run_dir_base=args.base,
            reports_dir=args.reports_dir,
            models_yaml=args.models_yaml if args.models_yaml.is_file() else None,
            force_rerun=args.force_rerun,
            progress_path=prog,
            extra_meta=extra,
        )
        print(f"harbor job complete: {root}")
        print("rewards:")
        for r in sorted((root / "rewards").glob("*.json")):
            print("  ", r)
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
