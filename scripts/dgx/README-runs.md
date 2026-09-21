# DGX benchmark runs (SWE-bench-Pro + NL2Repo-Bench x gpt-5.6-terra/luna)

Operator notes for reproducing the ~10% sample runs on the DGX box.
**No secrets in this file.** Credentials live in the gitignored `dgx.yaml`
(SSH) and `models.yaml` (model API key); both are read at runtime only.

## 0. TL;DR

```bash
# from the repo root, on the workstation
python3 scripts/dgx/build_sample_manifest.py     # -> reports/behaviour-task/sample-manifest.json
./scripts/dgx/dgx_ssh.sh 'echo ok'               # opens the multiplexed SSH master

# on the DGX (already done once; see sections below to rebuild)
~/dsm-dgx/make_configs.sh
~/dsm-dgx/launch_runs.sh

# back on the workstation, when runs finish
./scripts/dgx/pull_results.sh --all
```

## 1. The machine

`gx10-102d`, an **aarch64** NVIDIA GB10 (DGX Spark), Ubuntu 6.17 kernel,
3.6T disk (2.1T free), Docker 28.x, user in the `docker` group.
This is *not* the k8s cluster the reference bundles came from — there is no
evalhub, no opensandbox server running, and `/tasks` does not exist.

## 2. What produced the reference bundles

`evalhub-extract/*/config.json` shows the original harness was **Harbor**
(the CAIS/Terminal-Bench successor; `result.json` carries `task_name:
"cais/..."`, agent `opencode` 1.18.18 / `claude-code` 2.1.207) driven by an
internal Huawei "evalhub" k8s wrapper with an `opensandbox` environment and a
squid proxy at `squid.evalhub.svc.cluster.local:3128`.

None of that k8s machinery is reachable from the DGX. The reproduction here
drops the evalhub/opensandbox/squid layer entirely and runs **Harbor 0.22.0
with `environment.type: docker`**, which is exactly what the upstream adapter's
own `swebenchpro.yaml` does. The output layout is identical, which is what
`src/dsm_ae/harbor/` consumes.

## 3. Problems hit and how they were fixed

| # | Problem | Fix |
|---|---------|-----|
| 1 | Concurrent password SSH logins hung the session | `dgx_ssh.sh` uses `ControlMaster`/`ControlPersist` so all commands share one authenticated connection. Password is fed via `SSH_ASKPASS` (never in argv/logs). |
| 2 | Task images are **amd64**, DGX is **aarch64** → `exec format error` | `docker run --privileged --rm tonistiigi/binfmt --install amd64` registered `qemu-x86_64`. All runs export `DOCKER_DEFAULT_PLATFORM=linux/amd64`. |
| 3 | Reference config points at `squid.evalhub.svc.cluster.local` (k8s-internal, unresolvable) | Dropped. The DGX reaches the model endpoint directly over HTTPS; verified `/v1/models` = 200 and a real chat completion for both models. No proxy needed. |
| 4 | Harbor not installed | `uv venv ~/harbor-venv` + `uv pip install harbor==0.22.0`. |
| 5 | SWE-bench-Pro dataset absent (`/tasks` missing, not in the public Harbor registry) | Public adapter exists at `laude-institute/harbor:adapters/swebenchpro`; sparse-cloned and run with `--task-ids` to generate exactly the 70 sampled tasks from `ScaleAI/SWE-bench_Pro` on HuggingFace. |
| 6 | Adapter rejected every id (`Instance not found`) | Two causes: run-bundle dir names are **lowercased**, and I had stripped the `instance_` prefix. Canonical ids are used verbatim (`scripts/dgx/swebenchpro_instance_ids.txt`); the sampler asserts the canonical set matches the bundle universe case-insensitively. |
| 7 | Harbor `--dataset-path` does not exist; a dataset path must be a **parent dir of task dirs**, not one task | Configs point at `datasets/<bench>/`. Also: CLI flags like `-n` reset the parsed config, so the job is launched with `-c <config>` plus only timeout/env flags. |
| 8 | No public NL2Repo-Bench Harbor adapter | Reconstructed by `build_nl2repo_tasks.py` from two public sources — GHCR images `ghcr.io/multimodal-art-projection/nl2repobench/<name>:1.0` and the upstream repo's `test_files/<name>/{start.md,test_commands.json,test_case_count.txt}`. |
| 9 | NL2Repo images lack `start.md` (the requirements doc the task refers to) | The Dockerfile `COPY`s it into `/workspace/start.md`, matching the reference trajectories' first user turn. |
| 10 | NL2Repo verifier wrote reward to the wrong path | Harbor reads `/logs/verifier/reward.txt`, not `/logs/reward.txt`. Fixed; re-verified with the `nop` agent (0 exceptions, reward `0.000000`). |
| 11 | `AgentSetupTimeoutError` after 360 s | opencode's setup runs `apt-get install nodejs npm`, which is very slow under x86 emulation. Runs use `--agent-setup-timeout-multiplier 12`. |
| 12 | `more-Itertools` failed to build: *repository name must be lowercase* | The upstream `test_files/` dir keeps the package's original casing, but the published GHCR image is all-lowercase. The generator now lowercases the image ref only (the task dir name keeps upstream casing). Task regenerated; see "Known follow-up" below. |
| 13 | NL2Repo agent setup died: `apt-get update` → `404 Not Found` / *"does not have a Release file"* | The upstream images pin **Debian buster (10) / bullseye (11)**, both archived. Harbor's opencode `install()` calls `ensure_system_dependencies(curl, bash, coreutils, nodejs, npm)`; the images ship curl/bash/stdbuf but **no node/npm**, so it fell through to `apt-get install -y ... nodejs npm` against dead mirrors. Fixed in the generator's Dockerfile (`build_nl2repo_tasks.py`): (a) archived suites are repointed at `archive.debian.org` with `Acquire::Check-Valid-Until "false"`, and (b) a **pinned, sha256-checksummed Node v22.23.2 tarball** is unpacked into `/usr/local`, which makes Harbor's dependency check short-circuit so apt is never invoked at all. |

### Repair run (2026-09-07)

7 of the 20 NL2Repo trials and 3 of the SWE-bench-Pro trials raised exceptions.
Three distinct causes:

1. **Archived Debian apt repos** (problem 13 above) — `deepdiff` and
   `flask-restful`, in both jobs. Genuine setup failures; fixed in the
   generator and re-run.
2. **`more-Itertools` image-ref casing** (problem 12 above) — both jobs held
   the pre-fix plan. Re-run.
3. **Model-side 429 `model_cooldown`** — `mechanicalsoup` (terra) plus all
   three SWE-bench-Pro exceptions
   (`instance_gravitational__teleport__{iZwFoLH,bq6dyKb}`,
   `instance_tutao__tutanota-5181821__DD4qHmQ`). opencode's *run* phase, not
   setup: the endpoint returned
   `All credentials for model gpt-5.6-{terra,luna} are cooling down via
   provider codex` (HTTP 429, ~2.5 h reset). Each `agent/opencode.txt` holds
   exactly one event, that error. These are **not** environment bugs and need
   no code fix — they need re-running once the credential pool is warm, at
   rpm 6. All three SWE-bench-Pro ones already carry `reward.txt=0`, so they
   are scoreable but agent-less (no `trajectory.json`).

The repair run for causes 1 and 2 uses a separate dataset and jobs dir so the
main jobs are untouched:

```bash
# on the DGX
python3 ~/dsm-dgx/build_nl2repo_tasks.py \
  --out ~/dsm-dgx/datasets/nl2repo-fixup \
  --instances deepdiff flask-restful more-Itertools
# configs/nl2repobench-fixup-{terra,luna}.yaml -> jobs_dir ~/dsm-dgx/runs-fixup
tmux new-session -d -s dsm-nl2repobench-fixup-terra "harbor run -c ~/dsm-dgx/configs/nl2repobench-fixup-terra.yaml ..."
```

Concurrency stays at `n_concurrent_trials: 2` per job to respect rpm 6.
The output layout under `runs-fixup/` is identical, so
`src/dsm_ae/harbor/adapter.py` reads it unchanged.

## 4. Sample selection

`scripts/dgx/build_sample_manifest.py` → `reports/behaviour-task/sample-manifest.json`
(seed 42, deterministic — re-running gives an identical file).

- **SWE-bench-Pro: 70 / 731 (9.6%)**, stratified by repo with largest-remainder
  apportionment so all 11 repos appear:
  ansible 9, internetarchive 9, flipt-io 8, qutebrowser 8, gravitational 7,
  future-architect 6, navidrome 6, protonmail 6, element-hq 5, nodebb 4, tutao 2.
  Languages: **Go 27, Python 26, TypeScript 13, JavaScript 4**.
- **NL2Repo-Bench: 10 / 104 (9.6%)**, all Python:
  deepdiff, flask-restful, graphneuralnetwork, mechanicalsoup, mootdx,
  more-Itertools, paillier, pyperclip, sklearn, stamina.

## 5. Layout on the DGX

```
~/dsm-dgx/
  .env.models                # OPENAI_API_KEY / OPENAI_BASE_URL, mode 600
  configs/{swebenchpro,nl2repobench}-{terra,luna}.yaml
  datasets/swebenchpro/      # 70 generated Harbor tasks
  datasets/nl2repobench/     # 10 generated Harbor tasks
  runs/                      # job output (pull these back)
  logs/                      # one log per job
  harbor-src/                # sparse clone of the swebenchpro adapter
~/harbor-venv/               # harbor 0.22.0
```

## 6. Validation done before launching

- `oracle` agent on one SWE-bench-Pro task → **reward 1.0** in 2m05s
  (proves image build + test harness + reward plumbing all work under emulation).
- `nop` agent on one NL2Repo task → **reward 0.000000**, 0 exceptions
  (proves the reconstructed verifier scores and writes correctly).

## 7. Pulling results back

```bash
./scripts/dgx/pull_results.sh            # list
./scripts/dgx/pull_results.sh --all      # fetch into evalhub-runs/
```

Output layout per trial is `<run>/<instance>/agent/trajectory.json`,
`verifier/reward.txt`, `result.json` — unchanged for `src/dsm_ae/harbor/`.
Note `opencode` sets `SUPPORTS_ATIF = True`, so `agent/trajectory.json` is
emitted in the same ATIF schema as the reference bundles.

## 8. Cost / rate limiting

`models.yaml` pins **rpm 6** for both models. Each job uses
`n_concurrent_trials: 2`, so at most 8 agents are in flight with all four jobs
running. Do not raise this without raising rpm.

## 9. OPEN ISSUE: SWE-bench-Pro rewards are not yet trustworthy

**Status: under investigation. Do NOT report the current SWE-bench-Pro zeros
as model performance.**

The first SWE-bench-Pro rewards came back 6/6 zero. Investigating rather than
accepting them turned up **two independent infrastructure artifacts**, plus a
strong control that proves they are artifacts:

**Control.** The reference bundles (same tasks, real x86 harness) score
navidrome 0.526, gravitational 0.583, tutao 0.700. Getting 0.000 on those exact
repos is not a plausible model result -- it is our environment.

### Artifact A -- Go verifiers produce zero test results (root cause pending)
The four Go trials (navidrome, gravitational) all wrote `reward=0` with
`verifier/output.json == {"tests": []}` -- **zero tests ran**, so those rewards
measured nothing.

Two false leads were chased and are recorded here so they are not repeated:

1. *"Go's GC crashes under QEMU."* The navidrome verifier log does contain
   `fatal error: lfstack` from inside the Go runtime, which looked like a
   known QEMU multi-threaded-GC defect. Real, but not established as the cause.
2. *"The Go images cannot exec under emulation."* `docker run ... <img>
   /bin/sh` returns `cannot execute binary file`. This turned out to be a
   **probe artifact, not a defect**: in the same image `/usr/bin/bash`,
   `/bin/bash` and the explicit loader all run fine and print `x86_64`, and
   `go version` reports `go1.24.3 linux/amd64`. The ansible image -- whose
   trial produced a perfectly good result -- fails the identical `/bin/sh`
   probe. So `/bin/sh` says nothing about whether a task works.

**ROOT CAUSE CONFIRMED.** The Go images are valid amd64 (ELF `3e 00`), contain
the x86-64 loader, and `go version` reports `go1.24.3 linux/amd64` -- the
toolchain itself is fine. But running the task's own test target on a **clean
checkout with no agent involved** reproduces the crash deterministically:

```
cd /app && go test -tags netgo -run TestPersistence ./persistence/...
  default GOMAXPROCS   -> fatal error: lfstack
  GOMAXPROCS=1 -p 1    -> fatal error: lfstack
```

So the Go runtime's lock-free stack corrupts under `qemu-x86_64` regardless of
parallelism. **Serialising does not help**, which rules out the obvious
multi-threaded-GC mitigation. This is an emulator/runtime incompatibility, not
anything the model or the harness did. It is fully reproducible in one command,
which makes it easy to re-check on a different host or QEMU version.

**All mitigations tried have FAILED:**

| setting | result |
|---|---|
| default | `fatal error: lfstack` |
| `GOMAXPROCS=1 -p 1` | `fatal error: lfstack` |
| `GODEBUG=asyncpreemptoff=1` | `fatal error: lfstack` |
| `GOGC=off` | `SIGSEGV` |
| `GODEBUG=asyncpreemptoff=1 GOGC=off` | `SIGSEGV` |

Serialising, disabling async preemption, and disabling the GC all fail, so this
is not a tunable-parameter problem. **Conclusion: Go tests are not runnable
under qemu-x86_64 on this aarch64 box.** The 27 Go instances (39% of the
SWE-bench-Pro sample: flipt-io 8, gravitational 7, future-architect 6,
navidrome 6) cannot be measured on this hardware.

### Required decision (needs a human)

1. **Run the Go subset on a real x86_64 host.** Only option that yields the
   full stratified sample the study was designed around. Everything needed is
   reproducible: `build_sample_manifest.py` (seed 42) plus the swebenchpro
   adapter regenerate the identical 27 tasks anywhere.
2. **Report Python/TypeScript/JavaScript only**, stating explicitly that Go was
   not measurable on this hardware. Honest, but it removes the Go arm and
   weakens the language-vs-agentic comparison, since Go is the largest
   non-Python stratum.

Do **not** silently report the Go zeros. `triage_rewards.py` marks them
`ARTIFACT_NO_TESTS_RAN` and excludes them from per-language rates specifically
so this cannot happen by accident.

**Cost note (matters for the decision).** Go trials are *not* cheap. The agent
runs to completion first and only then does the verifier fail:

```
gravitational  agent_execution 23:53:51 -> 00:03:47  (~10 min), verifier 16s
navidrome      agent_execution 22:46:54 -> 23:21:06  (~34 min), verifier 13s
```

So each Go trial spends real model tokens producing a patch that can never be
scored. Across 27 Go instances x 2 models = 54 trials, that is a substantial
amount of spend on unmeasurable results.

Given rpm=6, those trials also occupy scarce request budget that the
measurable Python/TS/JS trials could use. If the decision is to defer Go to
real x86 hardware, the cheapest action is to **restart the two SWE-bench-Pro
jobs against a Go-free dataset directory** (the 43 non-Go tasks), rather than
let the current jobs work through all 27 Go instances twice. The NL2Repo jobs
are unaffected and should be left alone.

### Artifact B -- tutao (TypeScript) reward is mis-scored
The tutao trials **passed** their tests, but scored 0. The task's expected test
name embeds an assertion count that changes with the code:

```
required: 'test/api/Suite.ts | api tests (3029 assertions)'
observed: 'test/api/Suite.ts | api tests (882 assertions)'  PASSED
          'test/api/Suite.ts | api tests (223 assertions)'  PASSED
```

Exact-name matching cannot succeed here. This is **not** an inherent grader
bug: on the reference (real x86) harness **14/20 tutao instances scored > 0**,
so the same grader works there. Our environment produces a *different test
partitioning* (882 + 223 assertions instead of one 3029-assertion run), most
likely because the suite shards by timing/CPU and emulation changes that.

**Scope: 1 task out of 43 non-Go tasks.** Scanning every sampled task's
`tests/config.json` for expected names containing an assertion count:

```
tutao 1/2   element-hq 0/5   protonmail 0/6   nodebb 0/4
ansible 0/9   internetarchive 0/9   qutebrowser 0/8
```

Only `instance_tutao__tutanota-5181821...` is affected -- and it happens to be
the one task both TypeScript trials so far have run, which is why TS currently
shows a misleading 0.000. **TypeScript as a language is fine**; the other 12
TS/JS tasks use ordinary test names. `triage_rewards.py` now detects this task
and marks such trials `ARTIFACT_GRADER_NAME_MISMATCH`, so it is excluded
automatically rather than remembered.

### Mistake made during debugging (fixed)
While probing, a bind-mount created an empty directory at
`/usr/bin/qemu-x86_64` on the host, clobbering the binfmt interpreter path.
The `F` (fix-binary) flag kept a cached fd alive so existing runs were not
disturbed, but new containers mounting that path broke. Removed the stray
directory and reinstalled the real qemu binary (8.1 MB, from
`tonistiigi/binfmt`) at that path; `alpine` amd64 exec re-verified. The four
production jobs were checked before and after and were unaffected
(10 processes, 8 env containers, same reward counts).

### What must NOT happen
Reporting emulator-induced zeros as "the model is weak at Go", or grader-induced
zeros as "weak at TypeScript", would fabricate exactly the language-deficit
conclusion this study exists to distinguish from genuine agentic deficits.
Quarantine SWE-bench-Pro rewards until A and B are resolved.

NL2Repo-Bench (Python) is unaffected and is producing well-spread, plausible
rewards (0.98, 1.0, 0.0).

### Prepared, but NOT activated (awaiting the decision above)

`~/dsm-dgx/datasets/swebenchpro-nogo/` is staged on the DGX: symlinks to the
**43 non-Go tasks** (ansible 9, internetarchive 9, qutebrowser 8, protonmail 6,
element-hq 5, nodebb 4, tutao 2). Nothing points at it yet -- the four original
jobs are still running unchanged.

To switch the SWE-bench-Pro jobs onto it (only if option 2 is chosen):

```bash
tmux kill-session -t dsm-swebenchpro-terra
tmux kill-session -t dsm-swebenchpro-luna
sed -i 's|datasets/swebenchpro$|datasets/swebenchpro-nogo|' \
  ~/dsm-dgx/configs/swebenchpro-terra.yaml ~/dsm-dgx/configs/swebenchpro-luna.yaml
~/dsm-dgx/launch_runs.sh swebenchpro-terra swebenchpro-luna
```

Harbor skips trials it has already completed in the same `jobs_dir`, so the
finished Python/TS/JS trials are preserved.

### DECISION (2026-09-07): switch to `swebenchpro-nogo`, drain first

Option 2 chosen. Go is **not measurable on this hardware** and the failure is
not a tunable: the Go runtime dies under `qemu-x86_64` on aarch64 with
`fatal error: lfstack` (or SIGSEGV) on a clean checkout with no agent
involved, and every mitigation failed — `GOMAXPROCS=1 -p 1`,
`GODEBUG=asyncpreemptoff=1`, `GOGC=off`, and combinations.

The deciding factor was cost, not principle. Go trials do **not** fail
cheaply: the agent runs to completion first (gravitational ~10 min,
navidrome ~34 min) and only then does the verifier fail in ~15s with
`tests_run=0`. That is 27 Go instances x 2 models = **54 trials** paying full
token cost for rewards that `HarborTrial.scoreable` correctly refuses to
score, while consuming rpm=6 budget the measurable strata need.

Executed as `~/dsm-dgx/switch_nogo.sh` in tmux `nogo-switch` rather than
immediately: it polls until no `instance_*` containers remain (2h cap), then
kills and relaunches the two SWE-bench-Pro jobs against
`datasets/swebenchpro-nogo`. Restarting mid-trial would have discarded up to
an hour of already-paid agent work on four non-Go trials that survive the
switch anyway. Harbor skips completed trials in the same `jobs_dir`.

**Consequence for the study, stated plainly:** the SWE-bench-Pro arm on this
box covers Python / TypeScript / JavaScript only. Go is the largest non-Python
stratum in the sample (27 of 70), so its absence is a real limitation, not a
rounding error — the matched-triad composite fixture (`fixtures/composite/`)
carries the Go arm instead, where the toolchain runs natively. Reproducing the
Go SWE-bench-Pro subset requires real x86_64 hardware; seed 42 makes the
selection reproducible anywhere.

**TypeScript is provisional too.** `tutao` suffers a grader mismatch where the
suite passes but scores 0 because the expected test name embeds an assertion
count that shifts with the code. The reference harness does not show this.
Unlike "zero tests ran", "passed but mis-scored" has no clean structural
signature, so it is detected but not auto-excluded.

### Commit-attribution note (2026-09-07)

`scripts/dgx/build_nl2repo_tasks.py`, `triage_rewards.py`, and parts of this
README were authored by the NL2Repo-repair and triage workstreams but were
swept into commits `a107e6f` ("fix(task-layer): exclude trials where the
verifier ran zero tests") and `a208107` ("docs(dgx): record no-Go decision")
by a `git add -A scripts/dgx/` in a concurrent workstream. Those commit
messages do **not** describe the apt/Node repair or the triage classifier.
The content landed intact and is verified; history is left unrewritten
because the commits are already the shared base for later work. This note is
the correction of record.

### Problem 14: model-side 429 credential cooldown (not an environment bug)

Four trials died in opencode's **run** phase (not setup) with a ~1KB
`agent/opencode.txt` containing a single event: `All credentials for model
gpt-5.6-{terra,luna} are cooling down via provider codex`, HTTP 429,
`reset_seconds` ~7800-8800. Affected: `mechanicalsoup__qvyiCUS`,
`instance_tutao__tutanota-5181821__DD4qHmQ`,
`instance_gravitational__teleport__{bq6dyKb,iZwFoLH}`.

Scope check: **15 of 18** trials show cooldown text at least once, but only
those 4 died of it — the rest retried through. Live trials were confirmed
still streaming (opencode.txt at 100KB/43KB, updated within the minute), so
the cooldown is transient backpressure, not an outage. Nothing to fix in
code; these need re-running when the credential pool is warm.

Note for trajectory analysis: the two `gravitational` trials and the `tutao`
one have `reward.txt=0` but **no `trajectory.json`**, so they are useless for
behaviour scoring even though they look scoreable by reward alone. Any
re-run intended to feed `map_behaviour_to_task.py` must produce a trajectory,
not just a reward.

## 10. Observed: occasional per-trial agent stall (self-limiting, no action needed)

One trial (`instance_protonmail__webclients__cENF6s2`, luna) sat at ~4% CPU
with a **0-byte `agent/opencode.txt` for 73 minutes**. Diagnosis:

- `opencode` process alive, but its log stops after "project copy refresh done"
  and never reaches a `message=stream` line -- i.e. it never issued a model call.
- **Not rate limiting**: no 429/retry/timeout signals in the opencode log.
- **Not systemic**: the sibling protonmail trial on the *other* model was
  actively streaming at the same moment, and both jobs show healthy stream
  counts across trials (luna 1-34, terra 7-37 per trial).

So it is an isolated per-trial hang, not a model, endpoint, or rpm problem.

**It is self-limiting and needs no intervention:** the task's `timeout_sec =
3000` with `--agent-timeout-multiplier 2` gives a hard 6000s (100 min) cap, so
Harbor kills it ~01:55, and `--max-retries 1` grants one more attempt. Watch
for `AgentTimeoutError` in the job log to confirm the cap fired.

If stalls become frequent (say >10% of trials), that would change the picture
and warrant investigating opencode's startup path under emulation -- but a
single occurrence is expected noise at this concurrency.


### Problem 15: orphaned container survives Harbor's own trial reap

`instance_protonmail__webclients__cENF6s2` (luna) hit
`AgentTimeoutError: Agent execution timed out after 6000.0 seconds`. Harbor
reaped the *trial* correctly at 01:55 — `exception.txt` written, verifier
directory created, no `reward.txt` — but the **environment container was left
running**, still burning 103% CPU and 2.4GB an hour later.

The tell that distinguishes this from a live-but-slow trial: `agent/opencode.txt`
frozen at **0 bytes** while the container shows high CPU. A working trial's
opencode.txt grows steadily (the healthy siblings were at 142KB and 182KB,
touched within the minute). High CPU alone is not evidence of progress.

Why it mattered here beyond wasted compute: `switch_nogo.sh` gates on
`docker ps | grep instance` reaching zero before switching datasets. An
orphan that never exits blocks that drain **indefinitely** — the switch would
have sat until its 2h deadline and then fired mid-trial anyway, which is
exactly what the drain gate exists to avoid.

Resolved with `docker rm -f` on that one container after confirming from
`exception.txt` that the trial was already dead. Harbor's `--max-retries 1`
grants the instance another attempt.

**Check to run before trusting a drain gate:** cross-reference container
liveness against agent-log growth, not container status. A container in
`docker ps` is not proof a trial is alive.

## 11. IMPORTANT: exceptions live in result.json, not trial.log

A third failure class was missed for several hours because I was grepping
`trial.log`. **Harbor records trial-level failures in
`result.json -> exception_info`**, and a trial can fail there while `trial.log`
looks unremarkable. Any health check that greps only `trial.log` will silently
under-report failures. `triage_rewards.py` now reads `result.json`.

Census once that was fixed (34 trials so far):

```
ARTIFACT_APT_404                8   agent's install step 404s -> agent never runs
GENUINE_PASS                    8
INCOMPLETE                      6   still running
ARTIFACT_AGENT_SETUP_FAILED     4   other non-zero exit during setup
ARTIFACT_RuntimeError           2   the more-Itertools image-casing bug (fixed)
ARTIFACT_NO_TESTS_RAN           2   Go / qemu
ARTIFACT_AGENT_TIMEOUT          1   the 100-min stall, reaped as predicted
GENUINE_FAIL                    1
ARTIFACT_GRADER_NAME_MISMATCH   1
```

**18 quarantined vs 9 trustworthy.** Earlier per-language means in this file
were computed before APT_404/setup failures were detected and were therefore
too optimistic in their denominators; the current script supersedes them.

### Artifact C -- apt 404 on Debian 11 images (FIXABLE)

`opencode`'s setup runs `apt-get update && apt-get install -y curl bash
coreutils nodejs npm`. Several NL2Repo images are **Debian 11 (bullseye)**,
which is EOL and has moved to `archive.debian.org`, so the install dies with
`404 Not Found` and exit 100 -- **before the agent makes a single model call**.

Affected so far: deepdiff, flask-restful, graphneuralnetwork, pyperclip
(4 instances x 2 models = 8 trials).

**First attempted fix FAILED** (recorded so it is not retried): rewriting all
three sources to `archive.debian.org` still exits 100, because
`archive.debian.org` does **not** carry a `debian-security` suite for bullseye:

```
Ign:2 http://archive.debian.org/debian-security bullseye-security InRelease
E: The repository 'http://archive.debian.org/debian-security bullseye-security
   Release' does not have a Release file.
```

**Fix v2 VERIFIED WORKING** (tmux `apttest3`): point the main suites at the
archive **and delete the security lines**, which no longer exist anywhere for an
EOL release. Result: `exit=0`, `Setting up nodejs`, `node v12.22.12`,
`npm 7.5.2` -- i.e. the exact command that was failing now succeeds:

```dockerfile
RUN sed -i -e '/debian-security/d' -e '/security.debian.org/d' \
           -e 's|deb.debian.org/debian|archive.debian.org/debian|g' /etc/apt/sources.list \
 && printf 'Acquire::Check-Valid-Until "false";\n' > /etc/apt/apt.conf.d/99no-check-valid
```

Note on method: the *first* version of this test reported `exit=0` for the
"before" case -- it never reproduced the bug, because `>/dev/null 2>&1`
swallowed the real exit status. A test that cannot reproduce the failure cannot
validate the fix. The corrected test reproduces it (`exit=100`, 9 x 404) and is
what these results come from.

Unlike the Go problem this is a genuine environment fix, not a workaround that
changes what is measured: it only lets the agent's own install step succeed.

### Artifact D -- upstream model quota exhaustion (429 cooling down)

Four trials died with opencode exiting 1 after the endpoint returned **HTTP
429**:

```
"All credentials for model gpt-5.6-terra are cooling down via provider codex"
reset_seconds: 8776   (~2h26m)
```

This is **not** our rpm setting and not something a retry solves quickly -- it
is the upstream provider behind the gateway exhausting its credentials, with a
multi-hour cooldown. Three of the four fired at the *same minute* (00:03), i.e.
a thundering herd from 8 concurrent agents starting work together.

Both models responded 200 again on a later manual probe, so the cooldown
clears -- but any trial in flight when it hits is lost, and it will recur.

**Update -- this was a startup burst, not an ongoing bleed.** The count has
stayed at 4 with **zero new 429s in the following hour**, and the endpoint
probes 200. All four hit within ~16 minutes of the jobs starting, when 8 agents
began work simultaneously; once trials desynchronised the pressure disappeared.

So lowering concurrency is **optional, not urgent**. If you want to reduce the
risk of losing trials to a future cooldown, drop `n_concurrent_trials` 2 -> 1
(4 agents instead of 8) and stagger job starts -- wall-clock cost is modest
since emulation is usually the bottleneck. But restarting the running jobs to
achieve this would cost more than it saves right now.

Note `--max-retries 1` does retry these, but a retry that starts inside a
2.4-hour cooldown just fails again, so retries are not a real mitigation here.


### Apt fix: VERIFIED by outcome (2026-09-07 02:23)

The `archive.debian.org` + pinned-Node repair is confirmed working, not merely
"built without error". In `runs-fixup`:

```
flask-restful__6KAohgZ = 1.000000
flask-restful__VDLzPdk = 1.000000
flask-restful__3gjirmY = 0.000000   (nop-agent control, correctly 0)
```

`flask-restful` is a Debian 10 buster image and was one of the 8 instances
that previously died at agent setup with apt 404s before making a single model
call. Two real agent trials now reach the verifier and **solve the task**.
That is outcome-level proof: the environment fix restored measurability
without changing what is being measured.

Diagnosis was independently corroborated two ways: the image's `sources.list`
points at `deb.debian.org` for `bullseye`/`bullseye-security` (EOL, archived),
and the 8 failures are spread across ~2.5h (23:21 → 01:35) rather than
clustered — systematic, not a transient mirror outage.

### Concurrency lowered 2 -> 1 (2026-09-07 02:19)

Applied to all 7 configs. 12 trials had died with `NonZeroAgentExitCodeError`,
predominantly HTTP 429 `credentials cooling down via provider codex` with
~2.4h resets — three firing in the same minute from 8 concurrent agents. That
is upstream provider capacity, **not** our `rpm: 6` setting, so the fix is
fewer simultaneous agents rather than slower request pacing.

Deliberately not applied by restarting: running jobs keep their old value
until the `nogo-switch` relaunch picks up the new configs, so no in-flight
trial is killed to apply a throughput tweak.

**Label precision matters here.** These 429 deaths occur *mid-run*, not during
setup, and were initially mislabelled `ARTIFACT_AGENT_SETUP_FAILED`. They are
now `ARTIFACT_MODEL_QUOTA_429`. The two route to different owners: apt 404 is
ours to fix, quota exhaustion is the gateway's capacity.

### Apt fix v2 is unnecessary — the Node pin already bypasses apt entirely

A follow-up investigation found that `archive.debian.org` carries **no
`debian-security` suite for bullseye**, so rewriting that line to the archive
host still 404s and the security line must be *deleted*, not rewritten. That
finding is correct in isolation, and would matter for any image that reaches
apt.

**No image in this run does.** Measured across all 7 fixup trials
(`runs-fixup`), covering buster *and* bullseye bases:

```
deepdiff__fFcGCAa       reward=-         exc=no  apt_errs=0
deepdiff__sCBxcoN       reward=-         exc=no  apt_errs=0
more-Itertools__K2x9T4G reward=-         exc=no  apt_errs=0
more-Itertools__39Mm2jr reward=-         exc=no  apt_errs=0
flask-restful__6KAohgZ  reward=1.000000  exc=no  apt_errs=0
flask-restful__VDLzPdk  reward=1.000000  exc=no  apt_errs=0
flask-restful__3gjirmY  reward=0.000000  exc=no  apt_errs=0   (nop control)
```

`deepdiff` is the bullseye case — the one the v2 fix targets. Its trial.log
contains **zero `apt-get update|install` invocations**, and its
`agent/opencode.txt` is at 745KB updated within the minute, i.e. well past
setup and actively running.

The reason is the *other* half of the original repair: pinning Node v22 into
the image makes Harbor's `ensure_system_dependencies` probe succeed, and that
function **returns early without shelling out to apt**. The archive rewrite
was only ever defense-in-depth for something else in the image invoking apt;
nothing does.

**Conclusion:** the security-suite deletion is worth keeping in the generator
for correctness, but it is not blocking anything and no re-verification run is
needed. Zero exceptions across all 7 fixup trials.

### 429 urgency: correctly downgraded

All 4 quota failures hit within ~16 minutes of startup, when 8 agents began
simultaneously; none in the hours since, and endpoint probes return 200. A
startup burst, not an ongoing bleed. The concurrency 2->1 change already
applied to the configs stays (it costs nothing and removes the herd at the
next relaunch), but it needed no restart and none was performed.

## 12. Reconciliation: does the apt fix still matter? (both measurements were right)

The parent session measured `apt_errs=0` and **zero apt-get invocations** across
its 7 fixup trials; I measured **22 of 36 trials invoking apt-get**, including
all 8 APT_404 failures. Both are correct -- they were measuring *different
datasets*.

The fixup tasks (`datasets/nl2repo-fixup`) carry an extra Dockerfile layer that
installs a **pinned Node v22.23.2 from a checksummed official tarball**. Harbor's
opencode setup probes `command -v node && command -v npm` first and only falls
through to `apt-get install ... nodejs npm` when that fails. With Node
preinstalled the probe returns early, so **apt is never reached**:

```
MAIN  deepdiff  -> Running command: apt-get update && apt-get install ...   (404, exit 100)
FIXUP deepdiff  -> Running command: set -euo pipefail; if ldd --version ... (apt=0, 895 KB agent output)
```

**Conclusion for the 8 APT_404 trials:** they are recoverable *only* by
regenerating against a task definition that avoids the apt path. The Node-pin
approach is strictly better than my sources.list rewrite:

- it removes the dependency on any distro feed rather than repairing one;
- it is deterministic (pinned version + sha256), so it cannot drift;
- it sidesteps the fact that the images ship **Node v12.22.12 / npm 7.5.2**
  (what my apt fix installs) -- ancient, and a plausible source of further
  opencode failures.

My `archive.debian.org` fix is still worth keeping for correctness (any task
that *does* reach apt on an EOL base will now work, and deleting the
`debian-security` line rather than rewriting it is required -- that suite does
not exist on the archive). But it is the fallback, not the primary fix.

## 13. Final accounting: NL2Repo-Bench main jobs (20 trials, both finished ~4h)

```
10  REWARDED        (5 instances x 2 models, all scored)
 8  APT_404         (4 instances x 2 models: deepdiff, flask-restful,
                     graphneuralnetwork, pyperclip -- agent never ran)
 2  RuntimeError    (more-Itertools x 2: "Docker compose command failed" --
                     the image-name casing bug, fixed after these launched)
--
20  total -- fully accounted for, nothing unexplained
```

Rewards (identical instances across both models, which is itself a good
consistency signal):

```
paillier        1.000000 / 1.000000      sklearn    0.985714 / 0.985714
stamina         0.983871 / 0.983871      mootdx     0.666667 / 0.657143
mechanicalsoup  1.000000 / 0.000000
```

Only `mechanicalsoup` diverges between models, and the 0.000000 side is the
**429 quota** trial (`qvyiCUS`) -- an infrastructure loss, not a luna/terra
capability difference. Reward parity everywhere else suggests the harness is
measuring stably.


### Correction: apt DOES still matter — I measured the wrong dataset

An earlier entry above ("Apt fix v2 is unnecessary") generalized from the
**fixup** trials to all trials. That was wrong. Measured across both:

```
main nl2repo trials invoking apt-get:  18
fixup trials invoking apt-get:          0
```

Both observations were correct; they were of **different task definitions**.
The fixup Dockerfile preinstalls a checksummed Node v22.23.2 tarball, and
Harbor's `ensure_system_dependencies` probes `command -v node && npm` before
falling through to `apt-get install nodejs npm` — so the fixup path never
reaches apt, while the un-regenerated main path still does and still 404s.

**Consequence:** the 8 `ARTIFACT_APT_404` trials are **not** already fine.
They are recoverable only by regenerating those tasks against a definition
that avoids the apt path.

**Which fix is primary.** The Node pin, not the archive rewrite:

- it removes the distro-feed dependency rather than repairing it, and is
  deterministic (pinned version + sha256);
- the apt path, even when repaired, installs **Node v12.22.12 / npm 7.5.2**
  from bullseye — ancient, and a plausible source of downstream opencode
  failures. A "working" apt fix would have quietly shipped a Node three major
  versions behind what opencode expects.

Keep the `archive.debian.org` rewrite (with `debian-security` **deleted**, not
rewritten — that suite does not exist on the archive) only as a fallback for
any task that still reaches apt.

### NL2Repo final accounting — 20 trials, nothing unexplained

```
10  REWARDED
 8  ARTIFACT_APT_404      deepdiff, flask-restful, graphneuralnetwork, pyperclip (x2 models)
 2  ARTIFACT_RuntimeError more-Itertools x2 -- "Docker compose command failed" (casing bug)
```

No new failure classes. The 429s are not in this set; they hit SWE-bench-Pro
and `mechanicalsoup`, and `mechanicalsoup` still scored.

Cross-model parity on the rewarded trials is near-exact:

```
paillier        1.000000 / 1.000000     sklearn   0.985714 / 0.985714
stamina         0.983871 / 0.983871     mootdx    0.666667 / 0.657143
mechanicalsoup  1.000000 / 0.000000
```

Only `mechanicalsoup` diverges, and the zero side is the 429 quota trial
(`qvyiCUS`) — an infrastructure loss, not a luna/terra capability gap. That
parity is a useful stability signal for the harness itself.

## 14. Later-emerging artifacts (found after the NL2Repo jobs finished)

### apt 404 also hits SWE-bench-Pro (not just NL2Repo)
`ARTIFACT_APT_404` rose 8 -> 10 as `gravitational/teleport` trials landed on
both models. Their images are **bullseye** too, with 4 x `404 Not Found`. So the
EOL-Debian problem is not NL2Repo-specific -- any task whose base is an archived
Debian release and whose setup reaches apt will fail the same way. The Node-pin
fix (parent session's approach) covers these as well, since it stops setup ever
reaching apt.

Note these are *gravitational* trials, i.e. Go -- already unmeasurable here for
the qemu reason. They would need the Node pin **and** real x86 to yield data.

### `ApiRateLimitError` is mislabeled -- it is an OOM, not a rate limit
One trial (`instance_internetarchive__openli__bStsLW`, terra) is recorded by
Harbor as `ApiRateLimitError`. That label is wrong, and taking it at face value
would send a future investigator hunting a quota problem that does not exist:

```
exception : ApiRateLimitError, "Command failed (exit 137): ... opencode run ..."
429 markers in opencode.txt : 0        (a real quota failure leaves "cooling down")
opencode.txt                : 333 KB   (the agent had been working normally)
task memory_mb              : 4096
host free memory            : 54 GB    (so the HOST was not short of memory)
```

**Exit 137 = 128 + 9 = SIGKILL.** With no 429 markers, plenty of host memory,
and a hard 4096 MB per-task cap, this is the container's cgroup OOM-killing
opencode -- `internetarchive/openlibrary` is a heavy Python repo and opencode
holds a large context. Compare the genuine quota failures, which carry
`"All credentials ... are cooling down"` and `statusCode: 429` (see Artifact D).

**Implication:** distinguish these two. A real 429 is a provider capacity issue
that resolves on its own; an OOM is fixed by raising `memory_mb` for that task.
`triage_rewards.py` currently trusts Harbor's exception type here and will
report it as `ARTIFACT_ApiRateLimitError`; treat that verdict as
"agent killed -- check for exit 137 and 0 x 429 markers before assuming quota".

## 15. Why TypeScript still has zero trustworthy data (4 trials, 4 different artifacts)

All 17 TS/JS instances are measurable in principle -- the language is not
blocked the way Go is -- but every TS trial completed so far has been lost to a
*different* artifact:

```
protonmail cENF6s2  ARTIFACT_AGENT_NEVER_STARTED       0-byte opencode.txt, 100 min
protonmail t9zVbpW  ARTIFACT_TIMEOUT_BUDGET_TOO_SMALL  384 KB, killed mid-step
tutao      rCo7Tw   ARTIFACT_GRADER_NAME_MISMATCH      tests passed, name unmatched
tutao      DD4qHm   ARTIFACT_MODEL_QUOTA_429           provider cooldown
```

This is bad luck rather than a systematic TS problem, but it means **no TS
conclusion can be drawn yet**, and the per-language table correctly shows
nothing rather than a fabricated 0.000.

### AgentTimeoutError conflates two different failures
The two protonmail trials shared one exception type but are not the same event,
and they need opposite responses:

- `cENF6s2`: **0 bytes** of agent output over the full 100 minutes -- the agent
  never issued a model call (the startup hang in section 10). Retrying is the
  right response; more time would not have helped.
- `t9zVbpW`: **384 KB** and still completing steps at the cutoff (last record is
  a `step-finish` with 62 120 tokens and cache reads). Genuine work, truncated.
  Here the budget really is too small: `timeout_sec = 3000` x2 = 6000 s, and
  `protonmail/webclients` is a large monorepo whose file operations are slow
  under emulation.

`triage_rewards.py` now splits these into `ARTIFACT_AGENT_NEVER_STARTED` and
`ARTIFACT_TIMEOUT_BUDGET_TOO_SMALL` by output size, so the fix is obvious from
the verdict. If TS trials keep hitting the cap, raise
`--agent-timeout-multiplier` from 2 to 3-4 for the SWE-bench-Pro jobs.

### Go containment confirmed
All 10 `ARTIFACT_NO_TESTS_RAN` are Go, and no non-Go trial has ever landed in
that class. The qemu defect is exactly as scoped -- it has not leaked into
Python, TypeScript or JavaScript.

## 16. Zero tests is not automatically an artifact (correction from the parent session)

`triage_rewards.py` classified any trial with `output.json == {"tests": []}` as
`ARTIFACT_NO_TESTS_RAN`. That rule is too broad. The parent session found, in
the reference corpus, that some zero-test trials are **pytest collection
errors** -- the agent's own patch broke an import, so nothing could be
collected. That is a *genuine model failure* and must stay in the scored set;
excluding it discards real signal (narrowing the exclusion moved
`premature_stop` to the strongest result in their mapping).

Two further corrections to what I had written earlier:

- The zero-test artifact is **not Go-exclusive in general**. The reference
  bundles contain 31 TypeScript and 6 Python zero-test trials. It is Go-only
  *in these DGX runs*, which is a fact about this hardware, not about the
  benchmark.
- So "Go containment breaking" would not have invalidated anything. My monitor
  alert on that was also a false positive: it matched the indented summary
  counter line (`  ARTIFACT_NO_TESTS_RAN    16`) and read "16" as a language.
  Detail rows start at column 1; the fixed check anchors with `^`.

The classifier now checks the verifier stdout for `ERROR collecting`,
`ImportError`, `ModuleNotFoundError` or `errors during collection` before
quarantining a zero-test trial, and scores it `GENUINE_FAIL` when present.

**Verified against the current DGX runs: zero reclassifications** -- all 16
zero-test trials there are Go runtime crashes with no collection error, so the
counts are unchanged. The guard matters for future runs and for any re-analysis
of the reference corpus.

## 17. Go-free switch: AUTHORISED and armed (v2)

The user approved switching SWE-bench-Pro to the 43-task Go-free dataset; the
cost projection in section 15 is what informed it (2.1 trials/h/job, ~34 Go
trials remaining ~= 8h of the projected 24h producing nothing measurable).

Armed by the parent session as `switch_nogo_v2.sh`, tmux `nogo-v2`, log
`logs/nogo-v2.log`. **This is expected automation -- do not escalate it as
unattributed.** Two fixes over the version that was killed:

1. **No deadline.** v1 switched after 2h regardless of drain, which would have
   killed live trials. v2 waits indefinitely for a real drain.
2. **Orphans excluded from the live count.** A trial is live only if it has
   neither a reward nor an `exception.txt`. Harbor reaps a timed-out trial but
   leaves its container running at ~100% CPU forever; counting those would
   block the drain permanently.

On firing it kills both `dsm-swebenchpro-*` sessions, repoints the configs at
`datasets/swebenchpro-nogo`, and relaunches at concurrency 1. Harbor skips
completed trials in the same `jobs_dir`, so the existing rewards survive.

Monitoring adjusted accordingly: watching relaunch completion (a failed
relaunch would silently end the run) and orphaned containers (each blocks the
drain); Go-containment watch dropped as moot post-switch.


### Concurrency restored to 2 before the switch relaunch (2026-09-07 07:51)

The 2->1 drop was applied when 429 quota failures looked like an ongoing
bleed. They were not. All four cluster at **00:03-00:19** — a thundering herd
from 8 agents starting simultaneously — with **none in the 7.5h since**, and
endpoint probes returning 200 throughout.

Leaving concurrency at 1 through the relaunch would have roughly halved
throughput against ~16h of remaining non-Go work, buying nothing: the pressure
it guards against was a startup transient, and the relaunch itself is the only
moment that recreates a simultaneous start. Restored to 2 in the
`swebenchpro-*` configs before `switch_nogo_v2` fires, so the relaunch picks
it up.

If 429s do reappear after the relaunch, staggering the two job starts is the
better lever than halving concurrency permanently — it removes the herd
without paying for it in wall-clock for the rest of the run.

### Problem 16: a drain gate on an unreachable condition never fires

`switch_nogo_v2.sh` waited for the live SWE-bench-Pro trial count to reach
zero. It never will. With ~50 tasks still queued per job, Harbor backfills a
new trial the instant one completes, so the count oscillates rather than
settling — observed directly in the log:

```
08:08  3 live trial(s); waiting
08:13  4 live trial(s); waiting
08:18  4 live trial(s); waiting
```

The 4→3→4 bounce is the tell: that is not slow progress toward zero, it is a
steady state. Harbor's launcher exposes no `--drain` or graceful-stop flag
(only timeout multipliers and `--max-retries`), so "wait for quiet" is not
achievable while work remains queued.

**Replaced with a low-water gate** (`switch_nogo_v3.sh`): switch as soon as no
in-flight trial has more than ~20KB of agent output, with a 90-minute cap.
Rationale — a trial at 0B is still in setup and loses nothing; one at 300KB is
mid-reasoning and worth waiting out. Crucially, **every in-flight task is
re-queued by the relaunch**: Harbor skips only *completed* trials, so an
interrupted trial is re-run, not dropped from the sample. That makes the
tradeoff "a few minutes of duplicated agent work" against "~8h of unscoreable
Go spend," which is not close.

Verified before arming: `peak_live_bytes()` returned 297874B against a
largest-in-flight of ~293KB, i.e. it correctly refuses to switch right now.

**General lesson:** when arming a gate, check that its condition is reachable
under the system's own steady-state behaviour. The v2 gate was safe in the
sense that it would never destroy work — and useless for exactly the same
reason.

### Problem 17: an agent cat'd a binary into its transcript (198MB)

`instance_internetarchive__openli__3VLU8dC` grew its `opencode.txt` to
**198MB at ~25MB/min**. The tail is raw x86 machine code — the agent dumped a
binary file into its own output. 33% of the last 200KB is non-printable.

This is a genuine (if pathological) agent behaviour worth noting on its own:
an agent exploring a repo can destroy its own context and burn tokens by
`cat`-ing a compiled artifact. Disk was never at risk here (2.0T free).

**It also broke the low-water gate**, which used raw file size as a proxy for
"how much reasoning would be lost on interrupt". Byte count does not
distinguish reasoning from garbage, so this single trial pinned the gate open
and it would have waited out its full cap for no reason.

Fixed: `peak_live_bytes()` now measures **printable bytes over a bounded 2MB
tail** rather than raw size. Effect on the live measurement was immediate:

```
before  198,544,910 B
after     1,360,406 B
```

The 2MB cap also keeps the check cheap when a transcript is enormous.

**Lesson:** a heuristic that stands in for "how much work would be lost" must
be robust to output that is large but worthless. Prefer a bounded, filtered
measurement over a raw size whenever an agent controls what lands in the file.

## 18. Agent behaviour worth instrumenting: self-inflicted context destruction

Found by the parent session while fixing its drain gate, verified here.

Trial `instance_internetarchive__openli__3VLU8dC` grew `agent/opencode.txt` to
**199,405,070 bytes (~199 MB)** at roughly 25 MB/min by `cat`-ing a compiled
binary into its own transcript. About a third of the tail is non-printable
x86: a 2 MB tail contains only **1,360,406 printable bytes**.

This is an *agent* failure mode, not infrastructure: the agent destroys its own
context and burns tokens by dumping a build artifact. No current DSM-AE
instrument detects it, though it sits near the `thrash_edit` / `read_loop`
family. A candidate signal is cheap and specific:

    non-printable ratio of a bounded tail of agent output, or
    per-step observation growth rate (bytes/min) far above the session median

Two things make it more interesting, both checked here rather than assumed:

1. **It still scored `reward=1`.** The agent recovered and solved the task. So
   this behaviour is *not* visible in the outcome oracle at all -- exactly the
   kind of behavioural deficit that a task-success metric cannot see, which is
   the premise of the behaviour->task mapping.
2. **It does not contaminate the ATIF artifact.** `trajectory.json` is
   **108 KB**, well-formed `ATIF-v1.7`, 15 steps, largest step 43 KB. The dump
   lives only in the raw `opencode.txt` stream. So `src/dsm_ae/harbor/` ingests
   this trial normally and the corpus is not polluted -- but equally, **an
   instrument reading only `trajectory.json` can never detect this behaviour**.
   Catching it requires looking at the raw agent stream.

### Correction to section 17's monitoring note
I described the v2 gate as having "died silently". It did not die -- the parent
session **killed it deliberately** because its condition was unreachable: it
waited for live trials to reach zero, but with ~50 tasks still queued Harbor
backfills as soon as one finishes, so the count oscillates (4->3->4 in its own
log) and never settles. Harbor exposes no graceful-stop flag. The observable
symptom (a gate that can never fire) was real and worth flagging; the cause was
a deliberate kill, not a crash.

v3 replaces the unreachable "zero live trials" condition with a **low-water
mark**: switch once the most-advanced live trial holds <= 20 KB of *printable*
agent output, capped at 90 min. Measuring printable bytes over a bounded 2 MB
tail rather than raw file size is what stops the 199 MB binary-dump trial from
pinning the gate open forever (198,544,910 B -> 1,360,406 B on the same
instant).

**Verified:** Harbor does re-queue interrupted trials, so the deadline path is
safe. The two protonmail trials killed in the v1 episode reappeared as fresh
attempts (`kJq8BYM`, `WPXbubJ`), both progressing. Re-queueing preserves the
*task*, not the *outcome* -- a retried trial can still fail for its own reasons.

## 19. THE SWITCH FIRED AND THE RUN IS DOWN (needs a decision)

At 09:40 the v3 gate hit its 45-minute cap and switched. The relaunch **failed**
and **all four benchmark jobs are now stopped**. No data was lost, but nothing
is running.

### What happened

```
09:40 waited 45m (peak 585844B); switching anyway
09:40 stopping swebenchpro sessions
09:41 repointing configs at swebenchpro-nogo
09:41 relaunching ... LAUNCHED both sessions
09:41 post-relaunch: sessions=0 harbor_procs=1
```

Both relaunched jobs died within a second:

```
FileExistsError: Job directory /home/bmc/dsm-dgx/runs/swebenchpro-gpt56terra
already exists and cannot be resumed with a different config.
```

Confirmed in `harbor/job.py:248-257`: on resume Harbor compares the **entire
stored JobConfig** to the new one and refuses on *any* difference.

### The assumption that broke

The switch plan rested on "Harbor skips completed trials in the same
`jobs_dir`, so the existing rewards survive". That is true **only when the
config is byte-identical**. Changing `datasets[].path` from `swebenchpro` to
`swebenchpro-nogo` is exactly the kind of change it rejects -- so resuming into
the same `jobs_dir` with the new dataset can never work. The reuse that made
the switch cheap is the same mechanism that forbids it.

The tmux server is also gone entirely (`no server running`), so the NL2Repo
sessions went with it; those two jobs had already finished, so nothing was lost
there.

### State: data intact, nothing running

```
48 reward.txt preserved   nl2repo luna 5, terra 5; swebenchpro luna 19, terra 19
python n=24 mean=0.803    unchanged by the failure
4 orphaned env containers still up
tmux sessions: none       harbor processes: 0
```

### Options (NOT actioned -- reporting only)

1. **New `jobs_dir` for the nogo run** (e.g. `runs-nogo/`). Cleanest: leaves the
   48 existing rewards untouched and lets the 43 non-Go tasks run under a config
   Harbor accepts. Cost: the ~19 non-Go trials already completed would be re-run,
   since the skip logic is per-`jobs_dir`.
2. **New `job_name`** (e.g. `swebenchpro-nogo-gpt56terra`) with the same
   `jobs_dir`. Harbor keys the directory off `job_name`, so this sidesteps the
   config comparison while keeping everything under `runs/`. Same re-run cost.
3. **Revert the configs to `datasets/swebenchpro`** and relaunch unchanged. The
   original jobs would resume and skip completed trials -- but that undoes the
   approved Go-free switch and resumes burning Go trials.

Option 2 looks best: it preserves the existing rewards, satisfies Harbor's
constraint, and keeps the approved Go-free scope. The re-run cost is real but
small next to the ~8h of Go work the switch avoids.


### Problem 18: Harbor cannot resume a job dir under a changed config

The Go switch fired at 09:41, repointed the configs, and relaunched — and both
jobs died in under a second:

```
FileExistsError: Job directory .../runs/swebenchpro-gpt56terra
already exists and cannot be resumed with a different config.
```

Source: `harbor/job.py:253` — `if existing_config != self.config: raise
FileExistsError(...)`. Harbor compares the **entire stored JobConfig** on
resume and refuses on *any* difference. Repointing `datasets[].path` at
`swebenchpro-nogo` is exactly such a difference.

**This invalidated the assumption the whole switch plan rested on.** Every
earlier note here said "Harbor skips completed trials in the same `jobs_dir`,
so finished work survives the relaunch." That is true *only when the config is
byte-identical*. The reuse that made the switch look cheap is the same
mechanism that forbids it. The claim should have been checked against
`job.py` before the switch was armed, not after it failed.

**Also correcting an earlier diagnosis of mine:** I first attributed this to
the tmux server dying and taking the jobs with it. Wrong — tmux went down
*because* both jobs exited immediately; the server had no remaining sessions.
The dead tmux was a symptom, not the cause.

### Recovery: new job_name + seeded trial dirs

Chosen over a bare new `job_name` (which would re-run ~20 completed non-Go
trials, ~10h of duplicated agent time) and over reverting the switch (which
would resume ~8h of unscoreable Go spend).

`reseed_nogo.sh` copies completed **non-Go** trial dirs from
`runs/swebenchpro-gpt56*` into `runs/swebenchpro-nogo-gpt56*` so Harbor's
per-trial skip logic finds them. Go trials are deliberately not seeded — they
are unscoreable here and absent from the nogo dataset. The script is
idempotent.

Result:

```
gpt56terra: seeded 10 (Go skipped 9)
gpt56luna:  seeded 10 (Go skipped 9)
relaunched -> 12 trial dirs each, 10 rewards each preserved
             15 harbor procs, both sessions alive
```

Harbor added new trials alongside the seeded ones rather than restarting them,
confirming the seeding held. Jobs launched with `nohup` from outside any tmux
session this time, so no gate script's exit can orphan them.

## 20. Go containment BROKEN -- nodebb (JavaScript) also unmeasurable

I asserted several times that every zero-test trial was Go. **That is no longer
true**, and the earlier claim should be treated as scoped to the data available
at the time, not a property of the benchmark.

Four `nodebb` (JavaScript) trials are now `ARTIFACT_NO_TESTS_RAN`. The cause is
the same emulator class as Go, but a different victim:

```
verifier/run-script-stderr.txt:
qemu: uncaught target signal 11 (Segmentation fault) - core dumped
/tests/run_script.sh: line 4: 5999 Segmentation fault (core dumped) \
    redis-server --daemonize yes --protected-mode no --appendonly yes
cp: cannot stat '/tmp/test/.': No such file or directory
```

`redis-server` segfaults under `qemu-x86_64`, so NodeBB's test harness never
starts. `run-script-stdout.txt` is **68 bytes** -- the runner announces
"Running selected tests: test/i18n.js test/user.js test/messaging.js" and
produces nothing more. The verifier then reports `Required tests: 3510,
Passed tests: 0`.

This is **not** a collection error (the section 16 guard correctly does not
rescue it) and **not** a JavaScript weakness. It is a service dependency dying
under emulation, exactly parallel to the Go runtime crashing.

### What this changes

- The emulation problem is **not Go-specific**. It affects any task whose
  verifier needs a native binary that QEMU mishandles -- Go's runtime,
  `redis-server`, and plausibly other services (postgres, mongo) in tasks not
  yet reached.
- The Go-free dataset does **not** make everything measurable. `nodebb` is in
  the 43-task nogo set and still yields nothing: 4 of its 4 sampled instances x
  2 models are lost.
- Practical rule: `NO_TESTS_RAN` + a `qemu: uncaught target signal` in
  `run-script-stderr.txt` = emulator artifact, regardless of language. Worth
  checking stderr for that string before attributing any zero-test result.

### Current language picture

```
python       n=39  mean=0.776   measurable
javascript   0 usable           nodebb blocked by redis segfault
typescript   0 usable           6 INCOMPLETE (in flight), 4 lost to assorted artifacts
go           0 usable           runtime crash (sections 9, 15)
```

TypeScript is still the open question: it has never been blocked by a
*systematic* cause, only by four different one-off artifacts, and six trials
are currently in flight. If those land, TS becomes the second measurable
language.


### Problem 19: the emulation defect is not Go-specific — retraction

Earlier notes here (and several status reports) asserted that every zero-test
trial was Go, and treated "Go containment" as established. **That was wrong.**

Four **nodebb (JavaScript)** trials produce `tests=0` because `redis-server`
segfaults under QEMU before NodeBB's harness starts:

```
qemu: uncaught target signal 11 (Segmentation fault) - core dumped
/tests/run_script.sh: line 4: 5999 Segmentation fault (core dumped) \
    redis-server --daemonize yes --protected-mode no --appendonly yes
```

Verified: all 4 have `reward=0`, `tests=0`, and the qemu signature in the
verifier output. `run-script-stdout.txt` is 68 bytes, then silence; the
verifier reports `Required tests: 3510, Passed: 0`.

**What this changes:**

1. The defect is **any task whose verifier needs a native binary QEMU
   mishandles** — the Go runtime, `redis-server`, plausibly postgres/mongo in
   tasks not yet reached. Language was a proxy, not the mechanism.
2. **The Go-free dataset does not make everything measurable.** nodebb is 4 of
   the 43 nogo tasks (~9%), so the switch's benefit is smaller than the
   estimate used to justify it. It still avoided ~8h of Go spend; it does not
   deliver a fully measurable remainder.
3. JavaScript joins Go as unmeasurable on this hardware, leaving Python
   confirmed and TypeScript the open question.

`ARTIFACT_QEMU_SIGNAL` now detects this by stderr signature rather than by
language, so a future victim (postgres, mongo) is caught without anyone
re-deriving the pattern.

**Method note.** The reference corpus had already shown zero-test trials in
TypeScript and Python, not just Go — that was flagged and recorded as a fact
about the *corpus*. It was actually a fact about the *failure mode*, and
reading it narrowly is what let the too-strong containment claim survive as
long as it did. A counterexample to a claim is worth more attention than a
tally of confirmations.

## 21. Post-recovery check: the re-run cost is real, but the data is not double-counted

The recovery used **option 2** (new `job_name`, same `jobs_dir`), which worked:
all 48 pre-switch rewards survive and the nogo jobs are producing new ones
(68 total). Two things worth knowing about the resulting run directory:

### Duplicate trial names are expected, and harmless to the statistics
`runs/` now holds **92 trial dirs under 72 unique names**: 20 trials appear in
both an original `swebenchpro-gpt56*` job and a `swebenchpro-nogo-gpt56*` job,
because Harbor's skip logic is per-`job_name` and the new name starts an empty
slate.

Checked rather than assumed -- **no trial has two reward files**:

```
duplicated trial names        20
trials with two rewards        0
reward in original job only   20
reward in nogo job only        0
```

So the per-language means are not inflated by counting a trial twice. The nogo
copies are re-attempts still in progress; if any of them completes, that name
*will* hold two rewards and the mean would double-count. Worth re-checking
before publishing any final number:

```bash
find runs -maxdepth 3 -path "*/verifier/reward.txt" | sed 's|.*/\([^/]*\)/verifier.*|\1|' \
  | sort | uniq -d        # should print nothing
```

### The cost of option 2, quantified
All 20 duplicated trials already had a reward in the original job. The nogo jobs
are therefore re-running ~20 trials of already-successful work -- the re-run cost
I flagged when proposing the option, now measured rather than estimated. Against
the ~8 h of Go trials the switch avoids it is still the right trade, but it is
not free.

### `GRADER_NAME_MISMATCH` growth is not a spreading defect
The count went 2 -> 4, but all four trials are the **same task**
(`instance_tutao__tutanota-5181821...`) re-attempted in the nogo jobs. The
section 15 finding stands: exactly one task of the 43 is affected.

## 22. End-to-end retrieval VERIFIED (pull -> adapter, no code changes)

Tested the actual deliverable rather than assuming it, using a finished job:

```bash
./scripts/dgx/pull_results.sh                        # lists all 6 job dirs,
                                                     # incl. the new -nogo- ones
./scripts/dgx/pull_results.sh nl2repobench-gpt56terra # -> 11 MB tar.gz
```

Extracted and fed to the real adapter (`src/dsm_ae/harbor/adapter.py`,
untouched):

```
load_run(...) -> 4 trials
  mootdx__A4Ffnfq     reward=0.657143  tools=33  lang=python
  paillier__9PjvQko   reward=1.0       tools=37  lang=python
  sklearn__JbWdoFH    reward=0.985714  tools=26  lang=python
  stamina__raj93bQ    reward=0.983871  tools=26  lang=python
```

Rewards, tool-call extraction and language tagging all come through correctly,
so the DGX output layout is adapter-compatible with no code changes -- the
original requirement.

### Caveat: the adapter silently skips incomplete trials
Of the 10 instance dirs in that bundle, only 4 carry the full
`agent/trajectory.json` + `verifier/reward.txt` + `result.json` trio:

```
4 dirs  all three files          -> loaded
1 dir   reward + result, no traj -> skipped
5 dirs  result.json only         -> skipped
```

`load_run` yields 4 and says nothing about the other 6. That is reasonable
behaviour, but it means **`len(load_run(...))` is not the trial count** -- a
run whose agents all failed setup would load as an empty, entirely healthy-
looking corpus. Always cross-check against `triage_rewards.py`, which counts
every trial dir and names the reason each one is missing.

The 6 skipped here are the known APT_404 (agent never ran, so no trajectory)
and casing-bug trials -- consistent with section 13's accounting, not new loss.

## 23. TypeScript is measurable -- second language unblocked

After many cycles of TS being lost to one-off artifacts, two TS trials scored
genuinely:

```
GENUINE_PASS  typescript  1.0000  8 tests  instance_protonmail__webclients__L2FDXk9  (luna)
GENUINE_PASS  typescript  1.0000  8 tests  instance_protonmail__webclients__L8U7f5a  (terra)
```

Both really executed 8 tests and passed, so TypeScript joins Python as
measurable on this hardware. That settles the open question from sections 15
and 20: TS was never systematically blocked -- it was under-sampled and unlucky.

**Do not read `typescript n=2 mean=1.000` as "TS success rate is 100%".** Both
rows are the *same task* (`protonmail/webclients-d3e51...`) run on the two
models -- one instance, not two. n=2 here means two model-attempts at a single
problem, which says nothing about TS difficulty in general. The same caveat
applies to every early per-language mean in these runs, Python's included: the
denominator counts model-attempts, and instances are heavily repeated across
the two models.

Language status:

```
python       n=41  mean=0.763   measurable
typescript   n= 2  mean=1.000   measurable (1 distinct instance)
javascript   blocked            redis-server segfault under qemu (section 20)
go           blocked            Go runtime crash under qemu (sections 9, 15)
```

So the final study covers **2 of 4 languages** on this hardware. Python and
TypeScript are real; Go and JavaScript need a genuine x86_64 host. That is a
larger gap than the original "defer Go" decision assumed -- JavaScript was
expected to work and does not.

## 24. Report distinct instances, not attempts (the n= in these tables is inflated)

`triage_rewards.py` reports `n=` as **model-attempts**, and every instance is
attempted by both models (plus any Harbor retries and the ~20 nogo re-runs from
section 21). So the headline n roughly doubles the real sample size:

```
lang         attempts   distinct instances
python             43                   13
typescript          2                    1
```

Python's `n=43` is **13 distinct problems**, not 43 independent observations.
Anything published from these runs should quote distinct instances, or state
explicitly that n counts attempts -- otherwise the sample looks 3x stronger
than it is. (13 instances is also well under the 26 Python instances sampled,
i.e. Python itself is only about half-covered so far.)

### A caution about ad-hoc recomputation
While checking this I wrote a quick script to aggregate rewards directly from
`reward.txt`, and it produced `typescript: 6 attempts, mean 0.333` against the
triage's `n=2 mean=1.000`. **The triage was right and the ad-hoc script was
wrong**: it counted the four `tutao-5181821` trials, which have a reward of 0
but are quarantined as `GRADER_NAME_MISMATCH` -- their tests *passed* and the
grader could not match the assertion-count-bearing name (section 15).

The lesson is that a reward file alone does not mean a trial is scoreable.
Every artifact rule in `triage_rewards.py` exists because some trial's reward
is misleading; bypassing it to "just average the rewards" silently reintroduces
exactly the artifacts this whole exercise was set up to exclude. Use
`triage_rewards.py` as the single source of truth, and extend it rather than
recomputing alongside it.

## 25. FINAL STATE: DGX rebooted, runs stopped, all data preserved

At **17:38 the DGX rebooted** (`last reboot`: Tue Sep 8 17:38; uptime 27 min at
time of check). That killed the tmux server and both nogo jobs. This was **not**
a harness failure -- the jobs were healthy and had been running ~15.5 h.

Evidence they were killed rather than finishing: job-level `result.json` has
`finished_at: None`, and `logs/swebenchpro-nogo-*.log` are 0 bytes (the tmux
panes died with the server before flushing).

**No data was lost. Rewards grew 68 -> 111:**

```
nl2repobench-gpt56luna         5     swebenchpro-nogo-gpt56luna    32
nl2repobench-gpt56terra        5     swebenchpro-nogo-gpt56terra   31
swebenchpro-gpt56luna         19
swebenchpro-gpt56terra        19     total                        111
```

### Final measured results

```
python       n=63 attempts   instances=18   mean=0.766
typescript   n=11 attempts   instances= 6   mean=0.455
javascript   blocked -- redis-server segfault under qemu
go           blocked -- Go runtime crash under qemu
```

TypeScript is now a real result rather than a single lucky instance: 6 distinct
problems, mean 0.455, clearly separated from Python's 0.766. Whether that gap is
a genuine language effect or sampling noise at n=6 is a question for the
analysis, not for this harness work -- but the two languages are now
independently measurable, which was the point.

### Artifact census (final)

```
GENUINE_PASS   54     ARTIFACT_NO_TESTS_RAN            16   (go)
GENUINE_FAIL   20     ARTIFACT_APT_404                 10
INCOMPLETE      8     ARTIFACT_QEMU_SIGNAL              6   (nodebb/redis)
                      ARTIFACT_MODEL_QUOTA_429          5
                      ARTIFACT_AGENT_OOM_KILLED         4
                      ARTIFACT_GRADER_NAME_MISMATCH     4   (1 task)
                      ARTIFACT_TIMEOUT_BUDGET_TOO_SMALL 3
                      ARTIFACT_RuntimeError             2
                      ARTIFACT_AGENT_NEVER_STARTED      1
```

74 of 125 trials are scoreable; every excluded trial has a named, diagnosed
cause. Nothing is quarantined as "unexplained".

### To resume (needs a decision -- NOT actioned)

The jobs would restart cleanly: Harbor skips completed trials within the same
`job_name`, and the configs are unchanged since the reboot, so
`~/dsm-dgx/launch_runs.sh swebenchpro-nogo-terra swebenchpro-nogo-luna` (with
the nogo config names) would resume from 111 rewards rather than restart. About
10 of 43 nogo tasks per model remain unattempted.

**Correction on binfmt after reboot.** I initially reported that the reboot
cleared the `qemu-x86_64` registration, based on
`/proc/sys/fs/binfmt_misc/` appearing empty over SSH. **That was wrong.** The
directory is empty *in the SSH session's mount namespace*; the emulator is
registered and working:

```
docker run --rm --privileged tonistiigi/binfmt   -> emulators: [python3.12, qemu-x86_64]
docker run --rm --platform linux/amd64 alpine uname -m   -> x86_64
```

Verified against the resumed run: **0 trials with `exec format error`**. So no
binfmt action is needed after a reboot on this box. The right check is a real
amd64 `docker run` or the `tonistiigi/binfmt` report -- **not** listing
`/proc/sys/fs/binfmt_misc/`, which is namespace-dependent and misleads over SSH.



### Problem 20: post-reboot — AppArmor is the only real blocker, not binfmt

The DGX rebooted ~17:38 (uptime confirmed), killing both nogo jobs after
~15.5h of clean running. No data lost: 111 rewards / 109 trajectories on disk,
terra 31/43 and luna 32/43.

Two symptoms appeared, and it is worth separating them because the obvious
reading is wrong:

```
/proc/sys/fs/binfmt_misc/   -> 0 entries      (looks like emulation is gone)
mount | grep binfmt_misc    -> not mounted
docker run --platform=linux/amd64 alpine  -> fails
```

The failure message is **not** `exec format error`. It is:

```
Could not check if docker-default AppArmor profile was loaded:
open /sys/kernel/security/apparmor/profiles: no such file or directory
```

`securityfs` is not mounted after the reboot, so Docker cannot load its default
profile and **no container starts at all** — emulated or native. The empty
`binfmt_misc` directory is a red herring: it lives under the same unmounted
filesystem, and emulation is in fact fine. Proof, on the rebooted host:

```
docker run --rm --security-opt apparmor=unconfined --platform=linux/amd64 \
  alpine uname -m
-> x86_64
```

So there is exactly **one** blocker. Reinstalling binfmt
(`tonistiigi/binfmt --install amd64`) is harmless but does not fix anything,
and reporting "binfmt is gone, reinstall it" would have sent the next person
down the wrong path.

**Fix requires root** (`sudo` is not passwordless here, `/etc/docker/daemon.json`
is not writable, and Harbor never sets `security_opt` so there is no
config hook):

```bash
sudo mount -t securityfs securityfs /sys/kernel/security
sudo systemctl restart docker
```

Resume is otherwise clean — Harbor skips completed trials under the same
`job_name`, so a relaunch continues from 111 rewards. ~10 of 43 nogo tasks
remain per model.

**Method note.** Two failing checks pointed at emulation; one passing check
(the same run with AppArmor bypassed) identified the real cause. When several
symptoms appear together after an environment change, the discriminating test
is the one that *isolates* a single variable, not the one that confirms the
most symptoms.

### Problem 21: seeding a job dir cannot survive a dataset change — abandoned

The recovery plan after the reboot was to keep the 63 seeded trial dirs so
Harbor would skip them. It does not work, and the attempt cost four failed
relaunches:

1. **Root-owned leftovers** (91 files) from containers the reboot interrupted.
   Harbor's cleanup of two incomplete trial dirs failed as `bmc`. Cleared with
   a root container; no completed trial affected.
2. **`ValueError: Existing trial config does not match planned job config`**
   (`harbor/job.py:361`) — every *existing* trial must match a *planned* one.
3. Seeded trials recorded `task path: .../datasets/swebenchpro/...` while the
   job plans `.../swebenchpro-nogo/...`. Rewrote all 40 stale references —
   **still failed**, because Harbor compares more of the trial config than the
   dataset path.
4. **Abandoned the seeding.** Moved all 63 dirs to
   `runs/archive-seeded-{terra,luna}` and relaunched clean. Both sessions came
   up, 15 harbor procs, trials starting.

**Cost, stated plainly:** the ~20 already-completed non-Go trials now re-run —
about 10 hours. The seeding existed precisely to avoid that, and instead spent
several relaunch cycles before failing. The general lesson: Harbor's
per-trial config identity is opaque and strict; **treat a job dir as bound to
the exact config that created it.** If the config must change, start a new job
dir and merge results at analysis time, not on disk.

The 111 rewards are intact in the archive and are valid data — they are simply
invisible to Harbor's skip logic. Merge them when pulling results.

### Correction: binfmt was never cleared by the reboot

An earlier note here (and a status report) claimed the reboot cleared the
`qemu-x86_64` registration, based on `/proc/sys/fs/binfmt_misc/` appearing
empty over SSH. **That was wrong.** The directory is empty in the SSH
session's mount namespace, not on the host:

```
tonistiigi/binfmt                              -> qemu-x86_64 present
docker run --platform=linux/amd64 alpine       -> x86_64
trials failing with "exec format error"        -> 0
```

The real post-reboot blocker was AppArmor (`securityfs` unmounted), which
stopped *all* containers, emulated or not. The empty binfmt dir was a
coincidental symptom that pointed the wrong way.

**Check to use:** a real `docker run --platform=linux/amd64`, or the
`tonistiigi/binfmt` report — never a listing of `/proc/sys/fs/binfmt_misc/`
from a remote shell.

## 26. Post-reboot restart: results archived, jobs re-seeded (no data loss)

After the reboot the runs were restarted, and the run directory was
reorganised at 18:59:

```
archive-seeded-luna           32 dirs / 32 rewards   <- prior nogo results, preserved
archive-seeded-terra          31 dirs / 31 rewards
swebenchpro-nogo-gpt56luna     3 dirs /  1 reward    <- fresh job, restarted
swebenchpro-nogo-gpt56terra    4 dirs /  2 rewards
nl2repobench-gpt56{luna,terra} 10 dirs /  5 rewards each
swebenchpro-gpt56{luna,terra}  23 dirs / 19 rewards each
                                        ---
                                        114 total (was 111)
```

The completed nogo work was moved aside into `archive-seeded-*` rather than
deleted, so the `swebenchpro-nogo-*` job dirs start near-empty and Harbor
re-attempts the remaining tasks. Checked, not assumed:

- **rewards went up (111 -> 114)**, so nothing was lost in the move;
- **0 duplicate rewarded trial names**, so the per-language means are still not
  double-counted (4 task prefixes appear in both archive and live dirs, but
  none has two reward files yet);
- **language stats unchanged** (`python n=63/18 inst`, `typescript n=12/6 inst`),
  because `triage_rewards.py` globs every directory under `runs/` and does not
  care about job naming.

**Implication for retrieval:** `pull_results.sh` lists whatever job dirs exist,
so `archive-seeded-*` will show up alongside the live jobs and must be pulled
too -- they hold the majority of the SWE-bench-Pro results. Do not assume the
`swebenchpro-nogo-*` dirs contain the run.

The duplicate-name check remains the thing to re-run before publishing, since
the archive/live overlap is exactly the situation that could start
double-counting:

```bash
find runs -maxdepth 3 -path "*/verifier/reward.txt" \
  | sed 's|.*/\([^/]*\)/verifier.*|\1|' | sort | uniq -d   # must print nothing
```


### Retrieval: `archive-seeded-*` holds the MAJORITY of SWE-bench-Pro results

After the reboot recovery, the run directories are split:

```
runs/archive-seeded-terra            31 dirs / 31 rewards   <- prior results
runs/archive-seeded-luna             32 dirs / 32 rewards   <- prior results
runs/swebenchpro-nogo-gpt56{terra,luna}   3-4 dirs          <- fresh, restarted
```

**Anyone pulling only `swebenchpro-nogo-*` gets ~4 trials and will think that
is the run.** `pull_results.sh` lists whatever job dirs exist, so the archive
dirs appear alongside the live jobs and **must be pulled too**. This is a
retrieval hazard, not a data hazard — nothing was lost in the move (reward
count went 111 -> 114 across the reorganisation).

**Double-counting is handled at ingestion, not here.** Four task prefixes now
appear in both the archive and the live dirs
(`instance_ansible__ansible-11c177`, `instance_internetarchive__openli`,
`instance_protonmail__webclients`, `instance_tutao__tutanota-5181821`), so a
re-attempted trial completing in the live job could in principle collide with
its archived copy. `load_run` in `src/dsm_ae/harbor/adapter.py` dedupes by
`trial_name` and keeps the scoreable copy, so the mapping is safe. Keep the
shell check as the pre-publication gate anyway — it is cheap and catches the
condition before the adapter has to resolve it:

```bash
find runs -maxdepth 3 -path "*/verifier/reward.txt" \
  | sed 's|.*/\([^/]*\)/verifier.*|\1|' | sort | uniq -d   # must print nothing
```

Currently clean (verified 2026-09-08 20:55).

## 27. VERIFIED: archives are adapter-compatible -- but the adapter does NOT filter artifacts

`pull_results.sh` lists all 8 job dirs including both `archive-seeded-*`, so
`--all` retrieves the full corpus. Fetched `archive-seeded-terra` (424 MB) and
loaded it with the real, unmodified adapter:

```
load_run(...) -> 31 trials of 31 dirs      (100%, vs 4/10 for the NL2Repo bundle)
by language   -> python 21, typescript 8, javascript 2
  instance_ansible__ansible-11c177  reward=0.0  tools=35  python
  instance_ansible__ansible-29aea9  reward=1.0  tools=26  python
  ...
```

Rewards, tool-call extraction and language tagging are all correct. The
SWE-bench-Pro archives -- which hold the majority of the results -- ingest
cleanly with no code changes.

### The critical caveat for analysis

**`load_run` returns every trial that has a reward file, including the ones
`triage_rewards.py` quarantines.** From this bundle it loads:

```
javascript  reward=0.0  nodebb-a5afad27__Lt65Cc     <- redis segfault, 0 tests ran
javascript  reward=0.0  nodebb-a5afad27__PBi6jL     <- redis segfault, 0 tests ran
typescript  reward=0.0  tutanota-5181821__RfRyjk    <- tests PASSED, grader name mismatch
typescript  reward=0.0  tutanota-5181821__rCo7Tw    <- tests PASSED, grader name mismatch
```

Those four zeros are **infrastructure artifacts, not model failures**. An
analysis that calls `load_run` and averages `t.reward` would silently conclude
that JavaScript scores 0.000 and that TypeScript is far weaker than it is --
precisely the fabricated language-deficit this whole exercise exists to
prevent.

The adapter is not wrong to do this; ingesting everything is the right default
for a loader. But **`triage_rewards.py` is the filter, and it must be applied
on top of `load_run`** before any per-language number is computed. The mapping
is by trial name:

```python
from dsm_ae.harbor.adapter import load_run
# keep only trials triage_rewards.py verdicts as GENUINE_PASS / GENUINE_FAIL
scoreable = {name for name, verdict in triage_verdicts.items()
             if verdict.startswith("GENUINE_")}
trials = [t for t in load_run(run_dir) if t.trial_name in scoreable]
```

Cross-check: the adapter loads 8 TypeScript trials from this bundle, while the
trustworthy table reports `typescript n=12 instances=6` across *all* runs --
the difference is exactly the quarantined ones.

## 28. Remaining work and what the finished run will actually contain

Python attempts kept rising (63 -> 69) while distinct instances stayed pinned at
18 and TypeScript did not move at all, which looked like the jobs re-running
work instead of advancing. They are advancing -- the flat instance count has a
different cause.

Authoritative counts (matching `result.json`'s `task_name` against the dataset
dirs; note `task_name` carries a `scaleai/swe-bench-pro__` prefix and the
casing differs, so both must be normalised):

```
nogo tasks attempted   22 of 43
remaining              21

remaining by language   python 13   typescript 5   javascript 3
full nogo set           python 26   typescript 13  javascript 4
```

So the run is roughly half-way through the Go-free set, and **most of the
remaining work is Python** (13 of 21). The flat instance count is simply
repeated attempts on already-seen instances draining before new ones start.

### Projected final coverage

If the remaining 21 tasks complete and their artifact rate matches what we have
seen:

- **python** ~18 -> up to ~31 instances: the only language that will be
  well-sampled.
- **typescript** 6 -> up to ~11 instances: usable, still small.
- **javascript** 0 usable, and the 3 remaining nodebb tasks will also yield
  nothing -- every nodebb instance dies on the redis segfault (section 20).

That last point is worth stating plainly: **finishing the run will not produce
any JavaScript data.** JS coverage on this hardware is structurally zero, not
merely under-sampled, so no amount of additional runtime changes it.

### Caution on prefix-based counting
An earlier count in this section used truncated trial-dir prefixes and reported
"11 of 43 attempted", which was wrong -- Harbor truncates trial dir names, so
distinct tasks collapse onto the same prefix (the same trap as section 24).
Always resolve task identity through `result.json`'s `task_name`.

## 29. The flat instance count is normal, not a stall (checked twice)

`instances=18` held steady for ~10 monitor cycles while Python attempts climbed
63 -> 74, which looked like the jobs retrying instead of advancing. Checked
directly; **they are healthy**:

```
harbor procs 6      sessions 2      env containers 4
config -> datasets/swebenchpro-nogo (43 tasks)
rewards in last 60m  3
rewards in last 3h  11      (~3.7/h across both jobs)
```

Every task in the live jobs appears exactly **2x**, which is the two models --
not a retry loop. Distinct tasks did stay pinned at 22 of 43 across the check,
but that is a sampling artifact of *when* the counts were taken: trials that
start together finish together, so distinct-task count advances in steps while
the attempt count rises smoothly between them.

The earlier framing in section 28 ("repeated attempts drain before new ones
start") was the right intuition but stated too loosely -- it implied a backlog
being worked off. The accurate statement is that **attempts and distinct tasks
advance on different clocks**: attempts increment per completed trial, distinct
tasks only when a genuinely new task begins, and with concurrency 2 that happens
in bursts of 2.

Practical note for anyone watching these runs: **do not infer a stall from a
flat `instances=` count.** The signals that actually indicate a stall are zero
rewards over a multi-hour window, `harbor_procs=0`, or containers at ~0% CPU
with frozen `opencode.txt` (section 10). All three were checked here and all
three are healthy.


---

## 30. Model-endpoint failure modes seen while running the rev2 pack arms (2026-09-12)

Three distinct infrastructure failures, none of them scientific. Recorded so they
are recognised rather than re-diagnosed.

### 30.1 Stale container image — `KeyError: Unknown pack '<name>_rev2'`

The queue worker runs inside the `dsm-ae` container. `docker-compose.yml` mounts
`data/`, `reports/`, `logs/` and `models.yaml`, but **not `src/`** — application
code is baked into the image. Any new pack, registry change or CLI flag is
invisible to the running worker until the image is rebuilt.

Symptom: every job fails within seconds, with the container's registry listing
only the packs that existed at image build time.

Check, then fix:

```bash
docker exec dsm-ae python3 -c "from dsm_ae.packs.registry import list_packs; print(len(list_packs(include_skipped=True)))"
./docker-build.sh --down && ./docker-build.sh     # --down first: the script refuses while :8765 is held
```

Note the rebuild bakes in the current working tree, uncommitted changes included.

### 30.2 Rate limiting — `RateLimitError` / `BadGatewayError`

`models.yaml` pins `rpm: 6` for the gpt-5.6 family. Running pack arms at
concurrency 16 produced `litellm.RateLimitError: Rate limit exceeded` and
`BadGatewayError`. **Concurrency 8 runs clean.** Do not raise it without also
raising rpm.

### 30.2b The Qwen failures were a RENAMED MODEL, not the TokenizerManager bug

**Correction to §30.3 below.** The alternating OK/timeout behaviour on the Qwen
endpoint was diagnosed as the SGLang TokenizerManager bug. It was not. On
2026-09-12 the gateway was found to advertise exactly one id:

```
GET /v1/models  ->  ['vllm/Qwen3.8-27B-NVFP4']
```

The id in `models.yaml` was the older `Qwen3.8-27B-NVFP4-BF16-LMHead`. Against
the current gateway that id returns:

| id sent | result |
|---|---|
| `Qwen3.8-27B-NVFP4` | **OK, 8/8 probes, 1.9-4.3s** |
| `vllm/Qwen3.8-27B-NVFP4` | OK |
| `Qwen3.8-27B-NVFP4-BF16-LMHead` | HTTP 400 "could not auto resolve a provider" |
| `vllm/Qwen3.8-27B-NVFP4-BF16-LMHead` | HTTP 403 `model_blocked` |

After switching to the current id the endpoint is stable — no alternating
timeouts at all. `models.yaml` now carries `Qwen3.8-27B-NVFP4` as the live
entry, keeps the old name as a deprecated alias pointing at the same backend so
historical run records stay resolvable, and drops `timeout` from 1800s to 300s
so a hung call fails its trial instead of occupying the single worker slot for
half an hour.

**Lesson:** when an endpoint alternates between fast success and long hangs,
check `GET /v1/models` against the id being sent *before* concluding the backend
is wedged. A renamed model can produce backend-failure-shaped symptoms.

Note also: Qwen is served by the `gx10-4-kng` gateway only. The
`arcyleung-ubuntu` gateway returns `unknown provider for model
Qwen3.8-27B-NVFP4` in ~0.1s for every Qwen id, on both its Tailscale and LAN
addresses. It is not an alternate route.

### 30.3 SGLang backends stop inferencing — TokenizerManager state loss

The Bifrost-fronted SGLang backends on the DGX/GB10 host eventually log:

```
Received output for rid but the state was deleted in TokenizerManager
```

and stop serving inference. This is a real failure mode reported by the
operator, but **§30.2b is the more common cause of the same symptoms** — rule
out a renamed model id first. The signature from a client is distinctive,
because the gateway stays healthy while only generation is dead:

| Probe | Result when this bug is active |
|---|---|
| `GET /v1/models` | OK, ~0.4s |
| bad model name | HTTP 400 in ~0.4s (Bifrost routing is alive) |
| `POST /v1/chat/completions` | **alternates**: ~1.7s success, then timeout past 120s |
| occasional | `502 dial tcp 172.17.0.1:8000: connect: connection refused` |

A restart only partially clears it — after one restart the success rate was 2/8.
Retrying does not help, since the backend is not dropping the request, it is
never completing it.

Consequences for the queue: `models.yaml` sets `timeout: 1800` for the Qwen
endpoint, so a single unlucky call stalls the single worker slot for 30 minutes,
and the job sits at `0/30 starting` while ignoring cancellation. Clear it with
`JobStore.mark_failed(job_id, reason)` and restart the container to free the slot;
queued jobs survive in SQLite.

**Operational rule:** probe an endpoint before enqueueing against it. A quick
alternating-timeout check costs seconds and saves hours of stalled queue:

```bash
for i in 1 2 3 4; do
  curl -sS -o /dev/null -w "%{http_code} %{time_total}s\n" -m 20 \
    -H "Content-Type: application/json" -H "Authorization: Bearer $KEY" \
    -d '{"model":"<model>","messages":[{"role":"user","content":"hi"}],"max_tokens":8}' \
    "$BASE/v1/chat/completions"
done
```

### 30.4 Transient per-model gateway flapping

Distinct from 30.3 and self-healing. On `arcyleung-ubuntu`, `gpt-5.6-terra` timed
out 3/3 on `/v1/chat/completions` while `sol` and `luna` answered in ~1.3s, then
recovered to 5/5 minutes later. It was reachable on `/v1/responses` while still
hanging on `/v1/chat/completions`, so check both paths before concluding a model
is down.

This is **not** DNS: the failure reproduced identically on the Tailscale name and
on the LAN address `http://192.168.2.15:8317/v1`. That LAN address is a valid
faster route to the gpt-5.6 models (`/v1/models` in 0.0s vs 0.4s), but it does
**not** serve Qwen — Qwen is on a separate host and is not in that gateway's
28-model list.

### 30.5 gpt-5.6-terra upstream outage (2026-09-12)

Distinct from the transient flap in §30.4, which self-healed. As of 2026-09-12
`gpt-5.6-terra` times out on **every** route tried:

| route | terra | sol (control) |
|---|---|---|
| Tailscale `/v1/chat/completions` | Timeout 15s | — |
| LAN `/v1/chat/completions` | Timeout 15s | **OK 0.9s** |
| LAN `/v1/responses` | Timeout 15s | — |

Since `sol` answers in under a second on the same gateway and the same call
shape, this is a per-model upstream outage rather than a gateway or network
problem. terra is excluded from the rev2 arms until it answers a probe.

### 30.6 Flaky DNS for cross-tailnet Funnel hosts (2026-09-15)

**Symptom.** Requests to `gx10-4-kng.tail22da2e.ts.net` (the Qwen gateway) fail
roughly half the time with `httpx.ConnectError: [Errno -2] Name or service not
known` / `socket.gaierror -2`. This is what killed `rev2-qwen27b-default-c8b`
and `rev2-qwen27b-none-c8c`.

**It is not the network, and not MagicDNS.** Measured on the workstation:

| Path | Result |
|---|---|
| `dig @100.100.100.100 <host> A` ×20 | **20/20 NOERROR** |
| `dig @100.100.100.100 <host> AAAA` ×20 | **20/20 NOERROR** |
| `resolvectl query <host>` | all four records, 118ms |
| **`socket.getaddrinfo()` (glibc)** | **9/15 ok, 6/15 gaierror -2** |

The DNS server answers every query correctly; glibc intermittently fails to
return the answer. On a failed curl, `time_namelookup` is `0.000000s` and total
is 0.063s — the resolver gives up instantly rather than timing out.

**Two compounding causes.**

1. **Unroutable AAAA records.** MagicDNS returns both A (Tailscale Funnel
   ingress, e.g. `199.38.181.54` = `ingress-nyc-01.tailscale.com`) and AAAA
   (`2607:f740:f::684`). This host has **no global IPv6**: no global address,
   no default IPv6 route. Every IPv6 attempt fails instantly. `curl -6` is 0/4;
   `curl -4` reaches the server (HTTP 401 from the gateway).

2. **Cross-tailnet lookups are the flaky ones — because they are not tailnet
   lookups at all.** Confirmed by comparing the two sides (2026-09-16):

   | From | Resolves to | getaddrinfo | curl to :10000 |
   |---|---|---|---|
   | workstation (tailnet `tailb940e6`) | `199.38.181.54` + AAAA — **public Funnel ingress** | 9/15 | ~50%, ~300ms |
   | DGX `gx10-102d` (tailnet `tail22da2e`) | `100.110.26.37` — **direct peer** | **15/15** | **10/10, ~50ms** |

   `gx10-4-kng` is a peer of `tail22da2e`, which the DGX belongs to and the
   workstation does not. From inside that tailnet MagicDNS returns the peer's
   `100.x` address and traffic goes over WireGuard. From outside, the name only
   resolves because the host publishes a **Funnel**, so MagicDNS hands back
   Tailscale's public ingress servers (`ingress-nyc-01.tailscale.com`) plus
   AAAA records this host cannot route. The flakiness is a property of reaching
   a foreign tailnet over public ingress, not of DNS being broken.

   Hosts in our own tailnet resolve reliably; the foreign tailnet does not:

   | Host | tailnet | getaddrinfo |
   |---|---|---|
   | `arcyleung-ubuntu.tailb940e6.ts.net` | ours (in `search`) | **12/12 ok** |
   | `gx10-4-kng.tail22da2e.ts.net` | foreign | 10/12, 2 × gaierror |

   A trailing-dot FQDN does not help, so this is not search-domain expansion.

**Mitigations, in order of effectiveness.**

- **Pin the address in `/etc/hosts`** (most reliable; removes the resolver from
  the path entirely). Note the Funnel ingress IP can change, so re-check it if
  the endpoint starts refusing connections:

      199.38.181.54  gx10-4-kng.tail22da2e.ts.net

- **`options single-request-reopen` in `/etc/resolv.conf`** serialises the A and
  AAAA queries instead of sending them in parallel: 13/15 vs 10/15 baseline.
  Caveat: `/etc/resolv.conf` is generated by Tailscale and warns
  "DO NOT EDIT THIS FILE BY HAND"; the change will be overwritten. Set it
  per-process with `RES_OPTIONS=single-request-reopen` instead.

- **Force IPv4** where the client allows it. This removes the unroutable-AAAA
  half of the problem but not the cross-tailnet resolver failures (IPv4-forced
  was still 4/10 in one sample), so it is not sufficient alone.

- **Keep `num_retries` ≥ 2 and `max_attempts` ≥ 3** on any job pointed at a
  cross-tailnet endpoint. A single gaierror must not discard a 29/30 run.

**Best fix: run cross-tailnet work from inside that tailnet.** The DGX is a
member of `tail22da2e`, so it reaches the Qwen gateway over WireGuard at
`100.110.26.37` with no ingress hop: 10/10 curls at ~50ms, versus ~50% at
~300ms from the workstation. Anything long-running against that endpoint should
be driven from the DGX rather than the workstation.

**Note on the Docker worker.** The queue worker runs inside the `dsm-ae`
container, which uses Docker's embedded resolver rather than the host's glibc +
MagicDNS path, and measured **12/12** successful lookups. Queue jobs are
therefore *not* affected by this bug — only host-side scripts and probes are.
That is why jobs fail on gateway 502s but rarely on `gaierror -2`.
