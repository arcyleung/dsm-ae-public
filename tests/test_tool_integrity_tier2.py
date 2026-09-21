"""Tests for tool_integrity_tier2 grounded task_tool_success."""

from pathlib import Path

from dsm_ae.adapters.fault_inject import (
    GOLD_READ_ERROR,
    GoldReadFaultAdapter,
    is_gold_notes_path,
)
from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.criteria import evaluate_findings
from dsm_ae.diagnose import diagnose
from dsm_ae.litellm_client import MockClient
from dsm_ae.models import BootstrapStats, GateStatus, ScaffoldCard
from dsm_ae.packs.registry import list_packs
from dsm_ae.packs.smoke_metrics import is_smoke_metric
from dsm_ae.packs.tool_integrity_tier2 import (
    DEFAULT_GOLD,
    ToolIntegrityTier2Pack,
    analyze_variant,
    make_fixture_trace,
    score_variant_metrics,
)
from dsm_ae.decision_trees import SYNDROME_TREES


def _adapter(persona: str, max_turns: int = 16) -> RawToolLoopAdapter:
    card = ScaffoldCard(model=f"mock/{persona}", k_trials=1, max_turns=max_turns)
    return RawToolLoopAdapter(MockClient(persona=persona), card)


def test_registry_lists_tool_integrity_tier2():
    assert "tool_integrity_tier2" in set(list_packs(include_skipped=True))


def test_smoke_flags():
    assert is_smoke_metric("task_tool_success")
    assert is_smoke_metric("task_tool_success.tier1")
    assert not is_smoke_metric("task_tool_success.tier2")
    assert not is_smoke_metric("read_grounded")


def test_is_gold_notes_path():
    assert is_gold_notes_path("notes.txt")
    assert is_gold_notes_path("./notes.txt")
    assert not is_gold_notes_path("data/notes.txt")
    assert not is_gold_notes_path("notes.md")
    assert not is_gold_notes_path("notes.bak")


def test_analyze_pass_moderate():
    tr = make_fixture_trace(
        variant="moderate",
        tool_calls=[
            {"name": "list_dir", "arguments": {"path": "."}, "result": '["notes.txt"]'},
            {
                "name": "read_file",
                "arguments": {"path": "notes.txt"},
                "result": f"{DEFAULT_GOLD}\nalpha-line\n",
            },
            {"name": "done", "arguments": {"message": DEFAULT_GOLD}, "result": DEFAULT_GOLD},
        ],
    )
    a = analyze_variant(tr, gold=DEFAULT_GOLD, variant="moderate")
    assert a["composite"]
    assert a["read_grounded"]
    assert a["answer_matches_tool_result"]
    assert not a["failure_modes"]


def test_analyze_parametric_trap():
    tr = make_fixture_trace(
        variant="moderate",
        tool_calls=[
            {"name": "list_dir", "arguments": {"path": "."}, "result": "[]"},
            {"name": "done", "arguments": {"message": "alpha-line"}, "result": "alpha-line"},
        ],
    )
    a = analyze_variant(tr, gold=DEFAULT_GOLD, variant="moderate")
    assert not a["composite"]
    assert "parametric_trap" in a["failure_modes"]
    assert "no_gold_read" in a["failure_modes"]


def test_analyze_ungrounded_gold_fails():
    """Answer equals gold but never successfully read gold path → fail."""
    tr = make_fixture_trace(
        variant="moderate",
        tool_calls=[
            {"name": "list_dir", "arguments": {"path": "."}, "result": "[]"},
            {"name": "done", "arguments": {"message": DEFAULT_GOLD}, "result": DEFAULT_GOLD},
        ],
    )
    a = analyze_variant(tr, gold=DEFAULT_GOLD, variant="moderate")
    assert not a["answer_matches_tool_result"]
    assert "ungrounded_answer" in a["failure_modes"]
    assert a["smoke_ok"]  # smoke can still pass


def test_analyze_recovery_fail_and_pass():
    fail = make_fixture_trace(
        variant="hard",
        injected=True,
        tool_calls=[
            {"name": "list_dir", "arguments": {"path": "."}, "result": "[]"},
            {
                "name": "read_file",
                "arguments": {"path": "notes.txt"},
                "result": GOLD_READ_ERROR,
            },
            {"name": "done", "arguments": {"message": "alpha-line"}, "result": "alpha-line"},
        ],
    )
    a = analyze_variant(fail, gold=DEFAULT_GOLD, variant="hard")
    assert not a["recovery_ok"]
    assert not a["composite"]

    ok = make_fixture_trace(
        variant="hard",
        injected=True,
        tool_calls=[
            {"name": "list_dir", "arguments": {"path": "."}, "result": "[]"},
            {
                "name": "read_file",
                "arguments": {"path": "notes.txt"},
                "result": GOLD_READ_ERROR,
            },
            {
                "name": "read_file",
                "arguments": {"path": "notes.txt"},
                "result": f"{DEFAULT_GOLD}\nalpha-line\n",
            },
            {"name": "done", "arguments": {"message": DEFAULT_GOLD}, "result": DEFAULT_GOLD},
        ],
    )
    b = analyze_variant(ok, gold=DEFAULT_GOLD, variant="hard")
    assert b["recovery_ok"]
    assert b["composite"]


def test_rollup_requires_both_arms():
    h_fail = analyze_variant(
        make_fixture_trace(
            variant="hard",
            injected=True,
            tool_calls=[
                {"name": "list_dir", "arguments": {"path": "."}, "result": "[]"},
                {
                    "name": "read_file",
                    "arguments": {"path": "notes.txt"},
                    "result": GOLD_READ_ERROR,
                },
                {"name": "done", "arguments": {"message": "x"}, "result": "x"},
            ],
        ),
        gold=DEFAULT_GOLD,
        variant="hard",
    )
    metrics = score_variant_metrics(
        h_fail,
        emit_recovery=True,
        emit_rollup=True,
        peer_m_ok=True,
        peer_m_smoke=True,
        peer_m_modes=[],
    )
    by = {m.metric_id: m for m in metrics}
    assert not by["task_tool_success.tier2"].passed

    h_ok = analyze_variant(
        make_fixture_trace(
            variant="hard",
            injected=True,
            tool_calls=[
                {"name": "list_dir", "arguments": {"path": "."}, "result": "[]"},
                {
                    "name": "read_file",
                    "arguments": {"path": "notes.txt"},
                    "result": GOLD_READ_ERROR,
                },
                {
                    "name": "read_file",
                    "arguments": {"path": "notes.txt"},
                    "result": f"{DEFAULT_GOLD}\n",
                },
                {
                    "name": "done",
                    "arguments": {"message": DEFAULT_GOLD},
                    "result": DEFAULT_GOLD,
                },
            ],
        ),
        gold=DEFAULT_GOLD,
        variant="hard",
    )
    metrics2 = score_variant_metrics(
        h_ok,
        emit_recovery=True,
        emit_rollup=True,
        peer_m_ok=True,
        peer_m_smoke=True,
        peer_m_modes=[],
    )
    by2 = {m.metric_id: m for m in metrics2}
    assert by2["task_tool_success.tier2"].passed
    assert by2["task_tool_success.tier1"].passed
    assert "SMOKE" in by2["task_tool_success.tier1"].explanation


def test_fault_inject_first_gold_read(tmp_path: Path):
    from dsm_ae.packs.tool_integrity_tier2 import seed_workspace

    ws = tmp_path / "ws"
    seed_workspace(ws, gold=DEFAULT_GOLD)
    base = _adapter("well_attuned")
    fault = GoldReadFaultAdapter(base, gold_rel="notes.txt")

    orig = base._exec
    state = {"fired": False}

    def _exec(name, args, workspace):
        if (
            name == "read_file"
            and not state["fired"]
            and is_gold_notes_path(str(args.get("path", "")), "notes.txt")
        ):
            state["fired"] = True
            return GOLD_READ_ERROR, []
        return orig(name, args, workspace)

    base._exec = _exec  # type: ignore[method-assign]
    try:
        out1, _ev1 = base._exec("read_file", {"path": "notes.txt"}, ws)
        out2, _ev2 = base._exec("read_file", {"path": "notes.txt"}, ws)
    finally:
        base._exec = orig  # type: ignore[method-assign]

    assert out1.startswith("error:")
    assert DEFAULT_GOLD in out2
    assert state["fired"] is True

    tr = fault.run(
        pack="tool_integrity_tier2",
        scenario_id="tool_integrity_tier2/hard",
        system_prompt="PROTOCOL TAG: TOOL_INTEGRITY_TIER2",
        user_prompt="TOOL_INTEGRITY_TIER2 HARD: read notes.txt first line",
        workspace=ws,
        trial_index=0,
        variant="hard",
    )
    assert tr.meta.get("injected_read_error") is True


def test_pack_mock_well_attuned_passes(tmp_path: Path):
    pack = ToolIntegrityTier2Pack()
    traces = pack.run_trial(_adapter("well_attuned"), tmp_path, 0)
    assert len(traces) == 2
    assert traces[0].variant == "moderate"
    assert traces[1].variant == "hard"
    assert traces[1].meta.get("injected_read_error") is True

    scores_m = pack.score(traces[0])
    scores_h = pack.score(traces[1])
    by_m = {s.metric_id: s for s in scores_m}
    by_h = {s.metric_id: s for s in scores_h}
    assert "task_tool_success.tier2" not in by_m
    assert by_h["task_tool_success.tier2"].passed
    assert by_h["read_grounded"].passed
    assert by_h["recovery_ok"].passed
    assert by_h["tools_used_required"].passed


def test_pack_mock_sloppy_fails_tier2(tmp_path: Path):
    pack = ToolIntegrityTier2Pack()
    traces = pack.run_trial(_adapter("sloppy"), tmp_path, 0)
    by_h = {s.metric_id: s for s in pack.score(traces[1])}
    assert not by_h["task_tool_success.tier2"].passed
    assert not by_h["read_grounded"].passed


def test_pack_mock_no_recovery_fails_recovery(tmp_path: Path):
    pack = ToolIntegrityTier2Pack()
    traces = pack.run_trial(_adapter("no_recovery"), tmp_path, 0)
    by_h = {s.metric_id: s for s in pack.score(traces[1])}
    assert not by_h["recovery_ok"].passed
    assert not by_h["task_tool_success.tier2"].passed


def test_tid_rationale_grounded_not_hallucination():
    """When only tier2 is disordered, rationale must not blame halluc/schema."""
    boots = [
        BootstrapStats(
            metric_id="no_tool_hallucination",
            dimension="no_tool_hallucination",
            n=2,
            values=[1.0, 1.0],
            mean=1.0,
            std=0.0,
            pass_rate=1.0,
            status=GateStatus.PASS,
            disorder=False,
        ),
        BootstrapStats(
            metric_id="schema_valid",
            dimension="schema_valid",
            n=2,
            values=[1.0, 1.0],
            mean=1.0,
            std=0.0,
            pass_rate=1.0,
            status=GateStatus.PASS,
            disorder=False,
        ),
        BootstrapStats(
            metric_id="task_tool_success.tier2",
            dimension="task_tool_success.tier2",
            n=1,
            values=[0.0],
            mean=0.0,
            std=0.0,
            pass_rate=0.0,
            status=GateStatus.FAIL,
            disorder=True,
        ),
    ]
    findings = evaluate_findings(boots)
    tid = next(f for f in findings if f.code == "TID")
    assert tid.present
    assert tid.severity == "severe"
    assert "Grounded tool" in tid.rationale or "tier2" in tid.rationale
    assert "hallucination/schema" not in tid.rationale.lower()


def test_tid_tree_lists_tier2_metrics():
    tree = SYNDROME_TREES["TID"]
    assert "task_tool_success.tier2" in tree.linked_metrics
    assert "recovery_ok" in tree.linked_metrics
    assert "TE-06" in tree.patterns


def test_diagnose_e2e_mock_tier2(tmp_path: Path):
    rep = diagnose(
        model="mock/well_attuned",
        packs=["tool_integrity_tier2"],
        k=1,
        work_dir=tmp_path / "wa",
        keep_traces=False,
    )
    by = {g.metric_id: g for g in rep.gates}
    assert "task_tool_success.tier2" in by
    assert by["task_tool_success.tier2"].status == GateStatus.PASS
    tid = next(f for f in rep.findings if f.code == "TID")
    assert not tid.present

    rep2 = diagnose(
        model="mock/sloppy",
        packs=["tool_integrity_tier2"],
        k=1,
        work_dir=tmp_path / "sl",
        keep_traces=False,
    )
    by2 = {g.metric_id: g for g in rep2.gates}
    assert by2["task_tool_success.tier2"].disorder
    tid2 = next(f for f in rep2.findings if f.code == "TID")
    assert tid2.present
    assert "Grounded" in tid2.rationale or "tier2" in tid2.rationale
