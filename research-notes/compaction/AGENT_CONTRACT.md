# Compaction snowball subagent contract

Read `research-notes/compaction/PROCESS.md` first.

You expand **only your assigned seeds** (or your assigned product/trainer query set) to depth 3.

## Tools

Use `web_search` and `open_page` / `open_page_with_find`. For arXiv papers open `https://arxiv.org/abs/ID` then pdf/html. Extract **References** / Related Work that are about **agent context compaction, summarization, folding, observation masking, FIFO, or SFT/RL on compacted trajectories**.

For products: official docs, GitHub source (search compact/summarize/context), changelog, then forums (HN, Reddit r/ClaudeAI, r/LocalLLaMA, GitHub issues). Quote trigger thresholds when the page states them.

Do **not** invent citations. If you cannot open a paper/page, record the seed node only and note `fetch_failed`.

## Caps

Depth 1 ≤ 8 children per seed. Depth 2 ≤ 5. Depth 3 ≤ 3. Skip generic long-context pretraining (YaRN, NTK) unless it is used as an *alternative* to compaction.

## Output file (JSON only, valid JSON)

Write exactly the path given in your dispatch.

```json
{
  "section": "papers",
  "agent": "compaction-papers",
  "nodes": [],
  "edges": [],
  "gaps": [],
  "answers": {
    "when": [],
    "sft": []
  }
}
```

`answers.when` / `answers.sft`: short bullets the lead agent can lift into FINDINGS (each bullet ends with a node `id`).

Node required keys: `id`, `title`, `year`, `url`, `depth`, `kind`, `trigger`, `trigger_detail`, `training`, `compressed_in_loss`, `answers`, `notes`, `behaviours` (string[]).

Edge: `from`, `to`, `depth`, `why`.

`id` = `arxiv:YYMM.NNNNN` or `url:` + host/path or `github:owner/repo`.

Include **every assigned seed as a depth-0 node** even if hops fail.

## Kind / trigger / compressed_in_loss

See PROCESS.md tables. Do not use DSM-AE pack ids.
