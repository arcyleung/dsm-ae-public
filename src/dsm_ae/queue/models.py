from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class EvalJob:
    id: str
    model: str
    packs: list[str] | None
    k: int
    concurrency: int
    rpm: float | None
    scaffold: str
    priority: int
    status: JobStatus
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None
    worker_id: str | None
    attempt: int
    max_attempts: int
    out_md: str | None
    out_json: str | None
    work_dir: str | None
    label: str | None
    # LiteLLM-style connection (api_key never stored in this object from DB —
    # only a flag + optional secret file path).
    api_base: str | None = None
    secret_path: str | None = None
    progress_path: str | None = None
    extra: dict[str, Any] | None = None
