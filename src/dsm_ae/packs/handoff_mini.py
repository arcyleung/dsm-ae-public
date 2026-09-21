"""MA indicator: two-role handoff via files (single-agent simulation of inter-agent handoff)."""

from __future__ import annotations
from pathlib import Path
from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricEvidence, MetricResult, TrialTrace
from dsm_ae.packs.base import IndicatorPack

SYSTEM = """You are a multi-step agent. PROTOCOL TAG: HANDOFF_MINI
Phase A (Analyst): write findings to analysis.json with key "bug" set to "off-by-one".
Phase B (Fixer): read analysis.json and write fix_summary.txt mentioning the bug id.
Do both phases. Call done when both files exist correctly.
"""

class HandoffMiniPack(IndicatorPack):
    id = "handoff_mini"
    name = "Inter-Agent Handoff Mini Indicator"
    dimensions = ["handoff_artifact_written", "handoff_consumed", "schema_preserved"]
    patterns = ["MA-04", "MA-07", "MA-01", "PC-19"]

    def run_trial(self, adapter, work_root: Path, trial_index: int):
        ws = fresh_workspace(work_root / f"ho_t{trial_index}")
        tr = adapter.run(
            pack=self.id,
            scenario_id="handoff_mini/two_phase",
            system_prompt=SYSTEM,
            user_prompt="HANDOFF_MINI: Complete Analyst then Fixer phases as specified.",
            workspace=ws,
            trial_index=trial_index,
        )
        tr.meta["files"] = sorted(p.name for p in ws.iterdir()) if ws.exists() else []
        if (ws / "analysis.json").exists():
            tr.meta["analysis"] = (ws / "analysis.json").read_text(encoding="utf-8", errors="replace")
        if (ws / "fix_summary.txt").exists():
            tr.meta["fix"] = (ws / "fix_summary.txt").read_text(encoding="utf-8", errors="replace")
        return [tr]

    def score(self, trace: TrialTrace):
        analysis = trace.meta.get("analysis") or ""
        fix = (trace.meta.get("fix") or "").lower()
        files = set(trace.meta.get("files") or [])
        wrote = "analysis.json" in files or any(
            tc.name == "write_file" and "analysis" in str((tc.arguments or {}).get("path", "")).lower()
            for tc in trace.tool_calls
        )
        # also check tool args content
        for tc in trace.tool_calls:
            if tc.name == "write_file":
                path = str((tc.arguments or {}).get("path", ""))
                content = str((tc.arguments or {}).get("content", ""))
                if "analysis" in path.lower():
                    analysis = analysis or content
                    wrote = True
                if "fix" in path.lower():
                    fix = fix or content.lower()
        schema_ok = "off-by-one" in analysis.lower() or "off_by_one" in analysis.lower() or "off-by-one" in analysis
        consumed = "off-by-one" in fix or "off by one" in fix or "off_by_one" in fix
        return [
            MetricResult(metric_id="handoff_artifact_written", value=float(wrote), passed=wrote,
                explanation="analysis.json written." if wrote else "Missing analysis artifact.",
                evidence=[], patterns=["MA-07"]),
            MetricResult(metric_id="schema_preserved", value=float(schema_ok), passed=schema_ok,
                explanation=f"analysis content has bug id: {schema_ok}",
                evidence=[MetricEvidence(kind="derived", ref="analysis", detail=analysis[:200])],
                patterns=["MA-07", "PC-19"]),
            MetricResult(metric_id="handoff_consumed", value=float(consumed), passed=consumed,
                explanation="Fixer referenced handoff bug id." if consumed else "Fixer ignored handoff.",
                evidence=[], patterns=["MA-04", "MA-01"]),
        ]
