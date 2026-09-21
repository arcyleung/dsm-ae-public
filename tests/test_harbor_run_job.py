"""Tests for scripts/harbor_run_job.py (Task 4).

Fully offline; uses mock task_fn path; no harbor CLI or docker.
"""

import json
from pathlib import Path

import pytest


def test_harbor_run_job_offline_creates_artifacts_and_calls_cleanup(monkeypatch, tmp_path: Path):
    """End to end for k=2, multiple packs using the job script's mock path."""
    # patch cleanup so we can count without docker
    calls = []
    def fake_cleanup(job_id, **kw):
        calls.append(job_id)
        return {"containers_removed": 0, "job_id": job_id, "docker_available": False}

    # also patch inside runner used by the job script
    monkeypatch.setattr(
        "dsm_ae.harbor.runner.cleanup_docker_for_job",
        fake_cleanup,
    )
    # and the one in docker_cleanup if direct
    monkeypatch.setattr(
        "dsm_ae.harbor.docker_cleanup.cleanup_docker_for_job",
        fake_cleanup,
    )

    from scripts.harbor_run_job import run_harbor_job

    job_id = "jobtest42"
    root = run_harbor_job(
        job_id=job_id,
        model="mock/well_attuned",
        packs=["hello_metacog", "tool_integrity_tier2"],
        k=2,
        run_dir_base=tmp_path,
    )

    assert root == tmp_path / job_id
    assert (root / "meta.json").is_file()
    meta = json.loads((root / "meta.json").read_text())
    assert meta["job_id"] == job_id
    assert meta["k_trials"] == 2
    assert "hello_metacog" in meta["packs"]

    # rewards for each pack x trial
    rew_dir = root / "rewards"
    assert (rew_dir / "hello_metacog__t0.json").is_file()
    assert (rew_dir / "hello_metacog__t1.json").is_file()
    assert (rew_dir / "tool_integrity_tier2__t0.json").is_file()
    assert (rew_dir / "tool_integrity_tier2__t1.json").is_file()

    # trajectories dirs populated by the bridge score path
    traj_dir = root / "trajectories"
    assert (traj_dir / "hello_metacog__t0").is_dir()
    assert (traj_dir / "tool_integrity_tier2__t1" / "scores.json").is_file() or \
           (traj_dir / "tool_integrity_tier2__t1" / "meta.json").is_file()

    # docker_cleanup.json written (by runner)
    assert (root / "docker_cleanup.json").is_file()
    dc = json.loads((root / "docker_cleanup.json").read_text())
    assert dc["job_id"] == job_id

    # cleanup invoked at least once per trial (4) but at minimum 1 (idempotent)
    assert len(calls) >= 1
    assert calls[0] == job_id


def test_harbor_run_job_cli_smoke(monkeypatch, tmp_path: Path, capsys):
    """CLI entry works with --base for test sandbox."""
    calls = []
    def fake_c(job, **k):
        calls.append(job)
        return {"job_id": job}
    monkeypatch.setattr("dsm_ae.harbor.runner.cleanup_docker_for_job", fake_c)

    from scripts import harbor_run_job as mod

    # call main with argv
    rc = mod.main([
        "--job-id", "clismoke99",
        "--model", "mock/shallow",
        "--packs", "hello_metacog",
        "--k", "1",
        "--base", str(tmp_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "harbor job complete" in out or "clismoke99" in out

    jdir = tmp_path / "clismoke99"
    assert (jdir / "rewards" / "hello_metacog__t0.json").is_file()
