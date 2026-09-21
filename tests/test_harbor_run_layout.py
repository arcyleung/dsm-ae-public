"""TDD tests for DSM-AE Harbor run layout, docker cleanup, runner (Task 1b).

Write test first; expect import fail initially.
"""
from pathlib import Path

import json
import pytest

from dsm_ae.harbor.run_layout import (
    init_run,
    persist_reward,
    persist_trajectory,
    persist_logs,
    finalize_meta,
    harbor_run_dir,
)


def test_harbor_run_dir_layout(tmp_path: Path):
    """Core layout from global constraints."""
    from dsm_ae.harbor.run_layout import init_run, persist_reward, persist_trajectory
    # use base= for test override (direct parent); default would be reports/harbor_runs/
    root = init_run("abc12def", base=tmp_path, model="mock/well_attuned", packs=["hello_metacog"])
    # direct under passed base in tests (layout root is conventionally reports/harbor_runs)
    assert root.name == "abc12def"
    assert (root / "meta.json").is_file()
    meta = json.loads((root / "meta.json").read_text())
    assert meta["job_id"] == "abc12def"
    assert "model" in meta and meta["model"] == "mock/well_attuned"
    assert "packs" in meta

    persist_reward(root, "hello_metacog", 0, {"primary_pass": 1.0})
    assert (root / "rewards" / "hello_metacog__t0.json").is_file()
    rew = json.loads((root / "rewards" / "hello_metacog__t0.json").read_text())
    assert rew["primary_pass"] == 1.0

    # persist_trajectory should populate the subdir with expected files (from source or inline)
    traj_src = tmp_path / "src_traj"
    traj_src.mkdir()
    (traj_src / "litellm.jsonl").write_text('{"call":1}\n')
    (traj_src / "conversation.json").write_text("[]")
    (traj_src / "traces.json").write_text("[]")
    (traj_src / "scores.json").write_text("[]")
    (traj_src / "meta.json").write_text("{}")
    persist_trajectory(root, "hello_metacog", 0, traj_src)
    tdir = root / "trajectories" / "hello_metacog__t0"
    assert (tdir / "litellm.jsonl").is_file()
    assert (tdir / "conversation.json").is_file()
    assert (tdir / "traces.json").is_file()
    assert (tdir / "scores.json").is_file()
    assert (tdir / "meta.json").is_file()


def test_persist_logs_and_finalize(tmp_path: Path):
    root = init_run("jobxyz", base=tmp_path, model="x", packs=[])
    log_src = tmp_path / "logs_in"
    log_src.mkdir()
    (log_src / "verifier.log").write_text("ok")
    persist_logs(root, log_src)
    assert (root / "logs" / "verifier.log").is_file()

    finalize_meta(root, {"status": "done", "ended_at": "now"})
    meta = json.loads((root / "meta.json").read_text())
    assert meta.get("status") == "done"


def test_harbor_run_dir_helper(tmp_path: Path):
    d = harbor_run_dir("j1234567", base=tmp_path)
    assert d == tmp_path / "j1234567"
    # With base= (test override), direct under it. Default (no base): reports/harbor_runs/{job}
    # e.g. harbor_run_dir("job", reports_dir=Path("reports")) -> reports/harbor_runs/job
    assert d.name == "j1234567"


def test_cleanup_docker_is_idempotent(monkeypatch):
    from dsm_ae.harbor.docker_cleanup import cleanup_docker_for_job
    calls = []
    def fake_docker(*a, **k):
        calls.append((a, k))
        # simulate success
        return type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
    monkeypatch.setattr(
        "dsm_ae.harbor.docker_cleanup._docker",
        fake_docker,
    )
    info = cleanup_docker_for_job("abc12def")
    assert isinstance(info, dict)
    assert "removed" in info or "containers" in info or "containers_removed" in info
    assert len(calls) >= 1  # attempted docker ops


def test_cleanup_safe_when_no_docker(monkeypatch):
    from dsm_ae.harbor.docker_cleanup import cleanup_docker_for_job
    def fake_missing(*a, **k):
        import subprocess
        raise FileNotFoundError("docker not found")
    monkeypatch.setattr(
        "dsm_ae.harbor.docker_cleanup._docker",
        fake_missing,
    )
    info = cleanup_docker_for_job("nope1234")
    assert isinstance(info, dict)
    assert info.get("docker_available") is False or "error" in str(info).lower() or "not found" in str(info).lower()


def test_runner_always_cleans_in_finally(monkeypatch, tmp_path: Path):
    """Runner must cleanup even on failure, and write docker_cleanup.json."""
    from dsm_ae.harbor.runner import run_harbor_task
    from dsm_ae.harbor.docker_cleanup import cleanup_docker_for_job
    clean_calls = []
    def fake_cleanup(job_id, **kw):
        clean_calls.append(job_id)
        return {"containers_removed": 2, "job_id": job_id}
    monkeypatch.setattr(
        "dsm_ae.harbor.runner.cleanup_docker_for_job",
        fake_cleanup,
    )

    # success path
    def do_success(run_dir):
        (run_dir / "reward.json").write_text('{"primary_pass": 1.0}')
        return run_dir

    out = run_harbor_task(
        job_id="r1234567",
        model="mock/m",
        packs=["hello_metacog"],
        run_dir_base=tmp_path,
        task_fn=do_success,
    )
    assert (out / "meta.json").is_file()
    assert (out / "docker_cleanup.json").is_file()
    assert len(clean_calls) == 1

    # failure path still cleans
    def do_fail(run_dir):
        raise RuntimeError("simulated harbor crash")

    clean_calls.clear()
    with pytest.raises(RuntimeError):
        run_harbor_task(
            job_id="rfail001",
            model="mock/m",
            packs=["hello_metacog"],
            run_dir_base=tmp_path,
            task_fn=do_fail,
        )
    assert len(clean_calls) == 1
    fail_dir = tmp_path / "rfail001"
    dc = json.loads((fail_dir / "docker_cleanup.json").read_text())
    assert dc["job_id"] == "rfail001"


def test_docker_label_documentation():
    """Ensure docs in runner explain --label for starting containers."""
    from dsm_ae.harbor import runner as rmod
    src = rmod.__file__
    txt = Path(src).read_text()
    assert "dsm-ae.harbor.job" in txt or "--label" in txt
