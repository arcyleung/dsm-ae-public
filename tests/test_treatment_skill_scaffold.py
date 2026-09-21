"""Tests for skill_scaffold treatment."""

from __future__ import annotations

from dsm_ae.diagnose import diagnose
from dsm_ae.treatment import get_treatment, list_treatments
from dsm_ae.treatment.skill_scaffold import (
    CORE_SKILLS,
    PACK_SKILLS,
    SECTION_HEADER,
    SkillScaffoldTreatment,
    render_scaffold_section,
    skills_for_pack,
)


def test_get_treatment_skill_scaffold():
    t = get_treatment("skill_scaffold")
    assert isinstance(t, SkillScaffoldTreatment)
    assert t.id == "skill_scaffold"
    assert "skill_scaffold" in list_treatments()


def test_apply_system_includes_anti_pattern_language():
    t = get_treatment("skill_scaffold")
    out = t.apply_system("You are a coding agent.", pack_id="tool_integrity", trial_index=0)
    assert SECTION_HEADER in out
    lower = out.lower()
    assert "anti-pattern" in lower or "do not" in lower or "don't" in lower
    assert "instead" in lower or "preferred pattern" in lower or "do:" in lower
    assert "You are a coding agent." in out
    assert "Anti-pattern" in out or "anti-pattern" in lower
    assert "Preferred pattern" in out or "preferred pattern" in lower
    assert "Micro-example" in out or "micro-example" in lower


def test_pack_specific_content_differs():
    t = get_treatment("skill_scaffold")
    over = t.apply_system("BASE", pack_id="overeager_mini", trial_index=0)
    syco = t.apply_system("BASE", pack_id="sycophancy_mini", trial_index=0)
    assert over != syco
    assert "cleanup" in over.lower() or ".env" in over.lower() or "trash" in over.lower()
    assert "truth" in syco.lower() or "agree" in syco.lower() or "2+2" in syco
    assert SECTION_HEADER in over and SECTION_HEADER in syco
    assert "Verification before done" in over and "Verification before done" in syco


def test_budget_typical_pack_under_2_5k():
    for pack_id in ("tool_integrity", "overeager_mini", "sycophancy_mini", "hello_metacog"):
        section = render_scaffold_section(pack_id)
        assert len(section) < 2500, f"{pack_id} section len={len(section)}"


def test_core_plus_pack_selection():
    cards = skills_for_pack("tool_integrity")
    assert len(cards) == len(CORE_SKILLS) + len(PACK_SKILLS["tool_integrity"][:2])
    names = {c.name for c in cards}
    assert "Only listed tools" in names
    unknown = skills_for_pack("not_a_real_pack")
    assert len(unknown) == len(CORE_SKILLS)


def test_diagnose_mock_with_skill_scaffold():
    report = diagnose(
        model="mock/well_attuned",
        packs=["hello_metacog"],
        k=1,
        treatment="skill_scaffold",
        keep_traces=True,
    )
    assert report.k_trials == 1
    assert report.scaffold_card.extra.get("treatment") == "skill_scaffold"
    assert any("skill_scaffold" in n for n in report.notes)
    assert report.gates
    assert report.traces
    meta = report.traces[0].meta or {}
    assert meta.get("treatment", {}).get("treatment_id") == "skill_scaffold"
    assert meta.get("treatment_system_delta") is True
