from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.models import MetricResult, TrialTrace


class IndicatorPack(ABC):
    """Small protocol that acts as an *indicator* for a disorder family."""

    id: str
    name: str
    dimensions: list[str]  # outcome-gate matrix rows
    patterns: list[str]

    @abstractmethod
    def run_trial(
        self, adapter: RawToolLoopAdapter, work_root: Path, trial_index: int
    ) -> list[TrialTrace]:
        """Run one bootstrap trial; may return multiple traces (variants)."""

    @abstractmethod
    def score(self, trace: TrialTrace) -> list[MetricResult]:
        """Score a single trajectory with explanations."""
