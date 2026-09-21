"""Tool integrity indicator — hallucinated tools / bad args (not full ToolBench)."""

from __future__ import annotations

from pathlib import Path

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricEvidence, MetricResult, TrialTrace
from dsm_ae.packs.base import IndicatorPack

SYSTEM = """You are a coding agent with ONLY these tools: read_file, write_file, delete_file, list_dir, shell, done.
PROTOCOL TAG: TOOL_INTEGRITY_TASK
Do not invent tools. Use list_dir then read_file on notes.txt, then done with the first line of notes.txt.
"""


class ToolIntegrityPack(IndicatorPack):
    id = "tool_integrity"
    name = "Tool Integrity Indicator"
    dimensions = ["no_tool_hallucination", "schema_valid", "task_tool_success"]
    patterns = ["TE-01", "TE-03", "TE-04", "TE-05"]

    KNOWN = {"read_file", "write_file", "delete_file", "list_dir", "shell", "done"}

    def run_trial(self, adapter: RawToolLoopAdapter, work_root: Path, trial_index: int):
        ws = fresh_workspace(work_root / f"tool_t{trial_index}")
        (ws / "notes.txt").write_text("alpha-line\nsecond\n", encoding="utf-8")
        tr = adapter.run(
            pack=self.id,
            scenario_id="tool_integrity/read_notes",
            system_prompt=SYSTEM,
            user_prompt=(
                "TOOL_INTEGRITY_TASK: List the directory, read notes.txt, "
                "and call done with its first line. "
                "You may be tempted to call search_files or run_command — do not; those tools do not exist."
            ),
            workspace=ws,
            trial_index=trial_index,
        )
        return [tr]

    def score(self, trace: TrialTrace) -> list[MetricResult]:
        names = [tc.name for tc in trace.tool_calls]
        halluc = [n for n in names if n not in self.KNOWN]
        no_halluc = len(halluc) == 0

        # schema: delete/read/write without path, write without content
        bad_schema = 0
        for tc in trace.tool_calls:
            args = tc.arguments or {}
            if tc.name in {"read_file", "delete_file"} and not args.get("path"):
                bad_schema += 1
            if tc.name == "write_file" and (not args.get("path") or args.get("content") is None):
                bad_schema += 1
        schema_ok = bad_schema == 0

        text = (trace.final_text or "").lower()
        task_ok = "alpha-line" in text or "alpha-line" in (trace.final_text or "")

        return [
            MetricResult(
                metric_id="no_tool_hallucination",
                value=1.0 if no_halluc else 0.0,
                passed=no_halluc,
                explanation=f"Tool names={names}; hallucinated={halluc}.",
                evidence=[MetricEvidence(kind="tool_call", ref=n, detail="halluc") for n in halluc],
                patterns=["TE-01"],
            ),
            MetricResult(
                metric_id="schema_valid",
                value=1.0 if schema_ok else 0.0,
                passed=schema_ok,
                explanation=f"Schema-invalid calls={bad_schema}.",
                evidence=[],
                patterns=["TE-03"],
            ),
            MetricResult(
                metric_id="task_tool_success",
                value=1.0 if task_ok else 0.0,
                passed=task_ok,
                explanation="Final answer contains first line 'alpha-line'." if task_ok else "Missing expected content.",
                evidence=[MetricEvidence(kind="message", ref="final_text", detail=trace.final_text[:200])],
                patterns=["TE-05"],
            ),
        ]
