"""Worker e2e: claim → diagnose(mock) → artifacts → status."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from dsm_ae.cli import app
from dsm_ae.queue.models import JobStatus
from dsm_ae.queue.store import JobStore
from dsm_ae.queue.worker import run_loop, run_one

runner = CliRunner()


def test_run_one_mock(tmp_path: Path):
    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    store = JobStore(db)
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=2)
    ok = run_one(store, worker_id="t", reports_dir=reports, models_yaml=None)
    assert ok is True
    job = store.get(jid)
    assert job is not None
    assert job.status.value == "succeeded"
    assert job.out_json is not None
    assert Path(job.out_json).is_file()
    assert job.out_md is not None
    assert Path(job.out_md).is_file()
    # idle when empty
    assert run_one(store, worker_id="t", reports_dir=reports, models_yaml=None) is None


def test_run_one_respects_custom_out_paths(tmp_path: Path):
    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    custom_md = tmp_path / "custom" / "out.md"
    custom_json = tmp_path / "custom" / "out.json"
    store = JobStore(db)
    jid = store.enqueue(
        model="mock/well_attuned",
        packs=["hello_metacog"],
        k=1,
        out_md=str(custom_md),
        out_json=str(custom_json),
    )
    ok = run_one(store, worker_id="t", reports_dir=reports, models_yaml=None)
    assert ok is True
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
    assert Path(job.out_md) == custom_md
    assert Path(job.out_json) == custom_json
    assert custom_md.is_file()
    assert custom_json.is_file()


def test_run_one_failure_marks_failed(tmp_path: Path):
    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    store = JobStore(db)
    jid = store.enqueue(model="mock/well_attuned", packs=["no_such_pack_xyz"], k=1)
    ok = run_one(store, worker_id="t", reports_dir=reports, models_yaml=None)
    assert ok is False
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error


def test_run_loop_once_drains_queue(tmp_path: Path):
    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    store = JobStore(db)
    store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=1)
    store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=1)
    run_loop(
        store,
        worker_id="loop",
        reports_dir=reports,
        models_yaml=None,
        once=True,
        poll_s=0.01,
        rebuild_html=False,
    )
    jobs = store.list_jobs()
    assert len(jobs) == 2
    assert all(j.status == JobStatus.SUCCEEDED for j in jobs)


def test_run_loop_reclaims_stale_running(tmp_path: Path):
    """Worker start marks long-running jobs failed via requeue_stale."""
    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    store = JobStore(db)
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=1)
    claimed = store.claim_next(worker_id="dead-worker")
    assert claimed is not None
    old = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
    store._conn.execute(
        "UPDATE eval_jobs SET started_at=? WHERE id=?",
        (old, jid),
    )
    store._conn.commit()

    reclaimed = run_loop(
        store,
        worker_id="new-worker",
        reports_dir=reports,
        models_yaml=None,
        once=True,
        poll_s=0.01,
        rebuild_html=False,
        stale_seconds=3600,
    )
    assert reclaimed == 1
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error is not None
    assert "stale" in job.error.lower()


def test_run_loop_stale_seconds_zero_skips_reclaim(tmp_path: Path):
    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    store = JobStore(db)
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=1)
    store.claim_next(worker_id="dead-worker")
    old = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
    store._conn.execute(
        "UPDATE eval_jobs SET started_at=? WHERE id=?",
        (old, jid),
    )
    store._conn.commit()

    reclaimed = run_loop(
        store,
        worker_id="new-worker",
        reports_dir=reports,
        models_yaml=None,
        once=True,
        poll_s=0.01,
        rebuild_html=False,
        stale_seconds=0,
    )
    assert reclaimed == 0
    assert store.get(jid).status == JobStatus.RUNNING


def test_worker_cli_once(tmp_path: Path):
    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    store = JobStore(db)
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=1)
    result = runner.invoke(
        app,
        [
            "worker",
            "--db",
            str(db),
            "--reports-dir",
            str(reports),
            "--once",
            "--worker-id",
            "cli-w",
            "--no-rebuild-html",
        ],
    )
    assert result.exit_code == 0, result.output
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
    assert job.worker_id == "cli-w"


def test_worker_cli_reclaims_stale(tmp_path: Path):
    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    store = JobStore(db)
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=1)
    store.claim_next(worker_id="dead")
    old = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
    store._conn.execute(
        "UPDATE eval_jobs SET started_at=? WHERE id=?",
        (old, jid),
    )
    store._conn.commit()

    result = runner.invoke(
        app,
        [
            "worker",
            "--db",
            str(db),
            "--reports-dir",
            str(reports),
            "--once",
            "--stale-seconds",
            "3600",
            "--no-rebuild-html",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "reclaimed" in result.output.lower() or "stale" in result.output.lower()
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.FAILED


def test_retry_resumes_from_checkpoints(tmp_path: Path):
    """Failed job re-queued reuses work_dir checkpoints (skips completed trials)."""
    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    store = JobStore(db)
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=2)
    assert run_one(store, worker_id="t1", reports_dir=reports, models_yaml=None) is True
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
    assert job.work_dir
    work = Path(job.work_dir)
    from dsm_ae.diagnose import count_trial_checkpoints

    assert count_trial_checkpoints(work) == 2

    # Simulate partial re-run: delete one checkpoint, mark failed, retry
    ckpts = sorted((work / ".dsm_ae_ckpt").glob("*.json"))
    ckpts[-1].unlink()
    store.mark_failed(jid, "simulated interrupt")
    assert store.retry(jid) is True
    assert run_one(store, worker_id="t2", reports_dir=reports, models_yaml=None) is True
    job2 = store.get(jid)
    assert job2 is not None
    assert job2.status == JobStatus.SUCCEEDED
    assert count_trial_checkpoints(work) == 2


def test_successful_job_rebuilds_matrix_html(tmp_path: Path):
    """On success, worker rebuilds dsm-ae-matrix.html and index.html under reports_dir."""
    import json

    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    # noise that must not break discovery
    (reports / "work" / "x" / "trajectories" / "p__t0").mkdir(parents=True)
    (reports / "work" / "x" / "trajectories" / "p__t0" / "scores.json").write_text(
        '{"not":"a report"}', encoding="utf-8"
    )
    # Seed a non-mock diagnosis JSON so matrix rebuild (which excludes mock/*)
    # still has something to render after the job writes its mock report.
    seed = {
        "run_id": "seed",
        "scaffold_card": {"model": "seed-model", "k_trials": 1, "scaffold": "raw"},
        "packs": ["hello_metacog"],
        "k_trials": 1,
        "gates": [
            {
                "metric_id": "files_read_complete",
                "dimension": "files_read_complete",
                "pass_rate": 1.0,
                "mean": 1.0,
                "std": 0.0,
                "status": "PASS",
                "disorder": False,
                "explanation": "seed",
            }
        ],
        "findings": [],
        "bootstraps": [],
        "traces": [],
        "notes": ["seed for matrix rebuild test"],
    }
    (reports / "seed-model.json").write_text(json.dumps(seed), encoding="utf-8")
    store = JobStore(db)
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=1)
    ok = run_one(store, worker_id="t", reports_dir=reports, models_yaml=None)
    assert ok is True
    job = store.get(jid)
    assert job is not None and job.status == JobStatus.SUCCEEDED
    matrix = reports / "dsm-ae-matrix.html"
    index = reports / "index.html"
    assert matrix.is_file(), "matrix HTML should be rebuilt after success"
    assert index.is_file(), "index.html mirror should be written"
    assert "DSM-AE" in matrix.read_text(encoding="utf-8")[:500]
    # progress mentions matrix
    from dsm_ae.queue.progress import progress_path_for

    prog = json.loads(Path(job.progress_path or progress_path_for(reports, jid)).read_text())
    assert prog.get("status") == "succeeded"
    assert "matrix" in (prog.get("message") or "").lower() or prog.get("matrix")


def test_run_one_harbor_mock(tmp_path: Path, monkeypatch):
    """Queue job with extra.runner=harbor uses Harbor path + queue progress."""
    calls = []

    def fake_cleanup(job_id, **kw):
        calls.append(job_id)
        return {"containers_removed": 0, "job_id": job_id, "docker_available": False}

    monkeypatch.setattr("dsm_ae.harbor.runner.cleanup_docker_for_job", fake_cleanup)

    db = tmp_path / "q.db"
    reports = tmp_path / "reports"
    store = JobStore(db)
    jid = store.enqueue(
        model="mock/well_attuned",
        packs=["hello_metacog", "overeager_mini"],
        k=2,
        label="harbor-test",
        extra={"runner": "harbor"},
    )
    ok = run_one(
        store,
        worker_id="h",
        reports_dir=reports,
        models_yaml=None,
        rebuild_html=False,
    )
    assert ok is True
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
    assert job.out_json is not None
    assert Path(job.out_json).is_file()
    # progress under queue path
    assert job.progress_path is not None
    prog = Path(job.progress_path)
    assert prog.is_file()
    import json

    data = json.loads(prog.read_text())
    assert data.get("runner") == "harbor"
    assert data.get("status") == "succeeded"
    assert data.get("done") == 4  # 2 packs × k=2
    assert data.get("total") == 4
    # harbor rewards exist
    rew = reports / "harbor_runs" / jid / "rewards"
    assert (rew / "hello_metacog__t0.json").is_file()
    assert (rew / "overeager_mini__t1.json").is_file()
    # import promotion
    imports = list((reports / "harbor_imports").glob("*_import_report.json"))
    assert imports
    rep = json.loads(Path(job.out_json).read_text())
    mids = {g.get("metric_id") for g in rep.get("gates") or []}
    # underscore ids (not dotted ghosts)
    assert not any("." in m and not m.endswith((".tier1", ".tier2", ".tier3")) for m in mids if m)
