"""Thin runner wrapper for Harbor tasks.

Responsibilities for Task 1b:
- Always call cleanup_docker_for_job in finally (success or fail)
- Persist artifacts to harbor_runs/{job_id} layout via run_layout
- Write docker_cleanup.json
- Thin wrapper for later queue integration: accepts task_fn or can be extended
- Documents how to label containers when starting Harbor / docker run

Usage skeleton (for queue integration later):
    def my_harbor_invocation(...):
        # e.g. harbor run ... or subprocess docker run --label dsm-ae.harbor.job=...
        ...

    run_harbor_task(job_id=..., model=..., packs=..., task_fn=...)
    # defaults to reports/harbor_runs/{job_id}; pass base=tmp or run_dir_base=... for tests/override

The runner itself does NOT invoke `harbor` binary yet (Task 2+); it manages layout + guaranteed cleanup.
"""
from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .docker_cleanup import cleanup_docker_for_job
from .run_layout import (
    finalize_meta,
    harbor_run_dir,
    init_run,
    persist_logs,
    persist_reward,
    persist_trajectory,
)


def run_harbor_task(
    *,
    job_id: str,
    model: str,
    packs: list[str],
    run_dir_base: Path | None = None,
    reports_dir: Path | None = None,
    base: Path | None = None,
    task_fn: Callable[[Path], Any] | None = None,
    # optional artifact sources for persist (used by caller after real harbor exec)
    reward: dict[str, Any] | None = None,
    traj_dir: Path | None = None,
    logs_dir: Path | None = None,
    pack_id: str | None = None,
    trial_i: int = 0,
    extra_meta: dict[str, Any] | None = None,
) -> Path:
    """Run a Harbor task (via provided task_fn), ensure layout, persist, and ALWAYS cleanup.

    Returns the run dir Path under harbor_runs layout.

    Defaults to reports/harbor_runs/{job_id} (via harbor_run_dir). For tests use
    run_dir_base=... or base=... (treated as direct parent of {job_id}).

    Cleanup is performed in finally even if task_fn raises or docker absent.
    docker_cleanup.json is always written (may contain "docker_available": false).

    To label containers from the caller's task_fn (or outer docker/harbor cmd):
        docker run --label dsm-ae.harbor.job={job_id} ...
        # or harbor CLI equivalent label support (passed through env or --label if supported)
        # The runner does not start containers; the invoker must pass the label using job_id.
    """
    # resolve override: base or legacy run_dir_base means "direct parent for job dir" (test compat)
    # if neither, init_run + harbor_run_dir default to reports/harbor_runs/{job_id}
    override_base = base or run_dir_base
    root = init_run(
        job_id,
        reports_dir=reports_dir,
        base=override_base,
        model=model,
        packs=packs,
        **(extra_meta or {}),
    )
    cleanup_info: dict[str, Any] = {}

    try:
        if task_fn is not None:
            result = task_fn(root)
            # If task_fn returned or wrote a reward inline, persist if provided separately
            if isinstance(result, dict) and "primary_pass" in result and reward is None:
                persist_reward(root, pack_id or (packs[0] if packs else "pack"), trial_i, result)
        else:
            # no-op task_fn path: allow direct persist via kwargs (for tests / manual)
            pass

        # Persist provided artifacts (post-harbor-run or from inside task_fn side effects)
        if reward is not None and pack_id is not None:
            persist_reward(root, pack_id, trial_i, reward)
        if traj_dir is not None and pack_id is not None:
            persist_trajectory(root, pack_id, trial_i, traj_dir)
        if logs_dir is not None:
            persist_logs(root, logs_dir)

        end_ts = datetime.now(timezone.utc).isoformat()
        finalize_meta(root, {"status": "succeeded", "ended_at": end_ts})  # runner records real end time

    except Exception:
        # record failure but proceed to cleanup
        tb = traceback.format_exc()
        end_ts = datetime.now(timezone.utc).isoformat()
        finalize_meta(root, {"status": "failed", "error": tb[:2000], "ended_at": end_ts})
        raise
    finally:
        # ALWAYS cleanup
        cleanup_info = cleanup_docker_for_job(job_id)
        # write the record
        dc_path = root / "docker_cleanup.json"
        dc_path.parent.mkdir(parents=True, exist_ok=True)
        dc_path.write_text(json.dumps(cleanup_info, indent=2, default=str), encoding="utf-8")
        # also merge summary into meta
        finalize_meta(root, {"docker_cleanup": {"containers_removed": cleanup_info.get("containers_removed", 0)}})

    return root
