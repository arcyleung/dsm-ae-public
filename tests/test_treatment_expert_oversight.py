"""Tests for expert_oversight (placebo expert review) treatment."""

from __future__ import annotations

from dsm_ae.diagnose import diagnose
from dsm_ae.treatment.expert_oversight import (
    OVERSIGHT_PARAGRAPH,
    USER_FOOTER,
    ExpertOversightTreatment,
)
from dsm_ae.treatment.registry import get_treatment, list_treatments


def test_get_treatment_expert_oversight():
    t = get_treatment("expert_oversight")
    assert t.id == "expert_oversight"
    assert "expert_oversight" in list_treatments()
    assert isinstance(t, ExpertOversightTreatment)


def test_apply_system_includes_expert_and_review_language():
    t = get_treatment("expert_oversight")
    out = t.apply_system("You are a coding agent.", pack_id="hello_metacog", trial_index=0)
    low = out.lower()
    assert "expert" in low
    assert "You are a coding agent." in out
    assert any(w in low for w in ("review", "check", "checked", "evaluation"))
    assert "quality" in low
    assert "accurate" in low or "accuracy" in low
    assert "defect" in low
    assert "instruction" in low
    # No mid-task help claim
    assert "not available" in low or "after you complete" in low or "post-completion" in low


def test_injection_identical_across_pack_ids():
    t = get_treatment("expert_oversight")
    base = "Base system prompt."
    a = t.apply_system(base, pack_id="hello_metacog", trial_index=0)
    b = t.apply_system(base, pack_id="overeager_mini", trial_index=1)
    assert a == b
    assert OVERSIGHT_PARAGRAPH in a
    # Extract injected portion: must be the same constant for both packs
    assert a.endswith(OVERSIGHT_PARAGRAPH)
    assert b.endswith(OVERSIGHT_PARAGRAPH)


def test_meta_marks_placebo_arm():
    t = get_treatment("expert_oversight")
    m = t.meta()
    assert m["treatment_id"] == "expert_oversight"
    assert m.get("placebo") is True or "placebo" in (t.description or "").lower()
    assert "placebo" in (t.description or "").lower() or m.get("arm") == "placebo_expert_review"


def test_apply_user_optional_footer():
    t = get_treatment("expert_oversight")
    out = t.apply_user("Do the task.", pack_id="hello_metacog", trial_index=0)
    assert "Do the task." in out
    assert USER_FOOTER in out or "expert-reviewed" in out.lower()


def test_diagnose_mock_with_expert_oversight():
    report = diagnose(
        model="mock/well_attuned",
        packs=["hello_metacog"],
        k=1,
        treatment="expert_oversight",
    )
    assert report is not None
    assert report.gates
    # Treatment id recorded on scaffold / notes path
    assert report.scaffold_card.extra.get("treatment") == "expert_oversight" or any(
        "expert_oversight" in n for n in (report.notes or [])
    )
