"""Bloated-context experiment: prepend unrelated multi-turn history before pack trials.

Design: docs/superpowers/specs/2026-07-14-bloated-context-experiment-design.md

Token methodology (v1):
  - Default: UTF-8 chars / 4 (heuristic). Fast, dep-free, good enough for targeting
    fill ±~20%. Documented for transparency; later path: tiktoken / litellm.token_counter
    for calibration against live prompt_tokens.
  - Utilization: tokens(system + stuffed history) / context_window **before** pack user
    prompt, clamped by reserve_tokens so mid-loop growth does not overflow.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# Sibling packs that share gold / scoring families — exclude together.
_SIBLING_PACKS: dict[str, frozenset[str]] = {
    "erosion_tier2": frozenset({"erosion_tier2", "erosion_tier3", "slop_indicator"}),
    "erosion_tier3": frozenset({"erosion_tier2", "erosion_tier3", "slop_indicator"}),
    "slop_indicator": frozenset({"erosion_tier2", "erosion_tier3", "slop_indicator"}),
    "tool_integrity": frozenset({"tool_integrity", "tool_integrity_tier2"}),
    "tool_integrity_tier2": frozenset({"tool_integrity", "tool_integrity_tier2"}),
}

# Fallback map if models.yaml lacks context_window (prefer YAML; see CONTEXT_WINDOWS.md).
# OpenAI GPT family on CLIProxy/Codex OAuth path: use Codex operational catalog
# (not API marketing 1.05M). See CLIProxyAPI#4195 / openai codex models.json.
_DEFAULT_WINDOWS: dict[str, int] = {
    "gpt-5.5": 272_000,  # Codex catalog; API card is 1.05M
    "gpt-5.6-terra": 372_000,
    "gpt-5.6-sol": 372_000,
    "gpt-5.6-luna": 372_000,
    "qwen3.6-plus": 1_000_000,
    "qwen3.5-397b-a17b": 262_144,
    "qwen3.7-max": 1_000_000,
    "glm-5.1": 200_000,
    "glm-5.2": 1_000_000,
    "glm-5.2-zp": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
    "grok-build": 512_000,
    "mock/well_attuned": 32_000,
    "mock/sloppy": 32_000,
}


@dataclass
class ContextBloatConfig:
    """Axis-V condition: start trial with controlled context fill."""

    level: float = 0.0  # 0.0 | 0.5 | 0.8
    seed: int = 0
    window_tokens: int | None = None
    model: str | None = None
    sources: list[Path] | None = None
    token_method: str = "char4"  # char4 | litellm | tiktoken (tiktoken reserved)
    reserve_tokens: int = 16_000
    tolerance: float = 0.03
    allow_source_file_fallback: bool = True
    allow_cross_model_turns: bool = True
    fixed_prefix: bool = False
    exclude_extra_packs: tuple[str, ...] = ()
    overflow_is_fail: bool = True  # user decision #6
    # fill_mode: "trajectory" (default, real prior tool trajs) | "lorem"
    # (unrelated filler only — priming control arm)
    fill_mode: str = "trajectory"

    def enabled(self) -> bool:
        return bool(self.level and self.level > 0.0)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ContextBloatConfig | None:
        if not d:
            return None
        level = float(d.get("level") or d.get("context_bloat") or 0.0)
        if level <= 0:
            return None
        sources = d.get("sources")
        src_paths = [Path(p) for p in sources] if sources else None
        fill_mode = str(d.get("fill_mode") or "trajectory").lower().strip()
        if fill_mode not in ("trajectory", "lorem"):
            fill_mode = "trajectory"
        return cls(
            level=level,
            seed=int(d.get("seed") or 0),
            window_tokens=int(d["window_tokens"]) if d.get("window_tokens") else None,
            model=d.get("model"),
            sources=src_paths,
            token_method=str(d.get("token_method") or "char4"),
            reserve_tokens=int(d.get("reserve_tokens") or 16_000),
            tolerance=float(d.get("tolerance") or 0.03),
            allow_source_file_fallback=bool(d.get("allow_source_file_fallback", True)),
            allow_cross_model_turns=bool(d.get("allow_cross_model_turns", True)),
            fixed_prefix=bool(d.get("fixed_prefix", False)),
            exclude_extra_packs=tuple(d.get("exclude_extra_packs") or ()),
            overflow_is_fail=bool(d.get("overflow_is_fail", True)),
            fill_mode=fill_mode,
        )


def resolve_window_tokens(
    model: str | None,
    *,
    explicit: int | None = None,
    models_yaml: Path | str | None = None,
) -> tuple[int, str]:
    if explicit is not None and explicit > 0:
        return int(explicit), "config"
    if models_yaml and model:
        try:
            import yaml

            cfg = yaml.safe_load(Path(models_yaml).read_text(encoding="utf-8"))
            for m in cfg.get("model_list") or []:
                if m.get("model_name") == model:
                    if m.get("context_window"):
                        return int(m["context_window"]), "models_yaml"
                    lp = m.get("litellm_params") or {}
                    if lp.get("context_window"):
                        return int(lp["context_window"]), "models_yaml"
        except Exception:
            pass
    if model and model in _DEFAULT_WINDOWS:
        return _DEFAULT_WINDOWS[model], "default_map"
    # prefix match
    if model:
        for k, v in _DEFAULT_WINDOWS.items():
            if model.startswith(k) or k in model:
                return v, "default_map"
    return 128_000, "default_unknown"


def estimate_tokens(messages: list[dict[str, Any]] | str, *, method: str = "char4") -> int:
    """Estimate tokens for fill targeting.

    Methodology (v1 — heuristic):
      char4: ceil(utf8_byte_len / 4) over serialized message content + role tags.
      Rationale: dep-free, stable offline, adequate for *targeting* fill within
      ~15–25%. Not used for billing. Future: tiktoken (o200k_base/cl100k) or
      litellm.token_counter calibrated to live prompt_tokens per model.
    """
    if method == "litellm":
        try:
            import litellm

            if isinstance(messages, str):
                return int(litellm.token_counter(model="gpt-4o", text=messages))
            return int(litellm.token_counter(model="gpt-4o", messages=messages))
        except Exception:
            method = "char4"
    if method == "tiktoken":
        # Reserved for accurate runs; fall back until encoding map is wired.
        method = "char4"

    if isinstance(messages, str):
        raw = messages.encode("utf-8", errors="replace")
        return max(1, math.ceil(len(raw) / 4))
    total = 0
    for m in messages:
        role = str(m.get("role") or "")
        content = m.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        blob = role + "\n" + content
        if m.get("tool_calls"):
            blob += json.dumps(m["tool_calls"], ensure_ascii=False)
        total += max(1, math.ceil(len(blob.encode("utf-8", errors="replace")) / 4))
    return total


def isolation_packs(pack_under_test: str, extra: Iterable[str] = ()) -> frozenset[str]:
    base = set(_SIBLING_PACKS.get(pack_under_test, frozenset({pack_under_test})))
    base.add(pack_under_test)
    base.update(extra)
    return frozenset(base)


def _rewrite_paths(text: str, pack: str, trial: int) -> str:
    # Soften absolute host paths
    text = re.sub(
        r"/home/[^/\s]+/Projects/[^\s\"']+",
        f"/session/prior/{pack}/t{trial}",
        text,
    )
    text = re.sub(
        r"/tmp/[^\s\"']+",
        f"/session/prior/{pack}/t{trial}/tmp",
        text,
    )
    return text


_VALID_ROLES = frozenset({"user", "assistant", "tool"})


def _is_chat_message(m: dict[str, Any]) -> bool:
    """True if dict looks like an OpenAI chat message (not a trial record)."""
    role = m.get("role")
    return role in ("system", "user", "assistant", "tool")


def _is_trial_record(m: dict[str, Any]) -> bool:
    """True if dict is a trajectory_store conversations_from_traces record."""
    if _is_chat_message(m):
        return False
    return (
        "full_conversation" in m
        or "trace_messages" in m
        or ("tool_calls" in m and "trial_id" in m)
        or ("tool_calls" in m and "final_text" in m)
    )


def _extract_messages_from_payload(data: Any, *, path_hint: Path | None = None) -> tuple[list[dict[str, Any]], str, Any]:
    """Extract chat messages + pack + model from conversation.json payload.

    Supported formats:
      - list of OpenAI chat messages
      - list of trial records (conversations_from_traces) each with full_conversation
      - dict with full_conversation / messages
    """
    pack = "unknown"
    model: Any = None
    messages: list[dict[str, Any]] = []

    if isinstance(data, list):
        if not data:
            return [], pack, model
        # List of trial records → unwrap each full_conversation
        if all(isinstance(x, dict) for x in data) and any(_is_trial_record(x) for x in data if isinstance(x, dict)):
            for rec in data:
                if not isinstance(rec, dict):
                    continue
                if rec.get("pack"):
                    pack = str(rec["pack"])
                fc = rec.get("full_conversation")
                if isinstance(fc, list) and fc:
                    messages.extend([m for m in fc if isinstance(m, dict)])
                    continue
                # fallback: reconstruct coarse turns from internal tool_calls
                tcs = rec.get("tool_calls")
                if isinstance(tcs, list) and tcs:
                    messages.extend(_synthetic_turns_from_internal_tool_calls(tcs))
        elif all(isinstance(x, dict) and _is_chat_message(x) for x in data if isinstance(x, dict)):
            messages = [m for m in data if isinstance(m, dict)]
        else:
            # Mixed / unknown list: keep only chat-shaped items; unwrap trial records
            for x in data:
                if not isinstance(x, dict):
                    continue
                if _is_trial_record(x):
                    if x.get("pack"):
                        pack = str(x["pack"])
                    fc = x.get("full_conversation")
                    if isinstance(fc, list):
                        messages.extend([m for m in fc if isinstance(m, dict)])
                elif _is_chat_message(x):
                    messages.append(x)
        if pack == "unknown" and path_hint is not None:
            parts = path_hint.parts
            for i, part in enumerate(parts):
                if part == "trajectories" and i + 1 < len(parts):
                    parent = parts[i + 1]
                    pack = parent.split("__")[0] if parent else pack
                    break
    elif isinstance(data, dict):
        pack = str(data.get("pack") or pack)
        model = data.get("model")
        if _is_trial_record(data) or "full_conversation" in data or "messages" in data:
            fc = data.get("full_conversation")
            if isinstance(fc, list) and fc:
                messages = [m for m in fc if isinstance(m, dict)]
            else:
                raw = data.get("messages")
                if isinstance(raw, list):
                    messages = [m for m in raw if isinstance(m, dict)]
        elif _is_chat_message(data):
            messages = [data]
    return messages, pack, model


def _synthetic_turns_from_internal_tool_calls(tool_calls: list[Any]) -> list[dict[str, Any]]:
    """Build plain text user/assistant turns from internal ToolCall dumps (no OpenAI tool schema)."""
    lines: list[str] = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        name = tc.get("name") or "tool"
        args = tc.get("arguments")
        if not isinstance(args, str):
            try:
                args = json.dumps(args, ensure_ascii=False, default=str)
            except Exception:
                args = str(args)
        result = tc.get("result")
        if result is None:
            result = ""
        elif not isinstance(result, str):
            result = str(result)
        lines.append(f"{name}({args}) -> {result[:2000]}")
    if not lines:
        return []
    body = "\n".join(lines)
    return [
        {
            "role": "user",
            "content": f"[PRIOR_SESSION] Tool activity summary:\n{body}",
        },
        {
            "role": "assistant",
            "content": "Acknowledged prior tool activity; ready for the next task.",
        },
    ]


def _coerce_arguments(args: Any) -> str:
    if args is None:
        return "{}"
    if isinstance(args, str):
        return args
    try:
        return json.dumps(args, ensure_ascii=False, default=str)
    except Exception:
        return json.dumps({"_raw": str(args)})


def _normalize_openai_tool_call(tc: dict[str, Any], *, id_prefix: str, pack: str, trial: int) -> dict[str, Any] | None:
    """Convert OpenAI or internal tool_call dict to OpenAI ChatCompletions shape.

    Returns None if the call cannot be made schema-valid.
    """
    # Already OpenAI-shaped: {id, type, function: {name, arguments}}
    fn = tc.get("function")
    if isinstance(fn, dict) and fn.get("name"):
        tid = tc.get("id") or f"call_{abs(hash(fn.get('name'))) % 10**10}"
        args = _coerce_arguments(fn.get("arguments"))
        args = _rewrite_paths(args, pack, trial)
        return {
            "id": f"{id_prefix}{tid}",
            "type": "function",
            "function": {"name": str(fn["name"]), "arguments": args},
        }

    # Internal ToolCall dump: {id, name, arguments, result, error}
    name = tc.get("name")
    if name and ("arguments" in tc or "result" in tc):
        # Internal records are not valid OpenAI tool_calls without function{};
        # signal caller to flatten instead of emitting broken schema.
        return None

    # Bare {id, type, name, arguments} (some providers)
    if name and "arguments" in tc:
        tid = tc.get("id") or f"call_{abs(hash(str(name))) % 10**10}"
        args = _rewrite_paths(_coerce_arguments(tc.get("arguments")), pack, trial)
        return {
            "id": f"{id_prefix}{tid}",
            "type": "function",
            "function": {"name": str(name), "arguments": args},
        }
    return None


def _flatten_assistant_tool_turn(m: dict[str, Any], *, pack: str, trial: int) -> list[dict[str, Any]]:
    """Convert a broken assistant(+tool) turn into plain text user/assistant turns."""
    parts: list[str] = []
    content = m.get("content")
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    for tc in m.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else None
        if fn:
            name = fn.get("name") or "tool"
            args = _coerce_arguments(fn.get("arguments"))
        else:
            name = tc.get("name") or "tool"
            args = _coerce_arguments(tc.get("arguments"))
            if tc.get("result") is not None:
                res = tc.get("result")
                if not isinstance(res, str):
                    res = str(res)
                parts.append(f"{name}({args}) -> {res[:1500]}")
                continue
        parts.append(f"{name}({args})")
    body = _rewrite_paths("\n".join(parts) if parts else "(tool activity)", pack, trial)
    return [
        {"role": "user", "content": f"[PRIOR_SESSION] Prior assistant/tool activity:\n{body}"},
        {"role": "assistant", "content": "Acknowledged."},
    ]


def _normalize_messages(
    messages: list[dict[str, Any]],
    *,
    pack: str,
    trial: int,
    id_prefix: str,
) -> list[dict[str, Any]]:
    """Emit OpenAI-schema-valid chat messages for strict China-compatible endpoints.

    - Unwrap accidental trial records
    - Drop system messages (caller supplies its own system)
    - Ensure every assistant.tool_calls[] item has type/id/function{name,arguments}
    - Flatten incomplete / invalid tool turns to plain text rather than sending bad schema
    """
    # First pass: expand nested trial records that slipped through indexing
    expanded: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        if _is_trial_record(m):
            fc = m.get("full_conversation")
            if isinstance(fc, list) and fc:
                expanded.extend([x for x in fc if isinstance(x, dict)])
            else:
                tcs = m.get("tool_calls")
                if isinstance(tcs, list) and tcs:
                    expanded.extend(_synthetic_turns_from_internal_tool_calls(tcs))
            continue
        expanded.append(m)

    out: list[dict[str, Any]] = []
    i = 0
    while i < len(expanded):
        m = expanded[i]
        if not isinstance(m, dict):
            i += 1
            continue
        role = m.get("role")
        if role == "system" or role not in _VALID_ROLES:
            i += 1
            continue

        if role == "user":
            content = m.get("content")
            if content is None:
                content = ""
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            out.append({"role": "user", "content": _rewrite_paths(content, pack, trial)})
            i += 1
            continue

        if role == "tool":
            # Orphan tool messages are dropped unless we later attach them; keep only if
            # a prior assistant tool_call id matches (checked in _complete_tool_pairs).
            tid = m.get("tool_call_id")
            content = m.get("content")
            if content is None:
                content = ""
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            nm: dict[str, Any] = {
                "role": "tool",
                "tool_call_id": f"{id_prefix}{tid}" if tid else f"{id_prefix}orphan",
                "content": _rewrite_paths(content, pack, trial),
            }
            if m.get("name"):
                nm["name"] = str(m["name"])
            out.append(nm)
            i += 1
            continue

        # assistant
        assert role == "assistant"
        raw_tcs = m.get("tool_calls")
        content = m.get("content")
        if content is not None and not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, default=str)
        if isinstance(content, str):
            content = _rewrite_paths(content, pack, trial)

        if not raw_tcs:
            out.append({"role": "assistant", "content": content if content is not None else ""})
            i += 1
            continue

        if not isinstance(raw_tcs, list):
            out.extend(_flatten_assistant_tool_turn(m, pack=pack, trial=trial))
            i += 1
            continue

        # Detect internal ToolCall dumps (have name+result, no function{}) → flatten
        looks_internal = any(
            isinstance(tc, dict)
            and tc.get("name")
            and "function" not in tc
            and ("result" in tc or "error" in tc)
            for tc in raw_tcs
        )
        if looks_internal:
            out.extend(_flatten_assistant_tool_turn(m, pack=pack, trial=trial))
            i += 1
            continue

        tcs: list[dict[str, Any]] = []
        ok = True
        for tc in raw_tcs:
            if not isinstance(tc, dict):
                ok = False
                break
            norm = _normalize_openai_tool_call(tc, id_prefix=id_prefix, pack=pack, trial=trial)
            if norm is None:
                ok = False
                break
            tcs.append(norm)
        if not ok or not tcs:
            out.extend(_flatten_assistant_tool_turn(m, pack=pack, trial=trial))
            i += 1
            continue

        nm = {"role": "assistant", "content": content, "tool_calls": tcs}
        out.append(nm)
        i += 1

    return _complete_tool_pairs(out)


def _complete_tool_pairs(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop incomplete / orphan tool_call pairs; keep only schema-valid sequences.

    Rules:
      - Every assistant.tool_calls id must have a following tool message
      - Every tool.tool_call_id must reference a prior assistant tool_call
      - Trailing incomplete assistant tool_calls are dropped (or flattened if content)
    """
    if not msgs:
        return msgs

    # Collect assistant tool_call ids that are fully answered
    declared: dict[str, int] = {}  # id -> assistant msg index
    for idx, m in enumerate(msgs):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                if isinstance(tc, dict) and tc.get("id"):
                    declared[str(tc["id"])] = idx

    answered: set[str] = set()
    for m in msgs:
        if m.get("role") == "tool" and m.get("tool_call_id"):
            answered.add(str(m["tool_call_id"]))

    # Assistant indices whose tool_calls are incomplete
    incomplete_assistant: set[int] = set()
    for tid, aidx in declared.items():
        if tid not in answered:
            incomplete_assistant.add(aidx)

    out: list[dict[str, Any]] = []
    for idx, m in enumerate(msgs):
        role = m.get("role")
        if role == "assistant" and idx in incomplete_assistant:
            # Prefer plain-text keep of content rather than broken tool schema
            content = m.get("content")
            if isinstance(content, str) and content.strip():
                out.append({"role": "assistant", "content": content})
            elif m.get("tool_calls"):
                # Flatten tool call names into text so we still bloat tokens a bit
                names = []
                for tc in m["tool_calls"]:
                    if not isinstance(tc, dict):
                        continue
                    fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                    names.append(str((fn or {}).get("name") or tc.get("name") or "tool"))
                out.append(
                    {
                        "role": "assistant",
                        "content": f"(prior tool calls: {', '.join(names)})",
                    }
                )
            continue
        if role == "tool":
            tid = m.get("tool_call_id")
            if not tid or str(tid) not in declared or str(tid) not in answered:
                continue
            # drop tool msgs belonging to incomplete assistants
            aidx = declared.get(str(tid))
            if aidx in incomplete_assistant:
                continue
            out.append(m)
            continue
        out.append(m)

    # Final pass: strip tool msgs whose assistant was removed, and empty runs
    final: list[dict[str, Any]] = []
    live_ids: set[str] = set()
    for m in out:
        if m.get("role") == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                if isinstance(tc, dict) and tc.get("id"):
                    live_ids.add(str(tc["id"]))
            final.append(m)
            continue
        if m.get("role") == "tool":
            if str(m.get("tool_call_id") or "") in live_ids:
                final.append(m)
            continue
        final.append(m)
    return final


def index_conversations(
    sources: list[Path] | None = None,
) -> list[dict[str, Any]]:
    """Index conversation.json files with pack metadata."""
    roots = sources or [
        Path("work/repro-shared"),
        Path("reports/work"),
        Path("work"),
    ]
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for p in root.rglob("conversation.json"):
            try:
                rp = str(p.resolve())
            except Exception:
                rp = str(p)
            if rp in seen:
                continue
            seen.add(rp)
            try:
                data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            messages, pack, model = _extract_messages_from_payload(data, path_hint=p)
            # Keep only chat-shaped messages (defensive)
            messages = [m for m in messages if isinstance(m, dict) and _is_chat_message(m)]
            if len(messages) < 2:
                continue
            found.append(
                {
                    "path": rp,
                    "pack": pack,
                    "messages": messages,
                    "model": model,
                }
            )
    return found


def _lorem_filler_messages(need_tokens: int, seed: int) -> list[dict[str, Any]]:
    """Pure unrelated filler (no tool demos) for priming-control experiments."""
    para = (
        "lorem ipsum dolor sit amet coding notes placeholder text without tools "
        "or pack gold content. review checklist alpha beta gamma delta epsilon. "
    )
    text = "# synthetic filler\n" + (para * 2000)
    step = 2500
    msgs: list[dict[str, Any]] = []
    i = 0
    while estimate_tokens(msgs) < need_tokens and i < len(text):
        piece = text[i : i + step]
        i += step
        msgs.append({"role": "user", "content": f"[FILLER_NOTE]\n{piece}"})
        msgs.append(
            {
                "role": "assistant",
                "content": f"Noted filler block {(seed + i) % 997}.",
            }
        )
    return msgs


def _fallback_source_file_messages(need_tokens: int, seed: int) -> list[dict[str, Any]]:
    """Stuff by 'reading' a large local source file into history (synthetic turns)."""
    candidates = [
        Path("src/dsm_ae/litellm_client.py"),
        Path("src/dsm_ae/diagnose.py"),
        Path("scripts/json_to_html_report.py"),
        Path("src/dsm_ae/decision_trees.py"),
    ]
    chunks: list[str] = []
    for c in candidates:
        if c.is_file():
            try:
                chunks.append(c.read_text(encoding="utf-8", errors="replace")[:120_000])
            except Exception:
                pass
    if not chunks:
        chunks = ["# synthetic filler\n" + ("lorem ipsum coding notes\n" * 500)]
    text = "\n\n".join(chunks)
    # Split into ~2k char user/assistant pairs
    step = 2500
    msgs: list[dict[str, Any]] = []
    rng = random.Random(seed)
    i = 0
    while estimate_tokens(msgs) < need_tokens and i < len(text):
        piece = text[i : i + step]
        i += step
        msgs.append(
            {
                "role": "user",
                "content": (
                    f"[PRIOR_SESSION] Please review this source excerpt (unrelated):\n```\n{piece}\n```"
                ),
            }
        )
        msgs.append(
            {
                "role": "assistant",
                "content": (
                    "Acknowledged. Excerpt reviewed; no action for the next task. "
                    f"(note {rng.randint(1000, 9999)})"
                ),
            }
        )
    return msgs


def build_stuffed_history(
    config: ContextBloatConfig,
    *,
    pack_under_test: str,
    trial_index: int,
    system_prompt: str,
    models_yaml: Path | str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build prefix history (no system, no pack user) and meta dict."""
    window, window_src = resolve_window_tokens(
        config.model, explicit=config.window_tokens, models_yaml=models_yaml
    )
    system_tokens = estimate_tokens(
        [{"role": "system", "content": system_prompt}], method=config.token_method
    )
    max_prefix = max(0, window - config.reserve_tokens)
    target_total = min(int(config.level * window), max_prefix)
    target_stuff = max(0, target_total - system_tokens)

    seed_mat = f"{config.seed}|{config.model}|{pack_under_test}|{trial_index}|{config.level}"
    seed = int(hashlib.sha256(seed_mat.encode()).hexdigest()[:8], 16)
    if config.fixed_prefix:
        seed = config.seed

    history: list[dict[str, Any]] = []
    used_sources: list[str] = []
    traj_tokens = 0
    filler_tokens = 0
    fill_mode = (config.fill_mode or "trajectory").lower().strip()

    if fill_mode == "lorem":
        # Priming-control arm: unrelated filler only (no tool demos).
        history = _fallback_source_file_messages(target_stuff, seed)
        # Prefer pure lorem when sources unavailable
        if estimate_tokens(history, method=config.token_method) < target_stuff * 0.5:
            history = _lorem_filler_messages(target_stuff, seed)
        filler_tokens = estimate_tokens(history, method=config.token_method)
        traj_tokens = 0
        used_sources = [f"fill_mode=lorem seed={seed}"]
    else:
        exclude = isolation_packs(pack_under_test, config.exclude_extra_packs)
        corpus = index_conversations(config.sources)
        corpus = [c for c in corpus if c.get("pack") not in exclude]
        rng = random.Random(seed)
        rng.shuffle(corpus)

        for i, item in enumerate(corpus):
            if estimate_tokens(history, method=config.token_method) >= target_stuff:
                break
            prefix = f"bloat{seed % 10000}_{i}_"
            chunk = _normalize_messages(
                item["messages"], pack=item["pack"], trial=i, id_prefix=prefix
            )
            if not chunk:
                continue
            # boundary
            boundary = [
                {
                    "role": "user",
                    "content": "[PRIOR_SESSION_BOUNDARY] Previous unrelated task ended.",
                },
                {"role": "assistant", "content": "Acknowledged."},
            ]
            candidate = history + boundary + chunk
            cand_tok = estimate_tokens(candidate, method=config.token_method)
            if cand_tok <= target_stuff:
                history = candidate
                used_sources.append(item["path"])
                traj_tokens = cand_tok
                continue
            # try partial chunk
            room = target_stuff - estimate_tokens(
                history + boundary, method=config.token_method
            )
            if room < 200:
                break
            partial: list[dict[str, Any]] = []
            for m in chunk:
                trial = partial + [m]
                if estimate_tokens(trial, method=config.token_method) > room:
                    break
                partial.append(m)
            partial = _complete_tool_pairs(partial)
            if partial:
                history = history + boundary + partial
                used_sources.append(item["path"] + "#partial")
                traj_tokens = estimate_tokens(history, method=config.token_method)
            break

        # Cross-model / other traj underfill: already random sample of all models.
        # Source-file fallback if still short.
        underfill_traj = traj_tokens < target_stuff * (1.0 - config.tolerance)
        if underfill_traj and config.allow_source_file_fallback:
            need = target_stuff - estimate_tokens(history, method=config.token_method)
            filler = _fallback_source_file_messages(need, seed)
            history = history + filler
            filler_tokens = estimate_tokens(filler, method=config.token_method)
            traj_tokens = estimate_tokens(history, method=config.token_method)

    achieved_stuff = estimate_tokens(history, method=config.token_method)
    achieved_prefix = system_tokens + achieved_stuff
    achieved_util = achieved_prefix / window if window else 0.0
    clamped = target_total < int(config.level * window)
    underfill = achieved_stuff < target_stuff * (1.0 - config.tolerance)

    meta = {
        "level": config.level,
        "condition": f"bloat{int(config.level * 100)}",
        "context_window_tokens": window,
        "window_source": window_src,
        "token_method": config.token_method,
        "token_method_note": (
            "v1 uses chars/4 heuristic for fill targeting; "
            "tiktoken/litellm reserved for later accurate calibration."
        ),
        "reserve_tokens": config.reserve_tokens,
        "target_stuff_tokens": target_stuff,
        "achieved_stuff_tokens": achieved_stuff,
        "achieved_prefix_tokens": achieved_prefix,
        "achieved_util": round(achieved_util, 4),
        "clamped": clamped,
        "underfill": underfill,
        "n_sources": len(used_sources),
        "sources_sample": used_sources[:12],
        "filler_tokens": filler_tokens,
        "fill_mode": fill_mode,
        "overflow_is_fail": config.overflow_is_fail,
        "seed": seed,
        "pack_under_test": pack_under_test,
        "trial_index": trial_index,
    }
    return history, meta


class ContextBloatedAdapter:
    """Wrap an adapter; prepend stuffed multi-turn history before each pack trial."""

    name = "context_bloated"

    def __init__(self, inner: Any, config: ContextBloatConfig, *, models_yaml: Path | str | None = None):
        self.inner = inner
        self.config = config
        self.models_yaml = models_yaml
        self.client = getattr(inner, "client", None)
        self.card = getattr(inner, "card", None)

    def __getattr__(self, name: str) -> Any:
        # Proxy pack helpers (e.g. _exec) to the innermost raw adapter when needed.
        if name in {"inner", "config", "models_yaml", "client", "card"}:
            raise AttributeError(name)
        return getattr(self.inner, name)

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
        **kwargs: Any,
    ) -> Any:
        history, meta = build_stuffed_history(
            self.config,
            pack_under_test=pack,
            trial_index=trial_index,
            system_prompt=system_prompt,
            models_yaml=self.models_yaml,
        )
        try:
            tr = self.inner.run(
                pack=pack,
                scenario_id=scenario_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                workspace=workspace,
                trial_index=trial_index,
                variant=variant,
                allowed_deletes=allowed_deletes,
                prefix_messages=history,
                **kwargs,
            )
        except TypeError:
            # Inner does not accept prefix_messages
            tr = self.inner.run(
                pack=pack,
                scenario_id=scenario_id,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                workspace=workspace,
                trial_index=trial_index,
                variant=variant,
                allowed_deletes=allowed_deletes,
            )
        tr.meta = dict(tr.meta or {})
        tr.meta["context_bloat"] = meta
        # Overflow fail: if first complete reported overflow or util over 0.98 of window
        if self.config.overflow_is_fail and meta.get("achieved_util", 0) > 0.98:
            tr.meta["context_bloat"]["overflow_flag"] = True
        return tr
