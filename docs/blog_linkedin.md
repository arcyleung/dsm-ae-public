# LinkedIn post

We matched 74.5% of an execution-based training-data filter without
running a single test.

If you are building SFT or RL datasets from agent traces, that number is
the pitch.

DeNovoSWE released 34,816 raw trajectories and the 11,463 they kept
after rebuilding every repository and running its tests. We ranked the
same traces on behavioural shape (sprawl, repeated edits, missing
verification) and kept the same number.

→ 74.5% agreement with their keep/discard decisions, on held-out data
(59.3% base rate)
→ 52% of their quality gain
→ milliseconds per trajectory, on a laptop

No 30-minute container stalls. No archived Debian mirrors. No sandboxes.

DSM-AE scores the trajectory itself with deterministic checks, not a
model grading another model. 19 models, 158 behavioural patterns.

Wonder what other weird behaviours current benchmarks cannot catch?
Here is a sample: one agent requested permission for the same command
185 times without ever telling the user it was blocked. Another spent
1,337 requests over 51 hours polling a background job. That task
succeeded, at roughly 200× the necessary cost.

Code and write-up: https://github.com/arcyleung/dsm-ae-public

#AIAgents #LLMEvaluation #SoftwareEngineering #DataQuality
