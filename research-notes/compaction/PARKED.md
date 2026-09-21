# Compaction study — PARKED (2026-09-01)

Paused so the DSM-AE survey/blog defense can be refined. Resume from here;
do not treat this file as findings (those live in `FINDINGS.md`).

## Where it stands

- Process + d=3 snowball: `PROCESS.md`, `seeds.json`, `section-*.json`, `tree.json`
- Q1 (when scaffolds compact) + Q2 (SFT loss) + Q3 (split-recipe fidelity): `FINDINGS.md`
- WebUI: `/compaction` → `reports/compaction/index.html` (bind-mounted; regenerate with
  `python3 scripts/generate_compaction_ui.py`)
- Extra extracts: `section-split-recipes.json`, `section-fidelity.json`

## Open next (when unparking)

1. Decide ACM re-roll vs CaT stitch for the SFT-only continuation slice.
2. Stand up TRACE/Slipstream PRE/POST K=3–5 as a **data filter**, not just a metric.
3. Do **not** start a harder TACT pack or more (max) evals unless asked.

## Session pointer

Parent conversation also covers TACT labelling, think-max GPT-5.6 evals, and the
literature snowball (`research-notes/snowball/`). Compaction is independent of
those packs on `cleaned`.
