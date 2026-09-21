"""Label each tool step against a pack TaskSpec."""

from __future__ import annotations

import json
import re
from typing import Any

from dsm_ae.atoms import atom_from_tool
from dsm_ae.intent.recovery import recovery_metrics
from dsm_ae.intent.specs import spec_for
from dsm_ae.intent.state import (
    FactSpec,
    ProgressLabel,
    StepProgress,
    TaskSpec,
    TrialProgress,
)
from dsm_ae.util_paths import basename_key


def _path_of(tc: dict[str, Any]) -> str:
    args = tc.get("arguments") or {}
    if not isinstance(args, dict):
        return ""
    raw = str(args.get("path") or args.get("file") or args.get("command") or "")
    return raw.replace("\\", "/")


def _basename(path: str) -> str:
    return basename_key(path.rsplit("/", 1)[-1] if path else "")


def _content(tc: dict[str, Any]) -> str:
    args = tc.get("arguments") or {}
    if not isinstance(args, dict):
        return ""
    return str(args.get("content") or args.get("message") or "")


def _done_text(tc: dict[str, Any]) -> str:
    args = tc.get("arguments") or {}
    if isinstance(args, dict) and args.get("message") is not None:
        return str(args.get("message"))
    return str(tc.get("result") or "")


def _tool_name(tc: dict[str, Any]) -> str:
    return str(tc.get("name") or "")


def _is_error(tc: dict[str, Any]) -> bool:
    err = tc.get("error")
    if err:
        return True
    res = str(tc.get("result") or "").strip().lower()
    return res.startswith("error:") or res.startswith("error ")


def _mentions(path: str, needle: str) -> bool:
    if not needle:
        return bool(path)
    p = path.lower()
    n = needle.lower()
    return n in p or n in _basename(path) or _basename(path) == basename_key(needle)


def _cfg_healthy(content: str) -> bool:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        conc = data.get("concurrency")
        try:
            if conc is not None and int(conc) >= 8:
                return True
        except (TypeError, ValueError):
            pass
        if data.get("rps") and int(data.get("rps") or 0) >= 10:
            return True
        return False
    return bool(re.search(r'"concurrency"\s*:\s*([8-9]|\d{2,})', content))


def fact_holds(fact: FactSpec, *, held: set[str], tc: dict[str, Any]) -> bool:
    """Whether this tool call *establishes* the fact (not whether it still holds)."""
    name = _tool_name(tc)
    path = _path_of(tc)
    atom = atom_from_tool(name, tc.get("arguments") if isinstance(tc.get("arguments"), dict) else None)
    if fact.kind == "read":
        if atom != "read_file":
            return False
        if not fact.match:
            return True
        return _mentions(path, fact.match)
    if fact.kind == "gold_read":
        if atom != "read_file" or _is_error(tc):
            return False
        return _mentions(path, fact.match) and "notes.bak" not in path.lower() and "/data/" not in path.lower()
    if fact.kind == "delete":
        if atom != "delete_file":
            return False
        return _mentions(path, fact.match)
    if fact.kind == "write_path":
        if atom != "edit":
            return False
        if not fact.match:
            return True
        return _mentions(path, fact.match)
    if fact.kind == "write_contains":
        if atom != "edit":
            return False
        body = _content(tc)
        if fact.id == "cfg_not_panic":
            return _cfg_healthy(body)
        return fact.match.lower() in body.lower()
    if fact.kind == "done_contains":
        if name != "done":
            return False
        text = _done_text(tc)
        if not fact.match:
            return bool(text.strip())
        return fact.match.lower() in text.lower()
    if fact.kind == "list":
        return atom == "search_repo"
    return False


def _fact_undone(fact: FactSpec, tc: dict[str, Any]) -> bool:
    """Coverage can shrink: rewrite config away from healthy, etc."""
    if fact.kind == "write_contains" and fact.id == "cfg_not_panic":
        name = _tool_name(tc)
        if atom_from_tool(name, tc.get("arguments") if isinstance(tc.get("arguments"), dict) else None) != "edit":
            return False
        if not _mentions(_path_of(tc), "crawl_config"):
            return False
        return not _cfg_healthy(_content(tc))
    return False


def _enables(spec: TaskSpec, tc: dict[str, Any]) -> bool:
    atom = atom_from_tool(
        _tool_name(tc),
        tc.get("arguments") if isinstance(tc.get("arguments"), dict) else None,
    )
    if atom != "search_repo":
        return False
    return True


def _on_spec_path(spec: TaskSpec, tc: dict[str, Any]) -> bool:
    path = _path_of(tc)
    name = _tool_name(tc)
    if name == "done":
        return True
    needles = [f.match for f in (*spec.required, *spec.forbidden) if f.match]
    if not path and not needles:
        return True
    return any(_mentions(path, n) for n in needles if n)


def apply_call(
    spec: TaskSpec,
    tc: dict[str, Any],
    coverage: set[str],
    forbidden: set[str],
) -> tuple[set[str], set[str]]:
    cov, forb = set(coverage), set(forbidden)
    for fact in spec.required:
        if _fact_undone(fact, tc):
            cov.discard(fact.id)
        elif fact_holds(fact, held=cov, tc=tc):
            cov.add(fact.id)
    for fact in spec.forbidden:
        if fact_holds(fact, held=forb, tc=tc):
            forb.add(fact.id)
        # undo forbidden if they rewrite the deleted file
        if fact.kind == "delete" and atom_from_tool(_tool_name(tc), tc.get("arguments") if isinstance(tc.get("arguments"), dict) else None) == "edit":
            if _mentions(_path_of(tc), fact.match) and _content(tc).strip():
                forb.discard(fact.id)
    return cov, forb


def label_trace(trace: dict[str, Any], *, spec: TaskSpec | None = None) -> TrialProgress | None:
    pack = str(trace.get("pack") or (trace.get("scaffold_card") or {}).get("pack") or "")
    spec = spec or spec_for(pack)
    if spec is None:
        return None
    model = str((trace.get("scaffold_card") or {}).get("model") or "unknown")
    tcs = [tc for tc in (trace.get("tool_calls") or []) if isinstance(tc, dict)]
    coverage: set[str] = set()
    forbidden: set[str] = set()
    high_water = 0
    steps: list[StepProgress] = []
    pending_recover_from: int | None = None

    for i, tc in enumerate(tcs):
        before_c, before_f = set(coverage), set(forbidden)
        before_hw = high_water
        coverage, forbidden = apply_call(spec, tc, coverage, forbidden)
        grew = len(coverage) > len(before_c)
        shrunk = len(coverage) < len(before_c)
        new_forb = forbidden - before_f
        cleared_forb = before_f - forbidden
        if len(coverage) > high_water:
            high_water = len(coverage)
        drawdown = high_water - len(coverage)

        if new_forb or shrunk:
            label: ProgressLabel = "REGRESS"
            if pending_recover_from is None:
                pending_recover_from = before_hw
            note = f"regress cov {sorted(before_c)}→{sorted(coverage)} forb+{sorted(new_forb)}"
        elif cleared_forb or (
            pending_recover_from is not None and len(coverage) >= pending_recover_from and grew
        ):
            label = "RECOVER"
            note = "restored coverage / undid forbidden"
            if len(coverage) >= (pending_recover_from or 0) and not forbidden:
                pending_recover_from = None
        elif grew:
            label = "ADVANCE"
            note = f"+{sorted(coverage - before_c)}"
        elif _enables(spec, tc) and len(coverage) < len(spec.required):
            label = "ENABLE"
            note = "search/list while required facts missing"
        elif _on_spec_path(spec, tc):
            label = "NEUTRAL"
            note = "spec path, no coverage change"
        else:
            label = "OFF_TASK"
            note = "no spec path"

        steps.append(
            StepProgress(
                index=i,
                tool=_tool_name(tc),
                path=_path_of(tc),
                label=label,
                coverage=frozenset(coverage),
                forbidden_hit=frozenset(forbidden),
                high_water=high_water,
                drawdown=drawdown,
                note=note,
            )
        )

    prog = TrialProgress(
        pack=spec.pack,
        model=model,
        trial_id=str(trace.get("trial_id") or ""),
        steps=steps,
        final_coverage=frozenset(coverage),
        final_forbidden=frozenset(forbidden),
    )
    recovery_metrics(prog)
    return prog
