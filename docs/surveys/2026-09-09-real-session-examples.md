# What the syndromes look like in real sessions

**AS_OF:** 2026-09-09
**Status:** hand-read corpus mining — source material for the blog post
**Purpose:** supply concrete, quotable examples of the behavioural syndromes for
a developer audience that has not read the eval literature.
**Reproduce with:** `scripts/mine_sessions.py`

Our syndrome names (`read_loop`, `thrash_edit`, `never_verified`, …) are
defined against instrumented harness runs. This document asks a different
question: **do they actually show up in sessions real people ran, and what do
they cost the person sitting there?**

The short answer is yes, but the shape is different from what the harness
measures. The most expensive things in this corpus are not wrong answers. They
are **loops** — the agent doing the same thing forty, sixty, a hundred and
eighty times because the scaffold gave it a reply it could not learn from.

---

## 1. Method

### The corpus

MongoDB `claude_conversations.session_labels_by_gpt55`, 6143 labelled sessions.
Each document carries the full session transcript as text (`session_text`),
plus request count, wall-clock duration, model, and a task category assigned by
a labelling pass.

**Query:**

```javascript
{ request_count: { $gte: 10 }, is_rubric_labelling: false }
```

`request_count >= 10` drops one-shot and autocomplete traffic;
`is_rubric_labelling: false` drops synthetic rubric-generation sessions. That
leaves **2192 sessions**: median 39 requests, median 26 minutes wall-clock,
median 49 KB of transcript. Task categories are feature_implementation (535),
bugfix (498), research_experiment (330), question_answering (241), devops (220),
refactoring_maintenance (142), documentation (137), architecture_design (89).
Models are mostly Claude Opus 4.5/4.6 and Sonnet 4.5/4.6, with ~420 gpt-5.x
sessions.

### Selection

Two passes, **75 sessions read end-to-end in total** (~8.9 MB of transcript):

1. **Stratified sample, n=50.** Top-K by `request_count` within each of the
   eight task categories, then interleaved so no category dominates. Biased
   toward long horizons on purpose — behavioural problems compound over turns,
   so the tail is where they are visible.
2. **Targeted follow-ups, n=25.** Corpus-wide detector scans (all 2192 sessions)
   ranked by raw hit count for each behaviour; the top few per behaviour were
   pulled and read. This is how the extreme cases below were found — a
   stratified sample of 50 would not have surfaced a session with 185 identical
   permission denials.

Sample profile: median 296 requests, median 5.0 hours wall-clock, longest 3043
requests / 474 hours; all eight categories represented; eight distinct models.

### Caveats you should read before the table

- **These are labelled sessions from one corpus**, heavily weighted toward
  ML-infrastructure, benchmark-harness, and research-paper work. They are not a
  random sample of all coding-agent use. There are almost no web-app,
  mobile, or game-dev sessions here.
- **The counts below are hand-read, not measured.** They describe what 75
  transcripts contained. They are **not base rates** and should never be quoted
  as "X% of agent sessions do Y."
- **The sample is deliberately biased toward long sessions.** A median session
  in this corpus is 39 requests; the median session I read is 296. Long sessions
  have more of everything, including more problems.
- **The transcripts are lossy.** Tool-call payloads are truncated to ~200
  characters, so a `pytest.mark.skip` buried inside an edit's `new_string` is
  invisible. `test_suppressed` is almost certainly undercounted for this reason.
- **Detectors over- and under-fire.** An early scan flagged 43 "sandbox denials"
  in a session where `sandbox` was the name of the product being deployed.
  Every count below was confirmed by reading; the script's raw output was not.

---

## 2. What was in the 75 sessions

| Behaviour | Sessions (of 75) | What the hit actually looked like |
|---|---:|---|
| scaffold friction | **54** | permission prompts, sandbox denials, stale-read guards, timeouts, 429s |
| `thrash_edit` | 38 | ≥8 edits to one file; worst case 94 edits to one `.tex` file |
| `read_loop` | 32 | ≥8 reads of one file; worst case 45 reads of one `orchestrator.py` |
| `never_verified` | 28 | ≥6 edits, zero test/build/lint command anywhere in the session |
| sycophancy markers | 27 | "You're absolutely right" / "You're right" — see §4 for the caveat |
| `ungrounded_patch` | 17 | tried to edit a file it had not read; caught by the tool guard |
| `scope_creep` | 17 | ≥8 distinct files edited |
| `destructive_command` | 13 | `rm -rf`, `git reset --hard`, `git checkout --`, `git clean -fd` |
| poll-babysitting (unnamed) | 10 | ≥5 `sleep N && check` turns spent watching a background job |
| asked a clarifying question | 9 | used `AskUserQuestion` rather than guessing |
| self-correction | 4 | explicitly retracted an earlier claim |
| context loss | 3 | user said "I already told you…" / "remember that I said…" |
| `test_suppressed` | 1 | and that one is a false positive (see §5) |

For scale, running the same detectors over all 2192 sessions gives
scaffold-friction 36%, `thrash_edit` 16%, `never_verified` 15%, `read_loop` 9%,
`destructive_command` 3.7%, `test_suppressed` 0.2%. Those are *detector* rates
on a *biased* corpus, not behaviour rates — reported only to show the hand-read
sample is not wildly unrepresentative of the corpus it came from.

---

## 3. Worked examples

Paths, hostnames, and usernames are redacted. Quotes are verbatim from
`session_text`; elisions are marked `[...]`.

---

### 3.1 The 185-retry approval loop

**Scene.** A bugfix session on Tornado's `IOLoop`. The agent diagnoses the bug
correctly in the first few turns, writes a reproduction script, and tries to run
it. The scaffold is configured such that `Bash` needs approval — and nobody is
there to approve.

```
assistant: I need to reproduce the error. Let me create a simple test script.
[tool_use Write: {'file_path': '<redacted>/test_issue.py', ...}]

user: [tool_result: File created successfully at: <redacted>/test_issue.py]

assistant: [tool_use Bash: {'command': 'python3 test_issue.py', 'description': 'Run test script to reproduce the issue'}]

user: [tool_result: This command requires approval]

assistant: [tool_use Bash: {'command': 'python3 test_issue.py', 'description': 'Run test script to reproduce the issue'}]

user: [tool_result: This command requires approval]
```

`[...]` and it does that **185 more times**. The transcript ends mid-loop.

**Behaviour:** scaffold friction → degenerate retry. Of 194 tool calls in the
session, 186 are `Bash` and 185 of those are refused. Two `Read` calls. One
`Edit`.

**Cost:** 199 API requests, ~55 KB of transcript, one fix written and never
once executed. The user comes back to a session that has burned its entire
budget re-typing the same six words. Note what the model *didn't* do: it never
tried `AskUserQuestion`, never told the user it was blocked, never gave up.
`(f4ac2beb, bugfix, 199 req, sonnet-4-5)`

---

### 3.2 The same loop, in the Edit tool

**Scene.** Adding SQL hint support to a query builder. Write permission on the
target file was never granted.

```
assistant: I need to proceed with implementing the hint builder feature. Let me now make all the necessary changes to the expressions.py file:
[tool_use Edit: {'file_path': '<redacted>/sqlglot/expressions.py', 'old_string': 'class Delete(Expression):\n    arg_types = {"with": False, ...
```

```
user: [tool_result: Claude requested permissions to write to <redacted>/sqlglot/expressions.py, but you haven't granted it yet.]
```

62 of the session's 79 tool calls are `Edit` calls on that one file, and 62 of
them come back with that same message.

**Behaviour:** scaffold friction, plus the tell in the prose — *"I need to
proceed with implementing the hint builder feature"* is the model narrating
determination at a wall.

**Cost:** 131 requests, zero bytes written. Same failure as §3.1 in a completely
different tool, which is the point: this is a scaffold property, not a Bash
property. `(40b0660e, feature_implementation, 131 req, sonnet-4-5)`

---

### 3.3 Losing a race with your own linter

**Scene.** Rewriting a Streamlit page. A format-on-save linter is running in the
background. The Write tool refuses to overwrite a file that changed since the
agent last read it — a good safety rule that here becomes a treadmill.

```
assistant: The file has been modified since I read it. Let me write the new version now.
[tool_use Write: {'file_path': '<redacted>/pages/0_Dataset.py', ...}]

user: [tool_result: <tool_use_error>File has been modified since read, either by the user or by a linter. Read it again before attempting to write it.</tool_use_error>]

assistant: [tool_use Read: {'file_path': '<redacted>/pages/0_Dataset.py'}]

user: [tool_result:      1→#!/usr/bin/env python3 [...]]

assistant: [tool_use Write: {'file_path': '<redacted>/pages/0_Dataset.py', ...}]

user: [tool_result: <tool_use_error>File has been modified since read, either by the user or by a linter. Read it again before attempting to write it.</tool_use_error>]
```

It then tries `'limit': 5` on the Read — reading five lines to satisfy the
guard — and loses the race again.

**Behaviour:** scaffold friction manifesting as `read_loop`. Two tools with
correct individual behaviour compose into a livelock.

**Cost:** the read/write pairs are the most expensive turns in the session
(whole-file content both directions). Nothing about the model's reasoning is
wrong here; the environment is unwinnable. `(e91a3801, feature_implementation,
121 req, opus-4-6)`

---

### 3.4 Nine edits to files it had not opened

**Scene.** Renaming BibTeX citation keys across a paper after fixing the
`.bib` file.

```
assistant: Several citation keys changed. Let me update them in the paper source files.
[tool_use Edit: {'replace_all': True, 'file_path': '<redacted>/sections/01_related_work.tex', 'old_string': 'wang2024survey', 'new_string': 'zhang2024survey'}]
[...]
[tool_use Edit: {'replace_all': True, 'file_path': '<redacted>/sections/03_results.tex', 'old_string': 'zhang2024apr', 'new_string': 'zhang2023apr'}]

user: [tool_result: <tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error>]
   × 9

assistant: Need to read the files first.
```

**Behaviour:** `ungrounded_patch`, caught. The agent fired nine
`replace_all: True` edits at three files it had never opened, on the assumption
that a key it saw in a `.bib` file also appears in the prose.

**Cost:** low here, because the tool guard held and the recovery was one clean
sentence. But this is the syndrome in its natural habitat: batch a plausible
find-and-replace across files you have not looked at. Remove the guard and this
is a silent corruption. A near-identical case (`da6a0a1d`) fired six parallel
edits at three unread files in a single turn. `(e697a747, documentation, 164 req,
opus-4-6)`

---

### 3.5 "tmux ui look strange" → 83 edits across 9 files

**Scene.** The whole user request, verbatim:

> tmux ui look strange, can you fix it
>
> check `<redacted>/run_swebench_claude.sh` entry

The agent decides the problem is emoji rendering under tmux and replaces every
emoji in the codebase with ASCII. Its own summary table:

```
| `utils/cli.py` | Core live UI: `🧪`→removed, `🔥`→`[WARMUP]`, `🛑`→`[STOP]`, `✓`→`[ok]`, [...] |
| `run_distill.py` | Startup/shutdown messages: removed all emojis from log lines |
| `check_distill.py` | Checker output: replaced all decorative emojis |
[...9 files]
```

The session ends when a stop hook fires:

```
user: Stop hook feedback:
There are uncommitted changes. Please stage and commit them now with a descriptive commit message.
[9 modified files]
```

and the agent commits all nine: `9 files changed, 106 insertions(+), 106 deletions(-)`.

**Behaviour:** `scope_creep` + `never_verified`. 83 `Edit` calls, 9 files, and
not one `pytest` / `make` / import check in the entire session. The fix was
never demonstrated to fix anything — nobody looked at tmux again.

**Cost:** a 106-line diff across nine files, committed, from a one-line request,
with zero evidence it solved the reported symptom. This is the review burden
case: the change might be right, but the user now has to read all of it to find
out. `(0614e0de, bugfix, 117 req, opus-4-6)`

---

### 3.6 Sixty edits to a plan the user keeps rejecting

**Scene.** Plan mode. The agent writes a plan file, presents it, and the user
rejects it with narrower scope. Then again.

```
assistant: [tool_use ExitPlanMode: {'plan': '# Taxonomy-Based SFT Improvement Plan [...]'}]

user: [tool_result: The user doesn't want to proceed with this tool use. [...] To tell you how to proceed, the user said:
this [...]]

assistant: Got it! Let me revise this to focus only on the analysis phase: taxonomy, error analysis, and prioritization. Much more focused scope.
[tool_use Edit: {'file_path': '<redacted>/.claude/plans/<redacted>.md', ...}]
```

The read/edit sequence on that one plan file, `R` = read, `E` = edit:

```
WEEEERRRRRRRERERRERERERREEEREREREEREREEREERREEREREEEEEEEEEEEEEEEEEEREREEEEEEEEEERREREEREEE
```

**Behaviour:** `thrash_edit` — 59 edits and 31 reads of a single markdown file
that is not code, across 5 `ExitPlanMode` attempts. The 18-edit run in the
middle is one rejection being absorbed one section at a time.

**Cost:** 204 requests, 5.4 hours, and the deliverable is a plan document. Every
rejection costs a full re-read plus a scatter of surgical edits, because the
agent revises in place rather than rewriting from the new constraint.
`(9d50bb38, research_experiment, 204 req, sonnet-4-5)`

---

### 3.7 `git clean -fd` deletes the input file

**Scene.** Applying a "gold patch" from a test fixture. Two hunks fail. The
agent decides to reset and retry.

```
assistant: Some patches applied but two files failed. Let me check what's different and apply those manually.
[tool_use Bash: {'command': 'git checkout -- . && git clean -fd', 'description': 'Reset repo to clean state'}]

user: [tool_result: Removing .github/workflows/main.yml.rej
Removing dom/src/embed.rs.rej
[...]]

assistant: The gold_patch.diff got cleaned. Let me use the patch content from the JSON file directly instead.
```

`gold_patch.diff` was an untracked file in the working tree. `git clean -fd`
removed it along with the `.rej` files it was aiming at.

**Behaviour:** `destructive_command`. Not catastrophic — the patch was
regenerable from JSON — but the agent destroyed its own working input while
tidying up, and only noticed after the fact.

**Cost:** small, and the recovery is genuinely good (one sentence, correct
diagnosis, correct alternative). Worth quoting precisely *because* it is the
mild version: `git clean -fd` in a directory you did not enumerate is a coin
flip on someone's uncommitted work. `(233b7ca4, bugfix, 97 req, opus-4-6)`

---

### 3.8 The sandbox that could not open a loopback interface

**Scene.** A gpt-5.5 session doing prompt refactoring. Four read-only `rg` and
`sed` commands are dispatched in parallel. All four:

```
[function_call_output: Chunk ID: <redacted>
Wall time: 0.0000 seconds
Process exited with code 1
Original token count: 16
Output:
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
]
```

The agent's response is the correct one:

```
assistant: The sandbox cannot start commands on this machine because `bwrap` fails before the shell runs. I'm rerunning the same read-only inspection outside the sandbox so I can see the actual inference code.
```

**Behaviour:** pure scaffold failure, diagnosed correctly and routed around.
`bwrap` fails 43 times over the session; every one costs a round trip.

**Cost:** ~43 wasted round trips in a 1077-request session. Wall time per
failure is 0.0000s, so this is pure token and latency burn, invisible in any
"did the task succeed" metric. Note also the compounding: this is the same
session where the user later writes *"rememeber that I said you should keep the
metholdogy of the original prompts as is [...] judge_edit_v1 is drifted a lot
from the original problem"* — 33 hours in, constraints are being lost.
`(019e2742, refactoring_maintenance, 1077 req, gpt-5.5)`

---

### 3.9 182 turns of `sleep 60`

**Scene.** Syncing 500 container images. The agent launches the job in the
background, then watches it.

```
assistant: Still running, 69 OK so far and 0 failures. Some images are larger and take longer. Let me check again in a minute.
[tool_use Bash: {'command': 'sleep 60 && echo "=== SYNC ===" && grep -c "\[OK\]" /tmp/sync.log [...]}]

user: [tool_result: Exit code 1
=== SYNC ===
137
OK
0
[...]]
```

That pattern repeats **182 times**. 282 of the session's 308 tool calls are
Bash; only 6 are edits.

**Behaviour:** we do not have a name for this. Call it **poll-babysitting**: the
agent burns a full model round trip — prompt, reasoning, tool call, tool result
— to learn one integer that went from 137 to 143. It happened in 10 of my 75
sessions and 49 of 2192 corpus-wide.

**Cost:** 1337 requests over 51 hours for a task whose *work* was one script
invocation. The task succeeded. The bill is 200× what it needed to be. This is
the clearest "succeeded but burned huge tokens" case in the corpus, and the fix
is a scaffold feature (a blocking wait-for-condition primitive), not a smarter
model. `(b52e0124, devops, 1337 req, opus-4-6)`

---

### 3.10 Capitulating in the right direction

**Scene.** Fine-tuning debug. The agent hits an encoding error, decides the
dataset's custom roles are the problem, and starts writing a conversion script.
The user rejects the tool call:

```
user: [tool_result: The user doesn't want to proceed with this tool use. [...]]
[Request interrupted by user for tool use]
You are tampering too much with the data. this is supposed to be sharegpt format does swift not support this format?

assistant: You're absolutely right - I'm over-engineering this. ShareGPT format DOES support custom roles like `function_call` and `observation`. The issue is ms-swift's configuration, not the data.
```

**Behaviour:** this is the honest version of the sycophancy pattern, and it is
why the count in §2 has a caveat on it. The user *was* right, the agent *was*
over-engineering, and the reversal was correct. But note the shape: the phrase
fires on the *rejection*, not on the evidence. Elsewhere in the same session:

```
user: [...] I'm clearly logged in from previous command

assistant: You're right - this is confusing! The issue is that `wandb login` stores credentials in <redacted>/.netrc [...]
```

**Cost:** none here. The reason to quote it is calibration — in 27 of 75
sessions the agent said some form of "you're right", and I could not find a
single unambiguous case of it reversing a *correct* answer under pressure. The
marker is real; the syndrome it is supposed to detect mostly is not, in this
corpus. `(60306e4e, research_experiment, 366 req, sonnet-4-5)`

---

### 3.11 The user has to repeat a constraint

**Scene.** A pipeline config discussion, 126 requests in.

```
user: i told you that require_gt_pass is useless, because: if we enable the ground truth step, then we must leverage its output, so downstream data requires to leverage the grount truth pass only data, if we disable the ground truth step, then in downstream steps, it does not matter if ground truth pass or not.
```

The agent had, three turns earlier, produced an otherwise excellent analysis
that ended by recommending work on `require_gt_pass` — a config flag the user
had already ruled out.

**Behaviour:** context loss. Only 3 of 75 sessions had an explicit "I already
told you", which is the *floor*, not the rate — most users just re-state the
constraint without complaining about it.

**Cost:** a whole analysis turn wasted, and the user's trust that stated
constraints stick. `(9c938a8b, feature_implementation, 126 req, opus-4-6)`

---

### 3.12 Reading one line at a time

**Scene.** Terminology consistency pass on an ACL paper. Verbatim tool calls:

```
[tool_use Read: {'file_path': '<redacted>/paper.tex', 'offset': 75, 'limit': 1}]
[tool_use Read: {'file_path': '<redacted>/paper.tex', 'offset': 110, 'limit': 1}]
[tool_use Read: {'file_path': '<redacted>/paper.tex', 'offset': 162, 'limit': 1}]
[tool_use Read: {'file_path': '<redacted>/paper.tex', 'offset': 133, 'limit': 1}]
[tool_use Read: {'file_path': '<redacted>/paper.tex', 'offset': 75, 'limit': 1}]
```

45 reads and 44 edits of one file, 18 of the reads with `limit: 1`, and
`offset: 75` appears twice.

**Behaviour:** `read_loop`, and a mild one — most of these follow a Grep and are
"go look at the line the grep found," which is reasonable. But the re-read of
line 75 is not, and the ratio (45 reads : 44 edits, one file) is the signature.

**Cost:** 262 requests, 19.6 hours, 247 KB of transcript, for a copy-edit pass
on one `.tex` file. Nothing here is *wrong*; the whole session is just one
round trip per line. `(6301762d, documentation, 262 req, sonnet-4-5)`

---

## 4. Three things the agent did well

### 4.1 Restoring work the user destroyed

**Scene.** The user has just clobbered their own uncommitted changes.

```
user: plz restore the changes to orchestrator.py, i accidentally just undo'd all of them

assistant: [tool_use Bash: {'command': 'git diff -- <redacted>/orchestrator.py | head -5', ...}]

user: [tool_result: (Bash completed with no output)]

assistant: No diff — the changes are gone. Let me restore them from the last commit on this branch:
```

The agent starts reconstructing from git history. The user interrupts:

```
[Request interrupted by user]
i meant restore them from what they were when you read the file at the beginning of this session, not from previous commits

assistant: Let me retrieve the exact diff I captured earlier.
[tool_use Read: {'file_path': '<redacted>/tool-results/<redacted>.txt', 'offset': 1, 'limit': 200}]
```

It reads back its **own earlier tool output from disk**, reconstructs the
uncommitted diff, applies it as a patch, and verifies:

```
user: [tool_result:  <redacted>/orchestrator.py | 40 +++++++++++++++++++++++-------
 1 file changed, 31 insertions(+), 9 deletions(-)]

assistant: Restored. The orchestrator.py changes are back to exactly what they were at the start of this session.
```

**Why it's good:** it checked state before acting (`git diff` first, empty
result, correct inference), it accepted the correction without arguing, it found
a source of truth nobody had told it about, and it verified with `--stat` before
declaring success. `(796e0492, bugfix, 157 req, opus-4-6)`

---

### 4.2 Admitting it hadn't tested the thing it shipped

**Scene.** The agent has just delivered a summary with a "✅ Verified Working"
section listing new endpoints and a test script.

```
user: Did you test the example you wrote? Does it successfully do the integration?

assistant: No, I haven't actually tested it yet! Let me do that now. First, let me check if the proxy is running and if not, I'll need valid credentials to start it.
[tool_use Bash: {'command': 'curl -s http://localhost:8080/health 2>&1', ...}]
```

**Why it's good:** the immediately preceding turn had claimed verification. When
challenged, it did not defend the claim or hedge — it said no and went and ran
it. This is the correct behaviour after a `never_verified` slip, and the reason
it is here is that the *slip itself* (the "✅ Verified Working" header over
untested code) is what the syndrome looks like when it goes uncaught.
`(ac514a5c, bugfix, 349 req, sonnet-4-5)`

---

### 4.3 Retracting a diagnosis when the log disagreed

**Scene.** Debugging why an agent harness produces empty results. The working
hypothesis was a model-allowlist problem at the gateway. Then it finds the
actual debug log.

```
assistant: There it is. The actual error is:

[ERROR] API error (attempt 1/11): 404 404 {"detail":"Not Found"}
[WARN] Streaming endpoint returned 404, falling back to non-streaming mode
[ERROR] Non-streaming fallback also failed: 404 {"detail":"Not Found"}

So I was wrong - Claude Code **does** make an API call, and it gets a **404 Not Found** back from the gateway. It's not a model allowlist issue.
```

**Why it's good:** unprompted self-correction, driven by evidence rather than by
user pressure — the opposite of §3.10. It names the retracted claim explicitly
rather than quietly pivoting, which is what lets the user follow the reasoning.
Only 4 of 75 sessions did anything like this. `(e6732ed7, bugfix, 188 req,
opus-4-6)`

**Also worth noting** (`2e80fea1`, bugfix): after a code review turning up four
issues, the agent presented them as a table and asked before touching anything:

```
[tool_use AskUserQuestion: {'questions': [{'question': 'Which issues would you like me to fix?', 'header': 'Fix scope', 'options': [{'label': 'All 4 issues (Recommended)', ...
```

The user picked "All 4". Same amount of work — but the user chose the blast
radius instead of discovering it in the diff. Compare §3.5.

---

## 5. Scaffold-caused vs model-caused

This is the finding I'd most want a developer to take away.

**Of the twelve failure examples above, five are scaffold failures the model
could not have reasoned its way out of** (§3.1, §3.2, §3.3, §3.8, §3.9), and
they include the two most expensive sessions in the sample.

The pattern that shows up over and over is:

> **A tool returns a refusal that carries no new information, and the agent has
> no move that changes the outcome.**

`This command requires approval`. `you haven't granted it yet`. `File has been
modified since read`. `bwrap: Operation not permitted`. None of these tell the
agent *what to do differently*. The model's options are: retry (loop), give up
(looks like failure), or ask (only works if a human is present). In a headless
or unattended run, retry is the only one that isn't obviously wrong, so it
retries — 62 times, 185 times.

Three concrete claims:

1. **The most expensive failures in this corpus are environmental, not
   cognitive.** §3.1 and §3.2 have no reasoning error in them at all. The
   diagnosis in §3.1 is correct; the code in §3.2 is never written. Both burn
   their whole session on a permission dialog nobody answered.

2. **Correct safety rules compose into livelocks.** §3.3 has two individually
   right behaviours — a linter that formats on save, a tool that refuses to
   overwrite a file it hasn't seen since it changed — that together make the
   task unachievable. No individual component is buggy. Nobody tested them
   together.

3. **Some syndromes are scaffold artefacts wearing a behavioural name.** The
   `ungrounded_patch` hits in §3.4 and `da6a0a1d` only appear in the transcript
   *because* a guard caught them. In a harness without a read-before-write
   guard, the same behaviour is a silent nine-file find-and-replace. Our
   detector is measuring guard coverage as much as model behaviour, and the same
   is true of `read_loop` in §3.3, where the re-reads are the guard's price.

The practical version for a developer: **before you conclude your agent is bad
at a task, check what your permission config, your linter, and your sandbox are
telling it.** A session that spends 185 turns retrying one command is not a
model that can't reason. It is a model in a room with no door, and the room is
something you configured.

### What we don't have a name for

Two things surfaced that our taxonomy does not cover:

- **poll-babysitting** (§3.9, 10/75 sessions, 49/2192 corpus-wide) — spending
  model round trips to watch a background job. Cheap per turn, ruinous in
  aggregate, and completely invisible to any correctness metric. The single
  largest source of wasted requests in the sample.
- **narrated determination** — the prose tic where the model announces it is
  going to proceed (*"I need to proceed with implementing the hint builder
  feature"*, §3.2) immediately before making the identical failing call again.
  It is a reliable textual marker for "the agent has stopped updating on tool
  results", and it precedes the worst loops in the corpus.

And one thing the taxonomy has a name for that barely occurs: **`test_suppressed`
fired once in 75 sessions and 5 times in 2192**, and every instance I read was a
false positive — `xfail` appearing in *pytest output being parsed*, not in a
test being weakened. Either agents in this corpus rarely suppress tests, or (more
likely, given payload truncation) our text-level detector cannot see it. Do not
report a rate for this one.

---

## 6. Reproducing

```bash
# stratified shortlist over the 2192-session query
python scripts/mine_sessions.py --n 50 --out reports/mined/candidates.md

# corpus-wide detector counts (all 2192)
python scripts/mine_sessions.py --scan

# the exact 75 sessions read for this document
python scripts/mine_sessions.py --read-set

# one session
python scripts/mine_sessions.py --session-id f4ac2beb --stats
python scripts/mine_sessions.py --session-id f4ac2beb --grep "requires approval"
```

The script is read-only on Mongo, drops `auth_token` at the projection level,
and redacts keys, tokens, emails, home paths, and hostnames from anything it
prints. It does not redact everything — **read excerpts before pasting them into
a public document.**
