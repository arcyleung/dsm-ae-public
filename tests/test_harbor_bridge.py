"""TDD tests for DSM-AE Harbor pack bridge (Task 1).

Write test first; expect import fail initially.
"""
from pathlib import Path

import json
import pytest

from dsm_ae.harbor.pack_bridge import prepare_workspace, score_workspace, write_reward


def test_prepare_and_score_hello_mock(tmp_path: Path):
    # Use mock well_attuned offline — no network
    ws = prepare_workspace("hello_metacog", tmp_path, trial_index=0, mock_persona="well_attuned")
    assert ws.is_dir()
    metrics = score_workspace("hello_metacog", tmp_path, trial_index=0)
    assert "protocol_success" in metrics or len(metrics) >= 1
    reward_path = tmp_path / "reward.json"
    write_reward(metrics, reward_path)
    data = reward_path.read_text()
    assert "pass" in data or "protocol" in data.lower() or "{" in data


def test_write_reward_shapes_floats_only(tmp_path: Path):
    metrics = {
        "protocol_success": {"value": 1.0, "passed": True},
        "files_read_complete": {"value": 1.0, "passed": True},
        "erosion_indicator.tier3": {"value": 0.0, "passed": True},
        "some_str": {"value": "notfloat", "passed": True},  # passed True so primary=1; value ignored as non-numeric
    }
    outp = tmp_path / "r.json"
    write_reward(metrics, outp)
    data = json.loads(outp.read_text())
    assert data["primary_pass"] == 1.0
    assert data["protocol_success"] == 1.0
    assert data["files_read_complete"] == 1.0
    assert data["erosion_indicator_tier3"] == 0.0
    assert "some_str" not in data
    # top level only floats
    for k, v in data.items():
        assert isinstance(v, float)


def test_write_reward_primary_fail(tmp_path: Path):
    metrics = {
        "protocol_success": {"value": 0.0, "passed": False},
    }
    outp = tmp_path / "r2.json"
    write_reward(metrics, outp)
    data = json.loads(outp.read_text())
    assert data["primary_pass"] == 0.0


def test_score_loads_existing_scores_json(tmp_path: Path):
    """If trajectories/.../scores.json present, load and return dict keyed by metric_id."""
    from dsm_ae.trajectory_store import trajectory_dir, save_trial_artifacts
    from dsm_ae.models import TrialTrace, MetricResult, ScaffoldCard

    pack_id = "hello_metacog"
    tdir = trajectory_dir(tmp_path, pack_id, 0)
    tdir.mkdir(parents=True, exist_ok=True)

    trace = TrialTrace(
        scenario_id="test",
        pack=pack_id,
        trial_index=0,
        scaffold_card=ScaffoldCard(model="mock/well_attuned"),
        final_text="Ready for request (mode: Autonomous)",
    )
    scores = [
        MetricResult(metric_id="protocol_success", value=1.0, passed=True, explanation="ok"),
        MetricResult(metric_id="files_read_complete", value=0.75, passed=False, explanation="partial"),
    ]
    save_trial_artifacts(tmp_path, pack_id, 0, [(pack_id, trace, scores)])

    metrics = score_workspace(pack_id, tmp_path, trial_index=0)
    assert "protocol_success" in metrics
    assert metrics["protocol_success"]["value"] == 1.0
    assert metrics["protocol_success"]["passed"] is True
    # dots would be kept in returned dict, replacement only in reward.json


def test_prepare_creates_dir_and_records_persona(tmp_path: Path):
    ws = prepare_workspace("hello_metacog", tmp_path, 1, mock_persona="shallow")
    assert ws.is_dir()
    meta = tmp_path / ".harbor_meta_hello_metacog__t1" / "persona.json"
    assert meta.is_file()
    assert "shallow" in meta.read_text()
