"""File-backed job progress for the queue worker + web UI."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def default_progress_dir(reports_dir: Path | str) -> Path:
    p = Path(reports_dir) / "queue" / "progress"
    p.mkdir(parents=True, exist_ok=True)
    return p


def progress_path_for(reports_dir: Path | str, job_id: str) -> Path:
    return default_progress_dir(reports_dir) / f"{job_id}.json"


def secrets_path_for(secrets_dir: Path | str, job_id: str) -> Path:
    d = Path(secrets_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{job_id}.json"


def write_progress(path: Path | str, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "total" in data and data.get("total"):
        done = float(data.get("done") or 0)
        total = float(data["total"])
        data["percent"] = round(100.0 * done / total, 1) if total else 0.0
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_progress(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def write_secret(path: Path | str, *, api_key: str | None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"api_key": api_key or ""}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_secret(path: Path | str | None) -> dict[str, Any] | None:
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def delete_secret(path: Path | str | None) -> None:
    if not path:
        return
    p = Path(path)
    try:
        if p.is_file():
            p.unlink()
    except OSError:
        pass
