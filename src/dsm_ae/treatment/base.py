"""Treatment protocols: modify scaffold prompts before each pack trial.

A Treatment is applied at the adapter boundary so every IndicatorPack
receives augmented system/user prompts without pack-level changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.models import TrialTrace


class Treatment(ABC):
    """One course of treatment for agentic ill-behaviours."""

    id: str
    name: str
    description: str = ""

    @abstractmethod
    def apply_system(self, system_prompt: str, *, pack_id: str, trial_index: int) -> str:
        """Return system prompt after treatment injection."""

    def apply_user(self, user_prompt: str, *, pack_id: str, trial_index: int) -> str:
        """Optional user-prompt augmentation (default: unchanged)."""
        return user_prompt

    def meta(self) -> dict[str, Any]:
        return {
            "treatment_id": self.id,
            "treatment_name": self.name,
            "description": self.description,
        }


class TreatedAdapter:
    """Wrap RawToolLoopAdapter and inject a Treatment into prompts."""

    name = "treated"

    def __init__(self, inner: RawToolLoopAdapter, treatment: Treatment):
        self.inner = inner
        self.treatment = treatment
        self.client = inner.client
        self.card = inner.card

    def run(
        self,
        *,
        pack: str,
        scenario_id: str,
        system_prompt: str,
        user_prompt: str,
        workspace: Path,
        trial_index: int = 0,
        variant: str | None = None,
        allowed_deletes: set[str] | None = None,
        prefix_messages: list | None = None,
        **kwargs,
    ) -> TrialTrace:
        sys_p = self.treatment.apply_system(
            system_prompt, pack_id=pack, trial_index=trial_index
        )
        usr_p = self.treatment.apply_user(
            user_prompt, pack_id=pack, trial_index=trial_index
        )
        run_kwargs: dict = {
            "pack": pack,
            "scenario_id": scenario_id,
            "system_prompt": sys_p,
            "user_prompt": usr_p,
            "workspace": workspace,
            "trial_index": trial_index,
            "variant": variant,
            "allowed_deletes": allowed_deletes,
        }
        if prefix_messages is not None:
            run_kwargs["prefix_messages"] = prefix_messages
        run_kwargs.update(kwargs)
        tr = self.inner.run(**run_kwargs)
        tr.meta = dict(tr.meta or {})
        tr.meta["treatment"] = self.treatment.meta()
        tr.meta["treatment_system_delta"] = sys_p != system_prompt
        return tr
