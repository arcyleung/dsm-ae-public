# DSM-AE Evaluation Queue + Comparison — Design Spec

**Date:** 2026-07-10  
**Status:** Draft for review  
**Goal:** Replace offline “edit models.yaml + run shell batch” with a **queued evaluation pipeline** so operators can enqueue models, watch progress, and compare results live.

---

## 1. Problem

Today evaluation is offline and process-oriented:

| Today | Pain |
|-------|------|
| `models.yaml` holds model ids + secrets + rpm | Secrets mixed with run intent; gitignored file is the only “registry” |
| Shell scripts (`run_full_suite_*.sh`) loop models | No shared queue, hard to pause/resume, easy to race the same model |
| `dsm-ae diagnose-batch --models a,b,c` | Sequential only; no persistence if the process dies mid-batch |
| HTML matrix regenerated manually / at end of scripts | Comparison lags; no “job status” surface |

**Desired:** operators **queue** model evaluation jobs; a **worker** drains the queue with rate limits; the **comparison matrix** updates as jobs complete.

Non-goals for v1:

- Multi-machine distributed workers / Kubernetes
- Multi-tenant auth / SaaS billing
- Replacing LiteLLM or packs
- Live streaming of every tool call (optional later)

---

## 2. Current architecture (anchors)

```
CLI (typer)
  └─ diagnose(model, packs, k, models_yaml, concurrency, rpm, …)
       ├─ resolve client from models.yaml / api_base / mock
       ├─ map_pool over (pack, trial) jobs
       ├─ bootstrap → gates → criteria findings
       └─ DiagnosisReport → MD/JSON under reports/
scripts/json_to_html_report.py
  └─ glob reports/**/*.json → dsm-ae-matrix.html
```

Reuse: `diagnose()`, `html-report`, pack registry, models.yaml resolution for **credentials only**.

---

## 3. Approaches considered

### A. Shell + file queue (minimal)

- Drop job JSON files into `queue/pending/`; a bash loop `mv`s to `running/` and invokes `dsm-ae diagnose`.
- **Pros:** zero deps. **Cons:** no good concurrency control across models, brittle status, poor UX.

### B. SQLite job queue + single worker process + thin HTTP UI (**recommended**)

- `EvalJob` rows in SQLite (`data/queue.db`).
- `dsm-ae queue enqueue|list|cancel` CLI.
- `dsm-ae worker` long-running process claims jobs (`BEGIN IMMEDIATE`), runs `diagnose()`, writes reports, regenerates HTML.
- Optional FastAPI (or Starlette) UI on a local port: submit model, see queue, embed/link matrix.
- **Pros:** durable, restart-safe, single-node simple, matches “demo on Tailscale” later. **Cons:** one primary worker (good enough; multi-worker can use SQLite locks later).

### C. Redis + RQ/Celery

- **Pros:** industry standard at scale. **Cons:** extra infra, overkill for local benchmark box, secrets still need a registry.

**Recommendation: B.** Keep models.yaml (or env) as the **credential directory**; treat the queue as the **run intent** layer.

---

## 4. Target architecture

```
                 ┌──────────────────────────────┐
  Operator CLI   │ dsm-ae queue enqueue …       │
  or Web form    │ dsm-ae queue list / cancel   │
                 └──────────────┬───────────────┘
                                │ INSERT job
                                ▼
                 ┌──────────────────────────────┐
                 │  SQLite: eval_jobs           │
                 │  status: queued|running|…    │
                 └──────────────┬───────────────┘
                                │ claim next
                                ▼
                 ┌──────────────────────────────┐
                 │  dsm-ae worker (1..N)        │
                 │  → diagnose()                │
                 │  → write reports/*.json      │
                 │  → rebuild matrix HTML       │
                 └──────────────┬───────────────┘
                                ▼
                 ┌──────────────────────────────┐
                 │  Static reports + /compare   │
                 │  (matrix HTML, job API)      │
                 └──────────────────────────────┘
```

### 4.1 Separation of concerns

| Layer | Responsibility | Source of truth |
|-------|----------------|-----------------|
| **Model registry** | How to call a model (api_base, key, rpm) | `models.yaml` / env (secrets stay out of git) |
| **Eval job** | What to run (model id, packs, k, concurrency, labels) | SQLite `eval_jobs` |
| **Artifacts** | Results for comparison | `reports/` JSON + HTML (unchanged schema) |
| **Presentation** | Queue status + matrix | Worker-regenerated HTML + small status API |

### 4.2 Job model

```text
EvalJob
  id            TEXT UUID
  model         TEXT          # must resolve via registry or mock/*
  packs         TEXT NULL     # comma list or NULL = all packs
  k             INT
  concurrency   INT
  rpm           FLOAT NULL    # override; else models.yaml
  scaffold      TEXT
  work_dir      TEXT NULL
  out_md        TEXT NULL     # default reports/queue/<id>.md
  out_json      TEXT NULL
  label         TEXT NULL     # display name in matrix (optional)
  priority      INT DEFAULT 0 # higher first
  status        ENUM queued|running|succeeded|failed|cancelled
  error         TEXT NULL
  created_at    TEXT ISO
  started_at    TEXT NULL
  finished_at   TEXT NULL
  worker_id     TEXT NULL
  attempt       INT DEFAULT 0
  max_attempts  INT DEFAULT 1
```

### 4.3 Worker semantics

1. Poll SQLite every `poll_s` (default 2s) or wait on a `threading.Event` woken by enqueue.
2. Claim: `UPDATE … SET status='running', worker_id=?, started_at=? WHERE id=(SELECT id FROM … WHERE status='queued' ORDER BY priority DESC, created_at ASC LIMIT 1)`.
3. Run `diagnose(...)` in-process (preferred) or subprocess `dsm-ae diagnose …` (isolation if a pack segfaults).
4. On success: write MD/JSON paths from job; set `succeeded`; run HTML rebuild.
5. On failure: store traceback snippet; `failed` or re-queue if `attempt < max_attempts`.
6. **Global model mutex (optional config):** default `max_in_flight_per_model=1` so two jobs for the same model never share rpm accidentally.
7. **Global worker concurrency:** default 1 job at a time (full suite is heavy); allow `--job-workers 1` first, later N with care for API rpm.

### 4.4 CLI surface

```bash
# Registry still secrets-only
export DSM_AE_MODELS_YAML=models.yaml

# Enqueue
dsm-ae queue enqueue -m gpt-5.6-terra --k 3 -j 2 --packs hello_metacog,overeager_mini
dsm-ae queue enqueue -m qwen3.7-max --full-suite      # packs = all list_packs()
dsm-ae queue enqueue-batch -m gpt-5.6-terra,gpt-5.6-sol,gpt-5.6-luna --k 3

# Inspect / control
dsm-ae queue list
dsm-ae queue status <id>
dsm-ae queue cancel <id>
dsm-ae queue retry <id>

# Drain
dsm-ae worker --models-yaml models.yaml --reports-dir reports --poll 2

# One-shot: process until empty then exit (CI)
dsm-ae worker --once
```

### 4.5 Comparison

- Keep **artifact schema** (`DiagnosisReport` JSON) stable so existing `json_to_html_report.py` works.
- Worker after each success:  
  `dsm-ae html-report -i reports -o reports/dsm-ae-matrix.html`
- Matrix already shows **NOT RUN** for missing packs/metrics — ideal for partial progressive fills.
- Optional job label → write under `reports/queue/<label-or-model>-<shortid>.json` so re-runs don’t clobber.

### 4.6 Web UI (v1 thin)

Serve alongside static reports (same port as demo, or FastAPI):

| Route | Behavior |
|-------|----------|
| `GET /` or `/dsm-ae/` | Redirect or serve matrix |
| `GET /queue` | HTML table of jobs |
| `POST /queue` | Enqueue (form: model, packs, k) |
| `GET /api/jobs` | JSON list |
| `POST /api/jobs` | JSON enqueue |
| `GET /api/jobs/{id}` | Status |

Auth for public funnel: **shared bearer token** or Tailscale Serve auth later; for temporary demo, bind `127.0.0.1` and only funnel GET of static matrix if needed.

### 4.7 models.yaml role change

| Before | After |
|--------|-------|
| Implicit “list of models to batch” | **Credential + rate-limit registry only** |
| Scripts hardcode model arrays | Queue holds the batch |
| `diagnose-batch` for multi-model | Becomes thin wrapper: enqueue-batch + worker --once |

Keep file format compatible with LiteLLM-style `model_list` already used by `resolve_from_models_yaml`.

---

## 5. Key decisions

1. **SQLite over Redis** — single-node durable queue without new services.
2. **Credentials stay in models.yaml** — jobs store model *names*, never api keys.
3. **Reuse `diagnose()`** — no second evaluation engine.
4. **One active job by default** — full-suite is pack×k heavy; parallelism stays inside a job via existing `--concurrency`.
5. **HTML rebuild on each completion** — progressive comparison for demos.
6. **Subprocess isolation optional** — flag `--isolate` for worker if packs leave dirty global state.

---

## 6. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| Worker crash mid-job | On startup, requeue `running` older than `stale_s` or mark failed |
| rpm exhaustion when two jobs hit same proxy | `max_in_flight_per_model=1`; honor job/models.yaml rpm |
| Report path collisions | Include job short-id in output filenames |
| Funnel exposes enqueue API | Default UI/API localhost-only; static matrix can be funneled separately |
| Large JSON traces | Existing omit-traces behavior; don’t store full traces in SQLite |

---

## 7. Success criteria

1. Operator can enqueue 3 models without editing shell scripts.
2. Killing and restarting `dsm-ae worker` resumes queued work; no double-run of succeeded jobs.
3. After each success, matrix HTML includes the new model (or updated artifact).
4. Mock path: `queue enqueue -m mock/well_attuned` works offline in CI.
5. Existing `pytest` suite still green; new tests for claim/cancel/retry.

---

## 8. Open questions (defaults if unanswered)

| # | Question | Default |
|---|----------|---------|
| Q1 | Web UI in v1 or CLI-only first? | **CLI + worker first**; thin UI in same PR if small |
| Q2 | Multi-job parallel workers? | **No** (1 job); pack-level concurrency unchanged |
| Q3 | Persist job history forever? | Keep last **500** jobs; artifacts on disk independent |
| Q4 | Replace shell scripts immediately? | Scripts call `queue enqueue-batch` + `worker --once` |

---

## 9. PR Plan

| PR | Title | Scope |
|----|-------|-------|
| PR1 | `feat(queue): SQLite job store + enqueue CLI` | `queue/store.py`, schema, CLI list/enqueue/cancel, tests |
| PR2 | `feat(queue): worker claims jobs and runs diagnose` | `queue/worker.py`, status transitions, report paths, HTML hook |
| PR3 | `feat(queue): thin status API + static matrix mount` | optional FastAPI, `/api/jobs`, serve reports |
| PR4 | `chore: migrate suite scripts to queue enqueue-batch` | shell scripts, README |

Each PR independently reviewable; PR1 has no worker; PR2 needs PR1.
