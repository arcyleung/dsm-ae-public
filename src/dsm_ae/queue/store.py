"""SQLite-backed eval job store. Uses BEGIN IMMEDIATE for claim."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dsm_ae.queue.models import EvalJob, JobStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_jobs (
  id TEXT PRIMARY KEY,
  model TEXT NOT NULL,
  packs_json TEXT,
  k INTEGER NOT NULL,
  concurrency INTEGER NOT NULL DEFAULT 1,
  rpm REAL,
  scaffold TEXT NOT NULL DEFAULT 'raw',
  priority INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  worker_id TEXT,
  attempt INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 1,
  out_md TEXT,
  out_json TEXT,
  work_dir TEXT,
  label TEXT,
  api_base TEXT,
  secret_path TEXT,
  progress_path TEXT,
  extra_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_prio
  ON eval_jobs(status, priority DESC, created_at ASC);
"""

# Columns added after first ship — applied via ALTER TABLE if missing.
_MIGRATE_COLS = (
    ("api_base", "TEXT"),
    ("secret_path", "TEXT"),
    ("progress_path", "TEXT"),
    ("extra_json", "TEXT"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_job(row: sqlite3.Row) -> EvalJob:
    packs_raw = row["packs_json"]
    packs: list[str] | None
    if packs_raw is None:
        packs = None
    else:
        packs = json.loads(packs_raw)
    keys = row.keys()
    extra_raw = row["extra_json"] if "extra_json" in keys else None
    extra: dict[str, Any] | None
    if extra_raw:
        try:
            extra = json.loads(extra_raw)
        except json.JSONDecodeError:
            extra = None
    else:
        extra = None
    return EvalJob(
        id=row["id"],
        model=row["model"],
        packs=packs,
        k=row["k"],
        concurrency=row["concurrency"],
        rpm=row["rpm"],
        scaffold=row["scaffold"],
        priority=row["priority"],
        status=JobStatus(row["status"]),
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        worker_id=row["worker_id"],
        attempt=row["attempt"],
        max_attempts=row["max_attempts"],
        out_md=row["out_md"],
        out_json=row["out_json"],
        work_dir=row["work_dir"],
        label=row["label"],
        api_base=row["api_base"] if "api_base" in keys else None,
        secret_path=row["secret_path"] if "secret_path" in keys else None,
        progress_path=row["progress_path"] if "progress_path" in keys else None,
        extra=extra,
    )


class JobStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        existing = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(eval_jobs)").fetchall()
        }
        for col, decl in _MIGRATE_COLS:
            if col not in existing:
                self._conn.execute(f"ALTER TABLE eval_jobs ADD COLUMN {col} {decl}")

    def enqueue(
        self,
        *,
        model: str,
        packs: list[str] | None = None,
        k: int = 3,
        concurrency: int = 1,
        rpm: float | None = None,
        scaffold: str = "raw",
        priority: int = 0,
        max_attempts: int = 1,
        label: str | None = None,
        out_md: str | None = None,
        out_json: str | None = None,
        work_dir: str | None = None,
        api_base: str | None = None,
        secret_path: str | None = None,
        progress_path: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> str:
        jid = str(uuid.uuid4())
        self._conn.execute(
            """INSERT INTO eval_jobs
            (id, model, packs_json, k, concurrency, rpm, scaffold, priority,
             status, created_at, max_attempts, label, out_md, out_json, work_dir, attempt,
             api_base, secret_path, progress_path, extra_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)""",
            (
                jid,
                model,
                json.dumps(packs) if packs is not None else None,
                k,
                concurrency,
                rpm,
                scaffold,
                priority,
                JobStatus.QUEUED.value,
                _now(),
                max_attempts,
                label,
                out_md,
                out_json,
                work_dir,
                api_base,
                secret_path,
                progress_path,
                json.dumps(extra) if extra else None,
            ),
        )
        self._conn.commit()
        return jid

    def claim_next(self, worker_id: str) -> EvalJob | None:
        cur = self._conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        row = cur.execute(
            """SELECT id FROM eval_jobs
               WHERE status=? ORDER BY priority DESC, created_at ASC LIMIT 1""",
            (JobStatus.QUEUED.value,),
        ).fetchone()
        if not row:
            self._conn.commit()
            return None
        jid = row["id"]
        cur.execute(
            """UPDATE eval_jobs SET status=?, worker_id=?, started_at=?, attempt=attempt+1
               WHERE id=? AND status=?""",
            (JobStatus.RUNNING.value, worker_id, _now(), jid, JobStatus.QUEUED.value),
        )
        self._conn.commit()
        return self.get(jid)

    def get(self, job_id: str) -> EvalJob | None:
        row = self._conn.execute(
            "SELECT * FROM eval_jobs WHERE id=?", (job_id,)
        ).fetchone()
        return _row_to_job(row) if row else None

    def list_jobs(self, limit: int = 100) -> list[EvalJob]:
        rows = self._conn.execute(
            "SELECT * FROM eval_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_job(r) for r in rows]

    def cancel(self, job_id: str) -> bool:
        cur = self._conn.execute(
            "UPDATE eval_jobs SET status=?, finished_at=? WHERE id=? AND status=?",
            (JobStatus.CANCELLED.value, _now(), job_id, JobStatus.QUEUED.value),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def retry(self, job_id: str) -> bool:
        """Re-queue a failed or cancelled job. Returns True if status changed."""
        cur = self._conn.execute(
            """UPDATE eval_jobs
               SET status=?, error=NULL, worker_id=NULL, started_at=NULL, finished_at=NULL
               WHERE id=? AND status IN (?, ?)""",
            (
                JobStatus.QUEUED.value,
                job_id,
                JobStatus.FAILED.value,
                JobStatus.CANCELLED.value,
            ),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def mark_succeeded(self, job_id: str, *, out_md: str, out_json: str) -> None:
        self._conn.execute(
            """UPDATE eval_jobs SET status=?, finished_at=?, out_md=?, out_json=?, error=NULL
               WHERE id=?""",
            (JobStatus.SUCCEEDED.value, _now(), out_md, out_json, job_id),
        )
        self._conn.commit()

    def mark_failed(self, job_id: str, error: str) -> None:
        self._conn.execute(
            """UPDATE eval_jobs SET status=?, finished_at=?, error=? WHERE id=?""",
            (JobStatus.FAILED.value, _now(), error[:4000], job_id),
        )
        self._conn.commit()

    def update_paths(
        self,
        job_id: str,
        *,
        progress_path: str | None = None,
        secret_path: str | None = None,
        work_dir: str | None = None,
    ) -> None:
        if progress_path is not None:
            self._conn.execute(
                "UPDATE eval_jobs SET progress_path=? WHERE id=?",
                (progress_path, job_id),
            )
        if secret_path is not None:
            self._conn.execute(
                "UPDATE eval_jobs SET secret_path=? WHERE id=?",
                (secret_path, job_id),
            )
        if work_dir is not None:
            self._conn.execute(
                "UPDATE eval_jobs SET work_dir=? WHERE id=?",
                (work_dir, job_id),
            )
        self._conn.commit()

    def requeue_stale(self, stale_seconds: float = 3600) -> int:
        """Mark long-running jobs failed so they can be retried manually."""
        now = datetime.now(timezone.utc)
        rows = self._conn.execute(
            "SELECT id, started_at FROM eval_jobs WHERE status=?",
            (JobStatus.RUNNING.value,),
        ).fetchall()
        n = 0
        finished = now.isoformat()
        for row in rows:
            started_raw = row["started_at"]
            if not started_raw:
                continue
            started = datetime.fromisoformat(started_raw)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            age = (now - started).total_seconds()
            if age <= stale_seconds:
                continue
            err = f"stale: running longer than {stale_seconds:g}s (age={age:.0f}s)"
            cur = self._conn.execute(
                """UPDATE eval_jobs SET status=?, finished_at=?, error=?
                   WHERE id=? AND status=?""",
                (
                    JobStatus.FAILED.value,
                    finished,
                    err[:4000],
                    row["id"],
                    JobStatus.RUNNING.value,
                ),
            )
            if cur.rowcount == 1:
                n += 1
        self._conn.commit()
        return n
