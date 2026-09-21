"""PC-07 / PC-15: plan atoms from reasoning vs executed tools."""

from __future__ import annotations

import re
from typing import Any

from dsm_ae.atoms import atom_from_tool

_VERB_ATOM = (
    (re.compile(r"\b(read|open|inspect|cat)\b", re.I), "read_file"),
    (re.compile(r"\b(write|edit|patch|update|create)\b", re.I), "edit"),
    (re.compile(r"\b(delete|remove|rm|unlink)\b", re.I), "delete_file"),
    (re.compile(r"\b(list|ls|glob|search|find|explore)\b", re.I), "search_repo"),
    (re.compile(r"\b(run|shell|execute|pytest|test)\b", re.I), "run_code"),
    (re.compile(r"\b(done|submit|finish|report)\b", re.I), "submit"),
)

_TOOL_TOKEN = re.compile(
    r"\b(read_file|write_file|delete_file|list_dir|shell|done|Read|Write)\b"
)


def reasoning_blobs(trace: dict[str, Any]) -> list[str]:
    blobs: list[str] = []
    for m in trace.get("messages") or []:
        if not isinstance(m, dict):
            continue
        rc = m.get("reasoning_content") or m.get("reasoning") or ""
        if isinstance(rc, str) and rc.strip():
            blobs.append(rc)
    meta = trace.get("meta") or {}
    fc = meta.get("full_conversation") or []
    if isinstance(fc, list):
        for m in fc:
            if not isinstance(m, dict):
                continue
            rc = m.get("reasoning_content") or m.get("reasoning") or ""
            if isinstance(rc, str) and rc.strip():
                blobs.append(rc)
    return blobs


def parse_plan_atoms(text: str) -> list[str]:
    atoms: list[str] = []
    for tok in _TOOL_TOKEN.findall(text):
        atoms.append(atom_from_tool(tok))
    lower_used = set()
    for cre, atom in _VERB_ATOM:
        if cre.search(text) and atom not in lower_used:
            # only add verb if not already from explicit tool token
            if atom not in atoms:
                atoms.append(atom)
            lower_used.add(atom)
    return atoms


def exec_atoms(trace: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for tc in trace.get("tool_calls") or []:
        if not isinstance(tc, dict):
            continue
        args = tc.get("arguments") if isinstance(tc.get("arguments"), dict) else None
        out.append(atom_from_tool(tc.get("name"), args))
    return out


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def order_agree(plan: list[str], execed: list[str]) -> float:
    """Fraction of adjacent plan pairs that appear in that order in exec."""
    if len(plan) < 2:
        return 1.0 if plan and plan[0] in execed else (1.0 if not plan else 0.0)
    first_idx = {}
    for i, a in enumerate(execed):
        first_idx.setdefault(a, i)
    ok = 0
    tot = 0
    for x, y in zip(plan, plan[1:]):
        tot += 1
        ix, iy = first_idx.get(x), first_idx.get(y)
        if ix is not None and iy is not None and ix <= iy:
            ok += 1
    return ok / tot if tot else 1.0


def plan_exec_scores(trace: dict[str, Any]) -> dict[str, Any] | None:
    blobs = reasoning_blobs(trace)
    if not blobs:
        return None
    plan: list[str] = []
    for b in blobs[:4]:
        for a in parse_plan_atoms(b):
            if a not in plan:
                plan.append(a)
    exe = exec_atoms(trace)
    if not plan:
        return {
            "has_plan": False,
            "plan_atoms": [],
            "exec_atoms": exe,
            "plan_exec_divergence": None,
            "ra_mismatch_score": None,
        }
    jac = jaccard(plan, exe)
    agr = order_agree(plan, exe)
    return {
        "has_plan": True,
        "plan_atoms": plan,
        "exec_atoms": exe,
        "plan_exec_divergence": 1.0 - jac,
        "ra_mismatch_score": 1.0 - agr,
    }
