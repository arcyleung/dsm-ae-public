from dsm_ae.diagnose import diagnose
from dsm_ae.models import GateStatus


def test_diagnose_well_attuned():
    report = diagnose(
        model="mock/well_attuned",
        packs=["hello_metacog", "overeager_mini"],
        k=3,
        keep_traces=True,
    )
    assert report.k_trials == 3
    assert report.gates
    # protocol should mostly pass
    proto = next(g for g in report.gates if g.metric_id == "protocol_success")
    assert proto.pass_rate >= 0.8
    assert proto.status == GateStatus.PASS
    mcd = next(f for f in report.findings if f.code == "MCD")
    assert not mcd.present


def test_diagnose_overeager_finding():
    report = diagnose(
        model="mock/overeager",
        packs=["overeager_mini"],
        k=3,
    )
    oasd = next(f for f in report.findings if f.code == "OASD")
    assert oasd.present


def test_diagnose_unstable():
    report = diagnose(
        model="mock/unstable",
        packs=["hello_metacog"],
        k=6,
        threshold_pass=0.8,
        threshold_std=0.25,
    )
    # alternating behavior should create instability on some metrics
    assert any(g.status.value in ("UNSTABLE", "FAIL") for g in report.gates)


def test_metrics_have_explanations():
    report = diagnose(model="mock/well_attuned", packs=["hello_metacog"], k=2)
    for b in report.bootstraps:
        assert b.per_trial
        for m in b.per_trial:
            assert m.explanation
            assert m.metric_id


def test_diagnose_resume_skips_checkpointed_trials(tmp_path):
    """Second run with same work_dir reuses checkpoints and skips LLM work."""
    work = tmp_path / "work"
    r1 = diagnose(
        model="mock/well_attuned",
        packs=["hello_metacog"],
        k=2,
        work_dir=work,
        resume=True,
    )
    assert r1.k_trials == 2
    from dsm_ae.diagnose import CHECKPOINT_DIRNAME, count_trial_checkpoints

    assert count_trial_checkpoints(work) == 2
    ckpt_dir = work / CHECKPOINT_DIRNAME
    mtimes = {p.name: p.stat().st_mtime for p in ckpt_dir.glob("*.json")}

    # Corrupt nothing; second run should load both and not rewrite (or rewrite ok)
    progress = []
    r2 = diagnose(
        model="mock/well_attuned",
        packs=["hello_metacog"],
        k=2,
        work_dir=work,
        resume=True,
        on_progress=progress.append,
    )
    assert any(p.get("resumed") for p in progress if p.get("phase") == "running")
    resumed_msgs = [
        p for p in progress if p.get("phase") == "running" and p.get("resumed")
    ]
    assert len(resumed_msgs) == 2
    assert any("Resumed 2/2" in n for n in r2.notes)
    # Checkpoints still present
    assert count_trial_checkpoints(work) == 2
    # Gates still sensible
    assert r2.gates


def test_diagnose_resume_false_reruns(tmp_path):
    work = tmp_path / "work"
    diagnose(model="mock/well_attuned", packs=["hello_metacog"], k=1, work_dir=work)
    progress = []
    diagnose(
        model="mock/well_attuned",
        packs=["hello_metacog"],
        k=1,
        work_dir=work,
        resume=False,
        on_progress=progress.append,
    )
    running = [p for p in progress if p.get("phase") == "running"]
    assert running
    assert all(not p.get("resumed") for p in running)


def test_trajectories_and_litellm_jsonl_persisted(tmp_path):
    """Each trial writes traces, conversation, scores, and litellm.jsonl."""
    work = tmp_path / "work"
    diagnose(
        model="mock/well_attuned",
        packs=["hello_metacog"],
        k=1,
        work_dir=work,
        resume=True,
    )
    from dsm_ae.trajectory_store import trajectory_dir

    tdir = trajectory_dir(work, "hello_metacog", 0)
    assert (tdir / "traces.json").is_file()
    assert (tdir / "scores.json").is_file()
    assert (tdir / "conversation.json").is_file()
    assert (tdir / "litellm.jsonl").is_file()
    assert (tdir / "meta.json").is_file()
    lines = (tdir / "litellm.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    import json
    rec = json.loads(lines[0])
    assert "request" in rec and "response" in rec
    assert "messages" in rec["request"]
    conv = json.loads((tdir / "conversation.json").read_text())
    assert conv and conv[0].get("full_conversation")
    # secrets never land in logs
    blob = (tdir / "litellm.jsonl").read_text()
    assert "api_key" not in blob or "***" in blob
