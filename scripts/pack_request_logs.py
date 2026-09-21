#!/usr/bin/env python3
"""Stage request-level logs into litellm/ + completions_logs/ and 7z them.

Redacts api_key / Authorization from copies. Does not modify originals.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_KEY_RE = re.compile(
    r"(api_key|authorization|x-api-key|x-dsm-ae-token)", re.I
)
SAFE = re.compile(r"[^\w.\-@()+]+")


def safe(s: str) -> str:
    return SAFE.sub("_", (s or "unknown").strip()) or "unknown"


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if SECRET_KEY_RE.search(str(k)):
                out[k] = "***REDACTED***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def copy_litellm(src: Path, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with src.open(encoding="utf-8", errors="replace") as inf, dest.open(
        "w", encoding="utf-8"
    ) as outf:
        for line in inf:
            line = line.strip()
            if not line:
                continue
            try:
                obj = redact(json.loads(line))
                outf.write(json.dumps(obj, default=str) + "\n")
            except json.JSONDecodeError:
                outf.write(line + "\n")
            n += 1
    return n


def human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for u, d in (("KB", 1024.0), ("MB", 1024.0**2), ("GB", 1024.0**3)):
        if n < d * 1024 or u == "GB":
            return f"{n / d:.1f} {u}"
    return str(n)


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


def infer_model(path: Path) -> tuple[str, str]:
    """Return (model_id, source_tag)."""
    parts = path.parts
    s = str(path)
    if "think-max" in parts or "gpt-5.6-sol_max" in s:
        for m in ("gpt-5.6-sol(max)", "gpt-5.6-terra(max)", "gpt-5.6-luna(max)"):
            slug = m.replace("(", "_").replace(")", "")
            if slug in s or m.replace("(", "_").replace(")", "") in s:
                return m, "think-max"
        if "sol_max" in s:
            return "gpt-5.6-sol(max)", "think-max-full"
        if "terra_max" in s:
            return "gpt-5.6-terra(max)", "think-max-full"
        if "luna_max" in s:
            return "gpt-5.6-luna(max)", "think-max-full"
    if "bloat50" in parts:
        # reports/bloat/bloat50/work/<model>/
        for i, p in enumerate(parts):
            if p == "work" and i + 1 < len(parts):
                return parts[i + 1], "bloat50"
    if "recency_bias" in parts:
        for i, p in enumerate(parts):
            if p == "recency_bias" and i + 1 < len(parts):
                return parts[i + 1], "recency"
    if "repro-shared" in parts:
        i = parts.index("repro-shared")
        return parts[i + 1], "repro-shared"
    if "work" in parts:
        i = parts.index("work")
        if i + 1 < len(parts):
            jid = parts[i + 1]
            if jid in JOB_MODEL:
                src = "full-suite-k10" if jid in {"dd08460f", "c9a70276"} else "queue"
                return JOB_MODEL[jid], src
            return jid, "queue-unknown"
    return "unknown", "misc"


def stage(dest: Path) -> dict:
    lit = dest / "litellm"
    comp = dest / "completions_logs"
    lit.mkdir(parents=True, exist_ok=True)
    comp.mkdir(parents=True, exist_ok=True)
    stats = defaultdict(lambda: {"litellm_files": 0, "litellm_calls": 0, "completions": 0})
    copied = []

    # --- litellm.jsonl ---
    for src in list((ROOT / "reports").rglob("litellm.jsonl")) + list(
        (ROOT / "work").rglob("litellm.jsonl")
    ):
        model, source = infer_model(src)
        pack_trial = src.parent.name  # {pack}__t{i}
        rel = lit / safe(model) / safe(source) / pack_trial / "litellm.jsonl"
        n = copy_litellm(src, rel)
        stats[model]["litellm_files"] += 1
        stats[model]["litellm_calls"] += n
        copied.append(("litellm", str(rel.relative_to(dest)), n, src.stat().st_size))

        # sibling conversation / traces next to that trial
        for fname in ("conversation.json", "traces.json", "meta.json", "scores.json"):
            sib = src.parent / fname
            if not sib.is_file():
                continue
            out = comp / safe(model) / safe(source) / pack_trial / fname
            try:
                obj = json.loads(sib.read_text(encoding="utf-8"))
                write_json(out, redact(obj))
            except json.JSONDecodeError:
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sib, out)
            stats[model]["completions"] += 1

    # --- repro-shared trial jsons (full_conversation, no litellm) ---
    repro = ROOT / "reports" / "repro-shared"
    if repro.is_dir():
        for src in repro.rglob("trial_*.json"):
            try:
                rel_from = src.relative_to(repro)
            except ValueError:
                continue
            model = rel_from.parts[0]
            pack = rel_from.parts[1] if len(rel_from.parts) > 1 else "unknown"
            out = (
                comp
                / safe(model)
                / "repro-shared"
                / safe(pack)
                / src.name
            )
            try:
                obj = json.loads(src.read_text(encoding="utf-8"))
                write_json(out, redact(obj))
            except json.JSONDecodeError:
                continue
            stats[model]["completions"] += 1
            copied.append(("completions", str(out.relative_to(dest)), 1, src.stat().st_size))

    # --- think-max / full-suite diagnosis JSON that still has traces ---
    for src in (ROOT / "reports").rglob("*.json"):
        if src.name in {
            "tree.json",
            "unknown-clusters.json",
            "unknown-nodes.json",
            "trajectory-inventory.json",
            "revalidation.json",
        }:
            continue
        if "trajectories" in src.parts or "repro-shared" in src.parts:
            continue
        if src.name in {"conversation.json", "traces.json", "scores.json", "meta.json"}:
            continue
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        traces = data.get("traces")
        if not isinstance(traces, list) or not traces:
            continue
        card = data.get("scaffold_card") or {}
        model = card.get("model") or data.get("model") or "unknown"
        out = (
            comp
            / safe(str(model))
            / "diagnosis-json"
            / safe(src.stem)
            / "report.json"
        )
        if out.exists():
            continue
        write_json(out, redact(data))
        stats[str(model)]["completions"] += 1

    manifest = dest / "MANIFEST.md"
    lines = [
        "# Request-level log archive",
        "",
        "Copies only. Secrets (`api_key`, Authorization) redacted.",
        "",
        "## Layout",
        "",
        "- `litellm/<model>/<source>/<pack>__tN/litellm.jsonl` — one JSON object per completion",
        "- `completions_logs/<model>/<source>/...` — conversation.json, traces.json, repro-shared trial_*.json, diagnosis reports that still embed traces",
        "",
        "## Per model",
        "",
        "| model | litellm files | litellm calls | completion artifacts |",
        "|---|---:|---:|---:|",
    ]
    for m in sorted(stats):
        s = stats[m]
        lines.append(
            f"| `{m}` | {s['litellm_files']} | {s['litellm_calls']} | {s['completions']} |"
        )
    lines.append("")
    lines.append(f"Staged files: {len(copied)}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"stats": dict(stats), "n_copied": len(copied)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dest",
        type=Path,
        default=ROOT / "reports" / "_request_logs_stage",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "reports" / "dsm-ae-request-logs.7z",
    )
    ap.add_argument("--skip-7z", action="store_true")
    args = ap.parse_args()
    dest = args.dest.resolve()
    out = args.out.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    info = stage(dest)
    print(json.dumps({"staged": str(dest), **{k: info[k] for k in info if k != "stats"}}, indent=2))
    print(f"models={len(info['stats'])} copied={info['n_copied']}")
    staged_bytes = sum(
        p.stat().st_size for p in dest.rglob("*") if p.is_file()
    )
    print(f"staged_size={human(staged_bytes)}")
    if args.skip_7z:
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    cmd = [
        "7z",
        "a",
        "-t7z",
        "-mx=5",
        "-mmt=on",
        str(out),
        ".",
    ]
    print("running", " ".join(cmd), "cwd", dest)
    subprocess.check_call(cmd, cwd=dest)
    print(f"wrote {out} ({human(out.stat().st_size)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
