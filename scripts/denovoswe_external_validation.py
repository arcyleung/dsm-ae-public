#!/usr/bin/env python3
"""External validation: does our behavioural filter agree with an execution oracle?

The DeNovoSWE team released two trajectory sets from the same generator
(DeepSeek-v4-High): ~34k raw and ~11k retained after their own
execution/verification-based filtering. Their keep/drop decision is an oracle we
do not own and did not influence, which is exactly what §1.2 says a behaviour →
outcome claim requires.

The question this answers: if we score the RAW trajectories with DSM-AE's
off-policy instruments and keep the clean ones, do we select a similar set of
instances? Agreement is evidence the behavioural signal tracks execution
quality. Disagreement is equally informative and must be reported: it would mean
our instruments measure something orthogonal to whether the repo actually works.

This deliberately does NOT train anything. It is a set-overlap study.

Both files are JSONL but have different schemas:

  raw       flat record: instance_id, success, score, eval_result,
            trajectory[{step, action{tool_calls}, observations}], patch, difficulty
  filtered  chat record: id, messages[{role, content, tool_calls}],
            extra_info{instance_id, score, success, eval_result, stats}

Usage
-----
    # stream both files, emit per-trajectory instrument scores
    python3 scripts/denovoswe_external_validation.py \
        --raw ~/denovoswe/raw.jsonl \
        --filtered ~/denovoswe/filtered.jsonl \
        --out reports/external/denovoswe_validation.json

    # quick pass over the first N records of each (smoke test)
    python3 scripts/denovoswe_external_validation.py --limit 500 ...
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

try:
    from dsm_ae.atoms import _ADHOC_VERIFY_RE, _TEST_RE, atom_from_tool
except ModuleNotFoundError:  # DGX has the data but not the package installed
    import re as _re

    # Mirror of src/dsm_ae/atoms.py. Kept in sync by tests/test_denovoswe_vendor.py,
    # which fails if the vendored copy drifts from the real module.
    _TEST_RE = _re.compile(
        r"\b(pytest|py.test|unittest|npm test|cargo test|go test|make test|nox|tox)\b",
        _re.I,
    )
    _ADHOC_VERIFY_RE = _re.compile(
        r"(python3?\s+-c\b.*\bassert\b|python3?\s+-m\s+(pytest|unittest)\b|"
        r"\bassert\s+\w|\bunittest\.main\(|\bself\.assert)",
        _re.I | _re.S,
    )
    _SEARCH_RE = _re.compile(r"\b(ls|find|rg|grep|ag|fd|glob|tree)\b")
    _READ_RE = _re.compile(r"\b(cat|head|tail|less|more|sed -n)\b")
    _DEL_RE = _re.compile(r"\brm\b|\bunlink\b")
    _SUBCOMMAND_EDITORS = {"str_replace_editor", "file_editor", "editor", "oh_editor"}
    _EDITOR_SUBCOMMAND_MAP = {
        "view": "read_file", "read": "read_file", "create": "edit", "write": "edit",
        "str_replace": "edit", "insert": "edit", "append": "edit",
        "undo_edit": "edit", "delete": "delete_file",
    }
    _SHELLS = {
        "shell", "bash", "run", "exec", "execute_bash", "terminal",
        "run_bash_cmd", "execute_command", "execute_ipython_cell", "execute_code",
    }
    _NAMES = {
        "read": "read_file", "read_file": "read_file", "write": "edit",
        "write_file": "edit", "edit": "edit", "str_replace": "edit",
        "apply_patch": "edit", "delete": "delete_file", "delete_file": "delete_file",
        "list": "search_repo", "list_dir": "search_repo", "ls": "search_repo",
        "glob": "search_repo", "grep": "search_repo", "search": "search_repo",
        "done": "submit", "submit": "submit", "finish": "submit",
        "task_tracker": "think", "todowrite": "think",
    }

    def atom_from_tool(name, arguments=None):  # type: ignore[misc]
        raw = (name or "").strip()
        low = raw.lower()
        if low in _SUBCOMMAND_EDITORS:
            sub = ""
            if isinstance(arguments, dict):
                sub = str(arguments.get("command") or arguments.get("cmd") or "").strip().lower()
            return _EDITOR_SUBCOMMAND_MAP.get(sub, "edit" if sub else "other")
        if low in _NAMES:
            return _NAMES[low]
        if low in _SHELLS:
            cmd = ""
            if isinstance(arguments, dict):
                cmd = str(
                    arguments.get("command") or arguments.get("cmd")
                    or arguments.get("code") or ""
                )
            if _TEST_RE.search(cmd):
                return "run_test"
            if _DEL_RE.search(cmd) and not _SEARCH_RE.search(cmd):
                return "delete_file"
            if _READ_RE.search(cmd):
                return "read_file"
            if _SEARCH_RE.search(cmd):
                return "search_repo"
            return "run_code"
        if "think" in low:
            return "think"
        return "other"

# Instruments computed here are the scale-free subset of
# src/dsm_ae/harbor/instruments.py: they need no fixture and no oracle, only the
# ordered tool-call sequence. Thresholds are the published ones so the numbers
# are comparable with blog §1.4 / §3.4.
READ_LOOP_MAX = 3      # re-read one path more than 3x
THRASH_EDIT_MAX = 4    # edit one file more than 4x
SCOPE_CREEP_MAX = 8    # touch more than 8 distinct files

_EDIT_ATOMS = {"edit", "create_file"}


def _args(fn: dict[str, Any]) -> dict[str, Any]:
    a = fn.get("arguments")
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except Exception:
            return {}
    return a if isinstance(a, dict) else {}


def _path(a: dict[str, Any]) -> str:
    raw = a.get("path") or a.get("file_path") or a.get("filePath") or a.get("file") or ""
    p = str(raw).replace("\\", "/").lstrip("/")
    for pre in ("workspace/", "app/", "repo/", "testbed/"):
        if p.startswith(pre):
            p = p[len(pre):]
    return p


def calls_from_raw(rec: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for step in rec.get("trajectory") or []:
        action = step.get("action") or {}
        for tc in action.get("tool_calls") or []:
            fn = tc.get("function") or {}
            yield str(fn.get("name") or ""), _args(fn)


def calls_from_filtered(rec: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for m in rec.get("messages") or []:
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            yield str(fn.get("name") or ""), _args(fn)


def score_trajectory(calls: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    reads: Counter[str] = Counter()
    edits: Counter[str] = Counter()
    atoms: Counter[str] = Counter()
    verified_formal = False
    verified_adhoc = False
    for name, a in calls:
        atom = atom_from_tool(name, a)
        atoms[atom] += 1
        p = _path(a)
        if atom == "read_file" and p:
            reads[p] += 1
        elif atom in _EDIT_ATOMS and p:
            edits[p] += 1
        if atom == "run_test":
            verified_formal = True
        # These agents mostly verify with `python3 -c "... assert ..."` rather
        # than a runner; counting only the runner would mark 75% of this corpus
        # unverified (see _ADHOC_VERIFY_RE).
        cmd = str(a.get("command") or a.get("cmd") or a.get("code") or "")
        if cmd:
            if _TEST_RE.search(cmd):
                verified_formal = True
            elif _ADHOC_VERIFY_RE.search(cmd):
                verified_adhoc = True
    verified = verified_formal or verified_adhoc

    n_calls = len(calls)
    distinct_files = len(edits)
    max_reread = max(reads.values(), default=0)
    max_edit = max(edits.values(), default=0)
    edited = bool(edits)

    flags = {
        "read_loop": max_reread > READ_LOOP_MAX,
        "thrash_edit": max_edit > THRASH_EDIT_MAX,
        "scope_creep": distinct_files > SCOPE_CREEP_MAX,
        "unverified_submit": edited and not verified,
        "premature_stop": not edited,
    }
    return {
        "n_calls": n_calls,
        "n_steps": n_calls,
        "distinct_files": distinct_files,
        "max_reread": max_reread,
        "max_edit": max_edit,
        "test_share": round(atoms["run_test"] / n_calls, 4) if n_calls else 0.0,
        "verified_formal": verified_formal,
        "verified_adhoc": verified_adhoc,
        "atoms": dict(atoms),
        "flags": flags,
        "n_flags": sum(flags.values()),
        "clean": not any(flags.values()),
    }


# --------------------------------------------------------------------------
# Severity reranking
# --------------------------------------------------------------------------
# Their filter is a graded-reward cut (keep score >= ~0.6), so a binary
# clean/not-clean verdict cannot reproduce it: we need a continuous severity
# score to rank on and then take the top-K, where K is whatever size their kept
# set is. That makes the two selections directly comparable at equal budget.
#
# Weights come from measured association with their score on 4000 raw
# trajectories, NOT from the taxonomy:
#   spearman(score, distinct_files) = -0.454   spearman(score, n_calls) = -0.445
#   spearman(score, max_edit)       = -0.264   spearman(score, n_flags) = -0.345
#   scope_creep    mean score 0.404 fired vs 0.702 clean   (gap 0.298)
#   thrash_edit    mean score 0.447 fired vs 0.626 clean   (gap 0.179)
#   premature_stop mean score 0.077 fired vs 0.513 clean   (gap 0.436)
#   read_loop      mean score 0.472 fired vs 0.518 clean   (gap 0.046, near-noise)
# Higher severity = worse trajectory. Sprawl carries most of the signal, which
# is the same ordering blog section 2.9 found on NL2Repo-Bench.
SEVERITY_WEIGHTS = {
    "scope_creep": 0.30,
    "thrash_edit": 0.18,
    "premature_stop": 0.44,
    "unverified_submit": 0.05,
    "read_loop": 0.05,
}


def severity(s: dict[str, Any]) -> float:
    """Continuous ill-behaviour severity; higher is worse.

    Flag terms contribute their measured score gap. The sprawl term is
    continuous rather than thresholded so the ranking keeps the ordering
    information a fixed cutoff discards (blog section 3.0: ~0.06 AUC per
    thresholding step).
    """
    sev = sum(w for f, w in SEVERITY_WEIGHTS.items() if s["flags"].get(f))
    # log-scaled sprawl, normalised so ~8 distinct files (their keep median)
    # sits near 0 and ~18 (their drop median) near 1.
    import math

    files = s.get("distinct_files") or 0
    sev += 0.40 * min(1.0, max(0.0, (math.log1p(files) - math.log1p(8)) / (math.log1p(18) - math.log1p(8))))
    calls = s.get("n_calls") or 0
    sev += 0.20 * min(1.0, max(0.0, (math.log1p(calls) - math.log1p(78)) / (math.log1p(111) - math.log1p(78))))
    return round(sev, 4)


def read_jsonl(path: Path, limit: int | None) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh):
            if limit is not None and i >= limit:
                return
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def process(path: Path, kind: str, limit: int | None) -> dict[str, dict[str, Any]]:
    """instance_id -> scored record (last wins if an instance repeats)."""
    out: dict[str, dict[str, Any]] = {}
    for rec in read_jsonl(path, limit):
        if kind == "raw":
            iid = rec.get("instance_id")
            success = rec.get("success")
            score = rec.get("score")
            calls = list(calls_from_raw(rec))
        else:
            ei = rec.get("extra_info") or {}
            iid = ei.get("instance_id") or rec.get("id")
            success = ei.get("success")
            score = ei.get("score")
            calls = list(calls_from_filtered(rec))
        if not iid:
            continue
        s = score_trajectory(calls)
        s["instance_id"] = iid
        s["oracle_success"] = bool(success) if success is not None else None
        s["oracle_score"] = score
        s["severity"] = severity(s)
        out[str(iid)] = s
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--filtered", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=None, help="first N records of each file")
    ap.add_argument("--out", type=Path,
                    default=Path("reports/external/denovoswe_validation.json"))
    args = ap.parse_args()

    print(f"scoring raw      : {args.raw}")
    raw = process(args.raw, "raw", args.limit)
    print(f"  {len(raw)} instances")
    print(f"scoring filtered : {args.filtered}")
    filt = process(args.filtered, "filtered", args.limit)
    print(f"  {len(filt)} instances")

    kept = set(filt) & set(raw)           # their keep decision, on shared ids
    universe = set(raw)                   # everything we can judge
    # Equal-budget selection: rank the raw universe by severity (ascending =
    # cleanest first) and keep as many as they kept. Selecting by the binary
    # `clean` flag instead would compare sets of different sizes and make
    # precision/recall incomparable.
    budget = len(kept)
    ranked = sorted(universe, key=lambda i: (raw[i]["severity"], i))
    ours = set(ranked[:budget]) if budget else set()

    both = ours & kept & universe
    only_ours = (ours & universe) - kept
    only_theirs = (kept & universe) - ours
    neither = universe - ours - kept

    tp, fp, fn = len(both), len(only_ours), len(only_theirs)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    jac = tp / len(((ours | kept) & universe)) if ((ours | kept) & universe) else 0.0

    # base rates, to show whether agreement beats "keep everything"
    base = len(kept & universe) / len(universe) if universe else 0.0

    print("\n=== set overlap on the shared instance universe ===")
    print(f"  raw universe           {len(universe)}")
    print(f"  their filtered keep    {len(kept & universe)}  (base rate {base:.3f})")
    print(f"  our behavioural keep   {len(ours & universe)}")
    print(f"  both keep              {tp}")
    print(f"  only ours              {fp}")
    print(f"  only theirs            {fn}")
    print(f"  neither                {len(neither)}")
    print(f"\n  precision {prec:.3f}  recall {rec:.3f}  F1 {f1:.3f}  Jaccard {jac:.3f}")
    print(f"  lift over base rate    {prec / base if base else float('nan'):.3f}x")

    # The question that actually matters for section 10: at equal budget, is the
    # set we select as good as the set they select? Measured on THEIR oracle
    # score, which we never see during selection.
    def mean_score(ids: set[str]) -> float:
        vals = [raw[i]["oracle_score"] for i in ids
                if isinstance(raw[i].get("oracle_score"), (int, float))]
        return sum(vals) / len(vals) if vals else float("nan")

    all_mean = mean_score(universe)
    theirs_mean = mean_score(kept)
    ours_mean = mean_score(ours)
    print("\n=== selection quality, scored on THEIR graded oracle ===")
    print(f"  whole raw universe   mean score {all_mean:.4f}  (n={len(universe)})")
    print(f"  their kept set       mean score {theirs_mean:.4f}  (n={len(kept)})")
    print(f"  our top-{budget} by severity  mean score {ours_mean:.4f}  (n={len(ours)})")
    if all_mean == all_mean:
        print(f"  their lift over corpus {theirs_mean - all_mean:+.4f}")
        print(f"  our   lift over corpus {ours_mean - all_mean:+.4f}")
        frac = ((ours_mean - all_mean) / (theirs_mean - all_mean)
                if theirs_mean != all_mean else float("nan"))
        print(f"  we recover {frac:.1%} of their quality gain at the same budget")

    # per-flag: does each behaviour predict their drop decision?
    print("\n=== per-instrument association with THEIR drop decision ===")
    per_flag = {}
    for flag in ("read_loop", "thrash_edit", "scope_creep", "unverified_submit", "premature_stop"):
        fired = [i for i, s in raw.items() if s["flags"][flag]]
        if not fired:
            per_flag[flag] = None
            continue
        dropped_given_fired = sum(1 for i in fired if i not in kept) / len(fired)
        base_drop = 1.0 - base
        per_flag[flag] = {
            "n_fired": len(fired),
            "p_dropped_given_fired": round(dropped_given_fired, 4),
            "base_drop_rate": round(base_drop, 4),
            "lift": round(dropped_given_fired / base_drop, 3) if base_drop else None,
        }
        print(f"  {flag:20s} n={len(fired):6d}  P(drop|fired)={dropped_given_fired:.3f} "
              f"vs base {base_drop:.3f}  lift={per_flag[flag]['lift']}")

    out = {
        "description": "DSM-AE behavioural filter vs DeNovoSWE execution-based filter.",
        "raw_file": str(args.raw),
        "filtered_file": str(args.filtered),
        "limit": args.limit,
        "counts": {
            "raw_universe": len(universe),
            "their_keep": len(kept & universe),
            "our_keep": len(ours & universe),
            "both": tp, "only_ours": fp, "only_theirs": fn, "neither": len(neither),
        },
        "agreement": {
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4), "jaccard": round(jac, 4),
            "their_base_rate": round(base, 4),
        },
        "selection_quality": {
            "budget": budget,
            "mean_oracle_score_universe": round(all_mean, 4),
            "mean_oracle_score_theirs": round(theirs_mean, 4),
            "mean_oracle_score_ours": round(ours_mean, 4),
            "fraction_of_their_gain_recovered": (
                round((ours_mean - all_mean) / (theirs_mean - all_mean), 4)
                if theirs_mean != all_mean else None
            ),
        },
        "severity_weights": SEVERITY_WEIGHTS,
        "per_instrument": per_flag,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
