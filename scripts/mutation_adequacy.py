#!/usr/bin/env python3
"""E2 — scaffold mutation adequacy and vacuity audit.

No live model. Two arms:

1. Synthetic vacuity: score every registered pack on traces that never
   had the opportunity to fail (no tools; no delete; no read; no shell).
   A gate that PASSes on an empty trajectory is vacuously passing.
2. Replay: take archived traces (default: gpt-5.6-terra full suite),
   strip delete / read / shell calls, re-score, and report which gates
   stay PASS.

Usage
-----
    python3 scripts/mutation_adequacy.py
    python3 scripts/mutation_adequacy.py --replay reports/full-suite/gpt-5.6-terra-max-full.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from dsm_ae.models import ScaffoldCard, ToolCall, TrialTrace
from dsm_ae.packs.registry import PACKS

MUTATIONS = {
    "empty": frozenset(),
    "no_delete": frozenset({"read_file", "write_file", "list_dir", "done", "shell"}),
    "no_read": frozenset({"write_file", "delete_file", "list_dir", "done", "shell"}),
    "no_shell": frozenset({"read_file", "write_file", "delete_file", "list_dir", "done"}),
}

DROP = {
    "no_delete": {"delete_file", "delete", "rm"},
    "no_read": {"read_file", "read", "Read"},
    "no_shell": {"shell", "bash", "run", "exec", "terminal"},
}

TASK_LIKE = {
    "task_completed",
    "task_tool_success",
    "task_tool_success.tier1",
    "task_tool_success.tier2",
    "done_nonempty",
    "final_answer_correct",
    "user_task_done",
    "task_answered",
}


def _card() -> ScaffoldCard:
    return ScaffoldCard(model="mutation-adequacy", scaffold="raw")


def _synthetic(pack_id: str, mutation: str) -> TrialTrace:
    allowed = MUTATIONS[mutation]
    calls = [
        ToolCall(name=n, arguments={"path": "keep.txt"}, result="ok")
        for n in ("read_file", "write_file", "list_dir", "done")
        if n in allowed
    ]
    return TrialTrace(
        scenario_id=f"{pack_id}/mutation_{mutation}",
        pack=pack_id,
        trial_index=0,
        scaffold_card=_card(),
        tool_calls=calls,
        final_text="",
        files_deleted=[],
        files_read=[],
        files_written=[],
        meta={"mutation": mutation},
    )


def _score(pack, trace: TrialTrace) -> list[dict]:
    try:
        results = pack.score(trace)
    except Exception as exc:  # packs may assume fixture-specific meta
        return [{"metric_id": "__score_error__", "passed": False, "error": f"{type(exc).__name__}: {exc}"}]
    out = []
    for r in results:
        out.append({
            "metric_id": r.metric_id,
            "passed": bool(r.passed),
            "value": r.value,
            "explanation": (r.explanation or "")[:240],
        })
    return out


def vacuity_audit() -> dict:
    rows = []
    for pack_id, pack in sorted(PACKS.items()):
        for mutation in MUTATIONS:
            scores = _score(pack, _synthetic(pack_id, mutation))
            for s in scores:
                if s.get("metric_id") == "__score_error__":
                    rows.append({
                        "pack": pack_id,
                        "mutation": mutation,
                        "metric_id": "__score_error__",
                        "passed": False,
                        "vacuous": False,
                        "error": s.get("error"),
                    })
                    continue
                vacuous = bool(s["passed"]) and mutation in {"empty", "no_delete"}
                rows.append({
                    "pack": pack_id,
                    "mutation": mutation,
                    "metric_id": s["metric_id"],
                    "passed": s["passed"],
                    "vacuous": vacuous and s["metric_id"] not in TASK_LIKE,
                    "task_like": s["metric_id"] in TASK_LIKE,
                    "explanation": s.get("explanation", ""),
                })
    return {"n_rows": len(rows), "rows": rows}


def replay(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    traces = data.get("traces") or []
    if not isinstance(traces, list) or not traces or not isinstance(traces[0], dict):
        return {"source": str(path), "error": "no replayable traces"}

    by_pack: dict[str, list] = defaultdict(list)
    for raw in traces:
        pid = raw.get("pack")
        if pid in PACKS:
            by_pack[pid].append(raw)

    summary = []
    for pack_id, raws in sorted(by_pack.items()):
        pack = PACKS[pack_id]
        for mut, drop in DROP.items():
            n = 0
            stayed_pass: dict[str, int] = defaultdict(int)
            n_scored: dict[str, int] = defaultdict(int)
            for raw in raws:
                try:
                    tr = TrialTrace.model_validate(raw)
                except Exception:
                    continue
                kept = [tc for tc in tr.tool_calls if tc.name not in drop]
                if len(kept) == len(tr.tool_calls) and mut != "no_delete":
                    # mutation did not change this trajectory
                    pass
                tr.tool_calls = kept
                if mut == "no_delete":
                    tr.files_deleted = []
                if mut == "no_read":
                    tr.files_read = []
                n += 1
                for s in _score(pack, tr):
                    mid = s.get("metric_id")
                    if mid == "__score_error__":
                        continue
                    n_scored[mid] += 1
                    if s["passed"]:
                        stayed_pass[mid] += 1
            for mid, denom in n_scored.items():
                rate = stayed_pass[mid] / denom if denom else 0.0
                summary.append({
                    "pack": pack_id,
                    "mutation": mut,
                    "metric_id": mid,
                    "n": denom,
                    "pass_rate_after": round(rate, 3),
                    "task_like": mid in TASK_LIKE,
                })
    return {"source": str(path), "n_traces": len(traces), "cells": summary}


def rev_compare(vacuity: dict) -> dict:
    """rev1 vs rev2 on the three seeded families, empty and no_delete."""
    pairs = [
        ("gate_discipline", "gate_discipline_rev2"),
        ("memory_context", "memory_context_rev2"),
        ("recency_bias_mini", "recency_bias_mini_rev2"),
    ]
    out = []
    rows = vacuity["rows"]
    for rev1, rev2 in pairs:
        for mutation in ("empty", "no_delete"):
            a = [r for r in rows if r["pack"] == rev1 and r["mutation"] == mutation]
            b = [r for r in rows if r["pack"] == rev2 and r["mutation"] == mutation]
            out.append({
                "rev1": rev1,
                "rev2": rev2,
                "mutation": mutation,
                "rev1_vacuous": [r["metric_id"] for r in a if r.get("vacuous")],
                "rev2_vacuous": [r["metric_id"] for r in b if r.get("vacuous")],
                "rev1_pass": [r["metric_id"] for r in a if r.get("passed")],
                "rev2_pass": [r["metric_id"] for r in b if r.get("passed")],
            })
    return {"pairs": out}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--replay",
        type=Path,
        default=Path("reports/full-suite/gpt-5.6-terra-max-full.json"),
    )
    ap.add_argument("--out", type=Path, default=Path("reports/mutation/results.json"))
    args = ap.parse_args()

    vacuity = vacuity_audit()
    replayed = replay(args.replay) if args.replay.is_file() else {"error": "missing replay file"}
    cmp_ = rev_compare(vacuity)

    vacuous = [r for r in vacuity["rows"] if r.get("vacuous")]
    print(f"packs scored: {len(PACKS)}")
    print(f"vacuous PASS on empty/no_delete (excluding task-completion gates): {len(vacuous)}")
    by_pack: dict[str, list[str]] = defaultdict(list)
    for r in vacuous:
        by_pack[r["pack"]].append(f"{r['mutation']}:{r['metric_id']}")
    for pack, items in sorted(by_pack.items()):
        print(f"  {pack:28s} {sorted(set(items))}")

    print("\nrev1 vs rev2 vacuity (empty / no_delete):")
    for p in cmp_["pairs"]:
        print(
            f"  {p['mutation']:10s} {p['rev1']:24s} vacuous={p['rev1_vacuous']}"
            f"  → {p['rev2']} vacuous={p['rev2_vacuous']}"
        )

    if "cells" in replayed:
        still = [
            c for c in replayed["cells"]
            if c["pass_rate_after"] >= 0.8 and not c["task_like"]
        ]
        print(f"\nreplay {replayed['source']}: {len(replayed['cells'])} cells; "
              f"{len(still)} non-task gates stay ≥0.80 after a tool is stripped")

    payload = {
        "vacuity": vacuity,
        "rev1_vs_rev2": cmp_,
        "replay": replayed,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
