"""Erosion tier3 — multi-checkpoint erosion *slope* (CQ-26 / ISDS).

Protocol: ≥3 checkpoints on a growing product (carry-forward workspace).
Primary metric: Δerosion per checkpoint (linear slope). Fail if slope is
rising significantly even when absolute erosion remains < 0.5 (tier1 floor).

Metric id: erosion_indicator.tier3
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricEvidence, MetricResult, TrialTrace
from dsm_ae.packs.base import IndicatorPack
from dsm_ae.packs.slop_indicator import analyze_code

SEED = '''"""search product seed — multi-checkpoint growth."""
import argparse
from pathlib import Path

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--pattern", required=True)
    args = ap.parse_args()
    print("not implemented")

if __name__ == "__main__":
    main()
'''

SYSTEM = """You are a coding agent.
PROTOCOL TAG: EROSION_TIER3
Edit main.py to satisfy the checkpoint. Carry forward prior features.
Prefer maintainable structure, but complete the requested features.
Call done(message=...) when finished.
"""

# Slope fail if erosion rises by more than this per checkpoint on average
SLOPE_E_FAIL = 0.03
# Soft mass-share slope fail
SLOPE_M_FAIL = 0.05
# Absolute end-state (stricter than tier1 0.5)
ABS_E_FAIL = 0.25
# Minimum checkpoints required for slope metric
MIN_CKPTS = 3


class ErosionTier3Pack(IndicatorPack):
    id = "erosion_tier3"
    name = "Erosion Indicator Tier3 (multi-checkpoint slope)"
    dimensions = [
        "tier3_features_land",
        "erosion_indicator.tier3",
        "erosion_slope",
        "quality_stable.tier3",
    ]
    patterns = ["CQ-01", "CQ-02", "CQ-26"]

    def run_trial(
        self, adapter: RawToolLoopAdapter, work_root: Path, trial_index: int
    ) -> list[TrialTrace]:
        ws = fresh_workspace(work_root / f"erosion_t3_t{trial_index}")
        (ws / "main.py").write_text(SEED, encoding="utf-8")
        traces: list[TrialTrace] = []
        history: list[dict[str, Any]] = []

        specs = [
            (
                1,
                "EROSION_TIER3 CHECKPOINT 1: Implement recursive content search under "
                "root for --pattern (regex); print matching file paths.",
            ),
            (
                2,
                "EROSION_TIER3 CHECKPOINT 2: Add optional --langs filter and skip binary "
                "files (NUL byte heuristic).",
            ),
            (
                3,
                "EROSION_TIER3 CHECKPOINT 3: Add --exclude-globs, --max-bytes, and "
                "symlink policy (do not follow symlinks by default).",
            ),
            (
                4,
                "EROSION_TIER3 CHECKPOINT 4: Multi-pattern OR mode (--patterns), line mode "
                "with optional colored context snippets.",
            ),
        ]
        for ckpt, user in specs:
            tr = adapter.run(
                pack=self.id,
                scenario_id=f"erosion_tier3/c{ckpt}",
                system_prompt=SYSTEM,
                user_prompt=user,
                workspace=ws,
                trial_index=trial_index,
                variant=f"c{ckpt}",
            )
            code = (ws / "main.py").read_text(encoding="utf-8") if (ws / "main.py").exists() else ""
            cm = analyze_code(code)
            history.append({"ckpt": ckpt, "metrics": cm})
            tr.meta["code"] = code
            tr.meta["checkpoint"] = ckpt
            tr.meta["code_metrics"] = cm
            tr.meta["history"] = list(history)
            tr.meta["metric_tier"] = "tier3"
            traces.append(tr)
        return traces

    def score(self, trace: TrialTrace) -> list[MetricResult]:
        code = trace.meta.get("code") or ""
        cm = trace.meta.get("code_metrics") or analyze_code(code)
        ckpt = int(trace.meta.get("checkpoint") or 1)
        history = trace.meta.get("history") or [{"ckpt": ckpt, "metrics": cm}]

        features_ok = _tier3_features(code, ckpt)
        slope_info = compute_erosion_slope(history)

        # On early checkpoints, slope may be provisional; still emit metrics.
        e_end = float(cm.get("erosion") or 0.0)
        mms = float(cm.get("max_mass_share") or 0.0)
        max_cc = int(cm.get("max_cc") or 0)
        # max_mass_share alone is high for any 2-helper modular CLI — require hot CC too
        abs_fail = e_end > ABS_E_FAIL or (mms > 0.55 and max_cc > 10)
        slope_fail = bool(slope_info.get("slope_fail"))
        # Primary: fail if slope rising significantly OR absolute end bad.
        # Slope is only decisive once we have ≥ MIN_CKPTS points; earlier ckpts
        # use absolute-only so modular short code does not false-FAIL.
        if len(history) < MIN_CKPTS:
            tier3_fail = abs_fail
        else:
            tier3_fail = slope_fail or abs_fail
        # Value: combine absolute erosion with normalized positive slope
        slope_e = float(slope_info.get("slope_e") or 0.0)
        tier3_value = min(1.0, max(e_end, max(0.0, slope_e) / max(SLOPE_E_FAIL, 1e-6) * 0.5))
        tier3_ok = not tier3_fail

        # quality_stable.tier3: real stability — not rising across checkpoints
        stable_ok = (not slope_fail) and (
            e_end <= float(slope_info.get("e_first") or e_end) + 0.05
        )
        # On ckpt < MIN_CKPTS, mark stable as pass placeholder if no rise yet
        if len(history) < MIN_CKPTS:
            stable_ok = not slope_fail

        return [
            MetricResult(
                metric_id="tier3_features_land",
                value=1.0 if features_ok else 0.0,
                passed=features_ok,
                explanation=f"Tier3 feature gate ckpt={ckpt}: ok={features_ok}.",
                evidence=[MetricEvidence(kind="derived", ref="code", detail=code[:200])],
                patterns=["CQ-10"],
                raw={"ckpt": ckpt},
            ),
            MetricResult(
                metric_id="erosion_indicator.tier3",
                value=tier3_value,
                passed=tier3_ok,
                explanation=(
                    f"Tier3 slope-aware erosion={tier3_value:.3f} "
                    f"(abs_e={e_end:.3f}, slope_e={slope_e:.4f}/ckpt, "
                    f"slope_fail={slope_fail}, abs_fail={abs_fail}). "
                    f"n_ckpts={len(history)}, max_cc={cm.get('max_cc')}. "
                    f"Fail if slope_e>{SLOPE_E_FAIL} even when abs_e<0.5."
                ),
                evidence=[
                    MetricEvidence(
                        kind="derived",
                        ref="slope",
                        detail=str(slope_info),
                    )
                ],
                patterns=["CQ-01", "CQ-26"],
                raw={
                    "tier": "tier3",
                    "smoke": False,
                    "metrics": cm,
                    "slope": slope_info,
                    "history_erosions": slope_info.get("erosions"),
                },
            ),
            MetricResult(
                metric_id="erosion_slope",
                value=max(0.0, slope_e),
                passed=not slope_fail,
                explanation=(
                    f"Erosion slope={slope_e:.4f} per checkpoint "
                    f"(fail if >{SLOPE_E_FAIL} with material rise). "
                    f"series={slope_info.get('erosions')}."
                ),
                evidence=[],
                patterns=["CQ-26"],
                raw=slope_info,
            ),
            MetricResult(
                metric_id="quality_stable.tier3",
                value=1.0 if stable_ok else 0.0,
                passed=stable_ok,
                explanation=(
                    "Quality stable across multi-ckpt trajectory (no material erosion rise)."
                    if stable_ok
                    else "Quality unstable: erosion rising across checkpoints."
                ),
                evidence=[],
                patterns=["CQ-01", "CQ-02", "CQ-26"],
                raw=slope_info,
            ),
        ]


def compute_erosion_slope(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute Δerosion and Δmax_mass_share slopes across checkpoint history."""
    erosions: list[float] = []
    mass_shares: list[float] = []
    max_ccs: list[int] = []
    for h in history:
        m = h.get("metrics") or {}
        erosions.append(float(m.get("erosion") or 0.0))
        mass_shares.append(float(m.get("max_mass_share") or 0.0))
        max_ccs.append(int(m.get("max_cc") or 0))

    n = len(erosions)
    if n < 2:
        return {
            "erosions": erosions,
            "mass_shares": mass_shares,
            "max_ccs": max_ccs,
            "slope_e": 0.0,
            "slope_m": 0.0,
            "slope_fail": False,
            "e_first": erosions[0] if erosions else 0.0,
            "e_last": erosions[-1] if erosions else 0.0,
            "n": n,
        }

    # Simple first-last slope; also check linear regression-ish mid if n>=3
    slope_e = (erosions[-1] - erosions[0]) / (n - 1)
    slope_m = (mass_shares[-1] - mass_shares[0]) / (n - 1)

    # Material rise: last > first by epsilon
    material_e = erosions[-1] > erosions[0] + 0.02
    material_m = mass_shares[-1] > mass_shares[0] + 0.1

    slope_fail = (slope_e > SLOPE_E_FAIL and material_e) or (
        slope_m > SLOPE_M_FAIL and material_m and mass_shares[-1] > mass_shares[0] + 0.1
    )

    # Also fail if any consecutive step jumps hard (patch spiral)
    for i in range(1, n):
        if erosions[i] - erosions[i - 1] > 0.15:
            slope_fail = True
            break
        if max_ccs[i] - max_ccs[i - 1] >= 6 and mass_shares[i] >= mass_shares[i - 1]:
            # complexity concentration spiral without dispersion
            if n >= MIN_CKPTS:
                slope_fail = True
                break

    return {
        "erosions": erosions,
        "mass_shares": mass_shares,
        "max_ccs": max_ccs,
        "slope_e": slope_e,
        "slope_m": slope_m,
        "slope_fail": slope_fail,
        "e_first": erosions[0],
        "e_last": erosions[-1],
        "n": n,
    }


def _tier3_features(code: str, ckpt: int) -> bool:
    low = code.lower()
    if ckpt == 1:
        return ("re" in low or "regex" in low) and (
            "rglob" in code or "os.walk" in code or "path" in low
        )
    if ckpt == 2:
        return "lang" in low or "suffix" in low or "binary" in low or "nul" in low
    if ckpt == 3:
        return "exclude" in low or "glob" in low or "max" in low
    # ckpt 4+
    return "pattern" in low and ("context" in low or "line" in low or "or" in low)


def synthetic_rising_erosion_history() -> list[dict[str, Any]]:
    """History where absolute erosion stays <0.5 but slope rises → tier3 fail."""
    return [
        {"ckpt": 1, "metrics": {"erosion": 0.0, "max_mass_share": 0.3, "max_cc": 4}},
        {"ckpt": 2, "metrics": {"erosion": 0.12, "max_mass_share": 0.4, "max_cc": 7}},
        {"ckpt": 3, "metrics": {"erosion": 0.28, "max_mass_share": 0.55, "max_cc": 11}},
        {"ckpt": 4, "metrics": {"erosion": 0.42, "max_mass_share": 0.7, "max_cc": 16}},
    ]


def synthetic_flat_erosion_history() -> list[dict[str, Any]]:
    return [
        {"ckpt": 1, "metrics": {"erosion": 0.0, "max_mass_share": 0.35, "max_cc": 5}},
        {"ckpt": 2, "metrics": {"erosion": 0.0, "max_mass_share": 0.32, "max_cc": 5}},
        {"ckpt": 3, "metrics": {"erosion": 0.0, "max_mass_share": 0.30, "max_cc": 4}},
        {"ckpt": 4, "metrics": {"erosion": 0.0, "max_mass_share": 0.28, "max_cc": 4}},
    ]
