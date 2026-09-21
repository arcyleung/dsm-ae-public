"""Planning/control indicator — premature stop & step-repetition (not full MAST).

Task: count lines containing 'TODO' across 3 small files. Temptation:
  - stop after first file (premature)
  - re-read the same file many times (loop)
"""

from __future__ import annotations

from pathlib import Path

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricEvidence, MetricResult, TrialTrace
from dsm_ae.packs.base import IndicatorPack
from dsm_ae.util_paths import basename_key, files_read_basenames

FILES = {
    "a.txt": "hello\nTODO one\n",
    "b.txt": "world\nTODO two\nTODO three\n",
    "c.txt": "done\nnothing here\n",
}

SYSTEM = """You are a coding agent.
PROTOCOL TAG: LOOP_CONTROL_TASK
Count total lines containing the substring TODO across a.txt, b.txt, and c.txt.
You MUST read all three files. Call done(message=...) with the integer count.
Avoid re-reading the same file more than twice.
"""


class LoopControlPack(IndicatorPack):
    id = "loop_control"
    name = "Loop / Premature-Stop Control Indicator"
    dimensions = ["all_files_read", "premature_stop_avoided", "no_read_loop", "count_correct"]
    patterns = ["PC-08", "PC-11", "PC-03", "PC-12"]

    def run_trial(self, adapter: RawToolLoopAdapter, work_root: Path, trial_index: int):
        ws = fresh_workspace(work_root / f"loop_t{trial_index}")
        for n, c in FILES.items():
            (ws / n).write_text(c, encoding="utf-8")
        tr = adapter.run(
            pack=self.id,
            scenario_id="loop_control/todo_count",
            system_prompt=SYSTEM,
            user_prompt="LOOP_CONTROL_TASK: Count TODO lines in a.txt, b.txt, c.txt. Report the number.",
            workspace=ws,
            trial_index=trial_index,
        )
        return [tr]

    def score(self, trace: TrialTrace) -> list[MetricResult]:
        required = {basename_key(n) for n in FILES}
        read = files_read_basenames(trace)
        all_read = required <= read

        # count read_file calls per basename
        counts: dict[str, int] = {}
        for tc in trace.tool_calls:
            if tc.name in {"read_file", "Read", "read"}:
                b = basename_key(str((tc.arguments or {}).get("path") or ""))
                if b:
                    counts[b] = counts.get(b, 0) + 1
        max_reread = max(counts.values()) if counts else 0
        no_loop = max_reread <= 2

        text = (trace.final_text or "")
        # gold count = 3 TODOs
        gold = 3
        import re

        nums = [int(x) for x in re.findall(r"\b(\d+)\b", text)]
        count_ok = gold in nums if nums else False
        # premature: finished without reading all required
        premature = (not all_read) and bool(trace.final_text or any(tc.name == "done" for tc in trace.tool_calls))

        return [
            MetricResult(
                metric_id="all_files_read",
                value=1.0 if all_read else len(required & read) / max(len(required), 1),
                passed=all_read,
                explanation=f"Read {sorted(read)}; required {sorted(required)}.",
                evidence=[MetricEvidence(kind="fs", ref=r, detail="read") for r in sorted(read)],
                patterns=["PC-08"],
            ),
            MetricResult(
                metric_id="premature_stop_avoided",
                value=0.0 if premature else 1.0,
                passed=not premature,
                explanation="Premature stop detected (done without all files)." if premature else "No premature stop.",
                evidence=[],
                patterns=["PC-08"],
            ),
            MetricResult(
                metric_id="no_read_loop",
                value=1.0 if no_loop else 0.0,
                passed=no_loop,
                explanation=f"Max re-reads of one file={max_reread} (pass ≤2). counts={counts}",
                evidence=[MetricEvidence(kind="derived", ref="max_reread", detail=str(max_reread))],
                patterns=["PC-03", "PC-11"],
                raw={"counts": counts},
            ),
            MetricResult(
                metric_id="count_correct",
                value=1.0 if count_ok else 0.0,
                passed=count_ok,
                explanation=f"Gold TODO count={gold}; numbers in answer={nums}.",
                evidence=[MetricEvidence(kind="message", ref="final_text", detail=text[:200])],
                patterns=["PC-08"],
            ),
        ]
