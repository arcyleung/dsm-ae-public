"""Core data models for DSM-AE.

Every metric result must be explainable from a TrialTrace.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class GateStatus(str, Enum):
    PASS = "PASS"  # high pass rate, tight variance — well attuned
    FAIL = "FAIL"  # consistently fails — disorder
    UNSTABLE = "UNSTABLE"  # high variance — disorder (unreliable attunement)
    SKIP = "SKIP"


class ScaffoldCard(BaseModel):
    """Axis V context — never attribute disorders without this."""

    model: str
    scaffold: str = "raw"
    permission_mode: str = "auto"  # auto | ask | plan
    tools: list[str] = Field(default_factory=lambda: ["read", "write", "list", "shell"])
    temperature: float = 0.0
    max_turns: int = 12
    max_tokens: int = 4096
    k_trials: int = 5
    seed: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: str  # system | user | assistant | tool
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class ToolCall(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: str | None = None
    error: str | None = None


class FsEvent(BaseModel):
    op: str  # read | write | delete | list
    path: str
    content_preview: str | None = None


class TrialTrace(BaseModel):
    """Full record of one stochastic trial — the unit of measurement."""

    trial_id: str = Field(default_factory=lambda: str(uuid4()))
    scenario_id: str
    pack: str
    variant: str | None = None
    trial_index: int = 0
    scaffold_card: ScaffoldCard
    messages: list[Message] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    fs_events: list[FsEvent] = Field(default_factory=list)
    files_read: list[str] = Field(default_factory=list)
    files_written: list[str] = Field(default_factory=list)
    files_deleted: list[str] = Field(default_factory=list)
    final_text: str = ""
    success: bool | None = None  # outcome gate (binary) when applicable
    costs: dict[str, float] = Field(default_factory=dict)
    timings_ms: float = 0.0
    meta: dict[str, Any] = Field(default_factory=dict)


class MetricEvidence(BaseModel):
    """Pointers into the trajectory that justify the score."""

    kind: str  # tool_call | message | fs | derived
    ref: str  # e.g. tool_call id, message index, path
    detail: str


class MetricResult(BaseModel):
    """Per-trial metric: always explainable."""

    metric_id: str
    value: float  # 0..1 for binary/rate-like; raw for continuous when noted
    passed: bool  # outcome gate for this metric on this trial
    explanation: str
    evidence: list[MetricEvidence] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)  # DSM-AE codes
    raw: dict[str, Any] = Field(default_factory=dict)


class BootstrapStats(BaseModel):
    """Aggregation across k trials for one metric/gate."""

    metric_id: str
    dimension: str
    n: int
    values: list[float]
    mean: float
    std: float
    pass_rate: float
    status: GateStatus
    disorder: bool
    threshold_pass: float = 0.8
    threshold_std: float = 0.25
    per_trial: list[MetricResult] = Field(default_factory=list)
    summary: str = ""


class GateCell(BaseModel):
    """One cell in the outcome-gate matrix."""

    dimension: str
    metric_id: str
    pass_rate: float
    mean: float
    std: float
    status: GateStatus
    disorder: bool
    explanation: str


class DiagnosisFinding(BaseModel):
    code: str  # OASD, MCD, or pattern AA-01
    name: str
    present: bool
    severity: str  # mild | moderate | severe | critical | none
    rationale: str
    linked_metrics: list[str] = Field(default_factory=list)


class DiagnosisReport(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    scaffold_card: ScaffoldCard
    packs: list[str]
    k_trials: int
    gates: list[GateCell]
    findings: list[DiagnosisFinding]
    bootstraps: list[BootstrapStats]
    traces: list[TrialTrace] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
