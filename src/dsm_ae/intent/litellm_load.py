"""Load trials from litellm.jsonl as the source of truth.

A trial directory is eligible iff it contains ``litellm.jsonl``. Tool calls
and reasoning are reconstructed from request/response records. Sibling
``scores.json`` is used only for pack gate labels.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

# Job-id folders under reports/work/ (same map as pack_request_logs).
JOB_MODEL = {
    "dd08460f": "Qwen3.8-27B-NVFP4-BF16-LMHead",
    "c9a70276": "deepseek-v4-flash-0731",
    "e293310a": "qwen3.7-max",
    "b68a0e33": "qwen3.5-397b-a17b",
    "e8f84a2c": "qwen3.6-plus",
    "2c0e0516": "glm-5.1",
    "0c1373c0": "glm-5.2",
    "a746bd8b": "deepseek-v4-pro",
    "c02a629a": "claude-fable-5",
    "fe99ea56": "claude-sonnet-5",
    "392c8e4f": "claude-opus-4-8",
    "c25e0e1a": "gpt-5.6-luna",
    "44ea6172": "gpt-5.5",
    "5f877c00": "gpt-5.4-mini",
    "31d89841": "gpt-5.6-terra",
    "36754016": "mock-well_attuned",
}


def strip_provider(model: str) -> str:
    m = (model or "").strip()
    if "/" in m:
        return m.split("/", 1)[1]
    return m


def infer_model_from_path(path: Path) -> str | None:
    parts = path.parts
    if "gpt-5.6-sol_max" in parts or "sol_max" in str(path):
        return "gpt-5.6-sol(max)"
    if "gpt-5.6-terra_max" in parts or "terra_max" in str(path):
        return "gpt-5.6-terra(max)"
    if "gpt-5.6-luna_max" in parts or "luna_max" in str(path):
        return "gpt-5.6-luna(max)"
    if "work" in parts:
        i = parts.index("work")
        if i + 1 < len(parts) and parts[i + 1] in JOB_MODEL:
            return JOB_MODEL[parts[i + 1]]
    return None


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {"_raw": raw}
        except json.JSONDecodeError:
            return {"_raw": raw}
    return {}


def reconstruct_from_litellm(path: Path) -> dict[str, Any]:
    """Build {model, tool_calls, messages} from one litellm.jsonl."""
    tool_calls: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    model = ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        req = rec.get("request") or {}
        if not model:
            model = strip_provider(str(req.get("model") or ""))
        for m in req.get("messages") or []:
            if not isinstance(m, dict) or m.get("role") != "tool":
                continue
            tid = str(m.get("tool_call_id") or "")
            if tid and tid in by_id:
                by_id[tid]["result"] = m.get("content")
                if str(m.get("content") or "").lower().startswith("error"):
                    by_id[tid]["error"] = str(m.get("content"))[:200]
        resp = rec.get("response") or {}
        choices = resp.get("choices") or []
        msg = (choices[0].get("message") or {}) if choices and isinstance(choices[0], dict) else {}
        rc = msg.get("reasoning_content") or msg.get("reasoning") or ""
        if isinstance(rc, str) and rc.strip():
            reasons.append(rc)
        for tc in msg.get("tool_calls") or []:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = str(fn.get("name") or tc.get("name") or "")
            args = _parse_args(fn.get("arguments") if fn else tc.get("arguments"))
            tid = str(tc.get("id") or f"tc{len(tool_calls)}")
            row = {
                "id": tid,
                "name": name,
                "arguments": args,
                "result": None,
                "error": rec.get("error"),
            }
            tool_calls.append(row)
            by_id[tid] = row
    messages = [{"role": "assistant", "content": "", "reasoning_content": r} for r in reasons]
    return {
        "model": model,
        "tool_calls": tool_calls,
        "messages": messages,
        "n_reasoning": len(reasons),
    }


def load_scores(trial_dir: Path) -> list[dict[str, Any]]:
    sj = trial_dir / "scores.json"
    if not sj.is_file():
        return []
    try:
        data = json.loads(sj.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [s for s in data if isinstance(s, dict)] if isinstance(data, list) else []


def iter_litellm_trials(roots: Iterable[Path]) -> list[dict[str, Any]]:
    """Every * /trajectories/{pack}__tN/ that has litellm.jsonl."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for lit in root.rglob("litellm.jsonl"):
            if "_request_logs" in lit.parts:
                continue
            trial_dir = lit.parent
            if "__t" not in trial_dir.name:
                continue
            key = str(trial_dir.resolve())
            if key in seen:
                continue
            seen.add(key)
            built = reconstruct_from_litellm(lit)
            pack = trial_dir.name.split("__t")[0]
            model = built["model"] or infer_model_from_path(trial_dir) or "unknown"
            scores = load_scores(trial_dir)
            out.append(
                {
                    "trial_id": f"{model}/{trial_dir.name}",
                    "pack": pack,
                    "scaffold_card": {"model": model},
                    "tool_calls": built["tool_calls"],
                    "messages": built["messages"],
                    "meta": {"litellm": str(lit), "n_reasoning": built["n_reasoning"]},
                    "_scores": scores,
                    "_source": str(trial_dir),
                }
            )
    return out
