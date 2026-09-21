"""Step-level evidence: sentinel events and trajectory trends.

Two things the pack battery cannot express, both named by the failure-attribution
literature and by the DSM analogy the project borrows from:

**Sentinel events** (DSM: a pathognomonic sign — one occurrence is diagnostic).
A per-model pass rate destroys these: one catastrophic event in 20 trials reads
as 0.95. `premature_stop` fired 16 times in the archived corpus and *every one*
failed the task; averaging that away is the wrong representation, not a weak
signal. Sentinels are therefore recorded as **events with a step index and an
evidence pointer**, never as a rate.

**Trajectory trends** (procgrep-style, per `dsm_ae.atoms`). A trajectory is an
ordered atom list; trends are how the *composition* of that list shifts across
the run. Q26/§1 of the evidence-levels note measured that discrimination rises
monotonically with evidence level — single binary gate 0.575 -> instrument
count 0.615 -> continuous trajectory feature 0.636 (AUC, replicated on two
harnesses). Every threshold discards ordering information, so trends are kept
continuous and unthresholded here; callers may threshold for reporting.

The failure-step formalism follows the survey's definition (Wang et al., *A
Survey for LLM Agent Trajectory Analysis*, §2.2): the failure step t* is the
earliest step after which no continuation succeeds. That is not computable
post-hoc without counterfactual rollouts, so what this module emits is
**candidate** sentinel steps — observable events that are *plausibly* decisive
— and they must be reported as candidates. The survey also records that
step-level attribution accuracy is 25-52% on Who&When and ~33% on
TraceElephant, which is the bar any localisation claim is measured against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from dsm_ae.atoms import atom_from_tool
from dsm_ae.harbor.adapter import HarborTrial
from dsm_ae.harbor.instruments import (
    _DESTRUCTIVE_RE,
    _EDIT_ATOMS,
    _SKIP_TEST_RE,
    _args,
    _atom,
    _cmd,
    _is_error,
    _norm_key,
    _path,
    _text_blob,
)

# Coarse execution phase, following the survey's task-execution-phase
# perspective (WHERE did it go wrong). Deliberately few and observable.
PHASES = ("plan_stage", "explore_stage", "implementation_stage", "verify_stage")


@dataclass
class SentinelEvent:
    """One structural, rare, near-deterministic occurrence at a known step.

    Recorded as an event, never averaged into a rate.
    """

    kind: str
    step: int  # index into trial.tool_calls
    phase: str
    detail: str
    evidence: str  # short quote/pointer so a human can check the call


@dataclass
class TrajectoryTrends:
    """Continuous, unthresholded shape of a trajectory."""

    n_calls: int
    atoms: list[str] = field(default_factory=list)
    # composition drift: atom mix in the first vs last third
    early_mix: dict[str, float] = field(default_factory=dict)
    late_mix: dict[str, float] = field(default_factory=dict)
    # scalar trends
    search_share: float = 0.0
    edit_share: float = 0.0
    test_share: float = 0.0
    error_share: float = 0.0
    repeat_read_ratio: float = 0.0  # reads of already-read paths / all reads
    late_edit_share: float = 0.0  # edits in the last third (churn near the end)
    first_edit_frac: float | None = None  # where the first edit falls in [0,1]
    first_test_frac: float | None = None
    distinct_files: int = 0
    n_phases_reached: int = 0


def phase_of(index: int, n: int, first_edit: int | None, first_test: int | None) -> str:
    """Coarse phase for a step.

    Boundaries are *behavioural* rather than positional where possible: the
    first edit opens implementation, the first test opens verification. A
    positional fallback keeps this defined for degenerate traces.
    """
    if n <= 0:
        return "plan_stage"
    if first_edit is None and first_test is None:
        # Never edited or tested: an exploration-only run.
        return "plan_stage" if index < max(1, n // 4) else "explore_stage"
    if first_test is not None and index >= first_test:
        return "verify_stage"
    if first_edit is not None and index >= first_edit:
        return "implementation_stage"
    return "plan_stage" if index < max(1, n // 4) else "explore_stage"


def _first_index(calls: list[dict[str, Any]], pred: Callable[[dict], bool]) -> int | None:
    for i, tc in enumerate(calls):
        if pred(tc):
            return i
    return None


def trends(t: HarborTrial) -> TrajectoryTrends:
    calls = t.tool_calls
    n = len(calls)
    atoms = [_atom(tc) for tc in calls]
    tr = TrajectoryTrends(n_calls=n, atoms=atoms)
    if n == 0:
        return tr

    third = max(1, n // 3)
    def mix(seq: list[str]) -> dict[str, float]:
        if not seq:
            return {}
        out: dict[str, float] = {}
        for a in seq:
            out[a] = out.get(a, 0.0) + 1.0
        return {k: v / len(seq) for k, v in out.items()}

    tr.early_mix = mix(atoms[:third])
    tr.late_mix = mix(atoms[-third:])
    tr.search_share = atoms.count("search_repo") / n
    tr.edit_share = sum(1 for a in atoms if a in _EDIT_ATOMS) / n
    tr.test_share = atoms.count("run_test") / n
    tr.error_share = sum(1 for tc in calls if _is_error(tc)) / n

    seen: set[str] = set()
    reads = repeats = 0
    for tc in calls:
        if _atom(tc) != "read_file":
            continue
        reads += 1
        k = _norm_key(_path(tc))
        if k and k in seen:
            repeats += 1
        seen.add(k)
    tr.repeat_read_ratio = (repeats / reads) if reads else 0.0

    late = atoms[-third:]
    tr.late_edit_share = (sum(1 for a in late if a in _EDIT_ATOMS) / len(late)) if late else 0.0

    fe = _first_index(calls, lambda tc: _atom(tc) in _EDIT_ATOMS)
    ft = _first_index(calls, lambda tc: _atom(tc) == "run_test")
    tr.first_edit_frac = (fe / n) if fe is not None else None
    tr.first_test_frac = (ft / n) if ft is not None else None
    tr.distinct_files = len({_norm_key(_path(tc)) for tc in calls if _path(tc)})
    tr.n_phases_reached = len({phase_of(i, n, fe, ft) for i in range(n)})
    return tr


def sentinels(t: HarborTrial) -> list[SentinelEvent]:
    """Candidate decisive events, with step index and evidence pointer.

    These are *observable* events, not proven failure steps: the survey's t* is
    defined over counterfactual continuations and is not recoverable post-hoc.
    Report as candidates.
    """
    calls = t.tool_calls
    n = len(calls)
    fe = _first_index(calls, lambda tc: _atom(tc) in _EDIT_ATOMS)
    ft = _first_index(calls, lambda tc: _atom(tc) == "run_test")
    out: list[SentinelEvent] = []

    def add(kind: str, i: int, detail: str, ev: str) -> None:
        out.append(
            SentinelEvent(
                kind=kind,
                step=i,
                phase=phase_of(i, n, fe, ft),
                detail=detail,
                evidence=ev[:200],
            )
        )

    read: set[str] = set()
    created: set[str] = set()
    for i, tc in enumerate(calls):
        atom = _atom(tc)
        key = _norm_key(_path(tc))

        if atom == "read_file" and not _is_error(tc):
            read.add(key)

        elif atom in _EDIT_ATOMS and key:
            a = _args(tc)
            is_patch = bool(a.get("oldString") or a.get("old_string") or a.get("search"))
            if is_patch and key not in read and key not in created:
                add("ungrounded_patch", i,
                    f"patched {key} without ever reading it", key)
            created.add(key)
            blob = _text_blob(tc)
            if _SKIP_TEST_RE.search(blob):
                add("test_suppressed", i,
                    f"wrote a skip/xfail marker into {key}", blob)

        cmd = _cmd(tc)
        if cmd and _DESTRUCTIVE_RE.search(cmd):
            add("destructive_command", i, "ran a destructive shell command", cmd)

    # Whole-trajectory sentinels (step = the point they become determined).
    if n and fe is None:
        add("never_edited", n - 1, "run ended without editing anything", "")

    if fe is not None and ft is None:
        add("never_verified", n - 1,
            "edited but never ran a test or build", "")

    return out


def summarize(t: HarborTrial) -> dict[str, Any]:
    """Compact record joining sentinels + trends to the external outcome."""
    tr = trends(t)
    sv = sentinels(t)
    return {
        "trial_name": t.trial_name,
        "task_name": t.task_name,
        "harness": t.harness,
        "language": t.language,
        "repo": t.repo,
        "reward": t.reward,
        "success": t.success,
        "n_calls": tr.n_calls,
        "search_share": round(tr.search_share, 4),
        "edit_share": round(tr.edit_share, 4),
        "test_share": round(tr.test_share, 4),
        "error_share": round(tr.error_share, 4),
        "repeat_read_ratio": round(tr.repeat_read_ratio, 4),
        "late_edit_share": round(tr.late_edit_share, 4),
        "first_edit_frac": tr.first_edit_frac,
        "first_test_frac": tr.first_test_frac,
        "distinct_files": tr.distinct_files,
        "n_phases_reached": tr.n_phases_reached,
        "sentinels": [
            {"kind": s.kind, "step": s.step, "phase": s.phase, "detail": s.detail}
            for s in sv
        ],
        "sentinel_kinds": sorted({s.kind for s in sv}),
        "n_sentinels": len(sv),
    }


def sentinel_table(trials: Iterable[HarborTrial]) -> dict[str, dict[str, Any]]:
    """Base rates per sentinel kind — counts and outcome, never a pass rate."""
    agg: dict[str, dict[str, Any]] = {}
    for t in trials:
        if t.success is None:
            continue
        kinds = {s.kind for s in sentinels(t)}
        for k in kinds:
            a = agg.setdefault(k, {"n_trials": 0, "n_failed": 0, "phases": {}})
            a["n_trials"] += 1
            a["n_failed"] += 0 if t.success else 1
        for s in sentinels(t):
            if s.kind in agg:
                agg[s.kind]["phases"][s.phase] = agg[s.kind]["phases"].get(s.phase, 0) + 1
    for k, a in agg.items():
        a["fail_rate"] = a["n_failed"] / a["n_trials"] if a["n_trials"] else None
    return agg
