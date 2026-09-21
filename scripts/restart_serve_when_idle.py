#!/usr/bin/env python3
"""Restart serve-queue only when no live eval jobs are running.

Never kill the server mid-run. Poll the queue DB until idle, then SIGTERM the
existing serve-queue process and start a fresh one with the same flags.

Usage examples::

  # Wait for zero status=running, then restart (queued jobs are fine — SQLite)
  python scripts/restart_serve_when_idle.py

  # Also treat long-frozen orphans as not-live (fail them first)
  python scripts/restart_serve_when_idle.py --fail-stale-progress 600

  # Dry-run: only print when idle would fire
  python scripts/restart_serve_when_idle.py --dry-run

Env (optional, same as manual serve)::

  DSM_AE_QUEUE_TOKEN, or load from .env in repo root.
"""
from __future__ import annotations

import argparse
import os
import re
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "queue.db"
DEFAULT_LOG = ROOT / "logs" / "serve-queue.log"
DEFAULT_MODELS = ROOT / "models.yaml"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip("'").strip('"')
        if k and k not in os.environ:
            os.environ[k] = v


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _running_jobs(db: Path) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT id, model, worker_id, started_at, progress_path
           FROM eval_jobs WHERE status='running' ORDER BY started_at"""
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        age_start = None
        started = _parse_iso(d.get("started_at"))
        if started:
            age_start = (_now() - started).total_seconds()
        prog_age = None
        msg = None
        pct = None
        pp = d.get("progress_path")
        if pp and Path(pp).is_file():
            try:
                import json

                prog = json.loads(Path(pp).read_text(encoding="utf-8"))
                msg = prog.get("message")
                pct = prog.get("percent")
                updated = _parse_iso(prog.get("updated_at"))
                if updated:
                    prog_age = (_now() - updated).total_seconds()
            except Exception:
                pass
        d["age_start_s"] = age_start
        d["prog_age_s"] = prog_age
        d["message"] = msg
        d["percent"] = pct
        out.append(d)
    return out


def _fail_stale_progress(db: Path, stale_s: float) -> list[str]:
    """Mark running jobs with no progress update for stale_s as failed."""
    import json

    failed: list[str] = []
    jobs = _running_jobs(db)
    conn = sqlite3.connect(str(db))
    for j in jobs:
        age = j.get("prog_age_s")
        # No progress file / no updated_at: use started_at as proxy
        if age is None:
            age = j.get("age_start_s")
        if age is None or age < stale_s:
            continue
        err = (
            f"stale-progress: no progress for {age:.0f}s "
            f"(threshold={stale_s:g}s); likely orphan after restart"
        )
        cur = conn.execute(
            """UPDATE eval_jobs SET status=?, finished_at=?, error=?
               WHERE id=? AND status='running'""",
            ("failed", _now().isoformat(), err[:4000], j["id"]),
        )
        if cur.rowcount == 1:
            failed.append(j["id"])
            pp = j.get("progress_path")
            if pp and Path(pp).is_file():
                try:
                    prog = json.loads(Path(pp).read_text(encoding="utf-8"))
                    prog["status"] = "failed"
                    prog["phase"] = "failed"
                    prog["message"] = err[:200]
                    prog["updated_at"] = _now().isoformat()
                    Path(pp).write_text(json.dumps(prog, indent=2), encoding="utf-8")
                except Exception:
                    pass
    conn.commit()
    conn.close()
    return failed


def _find_serve_pids(port: int) -> list[int]:
    pids: list[int] = []
    try:
        out = subprocess.check_output(["ss", "-tlnp"], text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        out = ""
    for line in out.splitlines():
        if f":{port}" not in line or "pid=" not in line:
            continue
        for m in re.finditer(r"pid=(\d+)", line):
            pids.append(int(m.group(1)))
    # Fallback: pgrep by cmdline
    try:
        raw = subprocess.check_output(
            ["pgrep", "-f", "dsm-ae serve-queue"], text=True
        ).strip()
        for line in raw.splitlines():
            try:
                pids.append(int(line.strip()))
            except ValueError:
                pass
    except subprocess.CalledProcessError:
        pass
    return sorted(set(pids))


def _stop_serve(port: int, grace_s: float = 8.0) -> None:
    pids = _find_serve_pids(port)
    if not pids:
        print("no serve-queue process found", flush=True)
        return
    for pid in pids:
        print(f"SIGTERM serve-queue pid={pid}", flush=True)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.time() + grace_s
    while time.time() < deadline:
        alive = [p for p in pids if Path(f"/proc/{p}").exists()]
        if not alive:
            break
        time.sleep(0.3)
    for pid in pids:
        if Path(f"/proc/{pid}").exists():
            print(f"SIGKILL serve-queue pid={pid}", flush=True)
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def _start_serve(
    *,
    host: str,
    port: int,
    public_base: str,
    db: Path,
    reports_dir: Path,
    models_yaml: Path | None,
    poll: float,
    log_path: Path,
) -> int:
    token = os.environ.get("DSM_AE_QUEUE_TOKEN") or ""
    cmd = [
        "dsm-ae",
        "serve-queue",
        "--host",
        host,
        "--port",
        str(port),
        "--public-base",
        public_base,
        "--db",
        str(db),
        "--reports-dir",
        str(reports_dir),
        "--poll",
        str(poll),
        "--with-worker",
    ]
    if token:
        cmd.extend(["--token", token])
    if models_yaml and models_yaml.is_file():
        cmd.extend(["--models-yaml", str(models_yaml)])

    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Truncate log for this boot
    logf = open(log_path, "w", encoding="utf-8")
    env = os.environ.copy()
    if token:
        env["DSM_AE_QUEUE_TOKEN"] = token
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=logf,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    logf.close()
    time.sleep(1.2)
    if proc.poll() is not None:
        print(
            f"serve-queue exited immediately code={proc.returncode}; see {log_path}",
            flush=True,
        )
        sys.exit(1)
    print(f"started serve-queue pid={proc.pid} log={log_path}", flush=True)
    return proc.pid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--poll", type=float, default=30.0, help="Seconds between checks")
    ap.add_argument(
        "--fail-stale-progress",
        type=float,
        default=0.0,
        metavar="SEC",
        help="If >0, mark running jobs with no progress for SEC as failed "
        "(orphans) so idle can be reached",
    )
    ap.add_argument(
        "--require-empty-queue",
        action="store_true",
        help="Also wait until no queued jobs remain",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--public-base", default="/dsm-ae")
    ap.add_argument("--reports-dir", type=Path, default=ROOT / "reports")
    ap.add_argument("--models-yaml", type=Path, default=DEFAULT_MODELS)
    ap.add_argument("--worker-poll", type=float, default=2.0)
    ap.add_argument("--log", type=Path, default=DEFAULT_LOG)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="When idle, print and exit without restarting",
    )
    ap.add_argument(
        "--max-wait",
        type=float,
        default=0.0,
        help="Give up after SEC seconds (0=wait forever)",
    )
    args = ap.parse_args()

    os.chdir(ROOT)
    _load_dotenv(ROOT / ".env")

    t0 = time.time()
    print(
        f"IDLE_RESTART_WAIT db={args.db} poll={args.poll}s "
        f"fail_stale_progress={args.fail_stale_progress or 'off'} "
        f"require_empty_queue={args.require_empty_queue} dry_run={args.dry_run}",
        flush=True,
    )

    while True:
        if args.max_wait and (time.time() - t0) > args.max_wait:
            print("IDLE_RESTART_TIMEOUT", flush=True)
            return 2

        if args.fail_stale_progress > 0:
            failed = _fail_stale_progress(args.db, args.fail_stale_progress)
            for jid in failed:
                print(f"FAILED_STALE_ORPHAN id={jid[:8]}", flush=True)

        running = _running_jobs(args.db)
        queued_n = 0
        if args.require_empty_queue:
            conn = sqlite3.connect(str(args.db))
            queued_n = conn.execute(
                "SELECT COUNT(*) FROM eval_jobs WHERE status='queued'"
            ).fetchone()[0]
            conn.close()

        if running:
            for j in running:
                print(
                    f"WAIT_RUNNING id={j['id'][:8]} model={j['model']} "
                    f"pct={j.get('percent')} prog_age_s="
                    f"{None if j.get('prog_age_s') is None else int(j['prog_age_s'])} "
                    f"msg={j.get('message')!r}",
                    flush=True,
                )
        elif args.require_empty_queue and queued_n:
            print(f"WAIT_QUEUED count={queued_n}", flush=True)
        else:
            print("IDLE — no live running jobs", flush=True)
            if args.dry_run:
                print("DRY_RUN skip restart", flush=True)
                return 0
            _stop_serve(args.port)
            _start_serve(
                host=args.host,
                port=args.port,
                public_base=args.public_base,
                db=args.db,
                reports_dir=args.reports_dir,
                models_yaml=args.models_yaml,
                poll=args.worker_poll,
                log_path=args.log,
            )
            print("IDLE_RESTART_DONE", flush=True)
            return 0

        time.sleep(args.poll)


if __name__ == "__main__":
    raise SystemExit(main())
