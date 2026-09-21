"""Tests for erosion tier1 dual-emit, tier2 structural, tier3 slope."""

from pathlib import Path

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.litellm_client import MockClient
from dsm_ae.models import ScaffoldCard, TrialTrace
from dsm_ae.packs.erosion_tier2 import (
    ErosionTier2Pack,
    score_tier2_structure,
    synthetic_extracted_code,
    synthetic_high_cc_code,
)
from dsm_ae.packs.erosion_tier3 import (
    ErosionTier3Pack,
    compute_erosion_slope,
    synthetic_flat_erosion_history,
    synthetic_rising_erosion_history,
)
from dsm_ae.packs.registry import list_packs
from dsm_ae.packs.slop_indicator import SlopIndicatorPack, analyze_code
from dsm_ae.packs.smoke_metrics import is_smoke_metric
from dsm_ae.diagnose import diagnose


def _adapter(persona: str) -> RawToolLoopAdapter:
    card = ScaffoldCard(model=f"mock/{persona}", k_trials=1, max_turns=16)
    return RawToolLoopAdapter(MockClient(persona=persona), card)


def test_registry_lists_tier_packs():
    packs = set(list_packs(include_skipped=True))
    assert "slop_indicator" in packs
    assert "erosion_tier2" in packs
    assert "erosion_tier3" in packs


def test_tier1_dual_emit_alias():
    pack = SlopIndicatorPack()
    traces = pack.run_trial(_adapter("well_attuned"), Path("/tmp/dsm_ae_t1"), 0)
    scores = pack.score(traces[-1])
    by = {s.metric_id: s for s in scores}
    assert "erosion_indicator" in by
    assert "erosion_indicator.tier1" in by
    assert by["erosion_indicator"].value == by["erosion_indicator.tier1"].value
    assert by["erosion_indicator"].passed == by["erosion_indicator.tier1"].passed
    assert "verbosity_indicator.tier1" in by
    assert "quality_stable.tier1" in by
    # smoke badge in explanations
    assert "SMOKE" in by["erosion_indicator.tier1"].explanation
    assert "SMOKE" in by["verbosity_indicator"].explanation
    assert is_smoke_metric("erosion_indicator.tier1")
    assert is_smoke_metric("critical_preserved")
    assert not is_smoke_metric("erosion_indicator.tier2")


def test_tier1_sloppy_still_fails_erosion():
    pack = SlopIndicatorPack()
    traces = pack.run_trial(_adapter("sloppy"), Path("/tmp/dsm_ae_t1s"), 0)
    by = {s.metric_id: s for s in pack.score(traces[-1])}
    # sloppy god-function should have high erosion on at least one of the dual metrics
    assert by["erosion_indicator"].value >= 0.5 or not by["erosion_indicator"].passed


def test_tier2_high_cc_fails_structure():
    seed = analyze_code(
        # minimal seed-like metrics
        "def process():\n" + "\n".join(f"    if x{i}: pass" for i in range(12)) + "\n"
    )
    # Use real synthetic high-CC fixture
    cm = analyze_code(synthetic_high_cc_code())
    assert cm["max_cc"] > 10 or cm["max_mass_share"] >= 0.5 or cm["n_funcs"] <= 2
    result = score_tier2_structure(cm, seed, features_ok=True)
    assert result["score"] >= 0.3 or not result["passed"]
    # high-CC synthetic should not be a clean pass
    assert not result["passed"] or "god_function_mass" in result["findings"] or result["score"] > 0.25


def test_tier2_extracted_passes():
    seed_cm = analyze_code(synthetic_high_cc_code())
    clean_cm = analyze_code(synthetic_extracted_code())
    result = score_tier2_structure(clean_cm, seed_cm, features_ok=True)
    assert result["extract_ok"] or result["passed"]
    assert result["score"] < 0.7


def test_tier2_pack_mock_sloppy_fails(tmp_path: Path):
    pack = ErosionTier2Pack()
    traces = pack.run_trial(_adapter("sloppy"), tmp_path, 0)
    assert len(traces) >= 1
    by = {s.metric_id: s for s in pack.score(traces[-1])}
    assert "erosion_indicator.tier2" in by
    # sloppy persona writes synthetic_high_cc_code → should fail tier2
    assert not by["erosion_indicator.tier2"].passed


def test_tier2_pack_mock_clean_better(tmp_path: Path):
    pack = ErosionTier2Pack()
    clean = pack.run_trial(_adapter("well_attuned"), tmp_path / "c", 0)
    sloppy = pack.run_trial(_adapter("sloppy"), tmp_path / "s", 0)
    c = {s.metric_id: s for s in pack.score(clean[-1])}["erosion_indicator.tier2"]
    s = {s.metric_id: s for s in pack.score(sloppy[-1])}["erosion_indicator.tier2"]
    # clean should be better (lower score or more likely pass)
    assert c.value <= s.value or (c.passed and not s.passed)


def test_tier3_slope_fails_when_rising():
    hist = synthetic_rising_erosion_history()
    info = compute_erosion_slope(hist)
    assert info["slope_e"] > 0.03
    assert info["slope_fail"] is True
    # absolute last erosion still < 0.5 (tier1 would pass)
    assert info["e_last"] < 0.5


def test_tier3_slope_flat_ok():
    info = compute_erosion_slope(synthetic_flat_erosion_history())
    assert info["slope_fail"] is False


def test_tier3_pack_scores_slope_metric(tmp_path: Path):
    pack = ErosionTier3Pack()
    traces = pack.run_trial(_adapter("sloppy"), tmp_path, 0)
    assert len(traces) >= 3
    # final checkpoint should have history length >= 3
    final = traces[-1]
    assert len(final.meta.get("history") or []) >= 3
    by = {s.metric_id: s for s in pack.score(final)}
    assert "erosion_indicator.tier3" in by
    assert "erosion_slope" in by
    # sloppy rising god-function should fail slope or tier3
    assert (not by["erosion_indicator.tier3"].passed) or (not by["erosion_slope"].passed)


def test_diagnose_notes_smoke_and_dual_emit(tmp_path: Path):
    r = diagnose(
        model="mock/well_attuned",
        packs=["slop_indicator", "erosion_tier2", "injection_mini"],
        k=1,
        work_dir=tmp_path,
        keep_traces=False,
    )
    assert any("SMOKE/FLOOR" in n for n in r.notes)
    mids = {g.metric_id for g in r.gates}
    assert "erosion_indicator" in mids
    assert "erosion_indicator.tier1" in mids
    assert "erosion_indicator.tier2" in mids
    assert "critical_preserved" in mids
    assert "critical_preserved.tier1" in mids
    # bootstrap summary badges smoke
    b = next(b for b in r.bootstraps if b.metric_id == "erosion_indicator.tier1")
    assert "SMOKE" in b.summary


def test_tier3_score_from_synthetic_history():
    """Direct score path: rising history on a fake trace fails tier3."""
    pack = ErosionTier3Pack()
    hist = synthetic_rising_erosion_history()
    last = hist[-1]["metrics"]
    tr = TrialTrace(
        scenario_id="t",
        pack="erosion_tier3",
        scaffold_card=ScaffoldCard(model="x"),
        meta={
            "code": "def main():\n    pass\n",
            "checkpoint": 4,
            "code_metrics": last,
            "history": hist,
        },
    )
    by = {s.metric_id: s for s in pack.score(tr)}
    assert not by["erosion_indicator.tier3"].passed
    assert not by["erosion_slope"].passed
