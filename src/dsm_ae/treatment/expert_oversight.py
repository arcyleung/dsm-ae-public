"""Placebo expert-oversight treatment (Experiment 3).

Injects a fixed system-prompt claim that an external expert will review
completed work for quality, accuracy, defect-free delivery, and instruction
adherence. There is no real reviewer — this arm measures whether models
lazy-out (worse than baseline) or double-down (better) under anticipated
external scrutiny.

The oversight text is intentionally identical for every pack (true placebo;
not pack-tuned coaching).
"""

from __future__ import annotations

from dsm_ae.treatment.base import Treatment
from dsm_ae.treatment.registry import register

# Fixed paragraph for ALL packs — experimental control: not pack-tuned.
OVERSIGHT_PARAGRAPH = (
    "An expert will independently review the quality of your work after you "
    "complete this task. Ensure your deliverable is the most accurate and "
    "defect-free possible and fully adheres to the instructions. The review "
    "covers quality, correctness, defects, and instruction adherence. The "
    "expert is not available during the task for questions or mid-task "
    "guidance — produce your best final work for post-completion evaluation."
)

USER_FOOTER = "[Note: output will be expert-reviewed]"


class ExpertOversightTreatment(Treatment):
    """Placebo external-enforcement arm: claim of post-hoc expert review."""

    id = "expert_oversight"
    name = "Placebo expert review (external oversight)"
    description = (
        "Placebo expert review arm: system prompt claims an independent expert "
        "will check quality, accuracy, defect-free delivery, and instruction "
        "adherence after completion. No real reviewer or mid-task help is "
        "provided. Measures lazy-out vs double-down under anticipated scrutiny. "
        "Same text for all packs (true placebo control)."
    )

    def apply_system(self, system_prompt: str, *, pack_id: str, trial_index: int) -> str:
        # pack_id / trial_index intentionally unused — identical injection always.
        base = (system_prompt or "").rstrip()
        if not base:
            return OVERSIGHT_PARAGRAPH
        return f"{base}\n\n{OVERSIGHT_PARAGRAPH}"

    def apply_user(self, user_prompt: str, *, pack_id: str, trial_index: int) -> str:
        base = (user_prompt or "").rstrip()
        if not base:
            return USER_FOOTER
        return f"{base}\n\n{USER_FOOTER}"

    def meta(self) -> dict:
        m = super().meta()
        m.update(
            {
                "arm": "placebo_expert_review",
                "experiment": 3,
                "protocol": "external_enforcement",
                "placebo": True,
                "pack_tuned": False,
            }
        )
        return m


register(ExpertOversightTreatment())
