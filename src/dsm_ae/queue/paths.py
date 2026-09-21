from pathlib import Path


def default_db_path(root: Path | None = None) -> Path:
    root = root or Path.cwd()
    return root / "data" / "queue.db"


def job_report_paths(reports_dir: Path, job_id: str, model: str, label: str | None):
    safe = (label or model).replace("/", "_").replace(".", "_")
    short = job_id[:8]
    base = reports_dir / "queue"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{safe}-{short}.md", base / f"{safe}-{short}.json"
