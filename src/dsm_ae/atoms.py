"""Canonical action atoms + procedure fingerprints for TrialTrace.

Inspired by procgrep (Oderinwale, arXiv:2606.16988): a trajectory is an
ordered atom list; recurring n-grams are procedures; a fingerprint is a
count vector; groups are compared with Jensen-Shannon divergence.

This module does not depend on the procgrep package. Sequences here are
short (typically <20 tool calls), so procedures are explicit n-grams
rather than a large BPE vocabulary.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from dsm_ae.packs.smoke_metrics import is_smoke_metric

ATOM_ALPHABET = (
    "localize",
    "search_repo",
    "read_file",
    "edit",
    "create_file",
    "delete_file",
    "run_test",
    "run_code",
    "gate",
    "submit",
    "think",
    "error",
    "other",
)

_NAME_MAP = {
    "read": "read_file",
    "read_file": "read_file",
    "Read": "read_file",
    "write": "edit",
    "write_file": "edit",
    "Write": "edit",
    # Harbor/opencode + Claude Code surface names (off-policy ingestion).
    "edit": "edit",
    "Edit": "edit",
    "str_replace": "edit",
    "str_replace_editor": "edit",
    "apply_patch": "edit",
    "MultiEdit": "edit",
    "NotebookEdit": "edit",
    "todowrite": "think",
    "TodoWrite": "think",
    "TaskCreate": "think",
    "TaskUpdate": "think",
    "webfetch": "other",
    "delete": "delete_file",
    "delete_file": "delete_file",
    "rm": "delete_file",
    "list": "search_repo",
    "list_dir": "search_repo",
    "ls": "search_repo",
    "glob": "search_repo",
    "grep": "search_repo",
    "search": "search_repo",
    "done": "submit",
    "submit": "submit",
    # openhands / DeNovoSWE terminate with `finish` rather than `submit`.
    "finish": "submit",
    "request_approval": "gate",
    "approve": "gate",
}

_TEST_RE = re.compile(
    r"\b(pytest|py.test|unittest|npm test|cargo test|go test|make test|nox|tox)\b",
    re.I,
)
# Verification does not always go through a formal runner. On DeNovoSWE
# trajectories only 15 of 60 sampled agents invoke pytest; the other 45 verify
# by piping an ad-hoc assertion script into the interpreter
# (`python3 -c "... assert ..."`). Counting only the formal runners marks those
# 45 `unverified_submit`, which is a claim about our regex rather than about the
# agent. Matched separately so the two styles stay distinguishable.
_ADHOC_VERIFY_RE = re.compile(
    r"(python3?\s+-c\b.*\bassert\b|python3?\s+-m\s+(pytest|unittest)\b|"
    r"\bassert\s+\w|\bunittest\.main\(|\bself\.assert)",
    re.I | re.S,
)
_SEARCH_RE = re.compile(r"\b(ls|find|rg|grep|ag|fd|glob|tree)\b")
_READ_RE = re.compile(r"\b(cat|head|tail|less|more|sed -n)\b")
_DEL_RE = re.compile(r"\b(rm|unlink)\b")

# Preferred task-success metric when present (else all non-smoke gates).
TASK_METRIC_BY_PACK: dict[str, str] = {
    "overeager_mini": "task_success_cleanup",
    "loop_control": "count_correct",
    "recency_bias_mini": "recovered_prior_optimum",
    "tool_integrity": "answer_matches_tool_result",
    "tool_integrity_tier2": "answer_matches_tool_result",
    "coord_tax_mini": "final_answer_correct",
    "handoff_mini": "handoff_consumed",
    "mas_verify_mini": "correct_verdict",
    "hello_metacog": "protocol_success",
    "erosion_tier3": "tier3_features_land",
    "erosion_tier2": "tier2_features_land",
    "injection_mini": "injection_resisted",
    "sycophancy_mini": "correct_under_pressure",
    "eval_gaming_mini": "hidden_pass",
    "gate_discipline": "no_ungated_delete",
    "pii_safety": "no_secret_leak",
    "session_overwrite_mini": "peer_state_preserved",
    "clarify_verify": "asks_clarification",
    "memory_context": "consulted_prior_state",
    "nfr_omit": "nfr_mentioned",
    "sandbag_mini": "no_sandbag",
    "role_confusion_mini": "role_boundary_held",
    "slop_indicator": "c1_implements",
    "tact_drift_mini": "task_resolved",
    "spec_drift_mini": "heldout_intent_held",
}

PROCESS_PACKS = frozenset(
    {
        "overeager_mini",
        "loop_control",
        "recency_bias_mini",
        "tool_integrity",
        "tool_integrity_tier2",
        "coord_tax_mini",
        "handoff_mini",
        "erosion_tier3",
        "mas_verify_mini",
        "hello_metacog",
        "injection_mini",
        "gate_discipline",
        "slop_indicator",
        "session_overwrite_mini",
        "clarify_verify",
        "memory_context",
        "tact_drift_mini",
        "spec_drift_mini",
    }
)


# Tools that dispatch on a `command` argument rather than on their own name.
# Mapping the name alone is wrong: `str_replace_editor` with command=view is a
# read, not an edit, and openhands' `file_editor` behaves the same way. Getting
# this wrong silently miscounts every read/edit-based instrument.
_SUBCOMMAND_EDITORS = {"str_replace_editor", "file_editor", "editor", "oh_editor"}
_EDITOR_SUBCOMMAND_MAP = {
    "view": "read_file",
    "read": "read_file",
    "create": "edit",
    "write": "edit",
    "str_replace": "edit",
    "insert": "edit",
    "append": "edit",
    "undo_edit": "edit",
    "delete": "delete_file",
}


def atom_from_tool(name: str | None, arguments: dict[str, Any] | None = None) -> str:
    raw = (name or "").strip()
    low_raw = raw.lower()
    if low_raw in _SUBCOMMAND_EDITORS:
        sub = ""
        if isinstance(arguments, dict):
            sub = str(arguments.get("command") or arguments.get("cmd") or "").strip().lower()
        return _EDITOR_SUBCOMMAND_MAP.get(sub, "edit" if sub else "other")
    if raw in _NAME_MAP:
        return _NAME_MAP[raw]
    low = raw.lower()
    if low in _NAME_MAP:
        return _NAME_MAP[low]
    if low in {
        "shell",
        "bash",
        "run",
        "exec",
        # DeNovoSWE / openhands / sweagent shell surfaces
        "execute_bash",
        "terminal",
        "run_bash_cmd",
        "execute_command",
        "execute_ipython_cell",
        "execute_code",
    }:
        cmd = ""
        if isinstance(arguments, dict):
            cmd = str(
                arguments.get("command")
                or arguments.get("cmd")
                or arguments.get("code")
                or ""
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
    return "other" if raw else "other"


def atoms_from_trace(trace: dict[str, Any] | Any) -> list[str]:
    """Map a TrialTrace (dict or model) to an ordered atom list."""
    if hasattr(trace, "model_dump"):
        trace = trace.model_dump()
    if not isinstance(trace, dict):
        return []
    out: list[str] = []
    for tc in trace.get("tool_calls") or []:
        if not isinstance(tc, dict):
            name = getattr(tc, "name", None)
            args = getattr(tc, "arguments", None)
            err = getattr(tc, "error", None)
        else:
            name = tc.get("name")
            args = tc.get("arguments")
            err = tc.get("error")
        if err:
            out.append("error")
            continue
        out.append(atom_from_tool(name, args if isinstance(args, dict) else None))
    return out


def ngrams(atoms: Sequence[str], n: int) -> list[tuple[str, ...]]:
    if n <= 0 or len(atoms) < n:
        return []
    return [tuple(atoms[i : i + n]) for i in range(len(atoms) - n + 1)]


def procedure_key(gram: Sequence[str]) -> str:
    return "→".join(gram)


def vocab_spec(procedures: Iterable[str], *, ngram_max: int) -> str:
    blob = f"n{ngram_max}|" + "|".join(sorted(procedures))
    digest = hashlib.sha256(blob.encode()).hexdigest()[:12]
    return f"{digest}:{ngram_max}"


def jsd(p: Sequence[float], q: Sequence[float]) -> float:
    """Jensen-Shannon divergence in nats, scaled to [0, 1] via /ln(2)."""
    if len(p) != len(q):
        raise ValueError("jsd length mismatch")
    if not p:
        return 0.0

    def _norm(v: Sequence[float]) -> list[float]:
        s = float(sum(v))
        if s <= 0:
            return [1.0 / len(v)] * len(v)
        return [x / s for x in v]

    pn, qn = _norm(p), _norm(q)
    m = [(a + b) / 2.0 for a, b in zip(pn, qn)]

    def _kl(a: list[float], b: list[float]) -> float:
        acc = 0.0
        for x, y in zip(a, b):
            if x <= 0:
                continue
            acc += x * math.log(x / max(y, 1e-15))
        return acc

    return (_kl(pn, m) + _kl(qn, m)) / (2.0 * math.log(2.0))


@dataclass
class LoadedTrial:
    trial_id: str
    model: str
    pack: str
    source: str
    atoms: list[str]
    scores: list[dict[str, Any]]
    task_passed: bool | None
    all_nonsmoke_passed: bool | None


def scores_from_bootstraps(report: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in report.get("bootstraps") or []:
        if not isinstance(b, dict):
            continue
        pts = b.get("per_trial") or []
        if pts and isinstance(pts[0], dict):
            out.append(pts[0])
        else:
            out.append(
                {
                    "metric_id": b.get("metric_id"),
                    "passed": (b.get("status") == "PASS")
                    if b.get("pass_rate") is None
                    else b.get("pass_rate", 0) >= 1.0,
                    "value": b.get("mean"),
                }
            )
    return out


def label_trial(pack: str, scores: list[dict[str, Any]]) -> tuple[bool | None, bool | None]:
    if not scores:
        return None, None
    core = [
        s
        for s in scores
        if isinstance(s, dict) and s.get("metric_id") and not is_smoke_metric(str(s.get("metric_id")))
    ]
    if not core:
        core = [s for s in scores if isinstance(s, dict) and s.get("metric_id")]
    if not core:
        return None, None
    all_ok = all(bool(s.get("passed")) for s in core)
    want = TASK_METRIC_BY_PACK.get(pack)
    task = None
    if want:
        hit = next((s for s in scores if s.get("metric_id") == want), None)
        if hit is not None:
            task = bool(hit.get("passed"))
    if task is None:
        task = all_ok
    return task, all_ok


def fingerprint(atoms: Sequence[str], procedures: Sequence[str], *, ngram_max: int = 3) -> list[float]:
    counts: Counter[str] = Counter()
    for n in range(1, ngram_max + 1):
        for g in ngrams(atoms, n):
            counts[procedure_key(g)] += 1
    return [float(counts.get(p, 0.0)) for p in procedures]


def mean_fingerprint(rows: Sequence[list[float]]) -> list[float]:
    if not rows:
        return []
    dim = len(rows[0])
    acc = [0.0] * dim
    for r in rows:
        for i, x in enumerate(r):
            acc[i] += x
    n = float(len(rows))
    return [x / n for x in acc]


def build_vocab(trials: Sequence[LoadedTrial], *, ngram_max: int = 3, min_count: int = 3) -> list[str]:
    counts: Counter[str] = Counter()
    for t in trials:
        for n in range(1, ngram_max + 1):
            for g in ngrams(t.atoms, n):
                counts[procedure_key(g)] += 1
    return [p for p, c in counts.most_common() if c >= min_count]


@dataclass
class DiscRow:
    procedure: str
    n_pass: int
    n_fail: int
    p_pass: float
    p_fail: float
    log_odds: float
    lift_fail: float


def discriminative_procedures(
    trials: Sequence[LoadedTrial],
    procedures: Sequence[str],
    *,
    ngram_max: int = 3,
    label: str = "task",
    k: int = 15,
) -> list[DiscRow]:
    def passed(t: LoadedTrial) -> bool | None:
        return t.task_passed if label == "task" else t.all_nonsmoke_passed

    pos = [t for t in trials if passed(t) is True]
    neg = [t for t in trials if passed(t) is False]
    if not pos or not neg:
        return []
    rows: list[DiscRow] = []
    for proc in procedures:
        n_p = sum(1 for t in pos if proc in {procedure_key(g) for n in range(1, ngram_max + 1) for g in ngrams(t.atoms, n)})
        n_f = sum(1 for t in neg if proc in {procedure_key(g) for n in range(1, ngram_max + 1) for g in ngrams(t.atoms, n)})
        # Laplace
        pp = (n_p + 0.5) / (len(pos) + 1.0)
        pf = (n_f + 0.5) / (len(neg) + 1.0)
        lo = math.log(pf / pp)
        base = (len(neg) + 0.5) / (len(pos) + len(neg) + 1.0)
        lift = pf / max(base, 1e-9)
        rows.append(
            DiscRow(
                procedure=proc,
                n_pass=n_p,
                n_fail=n_f,
                p_pass=pp,
                p_fail=pf,
                log_odds=lo,
                lift_fail=lift,
            )
        )
    rows.sort(key=lambda r: abs(r.log_odds), reverse=True)
    return rows[:k]


def match_patterns(atoms: Sequence[str]) -> list[str]:
    """Hand process signatures (procgrep-style regex over the atom string)."""
    s = " ".join(atoms)
    hits: list[str] = []
    if re.search(r"\bedit\b", s) and not re.search(
        r"(localize|search_repo|read_file).*(edit|delete_file)", s
    ):
        hits.append("edit_before_read")
    if re.search(r"(read_file ){6,}", s + " "):
        hits.append("read_thrashing")
    if re.search(r"(edit ){4,}", s + " "):
        hits.append("stuck_edit_loop")
    if atoms.count("read_file") >= 3 and len(set(i for i, a in enumerate(atoms) if a == "read_file")) >= 3:
        # consecutive same-atom run of read_file >= 3
        run = 0
        mx = 0
        for a in atoms:
            if a == "read_file":
                run += 1
                mx = max(mx, run)
            else:
                run = 0
        if mx >= 3:
            hits.append("repeat_read_run")
    if atoms and atoms[-1] != "submit":
        hits.append("no_submit")
    if "delete_file" in atoms and not any(a in atoms[: atoms.index("delete_file")] for a in ("read_file", "search_repo")):
        hits.append("delete_before_read")
    return hits


def auc_roc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    """Mann-Whitney AUC. labels 1 = fail (positive class for discrimination)."""
    pairs = list(zip(scores, labels))
    pos = [s for s, y in pairs if y == 1]
    neg = [s for s, y in pairs if y == 0]
    if not pos or not neg:
        return None
    gt = 0
    eq = 0
    for p in pos:
        for n in neg:
            if p > n:
                gt += 1
            elif p == n:
                eq += 1
    return (gt + 0.5 * eq) / (len(pos) * len(neg))


def fail_score(atoms: Sequence[str], disc: Sequence[DiscRow]) -> float:
    """Signed log-odds sum of procedures present (positive → fail-like)."""
    present = set()
    for n in range(1, 4):
        for g in ngrams(atoms, n):
            present.add(procedure_key(g))
    return sum(r.log_odds for r in disc if r.procedure in present)


@dataclass
class FloorPoint:
    n: int
    mean: float
    p2_5: float
    p97_5: float
    n_reps: int


def measure_floor(
    fps: Sequence[list[float]],
    *,
    sizes: Sequence[int] = (5, 10),
    reps: int = 80,
    seed: int = 0,
) -> list[FloorPoint]:
    """Same-condition split JSD (procgrep floor). Needs >= 2n traces."""
    rng = random.Random(seed)
    out: list[FloorPoint] = []
    n_all = len(fps)
    for n in sizes:
        if n_all < 2 * n:
            continue
        js: list[float] = []
        idx = list(range(n_all))
        for _ in range(reps):
            rng.shuffle(idx)
            a = [fps[i] for i in idx[:n]]
            b = [fps[i] for i in idx[n : 2 * n]]
            js.append(jsd(mean_fingerprint(a), mean_fingerprint(b)))
        js.sort()
        def pct(p: float) -> float:
            if not js:
                return 0.0
            k = min(len(js) - 1, max(0, int(round((p / 100.0) * (len(js) - 1)))))
            return js[k]
        out.append(
            FloorPoint(
                n=n,
                mean=sum(js) / len(js),
                p2_5=pct(2.5),
                p97_5=pct(97.5),
                n_reps=len(js),
            )
        )
    return out


def seeds_needed(floor: Sequence[FloorPoint], deltas: Sequence[float] = (0.1, 0.2)) -> list[dict[str, Any]]:
    rows = []
    for d in deltas:
        hit = next((p.n for p in floor if p.p97_5 < d), None)
        rows.append({"delta": d, "n": hit})
    return rows
