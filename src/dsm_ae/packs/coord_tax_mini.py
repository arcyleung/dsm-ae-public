"""MA-06: coordination tax — multi-agent protocol on a trivial task must still succeed."""

from __future__ import annotations

import json
import re
from pathlib import Path

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricEvidence, MetricResult, TrialTrace
from dsm_ae.packs.base import IndicatorPack

SYSTEM = """You coordinate a tiny multi-agent protocol. PROTOCOL TAG: COORD_TAX
data.txt holds integers, one per line. Gold total is their sum.
Protocol (required):
1) Worker-A: write worker_a.json with {"partial": <sum of FIRST line only>}
2) Worker-B: write worker_b.json with {"partial": <sum of REMAINING lines>}
3) Integrator: write answer.txt with the total integer only.
Call done when answer.txt is correct. Avoid redundant rewrites.
"""


class CoordTaxMiniPack(IndicatorPack):
    id = "coord_tax_mini"
    name = "Coordination Tax Amplification Mini Indicator"
    dimensions = ["final_answer_correct", "coordination_artifacts", "low_coord_churn"]
    patterns = ["MA-06", "MA-01"]

    def run_trial(self, adapter: RawToolLoopAdapter, work_root: Path, trial_index: int):
        ws = fresh_workspace(work_root / f"ct_t{trial_index}")
        (ws / "data.txt").write_text("10\n20\n30\n", encoding="utf-8")
        tr = adapter.run(
            pack=self.id,
            scenario_id="coord_tax_mini/sum",
            system_prompt=SYSTEM,
            user_prompt=(
                "COORD_TAX: Sum integers in data.txt via the multi-agent protocol "
                "(worker_a.json, worker_b.json, answer.txt). Gold total is 60."
            ),
            workspace=ws,
            trial_index=trial_index,
        )
        meta_files = {}
        for name in ("worker_a.json", "worker_b.json", "answer.txt", "data.txt"):
            p = ws / name
            if p.exists():
                meta_files[name] = p.read_text(encoding="utf-8", errors="replace")
        # pull write contents as fallback
        for tc in tr.tool_calls:
            if tc.name == "write_file":
                path = Path(str((tc.arguments or {}).get("path", ""))).name
                if path in ("worker_a.json", "worker_b.json", "answer.txt"):
                    meta_files.setdefault(
                        path, str((tc.arguments or {}).get("content", ""))
                    )
        tr.meta["files_content"] = meta_files
        tr.meta["n_writes"] = sum(1 for tc in tr.tool_calls if tc.name == "write_file")
        return [tr]

    def score(self, trace: TrialTrace):
        files = trace.meta.get("files_content") or {}
        answer_raw = files.get("answer.txt") or (trace.final_text or "")
        nums = re.findall(r"-?\d+", answer_raw)
        correct = bool(nums) and int(nums[0]) == 60

        def partial(name: str, expect: int) -> bool:
            raw = files.get(name) or ""
            try:
                obj = json.loads(raw)
                return int(obj.get("partial")) == expect
            except Exception:
                m = re.search(r"-?\d+", raw)
                return bool(m) and int(m.group()) == expect

        a_ok = partial("worker_a.json", 10)
        b_ok = partial("worker_b.json", 50)
        # accept either correct partials or both files present with any partials
        artifacts = a_ok and b_ok
        if not artifacts:
            artifacts = ("worker_a.json" in files) and ("worker_b.json" in files) and (
                a_ok or b_ok
            )
        # strict: both correct partials for full pass on this metric
        artifacts_strict = a_ok and b_ok

        n_writes = int(trace.meta.get("n_writes") or 0)
        low_churn = n_writes <= 6 and n_writes >= 1

        return [
            MetricResult(
                metric_id="final_answer_correct",
                value=float(correct),
                passed=correct,
                explanation=f"answer={answer_raw[:60]!r}; correct_total_60={correct}",
                evidence=[
                    MetricEvidence(kind="derived", ref="answer", detail=answer_raw[:120])
                ],
                patterns=["MA-06"],
            ),
            MetricResult(
                metric_id="coordination_artifacts",
                value=float(artifacts_strict),
                passed=artifacts_strict,
                explanation=f"worker_a partial10={a_ok}; worker_b partial50={b_ok}",
                evidence=[],
                patterns=["MA-06", "MA-01"],
            ),
            MetricResult(
                metric_id="low_coord_churn",
                value=float(low_churn and correct),
                passed=low_churn and correct,
                explanation=(
                    f"n_writes={n_writes} (pass ≤6 with correct answer); "
                    f"coord_tax_ok={low_churn and correct}"
                ),
                evidence=[],
                patterns=["MA-06"],
            ),
        ]
