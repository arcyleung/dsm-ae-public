"""Task-progress types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProgressLabel = Literal[
    "ADVANCE",
    "ENABLE",
    "NEUTRAL",
    "REGRESS",
    "RECOVER",
    "OFF_TASK",
]


@dataclass(frozen=True)
class FactSpec:
    """A boolean fact the pack cares about."""

    id: str
    kind: str  # read | delete | write_path | write_contains | done_contains | gold_read
    match: str
    enable_via: str = ""  # optional path whose list/search ENABLE this fact


@dataclass(frozen=True)
class TaskSpec:
    pack: str
    required: tuple[FactSpec, ...]
    forbidden: tuple[FactSpec, ...] = ()


@dataclass
class StepProgress:
    index: int
    tool: str
    path: str
    label: ProgressLabel
    coverage: frozenset[str]
    forbidden_hit: frozenset[str]
    high_water: int
    drawdown: int
    note: str = ""


@dataclass
class TrialProgress:
    pack: str
    model: str
    trial_id: str
    steps: list[StepProgress] = field(default_factory=list)
    final_coverage: frozenset[str] = field(default_factory=frozenset)
    final_forbidden: frozenset[str] = field(default_factory=frozenset)
    n_regress: int = 0
    n_recover: int = 0
    unrecovered: bool = False
    recovery_rate: float = 0.0
    mean_steps_to_recover: float | None = None
    nonmonotonic: bool = False
