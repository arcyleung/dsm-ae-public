# DSM-AE Harbor Operator Guide

**Additive** migration: DSM-AE indicator packs are exported as standard Harbor tasks (schema 1.3) under `harbor_tasks/dsm-ae/<pack_id>/`.

This allows running syndromes under `harbor run` (portable layout) while preserving DSM-AE scoring, bootstrap, gates, Comparison UI, and reports via a thin bridge + import.

**Source of truth for packs remains the Python registry + pack code.** Harbor tasks wrap fixtures + instruction + verifier scoring.

## Pack → Harbor mapping

| DSM-AE                  | Harbor                          |
|-------------------------|---------------------------------|
| `IndicatorPack.id`      | `task.name = "dsm-ae/<id>"`     |
| system+user prompts     | `instruction.md`                |
| workspace fixtures/gold | `environment/fixtures/`         |
| `pack.run_trial` (agent)| Harbor agent phase (via `-a`)   |
| `pack.score`            | `tests/test.sh` → `reward.json` |
| k trials                | outer loop (k separate runs)    |
| LiteLLM `litellm.jsonl` | `/logs/agent/` → trajectories/  |
| Syndrome criteria       | `[metadata].syndrome_codes`     |

## Export all packs

```bash
python scripts/harbor_export_all_packs.py --out harbor_tasks
```

- Generates (or refreshes) `harbor_tasks/dsm-ae/<pack>/` for every pack in `list_packs()`.
- Uses **monorepo build context** (do **not** vendor full `src/` per-pack).
- `task.toml`, `instruction.md` (from pack SYSTEM), `tests/test.sh` (calls bridge), `environment/Dockerfile` + pack `fixtures/`.
- `_template/` and top `README.md` refreshed.

See also: `harbor_tasks/dsm-ae/README.md` (includes regeneration instructions).

## Run

### Mock / offline smoke (recommended for tests + CI; no live LLM)

```bash
python scripts/harbor_run_job.py \
  --job-id smoke-hello-001 \
  --model mock/well_attuned \
  --packs hello_metacog \
  --k 2 \
  --base /tmp/harbor-test   # optional sandbox
```

- Uses `pack_bridge` + `MockClient` + outer `k` loop.
- Produces `reports/harbor_runs/<job_id>/` (or your base).
- No docker / harbor CLI required.
- Always safe.

Direct per-trial (advanced):

```bash
python -c '
from dsm_ae.harbor.pack_bridge import prepare_workspace, score_workspace, write_reward
from pathlib import Path
ws = prepare_workspace("hello_metacog", Path("/tmp/ws"), 0, mock_persona="well_attuned")
m = score_workspace("hello_metacog", Path("/tmp/ws"), 0)
write_reward(m, Path("/tmp/ws/reward.json"))
print(m)
'
```

### Live (real agent + model; notes)

Requires `harbor` CLI + a supported agent (e.g. `claude-code`, oracle for mock inside harbor, or custom).

Example (from repo root so monorepo COPY works):

```bash
harbor run -p harbor_tasks/dsm-ae/hello_metacog \
  -a claude-code \
  -m openai/gpt-5.5 \
  --build-context . \
  --dockerfile harbor_tasks/dsm-ae/hello_metacog/environment/Dockerfile
  # ... other harbor flags for env, dataset, k, etc.
```

**Env vars for LLM / OpenAI-compat (CLIProxy etc):**

- `OPENAI_API_BASE` (e.g. `https://your-proxy/v1`)
- `OPENAI_API_KEY`
- Model id passed via harbor `-m` (or equivalent); appears in agent phase.

Harbor (or your wrapper) must forward these into the container for the agent process.

**Network policy (LLM runs):**

Default generated: `[environment] network_mode = "no-network"` (safe for smoke/oracle).

For live LLM agent that must call out:

Edit (or override at run) the task's `task.toml`:

```toml
[environment]
network_mode = "allowlist"
# allowed_hosts = ["your-proxy-host", "api.openai.com"]  # adjust for your OpenAI-compat / CLIProxy
```

Some Harbor setups allow `[agent]` section equivalent:

```toml
[agent]
network_mode = "allowlist"
allowed_hosts = ["..."]
```

See generated `task.toml` comments for full LLM profile guidance.

**Docker labels (required):**

Containers started for a job **must** carry:

```
--label dsm-ae.harbor.job=${JOB_ID}
```

(or harbor passthrough equivalent).

## Import rewards (Harbor → DSM-AE reports)

After a harbor run (mock or live), import into gates/bootstraps/findings shape for matrix / Comparison:

```bash
python -m dsm_ae.harbor.import_rewards \
  --job-id smoke-hello-001 \
  --model mock/well_attuned \
  --out reports/harbor/hello-001.json \
  --print
```

Or programmatic:

```python
from dsm_ae.harbor.import_rewards import import_harbor_run, reward_dir_to_report
rep = import_harbor_run("smoke-hello-001", reports_dir=Path("reports"))
# or reward_dir_to_report(path_to_job_root, model=...)
```

Imported reports feed the same `evaluate_findings` + gate matrix path.

## harbor_runs layout + artifacts

All outputs under (default):

```
reports/harbor_runs/{job_id}/
  meta.json                 # model, packs, k_trials, timestamps, extra
  rewards/
    <pack>__t0.json
    <pack>__t1.json
    ...
  trajectories/
    <pack>__t0/
      litellm.jsonl
      conversation.json
      traces.json
      scores.json
      meta.json
    ...
  logs/                     # raw /logs from harbor (agent + verifier)
  docker_cleanup.json
  reward.json               # optional top-level convenience
```

- `trajectories/` populated by `persist_trajectory` (copies from agent `/logs/agent/` if present, or from DSM-AE native save).
- For native DSM-AE runs (non-harbor): use `work/{job}/` + `reports/work/...` (separate).
- `harbor_run_job.py` (outer k loop) + `run_harbor_task` ensure layout.

## Docker cleanup (always)

**Never leave orphans.** Global constraint + implementation:

- After **every** Harbor task (success or fail), remove containers + anon volumes for the job.
- Label containers: `dsm-ae.harbor.job={job_id}`
- **Always** wrap execution with:

```python
from dsm_ae.harbor.runner import run_harbor_task
from dsm_ae.harbor.scripts... import ...  # or harbor_run_job

run_harbor_task(job_id=job_id, model=..., packs=..., task_fn=your_invoke)
# OR
python scripts/harbor_run_job.py --job-id ...
```

This:
- Calls `cleanup_docker_for_job(job_id)` in `finally`
- Writes `docker_cleanup.json` (counts + errors; safe if no docker)
- Records summary in `meta.json`

Idempotent; safe when docker absent.

Manual cleanup example:

```python
from dsm_ae.harbor.docker_cleanup import cleanup_docker_for_job
info = cleanup_docker_for_job("your-job-id")
```

See `src/dsm_ae/harbor/docker_cleanup.py`, `runner.py`.

## Trajectory paths

- **Inside container (agent phase):** `/logs/agent/litellm.jsonl` (and related) if the Harbor agent emits LiteLLM-style logs.
- **Persisted:** `reports/harbor_runs/{job}/trajectories/<pack>__tN/litellm.jsonl` etc via `persist_trajectory`.
- Verifier may also write under `/logs/verifier/`.
- Scoring bridge (`score_workspace`) **prefers** `trajectories/.../scores.json` (real `MetricResult`s) before falling back to mock trial.
- Native (non-Harbor) DSM-AE trajectories live under `work/{id}/` or configured `trajectory_dir`.

## Context windows (important for GPT + history stuffing)

When running agents that stuff long history / bloat prefixes (see `context_bloat.py`, bloat experiments):

- **Use operational Codex catalog values** (what the path actually enforces):
  - gpt-5.5: **272000**
  - gpt-5.6-*: **372000**
- **Do not** use the marketing API card 1.05M — it will cause spurious overflow / bloat failures on CLIProxy/Codex paths.
- Source: `reports/backfill/CONTEXT_WINDOWS.md`, `src/dsm_ae/context_bloat.py:_DEFAULT_WINDOWS`, `models.yaml` entries.
- The bridge + scoring do not change this; agent-side history construction must respect it.

## Full list of exported packs

See `dsm_ae.packs.registry.list_packs()` (22 packs at time of writing, including tier2 variants).

## Testing / CI (lightweight)

No heavy GitHub Actions invented (none existed at Task 7 time; `.github/` absent).

**Manual CI command (offline harbor smoke only):**

```bash
pytest tests/test_harbor*.py -q --tb=line
```

- All new tests must be offline (mock only).
- The full harbor test suite **must stay green**.
- Export produces deterministic files (no live harbor CLI needed).
- `test_export_skips_live_harbor_when_no_cli` documents that live `harbor run` is optional/skipped when CLI absent.

To validate a single pack smoke:

```bash
python scripts/harbor_run_job.py --job-id ci-validate --model mock/well_attuned --packs hello_metacog,tool_integrity_tier2 --k 1 --base /tmp/ci-harbor
```

Then optionally import and spot-check.

## Related code / scripts

- `src/dsm_ae/harbor/`: `pack_bridge.py`, `run_layout.py`, `runner.py`, `docker_cleanup.py`, `import_rewards.py`
- `scripts/harbor_export_all_packs.py`
- `scripts/harbor_run_job.py`
- `harbor_tasks/dsm-ae/`
- `tests/test_harbor_*.py`

See plan: `docs/superpowers/plans/2026-07-17-harbor-pack-migration.md`

## Status

Tasks 1-5 complete (bridge, layout, export, runner+cleanup, import, k-loop).  
Tasks 6 (LLM network + agent path docs) + 7 (CI+docs) add documentation + policy + operator guide.

**Cleanup is non-negotiable; network allowlist only for LLM paths; offline smoke for validation.**
