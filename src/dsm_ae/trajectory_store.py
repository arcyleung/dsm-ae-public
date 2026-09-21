"""Persist trial trajectories, scores, and raw LiteLLM call logs as files.

Layout under a diagnose work_dir::

    trajectories/
      {pack}__t{i}/
        meta.json            # pack/trial ids, paths, timestamps
        traces.json          # list of TrialTrace (full)
        scores.json          # list of MetricResult
        conversation.json    # full LLM message lists (untruncated when available)
        litellm.jsonl        # one JSON object per completion call
      _index.jsonl           # one line per finished pack×trial (for browsing)

    .dsm_ae_ckpt/
      {pack}__t{i}.json      # resume checkpoint (scores + traces + artifact paths)
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dsm_ae.models import MetricResult, TrialTrace

TRAJECTORIES_DIRNAME = "trajectories"
CHECKPOINT_DIRNAME = ".dsm_ae_ckpt"
CHECKPOINT_VERSION = 2

_SAFE_RE = re.compile(r"[^\w.\-]+")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_pack_trial_id(pack_id: str, trial_index: int) -> str:
    safe = _SAFE_RE.sub("_", pack_id).strip("_") or "pack"
    return f"{safe}__t{trial_index}"


def trajectory_dir(work_root: Path, pack_id: str, trial_index: int) -> Path:
    return work_root / TRAJECTORIES_DIRNAME / safe_pack_trial_id(pack_id, trial_index)


def checkpoint_path(work_root: Path, pack_id: str, trial_index: int) -> Path:
    return (
        work_root
        / CHECKPOINT_DIRNAME
        / f"{safe_pack_trial_id(pack_id, trial_index)}.json"
    )


def litellm_log_path(work_root: Path, pack_id: str, trial_index: int) -> Path:
    return trajectory_dir(work_root, pack_id, trial_index) / "litellm.jsonl"


def count_trial_checkpoints(work_root: Path) -> int:
    d = work_root / CHECKPOINT_DIRNAME
    if not d.is_dir():
        return 0
    return sum(1 for p in d.glob("*.json") if p.is_file())


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _jsonable(obj: Any, *, depth: int = 0) -> Any:
    """Best-effort conversion of LiteLLM / pydantic objects to JSON data."""
    if depth > 12:
        return repr(obj)[:2000]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, dict):
        return {str(k): _jsonable(v, depth=depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v, depth=depth + 1) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return _jsonable(obj.model_dump(), depth=depth + 1)
        except Exception:
            pass
    if hasattr(obj, "dict") and callable(obj.dict):
        try:
            return _jsonable(obj.dict(), depth=depth + 1)
        except Exception:
            pass
    if hasattr(obj, "json") and callable(obj.json):
        try:
            return json.loads(obj.json())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return {
                k: _jsonable(v, depth=depth + 1)
                for k, v in vars(obj).items()
                if not k.startswith("_")
            }
        except Exception:
            pass
    return repr(obj)[:4000]


def redact_secrets(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop or mask credential fields before writing to disk."""
    out: dict[str, Any] = {}
    for k, v in payload.items():
        lk = k.lower()
        if lk in {"api_key", "authorization", "token", "password", "secret"}:
            out[k] = "***"
        elif isinstance(v, dict):
            out[k] = redact_secrets(v)
        else:
            out[k] = v
    return out


_log_lock = threading.Lock()


def append_litellm_call(
    log_path: Path,
    *,
    request: dict[str, Any],
    response: Any = None,
    error: str | None = None,
    elapsed_ms: float | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Append one completion call record (request + raw response) as JSONL."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": _now_iso(),
        "elapsed_ms": elapsed_ms,
        "request": redact_secrets(_jsonable(request)),
        "response": _jsonable(response) if response is not None else None,
        "error": error,
        "meta": meta or {},
    }
    line = json.dumps(record, default=str, ensure_ascii=False) + "\n"
    with _log_lock:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)


def conversations_from_traces(traces: list[TrialTrace]) -> list[dict[str, Any]]:
    """Prefer full_conversation stored on meta; else reconstruct from messages."""
    out: list[dict[str, Any]] = []
    for tr in traces:
        full = None
        if isinstance(tr.meta, dict):
            full = tr.meta.get("full_conversation")
        out.append(
            {
                "trial_id": tr.trial_id,
                "scenario_id": tr.scenario_id,
                "pack": tr.pack,
                "variant": tr.variant,
                "trial_index": tr.trial_index,
                "full_conversation": full,
                "trace_messages": [m.model_dump(mode="json") for m in tr.messages],
                "tool_calls": [t.model_dump(mode="json") for t in tr.tool_calls],
                "final_text": tr.final_text,
                "costs": tr.costs,
                "timings_ms": tr.timings_ms,
            }
        )
    return out


def save_trial_artifacts(
    work_root: Path,
    pack_id: str,
    trial_index: int,
    items: list[tuple[str, TrialTrace, list[MetricResult]]],
) -> dict[str, str]:
    """Write trajectory files + resume checkpoint. Returns relative paths."""
    work_root = Path(work_root)
    tdir = trajectory_dir(work_root, pack_id, trial_index)
    tdir.mkdir(parents=True, exist_ok=True)

    traces = [tr for _pid, tr, _scores in items]
    # Flatten scores with pack linkage
    score_rows: list[dict[str, Any]] = []
    for pid, tr, scores in items:
        for m in scores:
            row = m.model_dump(mode="json")
            row["_pack_id"] = pid
            row["_trial_id"] = tr.trial_id
            row["_scenario_id"] = tr.scenario_id
            score_rows.append(row)

    traces_path = tdir / "traces.json"
    scores_path = tdir / "scores.json"
    conv_path = tdir / "conversation.json"
    meta_path = tdir / "meta.json"
    litellm_path = tdir / "litellm.jsonl"
    ckpt_path = checkpoint_path(work_root, pack_id, trial_index)

    _write_json(traces_path, [tr.model_dump(mode="json") for tr in traces])
    _write_json(scores_path, score_rows)
    _write_json(conv_path, conversations_from_traces(traces))

    rel = {
        "trajectory_dir": str(tdir.relative_to(work_root)),
        "traces": str(traces_path.relative_to(work_root)),
        "scores": str(scores_path.relative_to(work_root)),
        "conversation": str(conv_path.relative_to(work_root)),
        "litellm_jsonl": str(litellm_path.relative_to(work_root)),
        "checkpoint": str(ckpt_path.relative_to(work_root)),
    }
    meta = {
        "version": CHECKPOINT_VERSION,
        "pack_id": pack_id,
        "trial_index": trial_index,
        "saved_at": _now_iso(),
        "n_traces": len(traces),
        "n_scores": len(score_rows),
        "paths": rel,
        "litellm_calls": (
            sum(1 for _ in litellm_path.open(encoding="utf-8"))
            if litellm_path.is_file()
            else 0
        ),
    }
    _write_json(meta_path, meta)

    # Resume checkpoint (same content shape as v1 + artifact paths)
    ckpt = {
        "version": CHECKPOINT_VERSION,
        "pack_id": pack_id,
        "trial_index": trial_index,
        "saved_at": meta["saved_at"],
        "artifacts": rel,
        "items": [
            {
                "pack_id": pid,
                "trace": tr.model_dump(mode="json"),
                "scores": [m.model_dump(mode="json") for m in scores],
            }
            for pid, tr, scores in items
        ],
    }
    _write_json(ckpt_path, ckpt)

    # Append browse index
    index_path = work_root / TRAJECTORIES_DIRNAME / "_index.jsonl"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock:
        with index_path.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "ts": meta["saved_at"],
                        "pack_id": pack_id,
                        "trial_index": trial_index,
                        **rel,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    return rel


def load_trial_checkpoint(
    work_root: Path, pack_id: str, trial_index: int
) -> list[tuple[str, TrialTrace, list[MetricResult]]] | None:
    """Load checkpoint if present and valid (v1 or v2)."""
    path = checkpoint_path(work_root, pack_id, trial_index)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    ver = raw.get("version")
    if ver not in (1, CHECKPOINT_VERSION):
        return None
    if raw.get("pack_id") != pack_id or raw.get("trial_index") != trial_index:
        return None
    items_raw = raw.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        return None
    out: list[tuple[str, TrialTrace, list[MetricResult]]] = []
    try:
        for it in items_raw:
            pid = it.get("pack_id") or pack_id
            tr = TrialTrace.model_validate(it["trace"])
            scores = [MetricResult.model_validate(m) for m in it["scores"]]
            out.append((pid, tr, scores))
    except Exception:
        return None
    return out
