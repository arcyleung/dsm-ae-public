"""Tests for SQLite-backed eval job store."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dsm_ae.queue.models import JobStatus
from dsm_ae.queue.store import JobStore


def test_enqueue_and_claim(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=2)
    job = store.claim_next(worker_id="w1")
    assert job is not None
    assert job.id == jid
    assert job.status == JobStatus.RUNNING
    assert store.claim_next(worker_id="w2") is None  # only one queued


def test_cancel_only_when_queued(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"])
    assert store.cancel(jid) is True
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.CANCELLED
    assert job.finished_at is not None

    # Already cancelled — cannot cancel again
    assert store.cancel(jid) is False

    jid2 = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"])
    claimed = store.claim_next(worker_id="w1")
    assert claimed is not None
    assert claimed.id == jid2
    # Running jobs cannot be cancelled
    assert store.cancel(jid2) is False
    assert store.get(jid2).status == JobStatus.RUNNING


def test_mark_succeeded(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"])
    job = store.claim_next(worker_id="w1")
    assert job is not None
    store.mark_succeeded(jid, out_md="/tmp/out.md", out_json="/tmp/out.json")
    done = store.get(jid)
    assert done is not None
    assert done.status == JobStatus.SUCCEEDED
    assert done.out_md == "/tmp/out.md"
    assert done.out_json == "/tmp/out.json"
    assert done.error is None
    assert done.finished_at is not None


def test_mark_failed(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    jid = store.enqueue(model="mock/well_attuned")
    store.claim_next(worker_id="w1")
    store.mark_failed(jid, "boom")
    job = store.get(jid)
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert job.error == "boom"
    assert job.finished_at is not None


def test_list_order(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    id1 = store.enqueue(model="m1", label="first")
    time.sleep(0.01)
    id2 = store.enqueue(model="m2", label="second")
    time.sleep(0.01)
    id3 = store.enqueue(model="m3", label="third")
    jobs = store.list_jobs()
    assert [j.id for j in jobs] == [id3, id2, id1]  # newest first
    limited = store.list_jobs(limit=2)
    assert len(limited) == 2
    assert limited[0].id == id3


def test_claim_priority(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    low = store.enqueue(model="low", priority=0)
    high = store.enqueue(model="high", priority=10)
    mid = store.enqueue(model="mid", priority=5)
    first = store.claim_next(worker_id="w1")
    second = store.claim_next(worker_id="w1")
    third = store.claim_next(worker_id="w1")
    assert first is not None and first.id == high
    assert second is not None and second.id == mid
    assert third is not None and third.id == low


def test_requeue_stale(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"])
    job = store.claim_next(worker_id="w1")
    assert job is not None
    assert job.status == JobStatus.RUNNING

    # Fresh running job should not be marked stale
    assert store.requeue_stale(stale_seconds=3600) == 0
    assert store.get(jid).status == JobStatus.RUNNING

    # Backdate started_at to simulate a long-running job
    old = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
    store._conn.execute(
        "UPDATE eval_jobs SET started_at=? WHERE id=?",
        (old, jid),
    )
    store._conn.commit()

    n = store.requeue_stale(stale_seconds=3600)
    assert n == 1
    stale = store.get(jid)
    assert stale is not None
    assert stale.status == JobStatus.FAILED
    assert stale.error is not None
    assert "stale" in stale.error.lower()
    assert stale.finished_at is not None

    # Already failed — no further action
    assert store.requeue_stale(stale_seconds=1) == 0


def test_enqueue_fields_roundtrip(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    jid = store.enqueue(
        model="gpt-x",
        packs=["a", "b"],
        k=5,
        concurrency=2,
        rpm=12.5,
        scaffold="raw",
        priority=3,
        max_attempts=2,
        label="lbl",
        out_md="x.md",
        out_json="x.json",
        work_dir="/tmp/w",
    )
    job = store.get(jid)
    assert job is not None
    assert job.model == "gpt-x"
    assert job.packs == ["a", "b"]
    assert job.k == 5
    assert job.concurrency == 2
    assert job.rpm == 12.5
    assert job.scaffold == "raw"
    assert job.priority == 3
    assert job.status == JobStatus.QUEUED
    assert job.max_attempts == 2
    assert job.attempt == 0
    assert job.label == "lbl"
    assert job.out_md == "x.md"
    assert job.out_json == "x.json"
    assert job.work_dir == "/tmp/w"
    assert job.worker_id is None
    assert job.started_at is None
    assert job.finished_at is None
    assert job.error is None

    claimed = store.claim_next(worker_id="worker-a")
    assert claimed is not None
    assert claimed.attempt == 1
    assert claimed.worker_id == "worker-a"
    assert claimed.started_at is not None


def test_enqueue_null_packs(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    jid = store.enqueue(model="m", packs=None)
    job = store.get(jid)
    assert job is not None
    assert job.packs is None


def test_retry_failed_and_cancelled(tmp_path: Path):
    store = JobStore(tmp_path / "q.db")
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"])
    store.claim_next(worker_id="w1")
    store.mark_failed(jid, "boom")
    failed = store.get(jid)
    assert failed is not None
    assert failed.status == JobStatus.FAILED
    assert failed.error == "boom"
    assert failed.worker_id == "w1"
    assert failed.started_at is not None
    assert failed.finished_at is not None

    assert store.retry(jid) is True
    again = store.get(jid)
    assert again is not None
    assert again.status == JobStatus.QUEUED
    assert again.error is None
    assert again.worker_id is None
    assert again.started_at is None
    assert again.finished_at is None

    # Queued jobs cannot be retried
    assert store.retry(jid) is False

    # Cancelled can be retried
    assert store.cancel(jid) is True
    assert store.retry(jid) is True
    assert store.get(jid).status == JobStatus.QUEUED

    # Succeeded cannot be retried
    claimed = store.claim_next(worker_id="w2")
    assert claimed is not None
    store.mark_succeeded(jid, out_md="a.md", out_json="a.json")
    assert store.retry(jid) is False
    assert store.get(jid).status == JobStatus.SUCCEEDED
