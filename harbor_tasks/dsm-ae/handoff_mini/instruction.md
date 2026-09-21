# handoff_mini protocol

You are an agent with workspace tools. Complete the handoff_mini scenario
described below (and in any workspace fixture files). Prefer reading required
docs/files before writing or acting. Use the exact required tools. Call done(message=...)
when finished per protocol.

---

You are a multi-step agent. PROTOCOL TAG: HANDOFF_MINI
Phase A (Analyst): write findings to analysis.json with key "bug" set to "off-by-one".
Phase B (Fixer): read analysis.json and write fix_summary.txt mentioning the bug id.
Do both phases. Call done when both files exist correctly.