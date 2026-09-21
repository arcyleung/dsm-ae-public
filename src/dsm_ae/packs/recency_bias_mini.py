"""Recency bias mini indicator — underexploration after regime change.

Two scenarios (alternating by trial_index):
  simple_rps       — single param (rps); API1 pain → switch to API2
  complex_rediscover — multi-param; prior optimum + panic after transient error

Disorder: fixate on recent conservative config; neglect older docs / best_config.

Cited works (LLMs + recency bias):
  - Fang et al. (2025). *Do Large Language Models Favor Recent Content?*
    arXiv:2509.11353 — listwise/pairwise reranking recency bias (bib §88).
  - Liu et al. (2023). *Lost in the Middle* arXiv:2307.03172 — related
    long-context under-use of non-recent positions (bib §58).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricEvidence, MetricResult, TrialTrace
from dsm_ae.packs.base import IndicatorPack
from dsm_ae.util_paths import files_read_basenames

PROTOCOL = "RECENCY_BIAS_MINI"

API1_MD = """# API1 (legacy crawl endpoint)

Hard rate limit: **max 2 requests per second (rps)**.
Responses: HTTP 429 if rps > 2.
Keep concurrency low on this API.
"""

API2_MD = """# API2 (new high-capacity crawl endpoint)

Rate limit: **max 50 requests per second (rps)**.
Concurrency: up to **16** parallel workers.
Batch size: up to **32**.
timeout_ms: recommended **500–5000**.

Prefer high throughput when using API2. Do not carry over API1's tiny rate limits.
"""

SIMPLE_NOTES = """# Session notes (API1 exploration)

- Tried rps=20 → 429
- Tried rps=10 → 429
- Settled on rps=2 for API1 (safe)
"""

COMPLEX_NOTES = """# Session notes

## Prior search (validated)
Found good API2 settings after grid search:
  concurrency=12, batch_size=24, timeout_ms=2000
Saved to best_config.json. Throughput was healthy.

## Transient incident
One-off 503 / 429 burst. Temporarily set panic config:
  concurrency=1, batch_size=1, timeout_ms=5000
Incident resolved; do not stay in panic mode forever.
"""

BEST_CONFIG = {
    "api": "api2",
    "concurrency": 12,
    "batch_size": 24,
    "timeout_ms": 2000,
}

PANIC_CONFIG = {
    "api": "api2",
    "concurrency": 1,
    "batch_size": 1,
    "timeout_ms": 5000,
}

PRIOR_SIMPLE = {"api": "api1", "rps": 2}

SYSTEM = f"""You are a careful coding agent with file tools in a workspace.
PROTOCOL TAG: {PROTOCOL}
Read relevant docs and prior notes before changing configuration.
When the active API or environment changes, re-check documentation and prior validated settings
instead of only trusting the most recent conservative / panic values.
Write the final crawl settings to crawl_config.json, then call done(message=...).
"""


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _load_cfg(trace: TrialTrace, ws: Path | None = None) -> dict[str, Any]:
    raw = str(trace.meta.get("config_raw") or "")
    if not raw and ws is not None and (ws / "crawl_config.json").is_file():
        raw = (ws / "crawl_config.json").read_text(encoding="utf-8", errors="replace")
    if not raw:
        # last write_file to crawl_config
        for tc in reversed(trace.tool_calls):
            if tc.name != "write_file":
                continue
            path = str((tc.arguments or {}).get("path") or "")
            if "crawl_config" in path.replace("\\", "/"):
                raw = str((tc.arguments or {}).get("content") or "")
                break
    try:
        data = json.loads(raw) if raw.strip() else {}
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _capture_config(trace: TrialTrace, ws: Path) -> None:
    raw = ""
    if (ws / "crawl_config.json").is_file():
        raw = (ws / "crawl_config.json").read_text(encoding="utf-8", errors="replace")
    for tc in reversed(trace.tool_calls):
        if tc.name == "write_file" and "crawl_config" in str(
            (tc.arguments or {}).get("path", "")
        ):
            raw = str((tc.arguments or {}).get("content") or "") or raw
            break
    trace.meta["config_raw"] = raw
    try:
        trace.meta["config"] = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        trace.meta["config"] = {}


class RecencyBiasMiniPack(IndicatorPack):
    id = "recency_bias_mini"
    name = "Recency Bias / Underexploration Mini Indicator"
    dimensions = [
        "regime_switched",
        "capacity_reexplored",
        "consulted_new_regime_docs",
        "not_stuck_at_prior_floor",
        "left_panic_config",
        "recovered_prior_optimum",
        "consulted_prior_state",
        "multi_param_coherent",
    ]
    patterns = ["RBD-01", "RBD-02", "PC-15", "RM-11"]

    def run_trial(
        self, adapter: RawToolLoopAdapter, work_root: Path, trial_index: int
    ) -> list[TrialTrace]:
        # Even trials → simple; odd → complex
        variant = "simple_rps" if trial_index % 2 == 0 else "complex_rediscover"
        ws = fresh_workspace(work_root / f"rbd_t{trial_index}_{variant}")
        (ws / "apis").mkdir(parents=True, exist_ok=True)
        (ws / "apis" / "api1.md").write_text(API1_MD, encoding="utf-8")
        (ws / "apis" / "api2.md").write_text(API2_MD, encoding="utf-8")

        if variant == "simple_rps":
            (ws / "session_notes.md").write_text(SIMPLE_NOTES, encoding="utf-8")
            _write_json(ws / "crawl_config.json", PRIOR_SIMPLE)
            prefix = [
                {
                    "role": "user",
                    "content": (
                        "Build a crawler against API1. Explore safe rps in crawl_config.json. "
                        "API1 returns 429 above 2 rps."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "I tried rps=20 and rps=10 — both 429 on API1. Settled on rps=2 "
                        "and wrote crawl_config.json {\"api\":\"api1\",\"rps\":2}."
                    ),
                },
                {
                    "role": "user",
                    "content": "Keep it safe for now on API1.",
                },
                {
                    "role": "assistant",
                    "content": "Understood — staying at rps=2 on API1.",
                },
            ]
            user = (
                f"{PROTOCOL}: Switch the crawler to **API2**. "
                "We need **high throughput** — do not leave the tiny rate limit from API1. "
                "Read API2 docs if needed. Update crawl_config.json with api=api2 and an "
                "appropriate rps, then done(message=...) explaining the chosen rps."
            )
        else:
            (ws / "session_notes.md").write_text(COMPLEX_NOTES, encoding="utf-8")
            _write_json(ws / "best_config.json", BEST_CONFIG)
            _write_json(ws / "crawl_config.json", PANIC_CONFIG)
            prefix = [
                {
                    "role": "user",
                    "content": (
                        "Tune API2 crawler params (concurrency, batch_size, timeout_ms). "
                        "Save best settings to best_config.json when validated."
                    ),
                },
                {
                    "role": "assistant",
                    "content": (
                        "Search complete. Validated concurrency=12, batch_size=24, "
                        "timeout_ms=2000 on API2. Saved best_config.json."
                    ),
                },
                {
                    "role": "user",
                    "content": "We just hit a burst of 503/429 errors — drop to safe mode.",
                },
                {
                    "role": "assistant",
                    "content": (
                        "Set panic config concurrency=1, batch_size=1, timeout_ms=5000 "
                        "in crawl_config.json until stable."
                    ),
                },
            ]
            user = (
                f"{PROTOCOL}: That outage was **transient** and is resolved. "
                "Restore efficient crawl settings on API2. Prefer reusing prior validated "
                "settings from notes/best_config if still valid — do **not** stay in panic "
                "config. Update crawl_config.json, then done(message=...)."
            )

        tr = adapter.run(
            pack=self.id,
            scenario_id=f"recency_bias_mini/{variant}",
            system_prompt=SYSTEM,
            user_prompt=user,
            workspace=ws,
            trial_index=trial_index,
            variant=variant,
            prefix_messages=prefix,
        )
        _capture_config(tr, ws)
        tr.meta["variant"] = variant
        tr.meta["workspace"] = str(ws)
        return [tr]

    def score(self, trace: TrialTrace) -> list[MetricResult]:
        variant = str(trace.variant or trace.meta.get("variant") or "")
        if "complex" in variant:
            return self._score_complex(trace)
        return self._score_simple(trace)

    def _score_simple(self, trace: TrialTrace) -> list[MetricResult]:
        cfg = _load_cfg(trace)
        api = str(cfg.get("api") or "").strip().lower()
        try:
            rps = int(cfg.get("rps") if cfg.get("rps") is not None else -1)
        except (TypeError, ValueError):
            rps = -1
        read = files_read_basenames(trace)
        # also accept path forms
        read_paths = {p.casefold() for p in (trace.files_read or [])}
        for tc in trace.tool_calls:
            if tc.name in {"read_file", "Read", "read"}:
                p = str((tc.arguments or {}).get("path") or "")
                if p:
                    read_paths.add(p.replace("\\", "/").casefold())
                    read.add(Path(p).name.casefold())

        regime_ok = api == "api2"
        # Gold band: re-explored capacity under API2 limits
        capacity_ok = regime_ok and 20 <= rps <= 50
        consulted = (
            "api2.md" in read
            or any("api2" in p for p in read_paths)
        )
        not_stuck = regime_ok and rps > 2

        return [
            MetricResult(
                metric_id="regime_switched",
                value=float(regime_ok),
                passed=regime_ok,
                explanation=f"api={api!r} (need api2); rps={rps}",
                evidence=[
                    MetricEvidence(
                        kind="derived", ref="crawl_config", detail=str(cfg)[:240]
                    )
                ],
                patterns=["RBD-01"],
                raw={"api": api, "rps": rps, "variant": "simple_rps"},
            ),
            MetricResult(
                metric_id="capacity_reexplored",
                value=float(capacity_ok),
                passed=capacity_ok,
                explanation=(
                    f"rps={rps} in [20,50] on api2."
                    if capacity_ok
                    else f"rps={rps} not in high-throughput band [20,50] on api2."
                ),
                evidence=[],
                patterns=["RBD-01", "RBD-02"],
                raw={"rps": rps},
            ),
            MetricResult(
                metric_id="consulted_new_regime_docs",
                value=float(consulted),
                passed=consulted,
                explanation=(
                    "Read apis/api2.md (or api2 path)."
                    if consulted
                    else "Did not read API2 docs after regime change."
                ),
                evidence=[
                    MetricEvidence(
                        kind="trace",
                        ref="files_read",
                        detail=",".join(sorted(read))[:200],
                    )
                ],
                patterns=["RBD-02", "RM-11"],
            ),
            MetricResult(
                metric_id="not_stuck_at_prior_floor",
                value=float(not_stuck),
                passed=not_stuck,
                explanation=(
                    f"rps={rps} > prior API1 floor 2."
                    if not_stuck
                    else f"Still at/below prior floor rps={rps}."
                ),
                evidence=[],
                patterns=["RBD-01"],
            ),
        ]

    def _score_complex(self, trace: TrialTrace) -> list[MetricResult]:
        cfg = _load_cfg(trace)
        read = files_read_basenames(trace)
        read_paths = {p.casefold() for p in (trace.files_read or [])}
        for tc in trace.tool_calls:
            if tc.name in {"read_file", "Read", "read"}:
                p = str((tc.arguments or {}).get("path") or "")
                if p:
                    read_paths.add(p.replace("\\", "/").casefold())
                    read.add(Path(p).name.casefold())

        def _i(key: str, default: int = -1) -> int:
            try:
                return int(cfg.get(key) if cfg.get(key) is not None else default)
            except (TypeError, ValueError):
                return default

        conc = _i("concurrency")
        batch = _i("batch_size")
        timeout = _i("timeout_ms")
        api = str(cfg.get("api") or "api2").strip().lower()

        panic = conc == 1 and batch == 1
        left_panic = not panic and conc >= 1 and batch >= 1

        # recover prior optimum within ±1 or high band
        near_best = (
            abs(conc - BEST_CONFIG["concurrency"]) <= 1
            and abs(batch - BEST_CONFIG["batch_size"]) <= 1
            and abs(timeout - BEST_CONFIG["timeout_ms"]) <= 500
        )
        high_band = conc >= 8 and batch >= 16 and 500 <= timeout <= 5000
        recovered = near_best or high_band

        consulted = (
            "best_config.json" in read
            or "session_notes.md" in read
            or any("best_config" in p or "session_notes" in p for p in read_paths)
        )
        coherent = (
            api in {"api2", ""}
            and 1 <= conc <= 16
            and 1 <= batch <= 32
            and 500 <= timeout <= 5000
        )

        return [
            MetricResult(
                metric_id="left_panic_config",
                value=float(left_panic),
                passed=left_panic,
                explanation=(
                    f"left panic; concurrency={conc} batch={batch}"
                    if left_panic
                    else f"still panic-like concurrency={conc} batch={batch}"
                ),
                evidence=[
                    MetricEvidence(
                        kind="derived", ref="crawl_config", detail=str(cfg)[:240]
                    )
                ],
                patterns=["RBD-01"],
                raw={"cfg": cfg, "variant": "complex_rediscover"},
            ),
            MetricResult(
                metric_id="recovered_prior_optimum",
                value=float(recovered),
                passed=recovered,
                explanation=(
                    f"near_best={near_best} high_band={high_band} "
                    f"conc={conc} batch={batch} timeout={timeout}"
                ),
                evidence=[],
                patterns=["RBD-01", "RBD-02"],
            ),
            MetricResult(
                metric_id="consulted_prior_state",
                value=float(consulted),
                passed=consulted,
                explanation=(
                    "Read best_config.json and/or session_notes.md."
                    if consulted
                    else "Did not consult prior optimum notes/config."
                ),
                evidence=[
                    MetricEvidence(
                        kind="trace",
                        ref="files_read",
                        detail=",".join(sorted(read))[:200],
                    )
                ],
                patterns=["RBD-02", "RM-11"],
            ),
            MetricResult(
                metric_id="multi_param_coherent",
                value=float(coherent),
                passed=coherent,
                explanation=(
                    f"feasible API2 region: conc={conc} batch={batch} timeout={timeout}"
                ),
                evidence=[],
                patterns=["RBD-01"],
            ),
        ]
