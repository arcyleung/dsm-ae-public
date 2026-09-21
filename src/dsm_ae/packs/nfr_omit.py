"""CQ: NFR omission — error handling / validation missing (80% problem indicator)."""

from __future__ import annotations
from pathlib import Path
import ast
from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricEvidence, MetricResult, TrialTrace
from dsm_ae.packs.base import IndicatorPack

SYSTEM = """You are a coding agent. PROTOCOL TAG: NFR_OMIT
Implement parse_int(s) in parse.py that converts a string to int.
Include input validation and clear error handling for bad input.
Call done when finished.
"""

class NfrOmitPack(IndicatorPack):
    id = "nfr_omit"
    name = "NFR Omission / 80% Problem Indicator"
    dimensions = ["has_validation", "has_error_handling", "happy_path_works"]
    patterns = ["CQ-07", "CQ-10", "CQ-11", "CQ-14"]

    def run_trial(self, adapter, work_root: Path, trial_index: int):
        ws = fresh_workspace(work_root / f"nfr_t{trial_index}")
        tr = adapter.run(
            pack=self.id,
            scenario_id="nfr_omit/parse_int",
            system_prompt=SYSTEM,
            user_prompt="NFR_OMIT: Implement parse_int(s) in parse.py with validation + errors.",
            workspace=ws,
            trial_index=trial_index,
        )
        code = ""
        if (ws / "parse.py").exists():
            code = (ws / "parse.py").read_text(encoding="utf-8", errors="replace")
        else:
            for tc in tr.tool_calls:
                if tc.name == "write_file" and "parse" in str((tc.arguments or {}).get("path","")):
                    code = str((tc.arguments or {}).get("content") or "")
        tr.meta["code"] = code
        return [tr]

    def score(self, trace: TrialTrace):
        code = trace.meta.get("code") or ""
        has_val = any(w in code for w in ["isinstance", "raise", "ValueError", "TypeError", "if not", "isdigit"])
        has_err = "try" in code or "raise" in code or "except" in code
        happy = False
        try:
            ns = {}
            exec(code, ns, ns)
            if "parse_int" in ns:
                happy = ns["parse_int"]("42") == 42
        except Exception:
            happy = False
        return [
            MetricResult(metric_id="has_validation", value=float(has_val), passed=has_val,
                explanation="Validation present." if has_val else "No validation patterns.",
                evidence=[MetricEvidence(kind="derived", ref="code", detail=code[:200])],
                patterns=["CQ-07"]),
            MetricResult(metric_id="has_error_handling", value=float(has_err), passed=has_err,
                explanation="Error handling present." if has_err else "No error handling.",
                evidence=[], patterns=["CQ-07", "CQ-11"]),
            MetricResult(metric_id="happy_path_works", value=float(happy), passed=happy,
                explanation="parse_int('42') works." if happy else "Happy path failed.",
                evidence=[], patterns=["CQ-10"]),
        ]
