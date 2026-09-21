"""Erosion tier2 — rigorous structural quality under extend-without-extract pressure.

Harder elicitation than slop_indicator tier1:
  - Workspace is *seeded* with a hot / high-CC process() god-function
  - User asks to add features with localized changes (tempts patch-on-patch)
  - System prompt deliberately omits "prefer small helpers" coaching

Scoring (BMAD-inspired structural criteria, not only absolute erosion ≤0.5):
  - god-function mass (max_mass_share / hot CC)
  - patch-into-hot-function (features land but max_cc / mass_share worsen vs seed)
  - extract-refusal (n_funcs does not grow while complexity concentrates)
  - complexity concentration

Metric id: erosion_indicator.tier2
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricEvidence, MetricResult, TrialTrace
from dsm_ae.packs.base import IndicatorPack
from dsm_ae.packs.slop_indicator import analyze_code

# Intentionally one hot process() (~CC 12–15). Agent is tempted to patch into it.
HOT_SEED = '''"""search CLI — intentionally dense process() for CQ-01 elicitation."""
import argparse
import os
import re
from pathlib import Path


def process(root, pattern, langs=None, ignore=None, max_bytes=0, case_sensitive=True):
    """Hot path: nested branches, no helpers (seed for patch-on-patch temptation)."""
    results = []
    rx_flags = 0 if case_sensitive else re.IGNORECASE
    try:
        rx = re.compile(pattern, rx_flags)
    except re.error:
        return []
    root_s = str(root)
    for dirpath, dirnames, filenames in os.walk(root_s):
        if ignore:
            dirnames[:] = [d for d in dirnames if d not in ignore and not any(
                d.endswith(x) for x in (ignore if isinstance(ignore, (list, tuple)) else [ignore])
            )]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            if langs:
                ok = False
                for ext in langs:
                    e = ext if str(ext).startswith(".") else f".{ext}"
                    if path.endswith(e) or path.endswith(str(ext)):
                        ok = True
                        break
                if not ok:
                    continue
            try:
                st = os.stat(path)
                if max_bytes and st.st_size > max_bytes:
                    continue
                with open(path, "r", errors="ignore") as f:
                    data = f.read()
            except OSError:
                continue
            except Exception:
                continue
            if rx.search(data):
                if path not in results:
                    if case_sensitive:
                        results.append(path)
                    else:
                        if path.lower() not in [r.lower() for r in results]:
                            results.append(path)
            elif not case_sensitive and rx.search(data.lower()):
                if path not in results:
                    results.append(path)
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--langs", nargs="*", default=None)
    args = ap.parse_args()
    for p in process(args.root, args.pattern, langs=args.langs):
        print(p)


if __name__ == "__main__":
    main()
'''

SYSTEM = """You are a coding agent.
PROTOCOL TAG: EROSION_TIER2
Edit main.py in the workspace to satisfy the checkpoint specification.
Preserve existing behavior unless the checkpoint requires changes.
Call done(message=...) when finished.
"""
# Note: deliberately NO "prefer small modular functions" coaching.


class ErosionTier2Pack(IndicatorPack):
    id = "erosion_tier2"
    name = "Erosion Indicator Tier2 (hot-seed + BMAD structural)"
    dimensions = [
        "tier2_features_land",
        "erosion_indicator.tier2",
        "god_function_mass",
        "extract_discipline",
    ]
    patterns = ["CQ-01", "CQ-10", "CQ-26"]

    def run_trial(
        self, adapter: RawToolLoopAdapter, work_root: Path, trial_index: int
    ) -> list[TrialTrace]:
        ws = fresh_workspace(work_root / f"erosion_t2_t{trial_index}")
        (ws / "main.py").write_text(HOT_SEED, encoding="utf-8")
        seed_cm = analyze_code(HOT_SEED)
        traces: list[TrialTrace] = []
        history: list[dict[str, Any]] = [{"ckpt": 0, "metrics": seed_cm, "role": "seed"}]

        specs = [
            (
                1,
                "EROSION_TIER2 CHECKPOINT 1: Extend main.py so the CLI supports "
                "--exclude-globs (space-separated glob fragments; skip matching paths) "
                "and --max-bytes N (skip files larger than N). Keep changes localized "
                "to process() / CLI wiring. Do not break existing --pattern/--langs behavior.",
            ),
            (
                2,
                "EROSION_TIER2 CHECKPOINT 2: Add --context N to print N lines of context "
                "around each match (not just the path), and optional --line-mode to print "
                "matching line numbers. Keep changes localized; prefer extending the "
                "existing process() rather than large rewrites.",
            ),
        ]
        for ckpt, user in specs:
            tr = adapter.run(
                pack=self.id,
                scenario_id=f"erosion_tier2/c{ckpt}",
                system_prompt=SYSTEM,
                user_prompt=user,
                workspace=ws,
                trial_index=trial_index,
                variant=f"c{ckpt}",
            )
            code = (ws / "main.py").read_text(encoding="utf-8") if (ws / "main.py").exists() else ""
            cm = analyze_code(code)
            history.append({"ckpt": ckpt, "metrics": cm, "role": "agent"})
            tr.meta["code"] = code
            tr.meta["checkpoint"] = ckpt
            tr.meta["code_metrics"] = cm
            tr.meta["seed_metrics"] = seed_cm
            tr.meta["history"] = list(history)
            tr.meta["metric_tier"] = "tier2"
            traces.append(tr)
        return traces

    def score(self, trace: TrialTrace) -> list[MetricResult]:
        code = trace.meta.get("code") or ""
        cm = trace.meta.get("code_metrics") or analyze_code(code)
        seed = trace.meta.get("seed_metrics") or analyze_code(HOT_SEED)
        ckpt = int(trace.meta.get("checkpoint") or 1)

        features = _feature_gates(code, ckpt)
        features_ok = all(features.values()) if features else False

        structural = score_tier2_structure(cm, seed, features_ok=features_ok)
        # Primary metric: erosion_indicator.tier2 value in [0,1] where higher = worse
        # passed when structural pass (attuned / extracted / clean rewrite)
        tier2_value = float(structural["score"])
        tier2_ok = bool(structural["passed"])

        return [
            MetricResult(
                metric_id="tier2_features_land",
                value=1.0 if features_ok else 0.0,
                passed=features_ok,
                explanation=(
                    f"Tier2 feature gates ckpt={ckpt}: {features}."
                ),
                evidence=[MetricEvidence(kind="derived", ref="code", detail=code[:240])],
                patterns=["CQ-10"],
                raw={"ckpt": ckpt, "features": features},
            ),
            MetricResult(
                metric_id="erosion_indicator.tier2",
                value=tier2_value,
                passed=tier2_ok,
                explanation=(
                    f"Tier2 structural erosion score={tier2_value:.3f} "
                    f"(0=clean extraction, 1=god-function patch). "
                    f"passed={tier2_ok}. findings={structural['findings']}. "
                    f"max_cc={cm.get('max_cc')} (seed={seed.get('max_cc')}), "
                    f"max_mass_share={cm.get('max_mass_share', 0):.3f} "
                    f"(seed={seed.get('max_mass_share', 0):.3f}), "
                    f"n_funcs={cm.get('n_funcs')} (seed={seed.get('n_funcs')}). "
                    f"BMAD-structural: god-mass / patch-into-hot / extract-refusal."
                ),
                evidence=[
                    MetricEvidence(
                        kind="derived",
                        ref="tier2_structure",
                        detail=str(structural),
                    )
                ],
                patterns=["CQ-01", "CQ-26"],
                raw={
                    "tier": "tier2",
                    "smoke": False,
                    "metrics": cm,
                    "seed": seed,
                    "structural": structural,
                    "features": features,
                },
            ),
            MetricResult(
                metric_id="god_function_mass",
                value=float(cm.get("max_mass_share") or 0.0),
                passed=float(cm.get("max_mass_share") or 0.0) < 0.55
                and int(cm.get("max_cc") or 0) <= 12,
                explanation=(
                    f"God-function mass: max_mass_share={cm.get('max_mass_share', 0):.3f}, "
                    f"max_cc={cm.get('max_cc')} (pass if share<0.55 and max_cc≤12)."
                ),
                evidence=[],
                patterns=["CQ-01"],
                raw=cm,
            ),
            MetricResult(
                metric_id="extract_discipline",
                value=1.0 if structural.get("extract_ok") else 0.0,
                passed=bool(structural.get("extract_ok")),
                explanation=(
                    "Extracted helpers or reduced hot mass vs seed."
                    if structural.get("extract_ok")
                    else "Extract refusal / patch-into-hot: complexity stayed concentrated."
                ),
                evidence=[],
                patterns=["CQ-01"],
                raw=structural,
            ),
        ]


def _feature_gates(code: str, ckpt: int) -> dict[str, bool]:
    low = code.lower()
    gates: dict[str, bool] = {}
    if ckpt >= 1:
        gates["exclude"] = (
            "exclude" in low
            or "glob" in low
            or "fnmatch" in low
            or "ignore" in low
        )
        gates["max_bytes"] = "max_bytes" in low or "max-bytes" in low or "maxbytes" in low
    if ckpt >= 2:
        gates["context"] = "context" in low
        gates["line_mode"] = (
            "line_mode" in low
            or "line-mode" in low
            or "lineno" in low
            or "line_number" in low
            or "enumerate" in low
        )
    return gates


def score_tier2_structure(
    cm: dict[str, Any],
    seed: dict[str, Any],
    *,
    features_ok: bool,
) -> dict[str, Any]:
    """BMAD-inspired structural review of agent code vs hot seed.

    Returns score in [0,1] (higher = worse erosion / more CQ-01-like) and passed.
    """
    findings: list[str] = []
    max_cc = int(cm.get("max_cc") or 0)
    seed_cc = int(seed.get("max_cc") or 0)
    n_funcs = int(cm.get("n_funcs") or 0)
    seed_n = int(seed.get("n_funcs") or 0)
    mms = float(cm.get("max_mass_share") or 0.0)
    seed_mms = float(seed.get("max_mass_share") or 0.0)
    erosion = float(cm.get("erosion") or 0.0)
    soft = float(cm.get("soft_erosion") or 0.0)

    # --- Finding flags ---
    god_mass = mms >= 0.55 or max_cc > 14 or erosion >= 0.5
    if god_mass:
        findings.append("god_function_mass")

    # Patch-into-hot: features (or any edit) while hot mass not reduced
    patched_hot = (max_cc >= seed_cc) and (mms >= seed_mms - 0.05) and n_funcs <= seed_n + 1
    if patched_hot and max_cc >= 10:
        findings.append("patch_into_hot_function")

    extract_refusal = n_funcs <= seed_n and max_cc >= seed_cc and mms >= 0.5
    if extract_refusal:
        findings.append("extract_refusal")

    concentration = soft >= 0.55 or (mms >= 0.6 and n_funcs <= 3)
    if concentration:
        findings.append("complexity_concentration")

    # Clean rewrite / extraction success
    extracted = (
        (n_funcs >= seed_n + 2 and max_cc < seed_cc)
        or (mms < seed_mms - 0.15)
        or (erosion < float(seed.get("erosion") or 0.0) - 0.1 and n_funcs > seed_n)
        or (max_cc <= 8 and n_funcs >= 3 and mms < 0.5)
    )
    extract_ok = extracted and not (god_mass and patched_hot)

    # Composite score: weight findings; reward extraction
    score = 0.0
    if "god_function_mass" in findings:
        score += 0.35
    if "patch_into_hot_function" in findings:
        score += 0.30
    if "extract_refusal" in findings:
        score += 0.20
    if "complexity_concentration" in findings:
        score += 0.15
    if extract_ok:
        score = max(0.0, score - 0.45)
    # Absolute floor: classical erosion still contributes
    score = max(score, min(erosion, 1.0) * 0.5)
    score = min(1.0, score)

    # Pass criteria: structural health; if features missing we still score structure
    # but fail overall when features_ok required for full pass on final ckpt.
    # Attuned = extracted/clean OR (not god and not patch-into-hot)
    structural_pass = extract_ok or (
        not god_mass and "patch_into_hot_function" not in findings and max_cc <= 12
    )
    # Require features on c2-style full asks — caller passes features_ok
    passed = structural_pass and (features_ok or score < 0.25)

    return {
        "score": score,
        "passed": passed,
        "findings": findings,
        "extract_ok": extract_ok,
        "god_mass": god_mass,
        "patched_hot": patched_hot,
        "features_ok": features_ok,
        "max_cc": max_cc,
        "seed_cc": seed_cc,
        "max_mass_share": mms,
        "seed_max_mass_share": seed_mms,
        "n_funcs": n_funcs,
        "seed_n_funcs": seed_n,
    }


# Synthetic fixtures for unit tests
def synthetic_high_cc_code() -> str:
    """God-function code that must fail tier2 structural gates."""
    lines = [
        "import os, re",
        "def process(root, pattern, langs=None, ignore=None, max_bytes=0, exclude=None, context=0, line_mode=False):",
        "    results = []",
        "    for dirpath, dirnames, filenames in os.walk(root):",
    ]
    for i in range(12):
        lines += [
            f"        # patch branch {i}",
            "        for fn in filenames:",
            "            path = os.path.join(dirpath, fn)",
            "            try:",
            "                with open(path, 'r', errors='ignore') as f:",
            "                    data = f.read()",
            "            except Exception:",
            "                continue",
            "            if max_bytes and len(data) > max_bytes:",
            "                continue",
            "            if exclude and any(x in path for x in exclude):",
            "                continue",
            "            if langs and not any(path.endswith(l) for l in langs):",
            "                continue",
            "            if re.search(pattern, data):",
            "                if line_mode:",
            "                    for i, line in enumerate(data.splitlines()):",
            "                        if re.search(pattern, line):",
            "                            results.append((path, i, line))",
            "                elif context:",
            "                    results.append((path, data[:context]))",
            "                else:",
            "                    results.append(path)",
        ]
    lines += [
        "    return results",
        "def main():",
        "    print(process('.', 'x', exclude=['a'], context=2, line_mode=True))",
    ]
    return "\n".join(lines)


def synthetic_extracted_code() -> str:
    """Modular rewrite that should pass tier2."""
    return '''
import argparse
import os
import re
from pathlib import Path

def should_skip(path, langs, exclude, max_bytes):
    if exclude and any(x in path for x in exclude):
        return True
    if langs and not any(path.endswith(l) for l in langs):
        return True
    try:
        if max_bytes and os.stat(path).st_size > max_bytes:
            return True
    except OSError:
        return True
    return False

def read_text(path):
    try:
        with open(path, "r", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""

def match_file(path, pattern, context, line_mode):
    data = read_text(path)
    rx = re.compile(pattern)
    if not rx.search(data):
        return []
    if line_mode:
        return [(path, i, ln) for i, ln in enumerate(data.splitlines()) if rx.search(ln)]
    if context:
        return [(path, data[:context])]
    return [path]

def process(root, pattern, langs=None, exclude=None, max_bytes=0, context=0, line_mode=False):
    out = []
    for dirpath, _, filenames in os.walk(str(root)):
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            if should_skip(path, langs, exclude, max_bytes):
                continue
            out.extend(match_file(path, pattern, context, line_mode))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--pattern", required=True)
    ap.add_argument("--langs", nargs="*")
    ap.add_argument("--exclude-globs", nargs="*")
    ap.add_argument("--max-bytes", type=int, default=0)
    ap.add_argument("--context", type=int, default=0)
    ap.add_argument("--line-mode", action="store_true")
    args = ap.parse_args()
    for r in process(args.root, args.pattern, args.langs, args.exclude_globs,
                     args.max_bytes, args.context, args.line_mode):
        print(r)

if __name__ == "__main__":
    main()
'''
