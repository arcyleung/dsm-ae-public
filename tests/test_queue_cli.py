"""CLI tests for dsm-ae queue commands."""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dsm_ae.cli import app
from dsm_ae.queue.models import JobStatus
from dsm_ae.queue.store import JobStore

runner = CliRunner()


def test_queue_enqueue_and_list(tmp_path: Path):
    db = tmp_path / "q.db"
    result = runner.invoke(
        app,
        [
            "queue",
            "enqueue",
            "-m",
            "mock/well_attuned",
            "-p",
            "hello_metacog",
            "--k",
            "1",
            "--db",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "enqueued" in result.output
    assert "mock/well_attuned" in result.output

    store = JobStore(db)
    jobs = store.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].model == "mock/well_attuned"
    assert jobs[0].packs == ["hello_metacog"]
    assert jobs[0].k == 1
    assert jobs[0].status == JobStatus.QUEUED

    listed = runner.invoke(app, ["queue", "list", "--db", str(db)])
    assert listed.exit_code == 0, listed.output
    # Rich may soft-wrap long cells; match stable fragments
    assert "mock/" in listed.output
    assert "well_attu" in listed.output or "mock/well_attuned" in listed.output
    assert "queued" in listed.output
    assert jobs[0].id[:8] in listed.output


def test_queue_enqueue_batch(tmp_path: Path):
    db = tmp_path / "q.db"
    result = runner.invoke(
        app,
        [
            "queue",
            "enqueue-batch",
            "-m",
            "mock/a,mock/b, mock/c",
            "-p",
            "hello_metacog",
            "--k",
            "2",
            "--db",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.output.count("enqueued") == 3
    store = JobStore(db)
    jobs = store.list_jobs()
    assert len(jobs) == 3
    models = {j.model for j in jobs}
    assert models == {"mock/a", "mock/b", "mock/c"}
    assert all(j.packs == ["hello_metacog"] for j in jobs)
    assert all(j.k == 2 for j in jobs)


def test_queue_status_cancel_retry(tmp_path: Path):
    db = tmp_path / "q.db"
    enq = runner.invoke(
        app,
        ["queue", "enqueue", "-m", "mock/x", "-p", "hello_metacog", "--db", str(db)],
    )
    assert enq.exit_code == 0, enq.output
    store = JobStore(db)
    jid = store.list_jobs()[0].id

    st = runner.invoke(app, ["queue", "status", jid, "--db", str(db)])
    assert st.exit_code == 0, st.output
    assert jid in st.output
    assert "queued" in st.output
    assert "mock/x" in st.output

    # Short prefix works
    short = runner.invoke(app, ["queue", "status", jid[:8], "--db", str(db)])
    assert short.exit_code == 0, short.output
    assert jid in short.output

    can = runner.invoke(app, ["queue", "cancel", jid[:8], "--db", str(db)])
    assert can.exit_code == 0, can.output
    assert "cancelled" in can.output
    assert store.get(jid).status == JobStatus.CANCELLED

    # Cancel again fails
    can2 = runner.invoke(app, ["queue", "cancel", jid, "--db", str(db)])
    assert can2.exit_code == 1
    assert "cannot cancel" in can2.output

    ret = runner.invoke(app, ["queue", "retry", jid, "--db", str(db)])
    assert ret.exit_code == 0, ret.output
    assert "re-queued" in ret.output
    assert store.get(jid).status == JobStatus.QUEUED

    # Fail then retry
    store.claim_next(worker_id="w1")
    store.mark_failed(jid, "err")
    ret2 = runner.invoke(app, ["queue", "retry", jid, "--db", str(db)])
    assert ret2.exit_code == 0, ret2.output
    job = store.get(jid)
    assert job.status == JobStatus.QUEUED
    assert job.error is None


def test_queue_enqueue_full_suite(tmp_path: Path):
    db = tmp_path / "q.db"
    result = runner.invoke(
        app,
        [
            "queue",
            "enqueue",
            "-m",
            "mock/well_attuned",
            "--full-suite",
            "--db",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    job = JobStore(db).list_jobs()[0]
    assert job.packs is not None
    assert len(job.packs) > 1
    assert "hello_metacog" in job.packs


def test_queue_status_missing(tmp_path: Path):
    db = tmp_path / "q.db"
    JobStore(db)  # create empty db
    result = runner.invoke(
        app, ["queue", "status", "00000000-0000-0000-0000-000000000000", "--db", str(db)]
    )
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_queue_reclaim(tmp_path: Path):
    from datetime import datetime, timedelta, timezone

    db = tmp_path / "q.db"
    store = JobStore(db)
    jid = store.enqueue(model="mock/x", packs=["hello_metacog"])
    store.claim_next(worker_id="w1")
    old = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
    store._conn.execute(
        "UPDATE eval_jobs SET started_at=? WHERE id=?",
        (old, jid),
    )
    store._conn.commit()

    result = runner.invoke(
        app, ["queue", "reclaim", "--stale-seconds", "3600", "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "reclaimed" in result.output.lower()
    assert "1" in result.output
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error is not None
    assert "stale" in job.error.lower()

    # Nothing left to reclaim
    result2 = runner.invoke(
        app, ["queue", "reclaim", "--stale-seconds", "3600", "--db", str(db)]
    )
    assert result2.exit_code == 0, result2.output
    assert "0" in result2.output
