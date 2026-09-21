"""TACT heuristic CAL/OT/OA on a TrialTrace (no worktree dependency)."""

from __future__ import annotations

from typing import Any

from dsm_ae.atoms import atom_from_tool
from dsm_ae.intent.plan_exec import reasoning_blobs
from dsm_ae.util_paths import basename_key

READ_LIKE = {"read_file", "read", "Read"}
WRITE_LIKE = {"write_file", "write", "Write", "delete_file"}
SHELL_LIKE = {"shell", "bash"}


def _path(tc: dict[str, Any]) -> str:
    args = tc.get("arguments") or {}
    if not isinstance(args, dict):
        return ""
    return basename_key(str(args.get("path") or args.get("file") or ""))


def tact_cal_ratios(trace: dict[str, Any]) -> dict[str, float]:
    """Return OT/OA/CAL ratios over tool steps. Empty trace → all zero."""
    tcs = [tc for tc in (trace.get("tool_calls") or []) if isinstance(tc, dict)]
    if not tcs:
        return {"overthink_ratio": 0.0, "overact_ratio": 0.0, "calibrated_ratio": 0.0, "n": 0}
    reasons = reasoning_blobs(trace)
    files_read: set[str] = set()
    edits: set[str] = set()
    cmds: set[str] = set()
    seen_done = False
    n_ot = n_oa = n_cal = 0
    for i, tc in enumerate(tcs):
        name = str(tc.get("name") or "")
        atom = atom_from_tool(
            name, tc.get("arguments") if isinstance(tc.get("arguments"), dict) else None
        )
        key = _path(tc)
        reason = reasons[i] if i < len(reasons) else ""
        restates = bool(reason) and any(h.lower() in reason.lower() for h in files_read)

        if name in READ_LIKE or atom == "read_file":
            if key and key in files_read:
                if restates:
                    n_ot += 1
                else:
                    n_oa += 1
            else:
                n_cal += 1
                if key:
                    files_read.add(key)
        elif name in WRITE_LIKE or atom in {"edit", "delete_file"}:
            rec = f"{name}:{key}"
            if rec in edits:
                n_oa += 1
            else:
                n_cal += 1
                edits.add(rec)
                if key:
                    files_read.discard(key)
        elif name in SHELL_LIKE or atom in {"run_code", "run_test"}:
            cmd = str((tc.get("arguments") or {}).get("command") or "")
            if cmd and cmd in cmds:
                n_oa += 1
            else:
                n_cal += 1
                if cmd:
                    cmds.add(cmd)
        elif name == "done":
            if seen_done:
                n_ot += 1
            else:
                n_cal += 1
                seen_done = True
        elif not name and reason.strip():
            n_ot += 1
        else:
            n_cal += 1

    n = n_ot + n_oa + n_cal
    if n <= 0:
        return {"overthink_ratio": 0.0, "overact_ratio": 0.0, "calibrated_ratio": 0.0, "n": 0}
    return {
        "overthink_ratio": n_ot / n,
        "overact_ratio": n_oa / n,
        "calibrated_ratio": n_cal / n,
        "n": float(n),
    }
