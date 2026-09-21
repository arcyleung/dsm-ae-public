#!/usr/bin/env python3
"""E5 — BFCL irrelevance vs overeager_mini, plus a seeded 8-task probe.

Downloads BFCL_v3_irrelevance.json (JSONL) if missing. No Docker.

    python3 scripts/e5_bfcl.py --models gpt-5.6-sol,Qwen3.8-27B-NVFP4
    python3 scripts/e5_bfcl.py --limit 40          # smoke
    python3 scripts/e5_bfcl.py --seed-probe-only
"""

from __future__ import annotations

import argparse
import json
import random
import urllib.request
from pathlib import Path
from typing import Any

from dsm_ae.litellm_client import make_client
from dsm_ae.packs.seeding import build_seed_prefix, lorem_control_messages

BFCL_URL = (
    "https://huggingface.co/datasets/gorilla-llm/"
    "Berkeley-Function-Calling-Leaderboard/resolve/main/BFCL_v3_irrelevance.json"
)
DEFAULT_DATA = Path("data/bfcl/BFCL_v3_irrelevance.jsonl")

# Published overeager_mini pass rates from existing suites (critical_trap_avoided).
# Filled from disk when those reports exist; used only as the "reduced OASD" trend.
OE_REPORTS = {
    "gpt-5.6-sol": Path("reports/full-suite/gpt-5.6-sol-max-full.json"),
    "Qwen3.8-27B-NVFP4": Path("reports/queue/full-qwen38-27b-nvfp4-dd08460f.json"),
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    raw = path.read_text(encoding="utf-8")
    if raw.lstrip().startswith("["):
        return json.loads(raw)
    for line in raw.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def ensure_dataset(path: Path) -> list[dict[str, Any]]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.stat().st_size < 1000:
        print(f"downloading {BFCL_URL} → {path}")
        req = urllib.request.Request(BFCL_URL, headers={"User-Agent": "dsm-ae-e5"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            path.write_bytes(resp.read())
    rows = load_jsonl(path)
    print(f"BFCL irrelevance tasks: {len(rows)}")
    return rows


_TYPE_MAP = {
    "float": "number",
    "double": "number",
    "dict": "object",
    "tuple": "array",
    "list": "array",
    "str": "string",
    "int": "integer",
    "bool": "boolean",
}


def _norm_schema(node: Any) -> Any:
    """BFCL uses JSON-Schema-ish types (`float`, `dict`) that OpenAI rejects."""
    if isinstance(node, list):
        return [_norm_schema(x) for x in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for k, v in node.items():
        if k == "type" and isinstance(v, str):
            out[k] = _TYPE_MAP.get(v.lower(), v)
        elif k == "type" and isinstance(v, list):
            out[k] = [_TYPE_MAP.get(str(t).lower(), t) for t in v]
        else:
            out[k] = _norm_schema(v)
    return out


def bfcl_fn_to_openai(fn: dict[str, Any]) -> dict[str, Any]:
    params = _norm_schema(dict(fn.get("parameters") or {}))
    if params.get("type") == "dict":
        params = {**params, "type": "object"}
    return {
        "type": "function",
        "function": {
            "name": str(fn.get("name") or "fn").replace(".", "_")[:64],
            "description": fn.get("description") or "",
            "parameters": params or {"type": "object", "properties": {}},
        },
    }


def user_text(row: dict[str, Any]) -> str:
    q = row.get("question")
    if isinstance(q, str):
        return q
    # BFCL: question is [[{role, content}, ...], ...]
    if isinstance(q, list) and q:
        turn = q[0]
        if isinstance(turn, list) and turn:
            return str(turn[0].get("content") or "")
        if isinstance(turn, dict):
            return str(turn.get("content") or "")
    return ""


def overeager_rates() -> dict[str, dict[str, float]]:
    out = {}
    for model, path in OE_REPORTS.items():
        if not path.is_file():
            continue
        d = json.loads(path.read_text(encoding="utf-8"))
        rates = {b["metric_id"]: float(b.get("pass_rate", 0.0)) for b in d.get("bootstraps") or []}
        out[model] = {
            "critical_trap_avoided": rates.get("critical_trap_avoided"),
            "overeager_rate": rates.get("overeager_rate"),
            "scope_safe": rates.get("scope_safe"),
        }
    return out


def run_one(client, row: dict[str, Any], prefix: list[dict[str, str]]) -> dict[str, Any]:
    tools = [bfcl_fn_to_openai(fn) for fn in (row.get("function") or [])]
    messages = list(prefix) + [{"role": "user", "content": user_text(row)}]
    try:
        res = client.complete(messages, tools=tools or None, temperature=0.0, max_tokens=512)
        n_calls = len(res.tool_calls or [])
        return {
            "id": row.get("id"),
            "n_tool_calls": n_calls,
            "passed": n_calls == 0,
            "content": (res.content or "")[:200],
            "error": None,
        }
    except Exception as exc:
        return {
            "id": row.get("id"),
            "n_tool_calls": None,
            "passed": False,
            "content": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def seed_prefix(mode: str, seed: int) -> list[dict[str, str]]:
    if mode == "none":
        return []
    if mode == "lorem":
        return lorem_control_messages(2500, seed=seed)
    msgs, _meta = build_seed_prefix(
        pool_name="mixed_engineering", n_turns=12, seed=seed, mode="trajectory"
    )
    return msgs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", default="gpt-5.6-sol,Qwen3.8-27B-NVFP4")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--limit", type=int, default=0, help="0 = all tasks")
    ap.add_argument("--seed-n", type=int, default=8)
    ap.add_argument("--seed-probe-only", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("reports/arms/bfcl_syndrome.json"))
    ap.add_argument("--models-yaml", type=Path, default=Path("models.yaml"))
    args = ap.parse_args()

    rows = ensure_dataset(args.data)
    if args.limit:
        rows = rows[: args.limit]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    oe = overeager_rates()

    full: dict[str, Any] = {"n_tasks": len(rows), "models": {}, "overeager": oe, "seed_probe": {}}
    if not args.seed_probe_only:
        for model in models:
            print(f"\n=== BFCL irrelevance  model={model}  n={len(rows)} ===")
            client = make_client(model, models_yaml=args.models_yaml)
            results = []
            ok = 0
            for i, row in enumerate(rows, 1):
                r = run_one(client, row, [])
                results.append(r)
                ok += int(bool(r["passed"]))
                if i % 25 == 0 or i == len(rows):
                    print(f"  {i}/{len(rows)}  pass={ok}/{i} ({ok/i:.2f})")
            acc = ok / len(rows) if rows else 0.0
            full["models"][model] = {
                "accuracy": acc,
                "n_pass": ok,
                "n": len(rows),
                "results": results,
            }
            print(f"  accuracy={acc:.3f}  overeager={oe.get(model)}")

    rng = random.Random(42)
    probe = rng.sample(rows, min(args.seed_n, len(rows)))
    print(f"\n=== seed probe n={len(probe)} tasks × 3 arms ===")
    for model in models:
        client = make_client(model, models_yaml=args.models_yaml)
        full["seed_probe"][model] = {}
        for mode in ("none", "lorem", "trajectory"):
            hits = []
            for i, row in enumerate(probe):
                r = run_one(client, row, seed_prefix(mode, seed=1000 + i))
                hits.append(r)
            acc = sum(1 for r in hits if r["passed"]) / len(hits) if hits else 0.0
            full["seed_probe"][model][mode] = {
                "accuracy": acc,
                "n_pass": sum(1 for r in hits if r["passed"]),
                "n": len(hits),
                "ids": [r["id"] for r in hits],
                "results": hits,
            }
            print(f"  {model:22s} {mode:12s} {acc:.2f} ({int(acc*len(hits))}/{len(hits)})")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(full, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
