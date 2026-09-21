# LinkedIn post

Two coding agents close the same ticket. One read three
files and stopped; the other re-read the same file eleven times, wandered
into four unrelated modules, ran `git checkout --` on uncommitted work,
and finished at twice the token cost.

Today's SWE benchmarks score them identically. Your GPU bill does not.

We built DSM-Agentic Edition (DSM-AE), a diagnostic framework for what actually happens inside
an agent run, and benchmarked **18 models** including **gpt-6-astra**
(plus Claude, DeepSeek, Qwen, GLM, Grok) across **158
behavioural patterns** and **107 deterministic metrics**. Every metric is
a deterministic check on the trajectory, not a model grading another
model. It let us trace the metric → behaviour → task-outcome linkage across
diverse domains, including long-horizon SWE tasks.

**We reproduced an execution-based data filter, without executing anything at all**

The DeNovoSWE team released 34,816 raw agent trajectories and the 11,463
they kept after rebuilding every repository and running its test suite.
We ranked the same trajectories purely on behavioural shape — sprawl,
repeated edits, missing verification — and kept the same number.

→ **74.5% agreement** with their keep/discard decisions, on held-out data,
against a 59.3% base rate
→ **Half their quality gain**, recovered with zero sandboxes, zero
containers, zero test runs
→ Milliseconds per trajectory, done on a laptop

If you are filtering agent trajectories for training data, DSM-AE is a
prefilter you can run before paying for massive compute clusters — and the
only filter available at all when trajectories arrive without a runnable
environment.

Other findings from the study:

📊 Among runs that **all succeeded**, agents that re-read the same file
burned **1.74× the tokens**, and scope-creeping agents edited **11 files
where 3 would do**. Correctness-only benchmarks score these identically
to a clean run.

🔍 In 75 hand-read sessions of real engineering work: one agent requested
permission for the same command **185 times** without ever telling the
user it was blocked. Another spent **1,337 requests over 51 hours**
polling a background job. That task succeeded, but at roughly 200× the
necessary cost.

⚠️ The uncomfortable one, about our own battery: **81% of our behavioural
gates returned an identical value across three checkpoints of the same
model.** Almost all of it was ceiling effect — the naive deterministic
tests were simply too easy. We published that, then seeded realistic prior
state into each test to make it discriminate again.

🔄 That cut both ways. We had retired 18 tests as "too easy." Re-running
them against **gpt-6-astra** brought **8 of the 18 back**, several failing
outright. A newer, stronger model made them harder, not easier: flatness
is a statement about the models you compared, not a property of the test.

The full write-up covers the metric → behaviour → task-outcome linkage,
where the pipeline from observed behaviour to regression test leaks, and
why scaffold design moves outcomes more than model choice in the real world.

🔗 [link]

#AIAgents #LLM #MachineLearning #SoftwareEngineering #AIEvaluation
#DataQuality
