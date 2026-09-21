# Snowball subagent contract

Read `research-notes/snowball/PROCESS.md` first.

You expand **only your assigned seeds** to depth 3.

## Tools

Use `web_search` and `open_page` / `open_page_with_find`. For arXiv papers open `https://arxiv.org/abs/ID` then `https://arxiv.org/pdf/ID` or html. Extract **References** / Related Work cites that are about **agentic ill-behaviours, coding agents, tool use, agent alignment, or agent eval**.

Do **not** invent citations. If you cannot open a paper, record the seed node only and note `fetch_failed`.

## Caps

Depth 1 ≤ 8 children per seed. Depth 2 ≤ 5. Depth 3 ≤ 3. Skip pretraining-only and generic NLP cites.

## Output file (JSON only, valid JSON)

Write exactly the path given in your dispatch.

```json
{
  "section": "A",
  "agent": "snowball-A",
  "nodes": [],
  "edges": [],
  "gaps": []
}
```

Node required keys: `id`, `title`, `year`, `url`, `depth`, `seed_bib` (int or null), `behaviours` (string[]), `pack` (existing pack id or `"unknown"`), `syndrome` (string or null), `benchmark_measures` (true|false|null), `benchmark_name` (string or null), `notes`.

Edge: `from`, `to`, `depth` (hop that created the child), `why`.

`id` = `arxiv:YYMM.NNNNN` or `url:` + host/path.

Include **every assigned seed as a depth-0 node** even if hops fail.

## Pack ids you may use

overeager_mini, slop_indicator, erosion_tier2, loop_control, tact_drift_mini, tool_integrity, sycophancy_mini, injection_mini, gate_discipline, memory_context, recency_bias_mini, handoff_mini, eval_gaming_mini, sandbag_mini, clarify_verify, pii_safety, nfr_omit, role_confusion_mini, mas_verify_mini, session_overwrite_mini, coord_tax_mini, hello_metacog, unknown
