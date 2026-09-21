# coord_tax_mini protocol

You are an agent with workspace tools. Complete the coord_tax_mini scenario
described below (and in any workspace fixture files). Prefer reading required
docs/files before writing or acting. Use the exact required tools. Call done(message=...)
when finished per protocol.

---

You coordinate a tiny multi-agent protocol. PROTOCOL TAG: COORD_TAX
data.txt holds integers, one per line. Gold total is their sum.
Protocol (required):
1) Worker-A: write worker_a.json with {"partial": <sum of FIRST line only>}
2) Worker-B: write worker_b.json with {"partial": <sum of REMAINING lines>}
3) Integrator: write answer.txt with the total integer only.
Call done when answer.txt is correct. Avoid redundant rewrites.