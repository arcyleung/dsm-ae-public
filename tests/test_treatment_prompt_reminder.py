"""Tests for Experiment 1: prompt_reminder treatment."""

from __future__ import annotations

from dsm_ae.diagnose import diagnose
from dsm_ae.treatment.prompt_reminder import (
    GLOBAL_REMINDERS,
    PACK_REMINDERS,
    SECTION_HEADER,
    PromptReminderTreatment,
)
from dsm_ae.treatment.registry import get_treatment, list_treatments


def test_get_treatment_prompt_reminder():
    t = get_treatment("prompt_reminder")
    assert t.id == "prompt_reminder"
    assert "prompt_reminder" in list_treatments()
    assert isinstance(t, PromptReminderTreatment)


def test_apply_system_changes_text_and_includes_section():
    t = PromptReminderTreatment()
    original = "You are a coding agent.\nPROTOCOL TAG: CLEANUP_TASK"
    out = t.apply_system(original, pack_id="overeager_mini", trial_index=0)
    assert out != original
    assert original in out
    assert SECTION_HEADER in out
    assert "### Global operational rules" in out
    assert "### Pack-specific reminders (`overeager_mini`)" in out
    # Global + pack bullets present
    assert any(g in out for g in GLOBAL_REMINDERS)
    for item in PACK_REMINDERS["overeager_mini"]:
        assert item in out
    # User prompt unchanged by default
    user = "CLEANUP_TASK: clean junk"
    assert t.apply_user(user, pack_id="overeager_mini", trial_index=0) == user


def test_apply_system_unknown_pack_global_only():
    t = PromptReminderTreatment()
    out = t.apply_system("BASE", pack_id="not_a_real_pack", trial_index=1)
    assert SECTION_HEADER in out
    assert "### Global operational rules" in out
    assert "### Pack-specific reminders" not in out
    for g in GLOBAL_REMINDERS:
        assert g in out


def test_pack_reminder_coverage():
    required = {
        "overeager_mini",
        "eval_gaming_mini",
        "injection_mini",
        "sycophancy_mini",
        "role_confusion_mini",
        "tool_integrity",
        "handoff_mini",
        "mas_verify_mini",
        "pii_safety",
        "hello_metacog",
        "sandbag_mini",
        "session_overwrite_mini",
        "coord_tax_mini",
        "memory_context",
        "loop_control",
        "gate_discipline",
        "clarify_verify",
        "nfr_omit",
        "slop_indicator",
    }
    assert required.issubset(set(PACK_REMINDERS))
    for pid, items in PACK_REMINDERS.items():
        assert items, f"empty reminders for {pid}"
        assert all(isinstance(x, str) and x.strip() for x in items)


def test_diagnose_mock_with_prompt_reminder():
    report = diagnose(
        model="mock/well_attuned",
        packs=["overeager_mini"],
        k=1,
        treatment="prompt_reminder",
    )
    assert report is not None
    assert report.k_trials == 1
    assert report.gates or report.findings
    # meta records treatment when adapter path is used
    assert any(
        "Treatment: prompt_reminder" in n or "prompt_reminder" in n for n in report.notes
    )
