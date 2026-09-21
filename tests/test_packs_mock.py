from pathlib import Path

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.litellm_client import MockClient
from dsm_ae.models import ScaffoldCard
from dsm_ae.packs.hello_metacog import HelloMetacogPack
from dsm_ae.packs.overeager_mini import OvereagerMiniPack
from dsm_ae.packs.slop_indicator import SlopIndicatorPack


def _adapter(persona: str) -> RawToolLoopAdapter:
    card = ScaffoldCard(model=f"mock/{persona}", k_trials=1, max_turns=16)
    return RawToolLoopAdapter(MockClient(persona=persona), card)


def test_hello_well_attuned(tmp_path: Path):
    pack = HelloMetacogPack()
    traces = pack.run_trial(_adapter("well_attuned"), tmp_path, 0)
    scores = pack.score(traces[0])
    by = {s.metric_id: s for s in scores}
    assert by["files_read_complete"].passed
    assert by["protocol_success"].passed


def test_hello_shallow_fails(tmp_path: Path):
    pack = HelloMetacogPack()
    traces = pack.run_trial(_adapter("shallow"), tmp_path, 0)
    scores = pack.score(traces[0])
    by = {s.metric_id: s for s in scores}
    assert not by["files_read_complete"].passed or not by["mood_authenticity"].passed


def test_overeager_persona_hits_trap(tmp_path: Path):
    pack = OvereagerMiniPack()
    traces = pack.run_trial(_adapter("overeager"), tmp_path, 0)
    # consent_stripped variant should overeager
    stripped = next(t for t in traces if t.variant == "consent_stripped")
    scores = pack.score(stripped)
    by = {s.metric_id: s for s in scores}
    assert by["overeager_rate"].value == 1.0
    assert not by["critical_trap_avoided"].passed


def test_overeager_careful_safe(tmp_path: Path):
    pack = OvereagerMiniPack()
    traces = pack.run_trial(_adapter("well_attuned"), tmp_path, 0)
    for t in traces:
        by = {s.metric_id: s for s in pack.score(t)}
        assert by["scope_safe"].passed
        assert by["critical_trap_avoided"].passed


def test_slop_personas_differ(tmp_path: Path):
    pack = SlopIndicatorPack()
    clean_traces = pack.run_trial(_adapter("well_attuned"), tmp_path / "c", 0)
    sloppy_traces = pack.run_trial(_adapter("sloppy"), tmp_path / "s", 0)
    clean_c2 = pack.score(clean_traces[-1])
    sloppy_c2 = pack.score(sloppy_traces[-1])
    ce = {s.metric_id: s for s in clean_c2}["erosion_indicator"].value
    se = {s.metric_id: s for s in sloppy_c2}["erosion_indicator"].value
    assert se >= ce
