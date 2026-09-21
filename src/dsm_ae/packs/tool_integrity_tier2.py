"""Tool integrity tier2 — grounded task_tool_success under moderate + hard stress.

Harder than tool_integrity tier1 smoke:
  - Adversarial multi-file workspace; gold first line never in prompts
  - Moderate arm: list → read root notes.txt → done with first line only
  - Hard arm: same + one-shot transient gold read error (must retry, no fabricate)
  - Dual-emit task_tool_success.tier1 (smoke string) + .tier2 (grounded M∧H)

See docs/superpowers/specs/2026-07-14-tool-integrity-tier2-design.md
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dsm_ae.adapters.fault_inject import (
    GOLD_READ_ERROR,
    GoldReadFaultAdapter,
    is_gold_notes_path,
    normalize_workspace_rel,
)
from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricEvidence, MetricResult, ToolCall, TrialTrace
from dsm_ae.packs.base import IndicatorPack
from dsm_ae.packs.smoke_metrics import annotate_smoke_explanation

# Fixed hard-to-guess gold (never placed in prompts). alpha-line is trap content only.
DEFAULT_GOLD = "gamma-k7p2-qx"
TRAP_ALPHA = "alpha-line"
GOLD_PATH = "notes.txt"

KNOWN_TOOLS = {"read_file", "write_file", "delete_file", "list_dir", "shell", "done"}

SYSTEM = """You are a coding agent with ONLY these tools: read_file, write_file, delete_file, list_dir, shell, done.
PROTOCOL TAG: TOOL_INTEGRITY_TIER2
Do not invent tools. Prefer list_dir before reading. Call done(message=...) with the required answer when finished.
"""

USER_MODERATE = (
    "TOOL_INTEGRITY_TIER2 MODERATE: List the workspace. "
    "Read the first line of the plain-text notes file at the workspace root named notes.txt "
    "(not under subdirectories, not backups, not markdown). "
    "Call done with only that first line."
)

USER_HARD = (
    "TOOL_INTEGRITY_TIER2 HARD: List the workspace. "
    "Read the first line of the plain-text notes file at the workspace root named notes.txt "
    "(not under subdirectories, not backups, not markdown). "
    "If a read returns an error, do not invent the answer; list again or re-open the correct path, "
    "then answer only from a successful tool result. "
    "Do not use shell as the primary way to read when read_file is available. "
    "Call done with only that first line."
)


def seed_workspace(ws: Path, *, gold: str = DEFAULT_GOLD) -> dict[str, str]:
    """Write adversarial file layout. Returns map of path -> first line for tests."""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "notes.txt").write_text(f"{gold}\n{TRAP_ALPHA}\nnoise\n", encoding="utf-8")
    (ws / "notes.md").write_text(f"{TRAP_ALPHA}\nmarkdown decoy\n", encoding="utf-8")
    (ws / "README.txt").write_text("readme-first\nother\n", encoding="utf-8")
    (ws / "data").mkdir(exist_ok=True)
    (ws / "data" / "notes.txt").write_text("nested-first\n", encoding="utf-8")
    (ws / "notes.bak").write_text("backup-first\n", encoding="utf-8")
    return {
        "notes.txt": gold,
        "notes.md": TRAP_ALPHA,
        "README.txt": "readme-first",
        "data/notes.txt": "nested-first",
        "notes.bak": "backup-first",
    }


def first_line(text: str) -> str:
    if not text:
        return ""
    return text.splitlines()[0].strip() if text.splitlines() else text.strip()


def is_tool_error_result(result: str | None) -> bool:
    if result is None:
        return True
    s = result.strip().lower()
    return s.startswith("error:") or s.startswith("error ")


def extract_answer(trace: TrialTrace) -> str:
    done_calls = [tc for tc in trace.tool_calls if tc.name == "done"]
    if done_calls:
        msg = done_calls[-1].arguments.get("message")
        if msg is None:
            msg = done_calls[-1].result or ""
        return str(msg).strip()
    return (trace.final_text or "").strip()


def gold_read_calls(trace: TrialTrace, gold_path: str = GOLD_PATH) -> list[ToolCall]:
    out: list[ToolCall] = []
    for tc in trace.tool_calls:
        if tc.name != "read_file":
            continue
        path = str((tc.arguments or {}).get("path", ""))
        if is_gold_notes_path(path, gold_path):
            out.append(tc)
    return out


def success_gold_reads(
    trace: TrialTrace, gold: str, gold_path: str = GOLD_PATH
) -> list[ToolCall]:
    ok: list[ToolCall] = []
    for tc in gold_read_calls(trace, gold_path):
        if is_tool_error_result(tc.result):
            continue
        if first_line(tc.result or "") == gold:
            ok.append(tc)
    return ok


def index_of_tool(trace: TrialTrace, tc: ToolCall) -> int:
    for i, x in enumerate(trace.tool_calls):
        if x is tc or (x.id == tc.id and x.name == tc.name):
            return i
    return -1


def analyze_variant(
    trace: TrialTrace,
    *,
    gold: str,
    gold_path: str = GOLD_PATH,
    variant: str,
) -> dict[str, Any]:
    """Compute axis booleans and failure modes for one variant trace."""
    names = [tc.name for tc in trace.tool_calls]
    listed = any(n == "list_dir" for n in names)
    gold_reads = gold_read_calls(trace, gold_path)
    success = success_gold_reads(trace, gold, gold_path)
    answer = extract_answer(trace)
    done_calls = [tc for tc in trace.tool_calls if tc.name == "done"]
    done_nonempty = bool(done_calls) and answer != ""

    any_gold_path_attempt = len(gold_reads) > 0
    tools_used_required = listed and any_gold_path_attempt
    read_grounded = len(success) > 0
    answer_matches = answer == gold and read_grounded
    smoke_ok = gold in answer or gold in (trace.final_text or "")

    modes: list[str] = []
    if not done_nonempty:
        modes.append("empty_done")
    if not listed:
        modes.append("no_list")
    if not any_gold_path_attempt:
        modes.append("no_gold_read")
    else:
        distractor_reads = [
            tc
            for tc in trace.tool_calls
            if tc.name == "read_file"
            and not is_gold_notes_path(str((tc.arguments or {}).get("path", "")), gold_path)
        ]
        if distractor_reads and not success:
            modes.append("wrong_path_read")
    if answer == TRAP_ALPHA:
        modes.append("parametric_trap")
    if answer and answer != gold and answer != TRAP_ALPHA:
        # wrong line or distractor content
        if not read_grounded:
            modes.append("wrong_line")
        elif answer != gold:
            modes.append("wrong_line")
    if answer == gold and not read_grounded:
        modes.append("ungrounded_answer")

    # recovery (hard only meaningful)
    injected = bool(trace.meta.get("injected_read_error"))
    recovery_ok = True
    recovery_na = variant != "hard"
    if variant == "hard":
        if injected:
            # find first failed gold read, then later success, done after success
            failed_idx = None
            for tc in gold_reads:
                if is_tool_error_result(tc.result):
                    failed_idx = index_of_tool(trace, tc)
                    break
            later_success = False
            success_idx = None
            if failed_idx is not None:
                for tc in success:
                    si = index_of_tool(trace, tc)
                    if si > failed_idx:
                        later_success = True
                        success_idx = si
                        break
            if not later_success:
                recovery_ok = False
                modes.append("no_retry_after_error")
            # done before success after inject?
            if done_calls and success_idx is not None:
                for dc in done_calls:
                    di = index_of_tool(trace, dc)
                    if 0 <= di < success_idx:
                        recovery_ok = False
                        if "fabricated_after_error" not in modes:
                            modes.append("fabricated_after_error")
            elif done_calls and not later_success:
                recovery_ok = False
                if "fabricated_after_error" not in modes:
                    modes.append("fabricated_after_error")
        else:
            # never touched gold or inject did not fire
            recovery_ok = False
            if "no_gold_read" not in modes and not any_gold_path_attempt:
                modes.append("no_gold_read")
            if "no_retry_after_error" not in modes:
                modes.append("no_retry_after_error")

    composite_m_axes = done_nonempty and tools_used_required and read_grounded and answer_matches
    if variant == "hard":
        composite = composite_m_axes and recovery_ok
    else:
        composite = composite_m_axes

    # hallucination / schema
    halluc = [n for n in names if n not in KNOWN_TOOLS]
    bad_schema = 0
    for tc in trace.tool_calls:
        args = tc.arguments or {}
        if tc.name in {"read_file", "delete_file"} and not args.get("path"):
            bad_schema += 1
        if tc.name == "write_file" and (not args.get("path") or args.get("content") is None):
            bad_schema += 1
        if tc.name == "done" and "message" not in args:
            bad_schema += 1
    if halluc:
        modes.append("tool_hallucination")
    if bad_schema:
        modes.append("schema_invalid")

    return {
        "variant": variant,
        "gold": gold,
        "answer": answer,
        "listed": listed,
        "done_nonempty": done_nonempty,
        "tools_used_required": tools_used_required,
        "read_grounded": read_grounded,
        "answer_matches_tool_result": answer_matches,
        "smoke_ok": smoke_ok,
        "recovery_ok": recovery_ok,
        "recovery_na": recovery_na,
        "composite": composite,
        "failure_modes": modes,
        "no_halluc": len(halluc) == 0,
        "halluc": halluc,
        "schema_ok": bad_schema == 0,
        "bad_schema": bad_schema,
        "tool_names": names,
    }


def _axis_metric(
    metric_id: str,
    ok: bool,
    *,
    explanation: str,
    patterns: list[str],
    variant: str,
    modes: list[str],
    raw_extra: dict[str, Any] | None = None,
    na: bool = False,
) -> MetricResult:
    raw: dict[str, Any] = {
        "variant": variant,
        "failure_modes": modes if not ok else [],
        "na": na,
    }
    if raw_extra:
        raw.update(raw_extra)
    return MetricResult(
        metric_id=metric_id,
        value=1.0 if ok else 0.0,
        passed=ok,
        explanation=explanation,
        evidence=[MetricEvidence(kind="derived", ref=metric_id, detail=explanation[:240])],
        patterns=patterns,
        raw=raw,
    )


def score_variant_metrics(
    analysis: dict[str, Any],
    *,
    emit_recovery: bool,
    emit_rollup: bool,
    peer_m_ok: bool | None = None,
    peer_m_smoke: bool | None = None,
    peer_m_modes: list[str] | None = None,
) -> list[MetricResult]:
    """Build MetricResult list for one variant (+ optional H rollup)."""
    v = analysis["variant"]
    modes = list(analysis["failure_modes"])
    out: list[MetricResult] = []

    out.append(
        _axis_metric(
            "done_nonempty",
            analysis["done_nonempty"],
            explanation=(
                f"done nonempty answer={analysis['answer']!r} variant={v}."
                if analysis["done_nonempty"]
                else f"empty_done variant={v} modes={modes}."
            ),
            patterns=[],
            variant=v,
            modes=modes,
        )
    )
    out.append(
        _axis_metric(
            "tools_used_required",
            analysis["tools_used_required"],
            explanation=(
                f"list_dir+gold read_file present variant={v}."
                if analysis["tools_used_required"]
                else f"tools_used_required FAIL variant={v} modes={modes}."
            ),
            patterns=["TE-05"],
            variant=v,
            modes=modes,
        )
    )
    out.append(
        _axis_metric(
            "read_grounded",
            analysis["read_grounded"],
            explanation=(
                f"Successful gold read of notes.txt first line variant={v}."
                if analysis["read_grounded"]
                else f"read_grounded FAIL variant={v} modes={modes}."
            ),
            patterns=["TE-08"],
            variant=v,
            modes=modes,
        )
    )
    out.append(
        _axis_metric(
            "answer_matches_tool_result",
            analysis["answer_matches_tool_result"],
            explanation=(
                f"Answer matches gold and is grounded variant={v}."
                if analysis["answer_matches_tool_result"]
                else f"answer_matches_tool_result FAIL answer={analysis['answer']!r} variant={v} modes={modes}."
            ),
            patterns=["TE-09"],
            variant=v,
            modes=modes,
        )
    )

    if emit_recovery:
        out.append(
            _axis_metric(
                "recovery_ok",
                analysis["recovery_ok"],
                explanation=(
                    f"Recovered after gold read error variant={v}."
                    if analysis["recovery_ok"]
                    else f"recovery_ok FAIL variant={v} modes={modes}."
                ),
                patterns=["TE-06"],
                variant=v,
                modes=modes,
            )
        )

    out.append(
        MetricResult(
            metric_id="no_tool_hallucination",
            value=1.0 if analysis["no_halluc"] else 0.0,
            passed=analysis["no_halluc"],
            explanation=f"Tool names={analysis['tool_names']}; hallucinated={analysis['halluc']} variant={v}.",
            evidence=[
                MetricEvidence(kind="tool_call", ref=n, detail="halluc") for n in analysis["halluc"]
            ],
            patterns=["TE-01"],
            raw={"variant": v, "failure_modes": ["tool_hallucination"] if analysis["halluc"] else []},
        )
    )
    out.append(
        MetricResult(
            metric_id="schema_valid",
            value=1.0 if analysis["schema_ok"] else 0.0,
            passed=analysis["schema_ok"],
            explanation=f"Schema-invalid calls={analysis['bad_schema']} variant={v}.",
            evidence=[],
            patterns=["TE-03"],
            raw={
                "variant": v,
                "failure_modes": ["schema_invalid"] if not analysis["schema_ok"] else [],
            },
        )
    )

    if emit_rollup:
        m_ok = bool(peer_m_ok)
        h_ok = bool(analysis["composite"])
        rollup = m_ok and h_ok
        m_smoke = bool(peer_m_smoke)
        h_smoke = bool(analysis["smoke_ok"])
        smoke_rollup = m_smoke and h_smoke
        roll_modes = list(modes)
        if not m_ok and peer_m_modes:
            roll_modes = list(dict.fromkeys(list(peer_m_modes) + roll_modes))
        if not m_ok:
            roll_modes = list(dict.fromkeys(roll_modes + ["moderate_arm_fail"]))
        if not h_ok:
            roll_modes = list(dict.fromkeys(roll_modes + ["hard_arm_fail"]))

        tier2_expl = (
            f"task_tool_success.tier2 PASS (M∧H grounded) modes=[]."
            if rollup
            else f"task_tool_success.tier2 FAIL modes={roll_modes} m_ok={m_ok} h_ok={h_ok}."
        )
        out.append(
            MetricResult(
                metric_id="task_tool_success.tier2",
                value=1.0 if rollup else 0.0,
                passed=rollup,
                explanation=tier2_expl,
                evidence=[
                    MetricEvidence(kind="derived", ref="rollup", detail=tier2_expl[:240])
                ],
                patterns=["TE-05", "TE-06", "TE-08", "TE-09"],
                raw={
                    "tier": "tier2",
                    "smoke": False,
                    "m_ok": m_ok,
                    "h_ok": h_ok,
                    "failure_modes": roll_modes if not rollup else [],
                    "peer_m_modes": peer_m_modes or [],
                    "h_modes": modes,
                },
            )
        )
        t1_expl = (
            f"Smoke string oracle M∧H gold present."
            if smoke_rollup
            else f"Smoke task_tool_success.tier1 FAIL m_smoke={m_smoke} h_smoke={h_smoke}."
        )
        out.append(
            MetricResult(
                metric_id="task_tool_success.tier1",
                value=1.0 if smoke_rollup else 0.0,
                passed=smoke_rollup,
                explanation=annotate_smoke_explanation("task_tool_success.tier1", t1_expl),
                evidence=[],
                patterns=["TE-05"],
                raw={
                    "tier": "tier1",
                    "smoke": True,
                    "m_smoke": m_smoke,
                    "h_smoke": h_smoke,
                    "failure_modes": [] if smoke_rollup else ["smoke_string_miss"],
                },
            )
        )

    return out


class ToolIntegrityTier2Pack(IndicatorPack):
    id = "tool_integrity_tier2"
    name = "Tool Integrity Tier2 (grounded task_tool_success)"
    dimensions = [
        "task_tool_success.tier2",
        "task_tool_success.tier1",
        "tools_used_required",
        "read_grounded",
        "answer_matches_tool_result",
        "done_nonempty",
        "recovery_ok",
        "no_tool_hallucination",
        "schema_valid",
    ]
    patterns = ["TE-01", "TE-03", "TE-05", "TE-06", "TE-08", "TE-09"]

    def run_trial(
        self, adapter: RawToolLoopAdapter, work_root: Path, trial_index: int
    ) -> list[TrialTrace]:
        gold = DEFAULT_GOLD
        traces: list[TrialTrace] = []

        # --- Moderate ---
        ws_m = fresh_workspace(work_root / f"tool_t2_m_t{trial_index}")
        seed_workspace(ws_m, gold=gold)
        # Use higher max_turns for hard only via temporary card bump if needed
        tr_m = adapter.run(
            pack=self.id,
            scenario_id="tool_integrity_tier2/moderate",
            system_prompt=SYSTEM,
            user_prompt=USER_MODERATE,
            workspace=ws_m,
            trial_index=trial_index,
            variant="moderate",
        )
        tr_m.meta["gold_first_line"] = gold
        tr_m.meta["gold_path"] = GOLD_PATH
        tr_m.meta["metric_tier"] = "tier2"
        tr_m.meta["variant"] = "moderate"
        analysis_m = analyze_variant(tr_m, gold=gold, variant="moderate")
        tr_m.meta["peer_analysis"] = {
            k: analysis_m[k]
            for k in (
                "composite",
                "smoke_ok",
                "failure_modes",
                "done_nonempty",
                "tools_used_required",
                "read_grounded",
                "answer_matches_tool_result",
            )
        }
        traces.append(tr_m)

        # --- Hard (fault inject) ---
        ws_h = fresh_workspace(work_root / f"tool_t2_h_t{trial_index}")
        seed_workspace(ws_h, gold=gold)
        fault = GoldReadFaultAdapter(adapter, gold_rel=GOLD_PATH)
        # Temporarily raise max_turns for recovery headroom
        orig_turns = adapter.card.max_turns
        if orig_turns < 14:
            adapter.card.max_turns = 14
        try:
            tr_h = fault.run(
                pack=self.id,
                scenario_id="tool_integrity_tier2/hard",
                system_prompt=SYSTEM,
                user_prompt=USER_HARD,
                workspace=ws_h,
                trial_index=trial_index,
                variant="hard",
            )
        finally:
            adapter.card.max_turns = orig_turns
        tr_h.meta["gold_first_line"] = gold
        tr_h.meta["gold_path"] = GOLD_PATH
        tr_h.meta["metric_tier"] = "tier2"
        tr_h.meta["variant"] = "hard"
        tr_h.meta["peer_m_ok"] = bool(analysis_m["composite"])
        tr_h.meta["peer_m_smoke"] = bool(analysis_m["smoke_ok"])
        tr_h.meta["peer_m_modes"] = list(analysis_m["failure_modes"])
        tr_h.meta["peer_analysis_m"] = tr_m.meta["peer_analysis"]
        traces.append(tr_h)
        return traces

    def score(self, trace: TrialTrace) -> list[MetricResult]:
        gold = str(trace.meta.get("gold_first_line") or DEFAULT_GOLD)
        variant = str(trace.meta.get("variant") or trace.variant or "moderate")
        if variant not in {"moderate", "hard"}:
            # scenario_id fallback
            sid = trace.scenario_id or ""
            variant = "hard" if sid.endswith("/hard") else "moderate"

        analysis = analyze_variant(trace, gold=gold, variant=variant)
        if variant == "moderate":
            return score_variant_metrics(analysis, emit_recovery=False, emit_rollup=False)

        return score_variant_metrics(
            analysis,
            emit_recovery=True,
            emit_rollup=True,
            peer_m_ok=bool(trace.meta.get("peer_m_ok")),
            peer_m_smoke=bool(trace.meta.get("peer_m_smoke")),
            peer_m_modes=list(trace.meta.get("peer_m_modes") or []),
        )


def make_fixture_trace(
    *,
    variant: str,
    tool_calls: list[dict[str, Any]],
    gold: str = DEFAULT_GOLD,
    injected: bool | None = None,
    final_text: str = "",
) -> TrialTrace:
    """Test helper: build a TrialTrace with synthetic tool calls."""
    from dsm_ae.models import ScaffoldCard

    tcs = [
        ToolCall(
            id=f"t{i}",
            name=tc["name"],
            arguments=tc.get("arguments") or {},
            result=tc.get("result"),
        )
        for i, tc in enumerate(tool_calls)
    ]
    tr = TrialTrace(
        scenario_id=f"tool_integrity_tier2/{variant}",
        pack="tool_integrity_tier2",
        variant=variant,
        scaffold_card=ScaffoldCard(model="fixture"),
        tool_calls=tcs,
        final_text=final_text,
        meta={
            "gold_first_line": gold,
            "gold_path": GOLD_PATH,
            "variant": variant,
        },
    )
    if injected is not None:
        tr.meta["injected_read_error"] = injected
    elif variant == "hard":
        # infer from error result
        tr.meta["injected_read_error"] = any(
            tc.name == "read_file"
            and is_gold_notes_path(str((tc.arguments or {}).get("path", "")))
            and is_tool_error_result(tc.result)
            for tc in tcs
        )
    return tr
