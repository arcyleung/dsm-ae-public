"""Orchestrate packs × k bootstrap trials → report.

Concurrency:
  - Default concurrency=1 → fully sequential (stable).
  - concurrency=N → ThreadPoolExecutor runs up to N (pack, trial) jobs at once.
  - Optional rpm rate-limits *LLM-facing* job starts (not a pre-opened connection pool).
  - There is no long-lived connection pool per model; each job shares a ModelClient
    with a lock around complete() when concurrency > 1.

Resume / checkpoints:
  - After each pack×trial job, artifacts are written under::

      {work_dir}/trajectories/{pack}__t{i}/
        traces.json          # TrialTrace(s)
        scores.json          # MetricResult(s)
        conversation.json    # full LLM message lists
        litellm.jsonl        # raw completion request/response per call
        meta.json
      {work_dir}/.dsm_ae_ckpt/{pack}__t{i}.json   # resume checkpoint

  - With ``resume=True`` (default when ``work_dir`` is set), completed checkpoints
    are loaded and those LLM trials are skipped — so a killed queue job can
    continue from the last finished trial via Retry/Continue.
  - Workspace side-effects alone are **not** enough to resume scoring; only
    checkpointed TrialTrace + MetricResult rows are authoritative.
"""

from __future__ import annotations

import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.criteria import evaluate_findings
from dsm_ae.litellm_client import ModelClient, make_client, resolve_from_models_yaml
from dsm_ae.metrics.bootstrap import bootstrap_metric, build_gate_matrix
from dsm_ae.models import DiagnosisReport, MetricResult, ScaffoldCard, TrialTrace
from dsm_ae.packs.registry import get_pack, list_packs
from dsm_ae.pool import RateLimiter, map_pool
from dsm_ae.trajectory_store import (
    CHECKPOINT_DIRNAME,
    TRAJECTORIES_DIRNAME,
    checkpoint_path,
    count_trial_checkpoints,
    litellm_log_path,
    load_trial_checkpoint,
    save_trial_artifacts,
)


def save_trial_checkpoint(
    work_root: Path,
    pack_id: str,
    trial_index: int,
    items: list[tuple[str, TrialTrace, list[MetricResult]]],
) -> Path:
    """Persist trajectory files + resume checkpoint; return checkpoint path."""
    save_trial_artifacts(work_root, pack_id, trial_index, items)
    return checkpoint_path(work_root, pack_id, trial_index)


class LockedClient(ModelClient):
    """Thread-safe wrapper around a ModelClient (serialize complete calls)."""

    def __init__(self, inner: ModelClient):
        self._inner = inner
        self._lock = threading.Lock()

    def complete(self, messages, tools=None, temperature=0.0, max_tokens=2048):
        with self._lock:
            return self._inner.complete(
                messages, tools=tools, temperature=temperature, max_tokens=max_tokens
            )

    def set_trial(self, i: int) -> None:
        if hasattr(self._inner, "set_trial"):
            with self._lock:
                self._inner.set_trial(i)  # type: ignore[attr-defined]

    def set_call_log(self, path) -> None:
        # Thread-local on ModelClient base — no lock needed for path pointer.
        self._inner.set_call_log(path)
        super().set_call_log(path)


def _infer_rpm(
    models_yaml: Path | str | None, model: str, rpm: float | None
) -> float | None:
    if rpm is not None:
        return rpm
    if not models_yaml:
        return None
    try:
        entry = resolve_from_models_yaml(models_yaml, model)
        params = entry.get("litellm_params") or {}
        v = params.get("rpm")
        return float(v) if v is not None else None
    except Exception:
        return None


def diagnose(
    *,
    model: str,
    packs: list[str] | None = None,
    k: int = 5,
    scaffold: str = "raw",
    permission_mode: str = "auto",
    work_dir: Path | None = None,
    mock_persona: str | None = None,
    threshold_pass: float = 0.8,
    threshold_std: float = 0.25,
    keep_traces: bool = True,
    models_yaml: Path | str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    max_turns: int = 10,
    concurrency: int = 1,
    rpm: float | None = None,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    client_extra: dict[str, Any] | None = None,
    resume: bool | None = None,
    treatment: str | None = None,
    context_bloat: float | dict[str, Any] | None = None,
) -> DiagnosisReport:
    """Run packs×k trials and build a DiagnosisReport.

    Parameters
    ----------
    resume:
        If True, skip pack×trial jobs that already have a valid checkpoint under
        ``work_dir/.dsm_ae_ckpt/``. Default: True when ``work_dir`` is set, else
        False (temp dirs are fresh).
    treatment:
        Optional treatment id (e.g. ``prompt_reminder``) to wrap the adapter and
        inject system/user prompt interventions before each pack trial.
    context_bloat:
        Optional bloated-context fill level (0.5 / 0.8) or config dict. Results
        should be written under a separate tree (e.g. reports/bloat/) by callers.
    """
    packs = packs or list_packs()
    inferred_rpm = _infer_rpm(models_yaml, model, rpm)
    bloat_cfg_raw: dict[str, Any] | None
    if context_bloat is None:
        bloat_cfg_raw = None
    elif isinstance(context_bloat, (int, float)):
        bloat_cfg_raw = {"level": float(context_bloat), "model": model}
    else:
        bloat_cfg_raw = dict(context_bloat)
        bloat_cfg_raw.setdefault("model", model)

    card = ScaffoldCard(
        model=model,
        scaffold=scaffold,
        permission_mode=permission_mode,
        k_trials=k,
        max_turns=max_turns,
        extra={
            "models_yaml": str(models_yaml) if models_yaml else None,
            "api_base": api_base,
            "concurrency": concurrency,
            "rpm": inferred_rpm,
            "treatment": treatment,
            "context_bloat": bloat_cfg_raw,
        },
    )
    # Strip non-LiteLLM keys from client_extra
    litellm_extra = dict(client_extra or {})
    for k_drop in (
        "context_bloat",
        "treatment",
        "label",
        "bloat_level",
        "seed_mode",
        "fill_mode",
    ):
        litellm_extra.pop(k_drop, None)

    raw_client: ModelClient = make_client(
        model,
        mock_persona=mock_persona,
        models_yaml=models_yaml,
        api_base=api_base,
        api_key=api_key,
        extra=litellm_extra or None,
    )
    client: ModelClient = (
        LockedClient(raw_client) if concurrency and concurrency > 1 else raw_client
    )
    adapter: Any = RawToolLoopAdapter(client, card)
    if treatment:
        from dsm_ae.treatment import TreatedAdapter, get_treatment

        t = get_treatment(treatment)
        adapter = TreatedAdapter(adapter, t)
    if bloat_cfg_raw:
        from dsm_ae.context_bloat import ContextBloatConfig, ContextBloatedAdapter

        bcfg = ContextBloatConfig.from_dict(bloat_cfg_raw)
        if bcfg and bcfg.enabled():
            bcfg.model = model
            adapter = ContextBloatedAdapter(adapter, bcfg, models_yaml=models_yaml)

    root = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="dsm_ae_"))
    root.mkdir(parents=True, exist_ok=True)
    do_resume = bool(resume) if resume is not None else bool(work_dir)
    preexisting = count_trial_checkpoints(root) if do_resume else 0

    notes: list[str] = [
        f"Work dir: {root}",
        f"Packs: {packs}",
        "Indicator protocols only (not full SlopCodeBench/OverEager-Bench).",
        f"Disorder if pass_rate < {threshold_pass} OR std > {threshold_std}.",
        f"Concurrency={concurrency} (N workers for pack×trial jobs; default 1=sequential).",
        f"RPM limit={inferred_rpm if inferred_rpm else 'none'} (job-start spacing, not connection pool).",
        f"Resume={do_resume} (checkpoints under {CHECKPOINT_DIRNAME}/).",
        f"Trajectories + LiteLLM JSONL under {TRAJECTORIES_DIRNAME}/.",
        f"Treatment: {treatment or 'none (baseline)'}.",
        f"Context bloat: {bloat_cfg_raw if bloat_cfg_raw else 'none (0% fill)'}.",
        # Smoke/floor honesty for weak gates (see weak-metric-audits/)
        "SMOKE/FLOOR metrics (tier1): erosion_indicator[.tier1], verbosity_indicator[.tier1], "
        "quality_stable[.tier1], critical_preserved[.tier1], task_tool_success[.tier1] — "
        "saturated floors, not full CQ-01/CQ-02/AA-04/TE diagnostics. "
        "Prefer erosion_indicator.tier2 / .tier3 and task_tool_success.tier2 when present.",
    ]
    if preexisting:
        notes.append(f"Found {preexisting} existing trial checkpoint(s) to reuse.")

    jobs: list[tuple[str, int]] = [
        (pack_id, trial_i) for pack_id in packs for trial_i in range(k)
    ]
    total = len(jobs)
    done_lock = threading.Lock()
    done_count = 0
    resumed_count = 0

    def _emit(payload: dict[str, Any]) -> None:
        if on_progress is None:
            return
        try:
            on_progress(payload)
        except Exception:
            pass

    _emit(
        {
            "phase": "starting",
            "status": "running",
            "done": 0,
            "total": total,
            "message": (
                f"Starting {total} pack×trial jobs"
                + (
                    f" ({preexisting} checkpoint(s) may be reused)"
                    if preexisting
                    else ""
                )
            ),
            "packs": list(packs),
            "k": k,
            "resume": do_resume,
            "checkpoints_found": preexisting,
        }
    )

    limiter = RateLimiter(inferred_rpm)

    def _run_job(job: tuple[str, int]) -> list[tuple[str, TrialTrace, list[MetricResult]]]:
        nonlocal done_count, resumed_count
        pack_id, trial_i = job

        if do_resume:
            cached = load_trial_checkpoint(root, pack_id, trial_i)
            if cached is not None:
                with done_lock:
                    done_count += 1
                    resumed_count += 1
                    cur = done_count
                    rcur = resumed_count
                _emit(
                    {
                        "phase": "running",
                        "status": "running",
                        "done": cur,
                        "total": total,
                        "current_pack": pack_id,
                        "current_trial": trial_i,
                        "resumed": True,
                        "resumed_count": rcur,
                        "message": (
                            f"{pack_id} trial {trial_i + 1}/{k} resumed from checkpoint "
                            f"({cur}/{total})"
                        ),
                    }
                )
                return cached

        pack = get_pack(pack_id)
        # set_trial for mock personas
        if hasattr(client, "set_trial"):
            client.set_trial(trial_i)  # type: ignore[attr-defined]
        elif hasattr(raw_client, "set_trial"):
            raw_client.set_trial(trial_i)  # type: ignore[attr-defined]

        # Raw LiteLLM (or mock) call log for this pack×trial
        call_log = litellm_log_path(root, pack_id, trial_i)
        try:
            if call_log.is_file():
                call_log.unlink()  # fresh log for this attempt
        except OSError:
            pass
        client.set_call_log(call_log)
        try:
            traces = pack.run_trial(adapter, root / pack_id, trial_i)
            out: list[tuple[str, TrialTrace, list[MetricResult]]] = []
            for tr in traces:
                out.append((pack_id, tr, pack.score(tr)))
        finally:
            client.set_call_log(None)

        try:
            save_trial_checkpoint(root, pack_id, trial_i, out)
        except Exception:
            # Checkpoint is best-effort; never fail the trial on write errors.
            pass
        with done_lock:
            done_count += 1
            cur = done_count
        _emit(
            {
                "phase": "running",
                "status": "running",
                "done": cur,
                "total": total,
                "current_pack": pack_id,
                "current_trial": trial_i,
                "resumed": False,
                "message": f"{pack_id} trial {trial_i + 1}/{k} complete ({cur}/{total})",
            }
        )
        return out

    # Rate limit is applied at job start when concurrency>1 via map_pool
    nested = map_pool(
        jobs,
        _run_job,
        concurrency=concurrency,
        rate_limiter=limiter if concurrency > 1 else None,
    )

    all_traces: list[TrialTrace] = []
    bucket: dict[str, list[MetricResult]] = {}
    for batch in nested:
        for _pack_id, tr, scores in batch:
            all_traces.append(tr)
            for m in scores:
                bucket.setdefault(m.metric_id, []).append(m)

    if resumed_count:
        notes.append(
            f"Resumed {resumed_count}/{total} pack×trial job(s) from checkpoint."
        )

    _emit(
        {
            "phase": "scoring",
            "status": "running",
            "done": total,
            "total": total,
            "message": "Scoring metrics and findings",
            "resumed_count": resumed_count,
        }
    )

    bootstraps = [
        bootstrap_metric(
            mid,
            mid,
            results,
            threshold_pass=threshold_pass,
            threshold_std=threshold_std,
        )
        for mid, results in bucket.items()
    ]
    bootstraps.sort(key=lambda b: b.metric_id)
    gates = build_gate_matrix(bootstraps)
    findings = evaluate_findings(bootstraps)

    report = DiagnosisReport(
        scaffold_card=card,
        packs=packs,
        k_trials=k,
        gates=gates,
        findings=findings,
        bootstraps=bootstraps,
        traces=all_traces if keep_traces else [],
        notes=notes,
    )
    _emit(
        {
            "phase": "done",
            "status": "succeeded",
            "done": total,
            "total": total,
            "message": "Diagnosis complete",
            "findings_present": sum(1 for f in findings if f.present),
            "resumed_count": resumed_count,
        }
    )
    return report
