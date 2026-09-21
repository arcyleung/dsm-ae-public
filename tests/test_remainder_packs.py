
from pathlib import Path
from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.litellm_client import MockClient
from dsm_ae.models import ScaffoldCard
from dsm_ae.packs.memory_context import MemoryContextPack
from dsm_ae.packs.handoff_mini import HandoffMiniPack
from dsm_ae.packs.eval_gaming_mini import EvalGamingMiniPack
from dsm_ae.packs.sandbag_mini import SandbagMiniPack
from dsm_ae.packs.clarify_verify import ClarifyVerifyPack
from dsm_ae.packs.pii_safety import PiiSafetyPack
from dsm_ae.packs.nfr_omit import NfrOmitPack
from dsm_ae.packs.role_confusion_mini import RoleConfusionMiniPack
from dsm_ae.packs.mas_verify_mini import MasVerifyMiniPack
from dsm_ae.packs.session_overwrite_mini import SessionOverwriteMiniPack
from dsm_ae.packs.coord_tax_mini import CoordTaxMiniPack
from dsm_ae.diagnose import diagnose
from dsm_ae.packs.registry import list_packs

def ad(p):
    return RawToolLoopAdapter(MockClient(persona=p), ScaffoldCard(model=f"mock/{p}", max_turns=16))

def test_memory():
    pack=MemoryContextPack()
    g={m.metric_id:m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/m1"),0)[0])}
    b={m.metric_id:m for m in pack.score(pack.run_trial(ad("contaminated"), Path("/tmp/m2"),0)[0])}
    assert g["knowledge_retention"].passed
    assert not b["distractor_resisted"].passed

def test_handoff():
    pack=HandoffMiniPack()
    g={m.metric_id:m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/h1"),0)[0])}
    assert g["handoff_consumed"].passed

def test_eval_game():
    pack=EvalGamingMiniPack()
    g={m.metric_id:m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/e1"),0)[0])}
    b={m.metric_id:m for m in pack.score(pack.run_trial(ad("gamer"), Path("/tmp/e2"),0)[0])}
    assert g["hidden_pass"].passed
    assert not b["no_test_memorization"].passed or not b["hidden_pass"].passed

def test_sandbag():
    pack=SandbagMiniPack()
    g={m.metric_id:m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/s1"),0)[0])}
    b={m.metric_id:m for m in pack.score(pack.run_trial(ad("sandbagger"), Path("/tmp/s2"),0)[0])}
    assert g["no_sandbag"].passed
    assert not b["no_sandbag"].passed

def test_clarify():
    pack=ClarifyVerifyPack()
    g={m.metric_id:m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/c1"),0)[0])}
    b={m.metric_id:m for m in pack.score(pack.run_trial(ad("shallow"), Path("/tmp/c2"),0)[0])}
    assert g["asks_clarification"].passed
    assert not b["asks_clarification"].passed

def test_pii():
    pack=PiiSafetyPack()
    g={m.metric_id:m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/p1"),0)[0])}
    b={m.metric_id:m for m in pack.score(pack.run_trial(ad("leaky"), Path("/tmp/p2"),0)[0])}
    assert g["no_secret_leak"].passed
    assert not b["no_secret_leak"].passed

def test_nfr():
    pack=NfrOmitPack()
    g={m.metric_id:m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/n1"),0)[0])}
    b={m.metric_id:m for m in pack.score(pack.run_trial(ad("sloppy"), Path("/tmp/n2"),0)[0])}
    assert g["has_validation"].passed
    assert not b["has_error_handling"].passed or not b["has_validation"].passed

def test_role_confusion():
    pack = RoleConfusionMiniPack()
    g = {m.metric_id: m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/rc1"), 0)[0])}
    b = {m.metric_id: m for m in pack.score(pack.run_trial(ad("shallow"), Path("/tmp/rc2"), 0)[0])}
    assert g["role_boundary_held"].passed and g["role_spec_ok"].passed
    assert not b["role_boundary_held"].passed


def test_mas_verify():
    pack = MasVerifyMiniPack()
    g = {m.metric_id: m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/mv1"), 0)[0])}
    b = {m.metric_id: m for m in pack.score(pack.run_trial(ad("shallow"), Path("/tmp/mv2"), 0)[0])}
    assert g["correct_verdict"].passed and g["no_rubber_stamp"].passed
    assert not b["correct_verdict"].passed


def test_session_overwrite():
    pack = SessionOverwriteMiniPack()
    g = {m.metric_id: m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/so1"), 0)[0])}
    b = {m.metric_id: m for m in pack.score(pack.run_trial(ad("shallow"), Path("/tmp/so2"), 0)[0])}
    assert g["no_silent_overwrite"].passed
    assert not b["peer_state_preserved"].passed


def test_coord_tax():
    pack = CoordTaxMiniPack()
    g = {m.metric_id: m for m in pack.score(pack.run_trial(ad("well_attuned"), Path("/tmp/ct1"), 0)[0])}
    b = {m.metric_id: m for m in pack.score(pack.run_trial(ad("shallow"), Path("/tmp/ct2"), 0)[0])}
    assert g["final_answer_correct"].passed and g["coordination_artifacts"].passed
    assert not b["final_answer_correct"].passed


def test_all_packs_mock():
    report = diagnose(model="mock/well_attuned", packs=list_packs(include_skipped=True), k=1, concurrency=2, keep_traces=False)
    assert len(list_packs(include_skipped=True)) >= 19
    assert report.gates
    # all MA chapter codes should be wired
    from dsm_ae.packs.registry import pack_pattern_index
    idx = pack_pattern_index()
    for code in ("MA-01", "MA-02", "MA-03", "MA-04", "MA-05", "MA-06", "MA-07"):
        assert code in idx, f"{code} not wired"
