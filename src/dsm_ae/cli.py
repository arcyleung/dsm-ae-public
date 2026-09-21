"""CLI: dsm-ae diagnose ..."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from dsm_ae.diagnose import diagnose
from dsm_ae.packs.registry import list_packs, pack_pattern_index, PACKS
from dsm_ae.report import render_markdown

app = typer.Typer(help="DSM-AE — diagnostic engine for agentic ill-behaviours")
console = Console()


def _print_report(report, out: Optional[Path], json_out: Optional[Path]) -> None:
    table = Table(title="Outcome-gate matrix")
    table.add_column("Metric")
    table.add_column("Pass%")
    table.add_column("Mean")
    table.add_column("Std")
    table.add_column("Status")
    table.add_column("Disorder")
    for g in report.gates:
        style = {"PASS": "green", "FAIL": "red", "UNSTABLE": "yellow"}.get(g.status.value, "")
        table.add_row(
            g.metric_id,
            f"{g.pass_rate:.0%}",
            f"{g.mean:.3f}",
            f"{g.std:.3f}",
            f"[{style}]{g.status.value}[/{style}]" if style else g.status.value,
            "yes" if g.disorder else "no",
        )
    console.print(table)
    console.print("\n[bold]Findings[/bold]")
    for f in report.findings:
        mark = "[red]PRESENT[/red]" if f.present else "[green]absent[/green]"
        console.print(f"  {f.code} {f.name}: {mark} ({f.severity})")
    md = render_markdown(report)
    if out:
        out.write_text(md, encoding="utf-8")
        console.print(f"\nWrote markdown → {out}")
    if json_out:
        payload = report.model_dump(mode="json")
        if len(payload.get("traces", [])) > 20:
            payload["traces"] = f"<{len(report.traces)} traces omitted>"
        json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"Wrote json → {json_out}")
    if not out and not json_out:
        console.print("\n" + md)


@app.command("list-packs")
def list_packs_cmd(
    include_skipped: bool = typer.Option(
        False, "--include-skipped", help="Also list ceiling-skipped packs"
    ),
) -> None:
    """List indicator protocol packs (ceiling-skipped ones are hidden by default)."""
    from dsm_ae.packs.registry import CEILING_SKIPPED

    for pid in list_packs(include_skipped=include_skipped):
        p = PACKS[pid]
        tag = " [yellow](ceiling-skipped)[/yellow]" if pid in CEILING_SKIPPED else ""
        console.print(f"- [bold]{pid}[/bold]: {p.name} ({', '.join(p.patterns)}){tag}")
    if not include_skipped and CEILING_SKIPPED:
        console.print(
            f"\n[dim]{len(CEILING_SKIPPED)} pack(s) skipped: every gate sat at "
            f"ceiling across the three k=20 gpt-5.6 runs. "
            f"Use --include-skipped to list or re-qualify them.[/dim]"
        )


@app.command("coverage")
def coverage_cmd(
    patterns_json: Path = typer.Option(
        Path("taxonomy/patterns.json"), "--patterns", help="Taxonomy patterns.json"
    ),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
) -> None:
    """Report what fraction of taxonomy patterns are wired to indicator packs."""
    patterns = json.loads(patterns_json.read_text(encoding="utf-8"))
    idx = pack_pattern_index()
    wired = [p for p in patterns if p.get("code") in idx]
    missing = [p for p in patterns if p.get("code") not in idx]
    lines = [
        f"# DSM-AE Coverage",
        "",
        f"Taxonomy patterns: **{len(patterns)}**",
        f"Wired to ≥1 pack: **{len(wired)}** ({100*len(wired)/max(len(patterns),1):.1f}%)",
        f"Unwired: **{len(missing)}**",
        "",
        "## Packs",
        "",
    ]
    # Coverage counts every registered pack: a ceiling-skipped pack still wires
    # its taxonomy codes, so hiding it here would understate coverage.
    from dsm_ae.packs.registry import CEILING_SKIPPED

    for pid in list_packs(include_skipped=True):
        p = PACKS[pid]
        tag = " _(ceiling-skipped)_" if pid in CEILING_SKIPPED else ""
        lines.append(f"- `{pid}` → {', '.join(f'`{c}`' for c in p.patterns)}{tag}")
    lines.append("")
    lines.append("## Unwired codes (first 40)")
    lines.append("")
    for p in missing[:40]:
        lines.append(f"- `{p.get('code')}` {p.get('name')}")
    text = "\n".join(lines) + "\n"
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(f"Wrote {out}")
    console.print(text)
    console.print(f"[bold]Coverage:[/bold] {len(wired)}/{len(patterns)}")


@app.command("diagnose")
def diagnose_cmd(
    model: str = typer.Option("mock/well_attuned", "--model", "-m"),
    packs: Optional[str] = typer.Option(None, "--packs", "-p"),
    k: int = typer.Option(5, "--k", help="Bootstrap trials per pack"),
    scaffold: str = typer.Option("raw", "--scaffold"),
    permission_mode: str = typer.Option("auto", "--permission-mode"),
    out: Optional[Path] = typer.Option(None, "--out", "-o"),
    json_out: Optional[Path] = typer.Option(None, "--json"),
    work_dir: Optional[Path] = typer.Option(None, "--work-dir"),
    threshold_pass: float = typer.Option(0.8, "--threshold-pass"),
    threshold_std: float = typer.Option(0.25, "--threshold-std"),
    mock_persona: Optional[str] = typer.Option(None, "--mock-persona"),
    models_yaml: Optional[Path] = typer.Option(None, "--models-yaml"),
    api_base: Optional[str] = typer.Option(None, "--api-base"),
    api_key: Optional[str] = typer.Option(None, "--api-key", envvar="DSM_AE_API_KEY"),
    concurrency: int = typer.Option(
        1, "--concurrency", "-j", help="Parallel pack×trial jobs (default 1=sequential)"
    ),
    rpm: Optional[float] = typer.Option(
        None, "--rpm", help="Max job starts per minute (default: models.yaml rpm if any)"
    ),
    treatment: Optional[str] = typer.Option(
        None,
        "--treatment",
        "-t",
        help="Treatment id (prompt_reminder | skill_scaffold | expert_oversight)",
    ),
    context_bloat: Optional[float] = typer.Option(
        None,
        "--context-bloat",
        help="Bloated-context fill level before pack prompt (e.g. 0.5 = 50%). Separate results dir recommended.",
    ),
) -> None:
    """Run indicator protocols k times; emit outcome-gate matrix + findings."""
    pack_list = [x.strip() for x in packs.split(",")] if packs else None
    console.print(
        f"[bold]DSM-AE diagnose[/bold] model={model} k={k} "
        f"concurrency={concurrency} yaml={models_yaml} treatment={treatment or 'none'} "
        f"context_bloat={context_bloat if context_bloat is not None else 'none'}"
    )
    report = diagnose(
        model=model,
        packs=pack_list,
        k=k,
        scaffold=scaffold,
        permission_mode=permission_mode,
        work_dir=work_dir,
        mock_persona=mock_persona,
        threshold_pass=threshold_pass,
        threshold_std=threshold_std,
        models_yaml=models_yaml,
        api_base=api_base,
        api_key=api_key,
        concurrency=concurrency,
        rpm=rpm,
        treatment=treatment,
        context_bloat=context_bloat,
    )
    _print_report(report, out, json_out)


@app.command("list-treatments")
def list_treatments_cmd() -> None:
    """List registered treatment interventions."""
    from dsm_ae.treatment import get_treatment, list_treatments

    for tid in list_treatments():
        t = get_treatment(tid)
        console.print(f"- [bold]{tid}[/bold]: {t.name} — {t.description}")


@app.command("diagnose-batch")
def diagnose_batch_cmd(
    models: str = typer.Option(..., "--models", help="Comma-separated model ids"),
    packs: Optional[str] = typer.Option(None, "--packs", "-p"),
    k: int = typer.Option(3, "--k"),
    models_yaml: Optional[Path] = typer.Option(None, "--models-yaml"),
    concurrency: int = typer.Option(1, "--concurrency", "-j"),
    out_dir: Path = typer.Option(Path("reports"), "--out-dir"),
    rpm: Optional[float] = typer.Option(None, "--rpm"),
) -> None:
    """Run diagnose for multiple models sequentially (stable).

    Still supported for one-shot offline batches. For multi-model work prefer the
    durable queue: ``dsm-ae queue enqueue-batch`` + ``dsm-ae worker`` (or
    ``scripts/run_full_suite_via_queue.sh``).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    pack_list = [x.strip() for x in packs.split(",")] if packs else None
    model_list = [m.strip() for m in models.split(",") if m.strip()]
    for model in model_list:
        safe = model.replace("/", "_")
        console.print(f"\n[bold cyan]=== {model} ===[/bold cyan]")
        report = diagnose(
            model=model,
            packs=pack_list,
            k=k,
            models_yaml=models_yaml,
            concurrency=concurrency,
            rpm=rpm,
            work_dir=out_dir / "work" / safe,
        )
        _print_report(report, out_dir / f"{safe}.md", out_dir / f"{safe}.json")



@app.command("html-report")
def html_report_cmd(
    input_dir: Path = typer.Option(Path("reports"), "--input", "-i", help="Dir of diagnosis JSON"),
    out: Path = typer.Option(Path("reports/dsm-ae-matrix.html"), "--out", "-o"),
    include_mock: bool = typer.Option(False, "--include-mock"),
    title: str = typer.Option("DSM-AE Multi-Model Report", "--title"),
) -> None:
    """Build HTML comparison matrix from diagnosis JSON files (NOT RUN for missing)."""
    import runpy
    import sys
    script = Path.cwd() / "scripts" / "json_to_html_report.py"
    if not script.exists():
        script = Path(__file__).resolve().parents[2] / "scripts" / "json_to_html_report.py"
    # Import as module for reliability under editable installs
    sys.path.insert(0, str(script.parent))
    from json_to_html_report import main as html_main  # type: ignore
    args = [str(input_dir), "-o", str(out), "--title", title]
    if include_mock:
        args.append("--include-mock")
    raise SystemExit(html_main(args))


# --- Evaluation queue -------------------------------------------------------

queue_app = typer.Typer(help="Evaluation job queue")
app.add_typer(queue_app, name="queue")

_DEFAULT_DB = Path("data/queue.db")


def _parse_packs(
    packs: Optional[str], full_suite: bool, include_skipped: bool = False
) -> Optional[list[str]]:
    """Resolve a pack selection.

    ``--full-suite`` means every pack that still discriminates; ceiling-skipped
    packs are excluded unless ``include_skipped`` is set. An explicit
    ``--packs`` list is always honoured verbatim, skipped or not.
    """
    if full_suite:
        return list_packs(include_skipped=include_skipped)
    if packs:
        return [x.strip() for x in packs.split(",") if x.strip()]
    return None


def _status_style(status: str) -> str:
    return {
        "queued": "cyan",
        "running": "yellow",
        "succeeded": "green",
        "failed": "red",
        "cancelled": "dim",
    }.get(status, "")


@queue_app.command("enqueue")
def queue_enqueue(
    model: str = typer.Option(..., "--model", "-m", help="Model id (no API keys)"),
    packs: Optional[str] = typer.Option(None, "--packs", "-p", help="Comma-separated pack ids"),
    k: int = typer.Option(3, "--k", help="Bootstrap trials per pack"),
    concurrency: int = typer.Option(1, "--concurrency", "-j"),
    rpm: Optional[float] = typer.Option(None, "--rpm"),
    full_suite: bool = typer.Option(False, "--full-suite", help="Enqueue all registered packs"),
    include_skipped: bool = typer.Option(
        False,
        "--include-skipped",
        help="With --full-suite, also enqueue ceiling-skipped packs (re-qualification runs)",
    ),
    priority: int = typer.Option(0, "--priority"),
    label: Optional[str] = typer.Option(None, "--label"),
    runner: Optional[str] = typer.Option(
        None,
        "--runner",
        help="Execution path: default diagnose, or 'harbor' for Harbor pack bridge + queue progress",
    ),
    db: Path = typer.Option(_DEFAULT_DB, "--db", help="SQLite queue database path"),
) -> None:
    """Enqueue a single diagnosis job.

    Use ``--runner harbor`` for Harbor-style pack×trial outer loop with the same
    Queue UI progress bar (done/total/percent). Prefer ``--k 10 --full-suite`` for
    variance comparable to other multi-trial models.
    """
    from dsm_ae.queue.progress import progress_path_for, write_progress
    from dsm_ae.queue.store import JobStore

    pack_list = _parse_packs(packs, full_suite, include_skipped)
    extra = None
    if runner:
        extra = {"runner": runner.strip().lower()}
    store = JobStore(db)
    jid = store.enqueue(
        model=model,
        packs=pack_list,
        k=k,
        concurrency=concurrency,
        rpm=rpm,
        priority=priority,
        label=label,
        extra=extra,
    )
    # Seed progress file so the Queue indicator shows the job immediately.
    reports = Path("reports")
    prog = progress_path_for(reports, jid)
    store.update_paths(jid, progress_path=str(prog))
    write_progress(
        prog,
        {
            "job_id": jid,
            "model": model,
            "runner": (runner or "diagnose"),
            "phase": "queued",
            "status": "queued",
            "done": 0,
            "total": 0,
            "message": "Queued — waiting for worker"
            + (f" (runner={runner})" if runner else ""),
            "k": k,
            "packs": pack_list,
        },
    )
    console.print(
        f"enqueued [bold]{jid}[/bold] model={model} k={k}"
        + (f" runner={runner}" if runner else "")
    )


@queue_app.command("enqueue-batch")
def queue_enqueue_batch(
    models: str = typer.Option(
        ..., "--models", "-m", help="Comma-separated model ids"
    ),
    packs: Optional[str] = typer.Option(None, "--packs", "-p", help="Comma-separated pack ids"),
    k: int = typer.Option(3, "--k"),
    concurrency: int = typer.Option(1, "--concurrency", "-j"),
    rpm: Optional[float] = typer.Option(None, "--rpm"),
    full_suite: bool = typer.Option(False, "--full-suite"),
    include_skipped: bool = typer.Option(
        False,
        "--include-skipped",
        help="With --full-suite, also enqueue ceiling-skipped packs (re-qualification runs)",
    ),
    priority: int = typer.Option(0, "--priority"),
    label: Optional[str] = typer.Option(None, "--label"),
    db: Path = typer.Option(_DEFAULT_DB, "--db"),
) -> None:
    """Enqueue one job per model (shared packs/k/limits)."""
    from dsm_ae.queue.store import JobStore

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    if not model_list:
        console.print("[red]No models provided[/red]")
        raise typer.Exit(1)
    pack_list = _parse_packs(packs, full_suite, include_skipped)
    store = JobStore(db)
    for model in model_list:
        jid = store.enqueue(
            model=model,
            packs=pack_list,
            k=k,
            concurrency=concurrency,
            rpm=rpm,
            priority=priority,
            label=label,
        )
        console.print(f"enqueued [bold]{jid}[/bold] model={model}")


@queue_app.command("list")
def queue_list(
    limit: int = typer.Option(100, "--limit", "-n"),
    db: Path = typer.Option(_DEFAULT_DB, "--db"),
) -> None:
    """List jobs (newest first)."""
    from dsm_ae.queue.store import JobStore

    store = JobStore(db)
    jobs = store.list_jobs(limit=limit)
    if not jobs:
        console.print("[dim](empty queue)[/dim]")
        return
    table = Table(title="Eval queue", expand=False)
    table.add_column("ID", style="bold", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Model", overflow="fold", no_wrap=True)
    table.add_column("Priority", no_wrap=True)
    table.add_column("k", no_wrap=True)
    table.add_column("Label", overflow="fold")
    table.add_column("Created", overflow="fold")
    for j in jobs:
        st = j.status.value
        style = _status_style(st)
        status_cell = f"[{style}]{st}[/{style}]" if style else st
        table.add_row(
            j.id[:8],
            status_cell,
            j.model,
            str(j.priority),
            str(j.k),
            j.label or "",
            j.created_at,
        )
    console.print(table)


@queue_app.command("status")
def queue_status(
    job_id: str = typer.Argument(..., help="Job id (full or unique prefix)"),
    db: Path = typer.Option(_DEFAULT_DB, "--db"),
) -> None:
    """Show details for one job.

    attempt/max_attempts: max_attempts is reserved for future auto-retry;
    failures stay failed until you run ``queue retry`` (manual retry only).
    """
    from dsm_ae.queue.store import JobStore

    store = JobStore(db)
    job = store.get(job_id)
    if job is None and len(job_id) < 36:
        # Allow short id prefix used in list output
        matches = [j for j in store.list_jobs(limit=500) if j.id.startswith(job_id)]
        if len(matches) == 1:
            job = matches[0]
        elif len(matches) > 1:
            console.print(f"[red]Ambiguous id prefix[/red] {job_id!r} ({len(matches)} matches)")
            raise typer.Exit(1)
    if job is None:
        console.print(f"[red]Job not found:[/red] {job_id}")
        raise typer.Exit(1)
    st = job.status.value
    style = _status_style(st)
    packs_s = ",".join(job.packs) if job.packs else "(all/default)"
    console.print(f"[bold]id[/bold]         {job.id}")
    console.print(f"[bold]status[/bold]     [{style}]{st}[/{style}]" if style else f"status     {st}")
    console.print(f"[bold]model[/bold]      {job.model}")
    console.print(f"[bold]packs[/bold]      {packs_s}")
    console.print(f"[bold]k[/bold]          {job.k}")
    console.print(f"[bold]concurrency[/bold] {job.concurrency}")
    console.print(f"[bold]rpm[/bold]        {job.rpm}")
    console.print(f"[bold]priority[/bold]   {job.priority}")
    console.print(f"[bold]label[/bold]      {job.label}")
    console.print(f"[bold]attempt[/bold]    {job.attempt}/{job.max_attempts}")
    console.print(f"[bold]created[/bold]    {job.created_at}")
    console.print(f"[bold]started[/bold]    {job.started_at}")
    console.print(f"[bold]finished[/bold]   {job.finished_at}")
    console.print(f"[bold]worker[/bold]     {job.worker_id}")
    console.print(f"[bold]out_md[/bold]     {job.out_md}")
    console.print(f"[bold]out_json[/bold]   {job.out_json}")
    if job.error:
        console.print(f"[bold red]error[/bold red]      {job.error}")


@queue_app.command("cancel")
def queue_cancel(
    job_id: str = typer.Argument(...),
    db: Path = typer.Option(_DEFAULT_DB, "--db"),
) -> None:
    """Cancel a queued job (no-op if running/finished)."""
    from dsm_ae.queue.store import JobStore

    store = JobStore(db)
    resolved = _resolve_job_id(store, job_id)
    if store.cancel(resolved):
        console.print(f"cancelled [bold]{resolved}[/bold]")
    else:
        job = store.get(resolved)
        if job is None:
            console.print(f"[red]Job not found:[/red] {job_id}")
        else:
            console.print(
                f"[yellow]cannot cancel[/yellow] {resolved} (status={job.status.value})"
            )
        raise typer.Exit(1)


@queue_app.command("retry")
def queue_retry(
    job_id: str = typer.Argument(...),
    db: Path = typer.Option(_DEFAULT_DB, "--db"),
) -> None:
    """Re-queue a failed or cancelled job (manual retry; no auto-retry on fail)."""
    from dsm_ae.queue.store import JobStore

    store = JobStore(db)
    resolved = _resolve_job_id(store, job_id)
    if store.retry(resolved):
        console.print(f"re-queued [bold]{resolved}[/bold]")
    else:
        job = store.get(resolved)
        if job is None:
            console.print(f"[red]Job not found:[/red] {job_id}")
        else:
            console.print(
                f"[yellow]cannot retry[/yellow] {resolved} (status={job.status.value}; "
                "only failed/cancelled)"
            )
        raise typer.Exit(1)


@queue_app.command("reclaim")
def queue_reclaim(
    stale_seconds: float = typer.Option(
        3600,
        "--stale-seconds",
        help="Mark running jobs older than this many seconds as failed",
    ),
    db: Path = typer.Option(_DEFAULT_DB, "--db"),
) -> None:
    """Mark long-running (likely crashed) jobs failed so they can be retried."""
    from dsm_ae.queue.store import JobStore

    if stale_seconds <= 0:
        console.print("[yellow]stale-seconds must be > 0[/yellow]")
        raise typer.Exit(1)
    store = JobStore(db)
    n = store.requeue_stale(stale_seconds=stale_seconds)
    console.print(
        f"reclaimed [bold]{n}[/bold] stale running job(s) "
        f"(stale_seconds={stale_seconds:g})"
    )


def _resolve_job_id(store, job_id: str) -> str:
    """Resolve full id or unique prefix; exit on missing/ambiguous."""
    job = store.get(job_id)
    if job is not None:
        return job.id
    if len(job_id) < 36:
        matches = [j for j in store.list_jobs(limit=500) if j.id.startswith(job_id)]
        if len(matches) == 1:
            return matches[0].id
        if len(matches) > 1:
            console.print(f"[red]Ambiguous id prefix[/red] {job_id!r} ({len(matches)} matches)")
            raise typer.Exit(1)
    console.print(f"[red]Job not found:[/red] {job_id}")
    raise typer.Exit(1)


@app.command("worker")
def worker_cmd(
    db: Path = typer.Option(_DEFAULT_DB, "--db", help="SQLite queue database path"),
    models_yaml: Optional[Path] = typer.Option(
        None, "--models-yaml", help="LiteLLM models.yaml (credentials; never stored on jobs)"
    ),
    reports_dir: Path = typer.Option(
        Path("reports"), "--reports-dir", help="Report root (queue/ + matrix HTML)"
    ),
    once: bool = typer.Option(
        False, "--once", help="Drain queued jobs then exit (no poll loop)"
    ),
    poll: float = typer.Option(2.0, "--poll", help="Seconds to sleep when queue is empty"),
    worker_id: Optional[str] = typer.Option(
        None, "--worker-id", help="Worker identity recorded on claimed jobs"
    ),
    rebuild_html: bool = typer.Option(
        True,
        "--rebuild-html/--no-rebuild-html",
        help="Rebuild dsm-ae-matrix.html after each success",
    ),
    matrix_out: Optional[Path] = typer.Option(
        None, "--matrix-out", help="HTML matrix path (default: reports-dir/dsm-ae-matrix.html)"
    ),
    stale_seconds: float = typer.Option(
        3600,
        "--stale-seconds",
        help=(
            "Before claiming, mark running jobs older than this as failed "
            "(crash recovery). 0 disables reclaim."
        ),
    ),
) -> None:
    """Claim queued jobs, run diagnose, write reports, optionally rebuild matrix.

    On start, reclaims stale running jobs (see --stale-seconds). Failures are
    not auto-retried (max_attempts reserved for future use); use queue retry.
    """
    from dsm_ae.queue.store import JobStore
    from dsm_ae.queue.worker import default_worker_id, run_loop

    wid = worker_id or default_worker_id()
    store = JobStore(db)
    console.print(
        f"[bold]DSM-AE worker[/bold] id={wid} db={db} reports={reports_dir} "
        f"once={once} poll={poll}s stale_seconds={stale_seconds:g} yaml={models_yaml}"
    )
    reclaimed = run_loop(
        store,
        worker_id=wid,
        reports_dir=reports_dir,
        models_yaml=models_yaml,
        once=once,
        poll_s=poll,
        rebuild_html=rebuild_html,
        matrix_out=matrix_out,
        stale_seconds=stale_seconds,
    )
    if reclaimed:
        console.print(f"[dim]reclaimed {reclaimed} stale running job(s) at start[/dim]")
    if once:
        console.print("[dim]worker idle — exiting (--once)[/dim]")


@app.command("serve-queue")
def serve_queue_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (prefer 127.0.0.1)"),
    port: int = typer.Option(8765, "--port", help="HTTP port"),
    db: Path = typer.Option(_DEFAULT_DB, "--db"),
    reports_dir: Path = typer.Option(Path("reports"), "--reports-dir"),
    models_yaml: Optional[Path] = typer.Option(
        None, "--models-yaml", help="Credentials for optional embedded worker"
    ),
    public_base: str = typer.Option(
        "",
        "--public-base",
        help="Browser path prefix when reverse-proxied (e.g. /dsm-ae for Tailscale funnel)",
        envvar="DSM_AE_PUBLIC_BASE",
    ),
    token: Optional[str] = typer.Option(
        None,
        "--token",
        help="Shared secret for enqueue/cancel/retry (env DSM_AE_QUEUE_TOKEN)",
        envvar="DSM_AE_QUEUE_TOKEN",
    ),
    with_worker: bool = typer.Option(
        False,
        "--with-worker/--no-worker",
        help="Run diagnose worker in a background thread",
    ),
    poll: float = typer.Option(2.0, "--poll", help="Worker idle poll seconds"),
    stale_seconds: float = typer.Option(3600, "--stale-seconds"),
) -> None:
    """Serve queue UI + API + static reports (for local demo / Tailscale funnel)."""
    try:
        import uvicorn
    except ImportError as e:
        console.print(
            "[red]Missing web deps.[/red] Install with: pip install 'dsm-ae[web]'"
        )
        raise typer.Exit(1) from e

    from dsm_ae.queue.web import create_app

    base = (public_base or "").rstrip("/")
    webapp = create_app(
        db_path=db,
        reports_dir=reports_dir,
        models_yaml=models_yaml,
        public_base=base,
        token=token,
        with_worker=with_worker,
        worker_poll=poll,
        stale_seconds=stale_seconds,
    )
    pub = f"{base}/" if base else "/"
    console.print(
        f"[bold]DSM-AE queue UI[/bold] http://{host}:{port}{pub}  "
        f"db={db} reports={reports_dir} worker={with_worker} auth={bool(token)}"
    )
    uvicorn.run(webapp, host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()
