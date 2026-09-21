"""Claim eval jobs, run diagnose, write reports, rebuild HTML matrix."""
from __future__ import annotations

import json
import socket
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any

from dsm_ae.diagnose import diagnose
from dsm_ae.queue.models import EvalJob
from dsm_ae.queue.paths import job_report_paths
from dsm_ae.queue.progress import (
    progress_path_for,
    read_secret,
    write_progress,
)
from dsm_ae.queue.store import JobStore
from dsm_ae.report import render_markdown


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


def run_one(
    store: JobStore,
    *,
    worker_id: str,
    reports_dir: Path,
    models_yaml: Path | None,
    rebuild_html: bool = True,
    matrix_out: Path | None = None,
) -> bool | None:
    """Claim and run at most one job. True=ran ok, False=ran fail, None=idle.

    On failure the job is marked failed (no auto-retry). ``max_attempts`` is
    reserved for a future auto-retry policy; use ``queue retry`` to re-queue
    manually. Prefer job.out_md / job.out_json when set, else default paths.
    Writes a progress JSON file under reports/queue/progress/ for the UI.
    """
    job = store.claim_next(worker_id)
    if job is None:
        return None
    reports_dir = Path(reports_dir)
    default_md, default_json = job_report_paths(
        reports_dir, job.id, job.model, job.label
    )
    md_path = Path(job.out_md) if job.out_md else default_md
    json_path = Path(job.out_json) if job.out_json else default_json
    work = Path(job.work_dir) if job.work_dir else reports_dir / "work" / job.id[:8]
    work.mkdir(parents=True, exist_ok=True)
    prog_path = (
        Path(job.progress_path)
        if job.progress_path
        else progress_path_for(reports_dir, job.id)
    )
    # Persist work_dir so Retry/Continue reuses the same tree + checkpoints.
    store.update_paths(
        job.id, progress_path=str(prog_path), work_dir=str(work)
    )

    def on_progress(payload: dict[str, Any]) -> None:
        write_progress(
            prog_path,
            {
                "job_id": job.id,
                "model": job.model,
                **payload,
            },
        )

    api_key = None
    secret = read_secret(job.secret_path)
    if secret:
        api_key = secret.get("api_key") or None
        if api_key == "":
            api_key = None

    write_progress(
        prog_path,
        {
            "job_id": job.id,
            "model": job.model,
            "phase": "claimed",
            "status": "running",
            "done": 0,
            "total": 0,
            "message": f"Claimed by {worker_id}",
        },
    )
    try:
        extra = dict(job.extra or {})
        # Bloated-context Axis V condition (separate results tree when set).
        context_bloat = extra.pop("context_bloat", None)
        if context_bloat is None and extra.get("bloat_level") is not None:
            context_bloat = float(extra.pop("bloat_level"))
        treatment = extra.pop("treatment", None)
        # E3 arm selector. Must not leak into LiteLLM kwargs.
        extra.pop("seed_mode", None)
        extra.pop("fill_mode", None)
        extra.pop("label", None)
        # Harbor path: outer k-trial pack runner with queue progress indicator.
        runner = str(extra.pop("runner", "") or "").strip().lower()
        if runner == "harbor" or extra.pop("harbor", False) is True:
            return _run_harbor_job(
                store,
                job=job,
                worker_id=worker_id,
                reports_dir=reports_dir,
                models_yaml=models_yaml,
                prog_path=prog_path,
                md_path=md_path,
                json_path=json_path,
                rebuild_html=rebuild_html,
                matrix_out=matrix_out,
                force_rerun=bool(extra.pop("force_rerun", False)),
            )

        # Remaining extra → LiteLLM client params only
        client_extra = extra or None

        # Default bloat outputs under reports/bloat/ so they never mix with baseline.
        if context_bloat is not None:
            level = (
                float(context_bloat)
                if isinstance(context_bloat, (int, float))
                else float((context_bloat or {}).get("level") or 0.5)
            )
            bloat_tag = f"bloat{int(round(level * 100))}"
            bloat_root = reports_dir / "bloat" / bloat_tag
            if not job.work_dir:
                work = bloat_root / "work" / job.id[:8]
                work.mkdir(parents=True, exist_ok=True)
                store.update_paths(job.id, work_dir=str(work))
            if not job.out_md:
                md_path = bloat_root / f"{job.model}-{job.id[:8]}.md"
            if not job.out_json:
                json_path = bloat_root / f"{job.model}-{job.id[:8]}.json"

        report = diagnose(
            model=job.model,
            packs=job.packs,
            k=job.k,
            concurrency=job.concurrency,
            rpm=job.rpm,
            scaffold=job.scaffold,
            models_yaml=models_yaml,
            api_base=job.api_base,
            api_key=api_key,
            work_dir=work,
            on_progress=on_progress,
            client_extra=client_extra,
            # Always resume when work_dir has .dsm_ae_ckpt/* from a prior attempt.
            resume=True,
            treatment=treatment if isinstance(treatment, str) else None,
            context_bloat=context_bloat,
        )
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_markdown(report), encoding="utf-8")
        payload = report.model_dump(mode="json")
        if len(payload.get("traces", [])) > 20:
            payload["traces"] = f"<{len(report.traces)} traces omitted>"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        store.mark_succeeded(job.id, out_md=str(md_path), out_json=str(json_path))
        write_progress(
            prog_path,
            {
                "job_id": job.id,
                "model": job.model,
                "phase": "scoring",
                "status": "succeeded",
                "done": 1,
                "total": 1,
                "percent": 100.0,
                "message": "Report written — rebuilding matrix HTML…",
                "out_json": str(json_path),
            },
        )
        matrix_msg = "matrix rebuild skipped"
        matrix_paths: list[str] = []
        if rebuild_html:
            ok_matrix, matrix_paths = _rebuild_matrix(reports_dir, matrix_out)
            matrix_msg = (
                f"matrix updated ({', '.join(matrix_paths)})"
                if ok_matrix
                else "matrix rebuild failed (see serve log)"
            )
        write_progress(
            prog_path,
            {
                "job_id": job.id,
                "model": job.model,
                "phase": "done",
                "status": "succeeded",
                "done": 1,
                "total": 1,
                "percent": 100.0,
                "message": f"Report written; {matrix_msg}",
                "out_json": str(json_path),
                "out_md": str(md_path),
                "matrix": matrix_paths,
            },
        )
        return True
    except Exception:
        err = traceback.format_exc()
        store.mark_failed(job.id, err)
        write_progress(
            prog_path,
            {
                "job_id": job.id,
                "model": job.model,
                "phase": "failed",
                "status": "failed",
                "message": err.splitlines()[-1] if err else "failed",
                "error": err[:2000],
            },
        )
        return False


def _run_harbor_job(
    store: JobStore,
    *,
    job: EvalJob,
    worker_id: str,
    reports_dir: Path,
    models_yaml: Path | None,
    prog_path: Path,
    md_path: Path,
    json_path: Path,
    rebuild_html: bool,
    matrix_out: Path | None,
    force_rerun: bool = False,
) -> bool:
    """Execute a queue job via Harbor pack bridge (k trials × packs).

    Progress is dual-written to the queue progress path (UI indicator) and
    ``reports/harbor_runs/{job_id}/progress.json``. On success, rewards are
    imported into a DiagnosisReport-shaped JSON under the job's out_json path
    and into ``reports/harbor_imports/`` for matrix pooling.
    """
    # Import lazily so diagnose-only workers don't require scripts/ on path.
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    if scripts_dir.is_dir() and str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from harbor_run_job import run_harbor_job  # type: ignore
    from dsm_ae.harbor.import_rewards import reward_dir_to_report
    from dsm_ae.models import DiagnosisReport
    from dsm_ae.packs.registry import list_packs

    packs = list(job.packs) if job.packs else list_packs()
    total = max(1, len(packs) * max(1, int(job.k)))
    harbor_root = reports_dir / "harbor_runs" / job.id
    harbor_prog = harbor_root / "progress.json"
    # Keep work_dir pointing at harbor tree for resume/debug.
    store.update_paths(job.id, work_dir=str(harbor_root), progress_path=str(prog_path))

    write_progress(
        prog_path,
        {
            "job_id": job.id,
            "model": job.model,
            "runner": "harbor",
            "phase": "harbor",
            "status": "running",
            "done": 0,
            "total": total,
            "message": f"Harbor claimed by {worker_id} — {len(packs)} packs × k={job.k}",
            "packs": packs,
            "k": job.k,
        },
    )

    try:
        root = run_harbor_job(
            job_id=job.id,
            model=job.model,
            packs=packs,
            k=int(job.k),
            reports_dir=reports_dir,
            models_yaml=models_yaml if models_yaml and models_yaml.is_file() else None,
            force_rerun=force_rerun,
            progress_paths=[prog_path, harbor_prog],
            extra_meta={
                "queue_job_id": job.id,
                "label": job.label,
                "worker_id": worker_id,
            },
        )

        write_progress(
            prog_path,
            {
                "job_id": job.id,
                "model": job.model,
                "runner": "harbor",
                "phase": "import",
                "status": "running",
                "done": total,
                "total": total,
                "message": "Importing Harbor rewards → diagnosis report…",
            },
        )
        rep = reward_dir_to_report(root, model=job.model, k=int(job.k))
        rep.setdefault("notes", []).append(f"queue_job_id={job.id}")
        rep.setdefault("notes", []).append(f"runner=harbor k={job.k}")

        md_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
        try:
            md_path.write_text(
                render_markdown(DiagnosisReport.model_validate(rep)),
                encoding="utf-8",
            )
        except Exception:
            md_path.write_text(
                f"# Harbor import — {job.model}\n\n"
                f"packs={packs}\nk={job.k}\njob={job.id}\n\n"
                f"gates={len(rep.get('gates') or [])} "
                f"findings={len(rep.get('findings') or [])}\n",
                encoding="utf-8",
            )

        # Promote for matrix pooling (harbor_runs/ is gitignored / ephemeral)
        imports_dir = reports_dir / "harbor_imports"
        imports_dir.mkdir(parents=True, exist_ok=True)
        import_copy = imports_dir / f"{job.id[:8]}_import_report.json"
        import_copy.write_text(
            json.dumps(rep, indent=2, default=str), encoding="utf-8"
        )

        store.mark_succeeded(job.id, out_md=str(md_path), out_json=str(json_path))

        matrix_msg = "matrix rebuild skipped"
        matrix_paths: list[str] = []
        if rebuild_html:
            write_progress(
                prog_path,
                {
                    "job_id": job.id,
                    "model": job.model,
                    "runner": "harbor",
                    "phase": "scoring",
                    "status": "succeeded",
                    "done": total,
                    "total": total,
                    "percent": 100.0,
                    "message": "Harbor complete — rebuilding matrix HTML…",
                    "out_json": str(json_path),
                    "harbor_root": str(root),
                },
            )
            ok_matrix, matrix_paths = _rebuild_matrix(reports_dir, matrix_out)
            matrix_msg = (
                f"matrix updated ({', '.join(matrix_paths)})"
                if ok_matrix
                else "matrix rebuild failed (see serve log)"
            )

        write_progress(
            prog_path,
            {
                "job_id": job.id,
                "model": job.model,
                "runner": "harbor",
                "phase": "done",
                "status": "succeeded",
                "done": total,
                "total": total,
                "percent": 100.0,
                "message": f"Harbor k={job.k} complete; {matrix_msg}",
                "out_json": str(json_path),
                "out_md": str(md_path),
                "harbor_root": str(root),
                "import_copy": str(import_copy),
                "matrix": matrix_paths,
            },
        )
        return True
    except Exception:
        err = traceback.format_exc()
        store.mark_failed(job.id, err)
        write_progress(
            prog_path,
            {
                "job_id": job.id,
                "model": job.model,
                "runner": "harbor",
                "phase": "failed",
                "status": "failed",
                "message": err.splitlines()[-1] if err else "harbor failed",
                "error": err[:2000],
            },
        )
        return False


def run_loop(
    store: JobStore,
    *,
    worker_id: str,
    reports_dir: Path,
    models_yaml: Path | None,
    once: bool = False,
    poll_s: float = 2.0,
    rebuild_html: bool = True,
    matrix_out: Path | None = None,
    stale_seconds: float = 3600,
) -> int:
    """Process jobs serially. With once=True, drain until idle then return.

    Before claiming, marks long-running jobs failed via ``requeue_stale`` so a
    crashed worker's claims can be retried with ``queue retry``. Pass
    ``stale_seconds=0`` to skip reclaim. Returns the number of stale jobs
    reclaimed at start.
    """
    reclaimed = 0
    if stale_seconds > 0:
        reclaimed = store.requeue_stale(stale_seconds=stale_seconds)
        if reclaimed:
            print(
                f"Reclaimed {reclaimed} stale running job(s) "
                f"(stale_seconds={stale_seconds:g})",
                file=sys.stderr,
            )
    while True:
        result = run_one(
            store,
            worker_id=worker_id,
            reports_dir=reports_dir,
            models_yaml=models_yaml,
            rebuild_html=rebuild_html,
            matrix_out=matrix_out,
        )
        if result is None:
            if once:
                return reclaimed
            time.sleep(poll_s)
    return reclaimed  # pragma: no cover — infinite poll loop


def _rebuild_matrix(
    reports_dir: Path, matrix_out: Path | None
) -> tuple[bool, list[str]]:
    """Rebuild multi-model HTML matrix from diagnosis JSON under reports_dir.

    Always writes ``dsm-ae-matrix.html`` and mirrors to ``index.html`` so both
    /matrix and the static reports root stay current. Failures are logged only
    — they must not fail an already-succeeded job.

    Returns (ok, list of written paths).
    """
    reports_dir = Path(reports_dir).resolve()
    primary = (
        Path(matrix_out).resolve()
        if matrix_out
        else reports_dir / "dsm-ae-matrix.html"
    )
    mirror = reports_dir / "index.html"
    written: list[str] = []
    try:
        # Prefer package-adjacent scripts/ over cwd (serve may start elsewhere).
        script = (
            Path(__file__).resolve().parents[3] / "scripts" / "json_to_html_report.py"
        )
        if not script.is_file():
            script = Path.cwd() / "scripts" / "json_to_html_report.py"
        if not script.is_file():
            print(
                f"HTML matrix rebuild skipped: script not found ({script})",
                file=sys.stderr,
            )
            return False, written

        sys.path.insert(0, str(script.parent))
        from json_to_html_report import main as html_main  # type: ignore

        # Do not pass --include-mock: mock/* columns (e.g. mock/well_attuned)
        # clutter the Comparison matrix; offline persona reports stay on disk.
        args = [
            str(reports_dir),
            "-o",
            str(primary),
            "--title",
            "DSM-AE Multi-Model Report",
        ]
        rc = html_main(args)
        if rc != 0:
            print(
                f"HTML matrix rebuild returned {rc} (out={primary})",
                file=sys.stderr,
            )
            return False, written

        written.append(str(primary))
        # Keep /reports/ index in sync (StaticFiles html=True serves index.html).
        if primary.resolve() != mirror.resolve():
            try:
                mirror.write_text(primary.read_text(encoding="utf-8"), encoding="utf-8")
                written.append(str(mirror))
            except OSError as e:
                print(f"matrix mirror to index.html failed: {e}", file=sys.stderr)
        # Context Bloat Comparison tab (baseline vs 50%) when bloat50 work exists.
        bloat_html = _rebuild_bloat_comparison(reports_dir)
        if bloat_html:
            written.append(bloat_html)
        print(f"Rebuilt matrix → {', '.join(written)}", flush=True)
        return True, written
    except Exception as e:
        print(f"HTML matrix rebuild failed (non-fatal): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return False, written


def _rebuild_bloat_comparison(reports_dir: Path) -> str | None:
    """Rebuild reports/bloat/bloat50/comparison.html if work trees exist."""
    bloat_work = reports_dir / "bloat" / "bloat50" / "work"
    if not bloat_work.is_dir():
        return None
    try:
        script = (
            Path(__file__).resolve().parents[3]
            / "scripts"
            / "build_bloat_comparison.py"
        )
        if not script.is_file():
            script = Path.cwd() / "scripts" / "build_bloat_comparison.py"
        if not script.is_file():
            return None
        sys.path.insert(0, str(script.parent))
        from build_bloat_comparison import main as bloat_main  # type: ignore

        rc = bloat_main(
            [
                "--reports-dir",
                str(reports_dir),
                "--models",
                "gpt-5.5,gpt-5.6-sol",
            ]
        )
        out = reports_dir / "bloat" / "bloat50" / "comparison.html"
        if rc == 0 and out.is_file():
            print(f"Rebuilt bloat comparison → {out}", flush=True)
            return str(out)
        return None
    except Exception as e:
        print(f"bloat comparison rebuild failed (non-fatal): {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None
