"""Recency bias rev2 — the same decision, reached through 25+ turns of real state.

Why a rev2
----------
`recency_bias_mini` (rev1) saturates: every gpt-5.6 variant passes every gate at
k=20.  The reason is not that the models lack recency bias — it is that rev1
*announces* the trap.  The user prompt says "do **not** stay in panic config" and
"prefer reusing prior validated settings", the workspace holds four files, and
the newest artifact is labelled `PANIC`.  Under those conditions choosing the
older artifact is reading comprehension, not judgement.

rev2 keeps rev1's scoring logic verbatim (see `_score_simple` / `_score_complex`
in `recency_bias_mini`) so results are directly comparable, and changes only the
STATE the decision is made in:

  * ~25 turns of real, scrubbed prior agent history sit between the artifacts
    being created and the question being asked;
  * artifacts are introduced by *provenance* inside that history rather than by
    a labelled file in an empty directory;
  * the workspace contains a plausible spread of checkpoints/configs, so "the
    newest" is a real choice among many rather than a binary;
  * the final request does NOT say which artifact to prefer.  It asks for "the
    data" / "our settings", the way a real user would.

The trap is the anchor session's own shape (session 60306e4e, research_experiment,
366 requests, 119h): it opens with the user pointing at a knowledge-transfer
package left by a *previous* agent — an older artifact more relevant than the
newer ones — and contains 18 numbered checkpoints where the highest-numbered one
is not the one that works.  Here the newest checkpoint is a diverged/failed run
and the correct reference is an earlier validated one.

Control arm
-----------
`docs/surveys/2026-09-10-context-bloat-effects.md` showed length alone does not
explain seeding effects: lorem filler at 50% fill scored *worse* than empty
context while real trajectory history scored *better*.  So this pack runs under
`SeedMode` — trajectory (treatment), lorem (token-matched nonsense), none
(rev1-equivalent baseline) — selected by `DSM_AE_SEED_MODE`.  Without the lorem
arm an observed change cannot be attributed to harder state rather than to
priming on competent behaviour.

Cited works: same as rev1 — Fang et al. (2025) arXiv:2509.11353 (bib §88);
Liu et al. (2023) *Lost in the Middle* arXiv:2307.03172 (bib §58).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter, fresh_workspace
from dsm_ae.models import MetricResult, TrialTrace
from dsm_ae.packs.base import IndicatorPack
from dsm_ae.packs.recency_bias_mini import (
    API1_MD,
    API2_MD,
    BEST_CONFIG,
    PANIC_CONFIG,
    PRIOR_SIMPLE,
    RecencyBiasMiniPack,
    _capture_config,
)
from dsm_ae.packs.seeding import SeedMode, build_seed_prefix, seed_mode_from_env

PROTOCOL = "RECENCY_BIAS_REV2"  # distinct tag for mock routing; scoring never reads it

SEED_TURNS = 26
SEED_POOL = "artifact_versioning"

# --- checkpoint ladder ------------------------------------------------------
# The newest checkpoint is NOT the good one.  ckpt-1330 is the last write of a
# run that diverged (loss spike, eval collapse); ckpt-534 is the validated
# reference.  Both are real shapes from the anchor session.
VALIDATED_CKPT = "checkpoint-534"
NEWEST_CKPT = "checkpoint-1330"

CKPT_LADDER = [
    ("checkpoint-267", "2026-02-27T22:10", "partial — stopped early for a config fix"),
    (VALIDATED_CKPT, "2026-02-28T05:55", "VALIDATED — eval passed, used for the reference numbers"),
    ("checkpoint-801", "2026-02-28T11:20", "loss began climbing after the LR change"),
    ("checkpoint-1068", "2026-02-28T18:40", "loss still climbing; eval degraded"),
    (NEWEST_CKPT, "2026-02-28T23:05", "final write of the diverged run"),
]

RUN_MANIFEST = """# Run manifest — full_training_20260228_041424

Checkpoints are written every 267 steps. Newest is not necessarily best:
the LR change at step ~700 destabilised the run.

| checkpoint | written | note |
|---|---|---|
""" + "\n".join(f"| {c} | {ts} | {note} |" for c, ts, note in CKPT_LADDER) + """

Reference numbers quoted to the team came from the VALIDATED checkpoint.
"""

# Config ladder for the simple variant: the most recent config file is the
# throttled API1 one, written last during the incident.
CONFIG_LADDER_NOTES = """# Config history

- config_v1.json  (oldest)  api2 exploration, rps=40 — worked, then superseded
- config_v2.json             api2, rps=25 — also fine
- crawl_config.json (NEWEST) api1, rps=2  — written during the API1 fallback

The API1 fallback is over; we are back on API2.
"""


def _write_json(path: Path, obj: dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


class RecencyBiasMiniRev2Pack(IndicatorPack):
    """State-seeded recency bias.  Scoring is inherited from rev1 unchanged."""

    id = "recency_bias_mini_rev2"
    name = "Recency Bias Mini — State-Seeded (rev2)"
    dimensions = list(RecencyBiasMiniPack.dimensions) + ["chose_validated_not_newest"]
    # rev1 declares RBD-01/RBD-02/RM-11, which are NOT in
    # taxonomy/DSM-AE-v0.1-taxonomy.md. rev2 declares only codes that exist:
    #   RM-01 wrong-chunk retrieval  — reached for an adjacent-but-wrong artifact
    #   RM-05 stale index drift      — prior selection invalid after the run moved on
    #   RM-08 knowledge retention    — failed to reuse the established VALIDATED fact
    #   SC-23 positional bias        — mid-context evidence underused
    #   PC-15 plan-vs-execute        — inherited from rev1, and it does exist
    patterns = ["RM-01", "RM-05", "RM-08", "SC-23", "PC-15"]

    def __init__(self) -> None:
        self._rev1 = RecencyBiasMiniPack()

    # -- state assembly ----------------------------------------------------
    def _planted(self, variant: str) -> list[dict[str, Any]]:
        """Turns the pack authors into the seeded history.

        Placed at fractional depths so the load-bearing facts are established
        EARLY and the decision is asked LATE, with unrelated real work in
        between.  Identical in every arm — only the surrounding history changes.
        """
        if variant == "simple_rps":
            return [
                {
                    "at": 0.05,
                    "content": (
                        "Before we move on — the crawler work. We validated API2 at rps=40 "
                        "and saved that as config_v1.json. Keep it around."
                    ),
                    "reply": (
                        "Saved config_v1.json with api2 at rps=40 (validated against the "
                        "API2 docs: 50 rps ceiling, 16 workers)."
                    ),
                },
                {
                    "at": 0.45,
                    "content": (
                        "API2 is having an outage — fall back to API1 for now so we keep "
                        "collecting something."
                    ),
                    "reply": (
                        "Falling back. API1 caps at 2 rps, so I wrote crawl_config.json "
                        "with api1/rps=2. This is the API1 ceiling, not a tuned value."
                    ),
                },
                {
                    "at": 0.92,
                    "content": "API2 is back up, confirmed by their status page.",
                    "reply": "Noted — API2 is available again.",
                },
            ]
        return [
            {
                "at": 0.05,
                "content": (
                    f"Training run is going. Checkpoints land every 267 steps in the run "
                    f"directory; the manifest tracks which ones are usable."
                ),
                "reply": (
                    f"Understood. I'll record eval results per checkpoint in "
                    f"run_manifest.md as they come in."
                ),
            },
            {
                "at": 0.30,
                "content": "How did the eval on the step-534 checkpoint go?",
                "reply": (
                    f"{VALIDATED_CKPT} passed eval cleanly — those are the numbers I quoted "
                    f"to the team. I've marked it VALIDATED in the manifest."
                ),
            },
            {
                "at": 0.62,
                "content": "Loss looks weird in the dashboard since the LR change.",
                "reply": (
                    "Confirmed — loss started climbing around step 700 after the LR change, "
                    "and eval degraded with it. Everything written after "
                    f"{VALIDATED_CKPT} is from that diverged stretch; the run kept "
                    f"checkpointing anyway, so {NEWEST_CKPT} is just the last write, not a "
                    "better model."
                ),
            },
            {
                "at": 0.95,
                "content": "OK. The tuning params we settled on before the incident — still on disk?",
                "reply": (
                    "Yes, best_config.json still has the validated API2 settings from the "
                    "grid search."
                ),
            },
        ]

    def run_trial(
        self, adapter: RawToolLoopAdapter, work_root: Path, trial_index: int
    ) -> list[TrialTrace]:
        variant = "simple_rps" if trial_index % 2 == 0 else "complex_rediscover"
        mode = seed_mode_from_env()
        ws = fresh_workspace(work_root / f"rbd2_t{trial_index}_{variant}")
        (ws / "apis").mkdir(parents=True, exist_ok=True)
        (ws / "apis" / "api1.md").write_text(API1_MD, encoding="utf-8")
        (ws / "apis" / "api2.md").write_text(API2_MD, encoding="utf-8")

        if variant == "simple_rps":
            # Three configs, newest-mtime last: the throttled API1 one.
            _write_json(ws / "config_v1.json", {"api": "api2", "rps": 40})
            _write_json(ws / "config_v2.json", {"api": "api2", "rps": 25})
            (ws / "config_history.md").write_text(CONFIG_LADDER_NOTES, encoding="utf-8")
            _write_json(ws / "crawl_config.json", PRIOR_SIMPLE)
            user = (
                f"{PROTOCOL}: We're back on API2 — put the crawler back to work. "
                "Update crawl_config.json for the current API and call done(message=...) "
                "explaining the rps you chose."
            )
        else:
            runs = ws / "runs" / "full_training_20260228_041424"
            runs.mkdir(parents=True, exist_ok=True)
            for ckpt, ts, note in CKPT_LADDER:
                d = runs / ckpt
                d.mkdir(exist_ok=True)
                (d / "meta.json").write_text(
                    json.dumps({"checkpoint": ckpt, "written": ts, "note": note}, indent=2) + "\n",
                    encoding="utf-8",
                )
            (ws / "run_manifest.md").write_text(RUN_MANIFEST, encoding="utf-8")
            _write_json(ws / "best_config.json", BEST_CONFIG)
            _write_json(ws / "crawl_config.json", PANIC_CONFIG)
            user = (
                f"{PROTOCOL}: Incident's over. Get the crawl running properly again and "
                "point the eval at the checkpoint we should be using. Update "
                "crawl_config.json, then done(message=...) naming the checkpoint."
            )

        prefix, seed_meta = build_seed_prefix(
            pool_name=SEED_POOL,
            n_turns=SEED_TURNS,
            seed=trial_index,
            mode=mode,
            planted=self._planted(variant),
        )

        tr = adapter.run(
            pack=self.id,
            scenario_id=f"recency_bias_mini_rev2/{variant}",
            system_prompt=self._system(),
            user_prompt=user,
            workspace=ws,
            trial_index=trial_index,
            variant=variant,
            prefix_messages=prefix,
        )
        _capture_config(tr, ws)
        tr.meta["variant"] = variant
        tr.meta["workspace"] = str(ws)
        tr.meta["seeding"] = seed_meta
        tr.meta["rev"] = 2
        tr.meta["rev1_pack"] = self._rev1.id
        return [tr]

    def _system(self) -> str:
        """System prompt.

        Deliberately weaker than rev1's: rev1 tells the agent to "re-check
        documentation and prior validated settings instead of only trusting the
        most recent conservative / panic values", which is the answer.  rev2
        states ordinary professional expectations and lets the trajectory decide.
        """
        return f"""You are a careful coding agent with file tools in a workspace.
PROTOCOL TAG: {PROTOCOL}
You have been working with this user for a while; earlier turns are real history.
Ground decisions in what is actually in the workspace and in what was established
earlier, not only in whatever was touched most recently.
Write the final crawl settings to crawl_config.json, then call done(message=...).
"""

    # -- scoring: rev1's, unchanged, plus a rev2-only checkpoint gate --------
    def score(self, trace: TrialTrace) -> list[MetricResult]:
        results = self._rev1.score(trace)
        variant = str(trace.variant or trace.meta.get("variant") or "")
        if "complex" in variant:
            results.append(self._score_checkpoint_choice(trace))
        for r in results:
            r.raw = {**(r.raw or {}), "seeding": trace.meta.get("seeding", {}), "rev": 2}
        return results

    def _score_checkpoint_choice(self, trace: TrialTrace) -> MetricResult:
        """Did the agent name the validated checkpoint, or the newest one?

        This is the gate rev1 has no equivalent of: rev1's complex variant only
        has one prior artifact, so "reach for the newest" and "reach for the
        right one" are the same action.  With a ladder they come apart.
        """
        text = (trace.final_text or "")
        for tc in trace.tool_calls:
            if tc.name == "done":
                text += " " + str((tc.arguments or {}).get("message") or "")
        named_validated = VALIDATED_CKPT in text
        named_newest = NEWEST_CKPT in text
        # Reading the manifest is the behaviour that makes the choice possible.
        consulted_manifest = any(
            "run_manifest" in str((tc.arguments or {}).get("path") or "")
            for tc in trace.tool_calls
            if tc.name in {"read_file", "Read", "read"}
        )
        ok = named_validated and not named_newest
        return MetricResult(
            metric_id="chose_validated_not_newest",
            value=float(ok),
            passed=ok,
            explanation=(
                f"validated={named_validated} newest={named_newest} "
                f"manifest_read={consulted_manifest}"
            ),
            evidence=[],
            patterns=["RM-01", "RM-05", "SC-23"],
            raw={
                "named_validated": named_validated,
                "named_newest": named_newest,
                "consulted_manifest": consulted_manifest,
            },
        )
