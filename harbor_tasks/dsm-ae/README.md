# dsm-ae Harbor Tasks (bulk exported)

All registered DSM-AE packs exported as Harbor tasks via `scripts/harbor_export_all_packs.py`.

## Layout (per pack under dsm-ae/<pack_id>/)
- `task.toml` — Harbor schema 1.3 + dsm_ae_pack, syndrome_codes, primary_metrics
- `instruction.md` — derived from pack SYSTEM + user templates
- `tests/test.sh` — always: `score_workspace(pack_id, Path("/app"), 0); write_reward(...) -> /logs/verifier/reward.json`
- `environment/Dockerfile` — monorepo style (see below)
- `environment/fixtures/` — **only pack-specific** gold files/contracts (hello contracts, notes.txt, etc). No dsm_ae/ source.
- `README.md` — per-pack pointer

## Critical: no src vendoring (Task 3 design fix)
Prior (Task 2 hello) vendored entire `src/dsm_ae` (~780KB+) into every task environment/.
**Do not do this.** It multiplies waste across 22+ packs.

Preferred Dockerfile (generated):
```dockerfile
FROM python:3.11-slim
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir -e .
WORKDIR /app
# pack-specific fixtures only
COPY harbor_tasks/dsm-ae/<pack>/environment/fixtures/ /app/
...
```
Build context **must be repo root**.

## How to run harbor with monorepo context
From the dsm-ae repo root (so COPY src reaches the shared package):
```
harbor run -p harbor_tasks/dsm-ae/<pack_id> -a oracle
# or with model, dataset, k etc.
harbor run -p harbor_tasks/dsm-ae/tool_integrity_tier2 -a claude-code -m anthropic/claude-...
```

If your harbor invocation uses explicit docker build context (recommended for monorepo):
```
harbor run -p harbor_tasks/dsm-ae/<pack_id> --build-context . --dockerfile harbor_tasks/dsm-ae/<pack_id>/environment/Dockerfile ...
```
(Exact flags depend on harbor version; -p points at task metadata, context provides src/ + pyproject.)

## Docker label + harbor_runs persist (Task 1b)
Containers **must** be labeled for cleanup:
```
docker ... --label dsm-ae.harbor.job=${JOB_ID}
# or harbor passthrough of labels
```

After run (agent + verifier), persist using:
```python
from dsm_ae.harbor.run_layout import init_run, persist_reward, persist_trajectory, persist_logs, finalize_meta
from dsm_ae.harbor.runner import run_harbor_task

root = init_run(job_id, model=..., packs=[pack_id])
persist_reward(root, pack_id, trial_index, json.load(open("/logs/verifier/reward.json")))
# trajectories from /logs/agent/* if captured during agent phase
persist_trajectory(root, pack_id, trial_index, agent_traj_dir)
...
finalize_meta(...)
```

Always wrap:
```python
run_harbor_task(job_id=job_id, model=..., packs=[pack], task_fn=invoke_fn)
```
Guarantees `cleanup_docker_for_job(job_id)` (removes labeled containers) + `docker_cleanup.json` in `reports/harbor_runs/{job_id}/`

Layout:
reports/harbor_runs/{job_id}/
  meta.json
  rewards/<pack>__tN.json
  trajectories/<pack>__tN/...
  docker_cleanup.json
  ...

## Regenerating
python scripts/harbor_export_all_packs.py --out harbor_tasks
(will overwrite; git rm any old vendored trees under environment/src if present)

Generated for all packs in registry.

## LLM agent path + network policy (Task 6)
- Default for smoke: `[environment] network_mode = "no-network"`
- For LLM agent runs: set `network_mode = "allowlist"` under `[environment]` (or `[agent]` per Harbor).
  Add `allowed_hosts = ["<proxy-host>", "api.openai.com"]` (OpenAI-compat / CLIProxy).
- Pass model + keys via Harbor env / docker: `OPENAI_API_BASE`, `OPENAI_API_KEY` (and model id via `-m`).
- Context windows: when agent stuffs history/bloat, use Codex operational (gpt-5.5: 272k, gpt-5.6: 372k) **not** the 1.05M marketing number. See reports/backfill/CONTEXT_WINDOWS.md .
- Docker label (required for cleanup): `--label dsm-ae.harbor.job={job_id}`
- **Cleanup always**: wrap with `run_harbor_task(...)` or `harbor_run_job(...)` (guarantees `cleanup_docker_for_job` + docker_cleanup.json even on failure).
- Smoke tests: offline mock only (`--model mock/well_attuned` or via harbor_run_job); no live LLM required for validation.
- Agent wrapper note: real agent phase uses Harbor-provided agent (e.g. `-a claude-code`); scoring re-uses `pack.score` / `RawToolLoopAdapter` logic only in mock path of pack_bridge. Trajectories (litellm.jsonl etc) land in `/logs/agent/` inside container; copied to harbor_runs trajectories/ by persist.