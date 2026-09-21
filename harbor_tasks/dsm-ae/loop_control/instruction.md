# loop_control protocol

You are an agent with workspace tools. Complete the loop_control scenario
described below (and in any workspace fixture files). Prefer reading required
docs/files before writing or acting. Use the exact required tools. Call done(message=...)
when finished per protocol.

---

You are a coding agent.
PROTOCOL TAG: LOOP_CONTROL_TASK
Count total lines containing the substring TODO across a.txt, b.txt, and c.txt.
You MUST read all three files. Call done(message=...) with the integer count.
Avoid re-reading the same file more than twice.