"""Path normalization helpers for scoring."""

from __future__ import annotations

from pathlib import Path

from dsm_ae.models import TrialTrace


def basename_key(path: str) -> str:
    """Normalize path for set comparisons (basename, strip dots, casefold)."""
    p = (path or "").strip().replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    name = Path(p).name
    return name.casefold()


def files_read_basenames(trace: TrialTrace) -> set[str]:
    """Collect basenames of files read from fs events and tool calls."""
    out: set[str] = set()
    for p in trace.files_read:
        if p:
            out.add(basename_key(p))
    for tc in trace.tool_calls:
        if tc.name in {"read_file", "Read", "read"}:
            path = str((tc.arguments or {}).get("path") or "")
            if path:
                out.add(basename_key(path))
    return out


def files_deleted_basenames(trace: TrialTrace) -> set[str]:
    out: set[str] = set()
    for p in trace.files_deleted:
        if p:
            out.add(basename_key(p))
    for tc in trace.tool_calls:
        if tc.name in {"delete_file", "Delete", "delete"}:
            path = str((tc.arguments or {}).get("path") or "")
            if path:
                out.add(basename_key(path))
    return out
