# Compaction snowball process (AS_OF 2026-09-01)

**Mode:** literature + product + SFT-practice snowball, not a new narrative review.  
**Seed document:** `docs/surveys/compaction.md` (Key References + named practitioner/product sources).  
**Depth:** 3 (seed = depth 0; cited-by-seed = 1; cited-by-those = 2; one more hop = 3).  
**Goal:** answer two operator questions and put the evidence tree in WebUI `/compaction`.

## Questions

1. **When do coding-agent scaffolds compact?** (Claude Code, Codex, Grok Build, Cursor, Cline, Aider, OpenHands, SWE-agent, Copilot, …) Trigger: token %, semantic boundary, user `/compact`, tool-output trim, subagent return, …
2. **How are compressed trajectories used for SFT?** Are compacted / summarized spans **preferred**, **discarded**, or **loss-masked** during data-quality filtering? Contrast **LlamaFactory / industry trainers** vs **academic agent-compaction papers**.

## Why this is bounded

Unfiltered depth-3 from ~35 seeds explodes. Keep only works that name **context compaction / summarization / folding / observation masking / FIFO truncation** for *agents*, or **SFT/RL data recipes** that mention compacted turns, loss masking of summaries, or trajectory filtering.

| Hop | Cap per parent | Keep if |
|---|---:|---|
| 0 | all seeds | listed in `seeds.json` |
| 1 | ≤ 8 outgoing | compaction trigger, representation, training on compacted state, or SFT filter of summaries |
| 2 | ≤ 5 outgoing | same filter |
| 3 | ≤ 3 outgoing | same filter |

Prefer the paper’s **References** / Related Work (arXiv abs/pdf, Semantic Scholar). Do not invent citations. For product docs / GitHub / forums, hop 1 is “related work it names or links” only (max 4).

## Node identity

- Prefer `arxiv:YYMM.NNNNN` when an arXiv id exists.
- Else a stable slug (`github:hiyouga/LLaMA-Factory`, `url:code.claude.com/...`).
- Dedup by arXiv id first, then normalized title.

## Fields every node must carry

| Field | Meaning |
|---|---|
| `kind` | `paper` / `product` / `trainer` / `forum` / `blog` |
| `trigger` | `threshold` / `semantic` / `agent_tool` / `manual` / `tool_trim` / `subagent` / `none` / `unknown` |
| `trigger_detail` | short phrase (e.g. “auto at 85% of context_window”) |
| `training` | `none` / `SFT` / `RL` / `distill` / `mixed` / `unknown` |
| `compressed_in_loss` | `preferred` / `discarded` / `masked` / `kept_as_context` / `mixed` / `unknown` |
| `answers` | subset of `["when","sft"]` this node informs |
| `notes` | one or two sentences; quote numbers |

`compressed_in_loss`:
- `preferred` — compacted/summary tokens are kept as training targets (or up-weighted)
- `discarded` — those turns dropped from the SFT corpus
- `masked` — present as context, loss not computed on them (CompactionRL w/o-summary-training)
- `kept_as_context` — left in the conversation; default next-token loss (no special filter)
- `mixed` / `unknown`

## Pipeline (this run)

1. **Seed registry** — `seeds.json` from `docs/surveys/compaction.md` §9 plus named products.  
2. **Parallel snowball** — papers / evals / scaffolds / SFT-industry / SFT-academic.  
3. **Merge** — `tree.json` + `FINDINGS.md` answering Q1 and Q2.  
4. **Compaction tab** — WebUI `/compaction` serves the summary + tree.  

[P2 complete] Five section agents done. Merged 134 nodes / 180 edges. AS_OF 2026-09-01.

## Outputs

```
research-notes/compaction/
  PROCESS.md
  AGENT_CONTRACT.md
  seeds.json
  section-papers.json
  section-evals.json
  section-scaffolds.json
  section-sft-industry.json
  section-sft-academic.json
  tree.json
  FINDINGS.md
reports/compaction/index.html
```

[P0 complete] Subagent: yes. Mode: standard (survey). AS_OF: 2026-09-01.
