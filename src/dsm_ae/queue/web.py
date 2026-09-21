"""Thin FastAPI UI for the evaluation queue + static report matrix.

Behind Tailscale funnel with --set-path=/dsm-ae the path prefix is stripped
before requests hit this app, so routes live at ``/``. Use ``public_base``
(e.g. ``/dsm-ae``) so HTML links resolve correctly in the browser.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from dsm_ae.litellm_client import make_client
from dsm_ae.packs.registry import list_packs
from dsm_ae.queue.models import EvalJob
from dsm_ae.queue.progress import (
    progress_path_for,
    read_progress,
    secrets_path_for,
    write_progress,
    write_secret,
)
from dsm_ae.queue.store import JobStore
from dsm_ae.queue.worker import default_worker_id, run_loop
from dsm_ae.queue.web_html import (
    render_comparison_page,
    render_queue_page,
    render_reports_page,
    render_treatment_page,
    render_literature_page,
    render_compaction_page,
)


class EnqueueBody(BaseModel):
    model: str = Field(..., min_length=1, description="Model id (LiteLLM model name)")
    packs: list[str] | None = None
    packs_csv: str | None = None
    k: int = 3
    concurrency: int = 1
    rpm: float | None = None
    full_suite: bool = False
    priority: int = 0
    label: str | None = None
    # LiteLLM-style connection (optional; falls back to models.yaml / mock)
    api_base: str | None = None
    api_key: str | None = Field(
        default=None, description="Stored in a secrets file, never returned by API"
    )
    timeout: float | None = None
    num_retries: int | None = None


class ConnectionTestBody(BaseModel):
    model: str = Field(..., min_length=1)
    api_base: str | None = None
    api_key: str | None = None
    timeout: float | None = 30.0
    num_retries: int | None = 0


# Matrix/report HTML changes often; never let browsers keep a stale Comparison view.
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _html(content: str, *, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(content, status_code=status_code, headers=dict(_NO_CACHE_HEADERS))


def _job_dict(job: EvalJob) -> dict[str, Any]:
    d = asdict(job)
    d["status"] = job.status.value
    # Never expose secret file path or raw key material to clients.
    d.pop("secret_path", None)
    d["has_api_key"] = bool(job.secret_path)
    d["progress"] = read_progress(job.progress_path)
    return d


def _parse_packs_list(
    packs: list[str] | None,
    packs_csv: str | None,
    full_suite: bool,
) -> list[str] | None:
    if full_suite:
        return list_packs()
    if packs:
        return [p.strip() for p in packs if p and p.strip()]
    if packs_csv and packs_csv.strip():
        return [x.strip() for x in packs_csv.split(",") if x.strip()]
    return None


def create_app(
    *,
    db_path: Path,
    reports_dir: Path,
    models_yaml: Path | None = None,
    public_base: str = "",
    token: str | None = None,
    with_worker: bool = False,
    worker_poll: float = 2.0,
    stale_seconds: float = 3600,
) -> FastAPI:
    """Build the queue UI app.

    Parameters
    ----------
    public_base:
        Browser-facing prefix (no trailing slash), e.g. ``/dsm-ae`` when funnel
        exposes that path. Empty string for bare host root.
    token:
        If set, mutating routes require ``Authorization: Bearer <token>`` or
        ``X-DSM-AE-Token`` header (or form field ``token`` for HTML posts).
    """
    db_path = Path(db_path)
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    base = public_base.rstrip("/")
    store = JobStore(db_path)
    resolved_token = token or os.environ.get("DSM_AE_QUEUE_TOKEN") or None
    yaml_path = Path(models_yaml) if models_yaml else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.worker_thread = None
        if with_worker:
            wid = default_worker_id()

            def _target() -> None:
                run_loop(
                    store,
                    worker_id=wid,
                    reports_dir=reports_dir,
                    models_yaml=yaml_path,
                    once=False,
                    poll_s=worker_poll,
                    rebuild_html=True,
                    stale_seconds=stale_seconds,
                )

            t = threading.Thread(target=_target, name="dsm-ae-worker", daemon=True)
            app.state.worker_thread = t
            t.start()
        yield

    app = FastAPI(
        title="DSM-AE Eval Queue",
        version="0.1.0",
        # Custom /docs below so openapi_url includes public_base (funnel-safe).
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    secrets_dir = db_path.parent / "job_secrets"
    secrets_dir.mkdir(parents=True, exist_ok=True)

    app.state.store = store
    app.state.reports_dir = reports_dir
    app.state.models_yaml = yaml_path
    app.state.public_base = base
    app.state.token = resolved_token
    app.state.worker_thread = None
    app.state.secrets_dir = secrets_dir

    # Optional dual-access: accept /dsm-ae/... when the prefix was NOT already
    # stripped (e.g. local curl http://127.0.0.1:8765/dsm-ae/api/jobs).
    # Do not rewrite root_path on every request — that breaks StaticFiles.
    if base:

        @app.middleware("http")
        async def _strip_public_base(request: Request, call_next):  # type: ignore[no-untyped-def]
            path = request.scope.get("path", "") or ""
            if path == base or path.startswith(base + "/"):
                request.scope["path"] = path[len(base) :] or "/"
            return await call_next(request)

    @app.middleware("http")
    async def _no_cache_ui_and_reports(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Disable caching for UI shells + /reports static HTML/JSON artifacts."""
        response = await call_next(request)
        path = request.scope.get("path", "") or ""
        no_cache = (
            path == "/"
            or path.startswith("/queue")
            or path.startswith("/matrix")
            or path.startswith("/reports")
            or path.startswith("/treatment")
            or path.startswith("/literature")
            or path.startswith("/compaction")
            or path.startswith("/api/jobs")
        )
        if no_cache:
            for k, v in _NO_CACHE_HEADERS.items():
                response.headers[k] = v
        return response

    def href(path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}" if base else path

    @app.get("/docs", include_in_schema=False)
    def swagger_ui() -> HTMLResponse:
        # Browser must fetch openapi under the funnel prefix; the app itself still
        # serves the schema at /openapi.json (proxy strips public_base).
        return get_swagger_ui_html(
            openapi_url=href("/openapi.json"),
            title=f"{app.title} - Swagger UI",
        )

    def require_token(
        request: Request,
        authorization: Optional[str] = Header(default=None),
        x_dsm_ae_token: Optional[str] = Header(default=None, alias="X-DSM-AE-Token"),
    ) -> None:
        """Require the *queue UI* shared secret (not the model API key).

        Accepts (first match wins): Authorization Bearer, X-DSM-AE-Token header,
        ``token`` query param, form field (via caller), or cookie ``dsm_ae_queue_token``.
        """
        expected = app.state.token
        if not expected:
            return
        got = None
        if authorization and authorization.lower().startswith("bearer "):
            got = authorization[7:].strip()
        if not got:
            got = (x_dsm_ae_token or "").strip() or None
        if not got:
            got = (request.query_params.get("token") or "").strip() or None
        if not got:
            got = (request.cookies.get("dsm_ae_queue_token") or "").strip() or None
        if not got:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "queue_token_missing",
                    "message": (
                        "Queue UI authentication required: provide the DSM-AE queue token "
                        "(from .env DSM_AE_QUEUE_TOKEN / --token). "
                        "This is separate from the model API key used for inference."
                    ),
                },
            )
        if got != expected:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "queue_token_invalid",
                    "message": (
                        "Queue UI authentication failed: the queue token is incorrect. "
                        "This is not a model endpoint / API-key error — re-enter the "
                        "DSM-AE queue token (DSM_AE_QUEUE_TOKEN), not the LiteLLM api_key."
                    ),
                },
            )

    def job_to_public(job: EvalJob) -> dict[str, Any]:
        return _job_dict(job)

    def _extra_from_body(timeout: float | None, num_retries: int | None) -> dict[str, Any] | None:
        extra: dict[str, Any] = {}
        if timeout is not None:
            extra["timeout"] = float(timeout)
        if num_retries is not None:
            extra["num_retries"] = int(num_retries)
        return extra or None

    def _enqueue_from_fields(
        *,
        model: str,
        packs: list[str] | None,
        k: int,
        concurrency: int,
        rpm: float | None,
        priority: int,
        label: str | None,
        api_base: str | None,
        api_key: str | None,
        timeout: float | None,
        num_retries: int | None,
    ) -> EvalJob:
        model = model.strip()
        api_base = (api_base or "").strip() or None
        extra = _extra_from_body(timeout, num_retries)
        jid = store.enqueue(
            model=model,
            packs=packs,
            k=k,
            concurrency=concurrency,
            rpm=rpm,
            priority=priority,
            label=label,
            api_base=api_base,
            extra=extra,
        )
        prog = progress_path_for(reports_dir, jid)
        store.update_paths(jid, progress_path=str(prog))
        write_progress(
            prog,
            {
                "job_id": jid,
                "model": model,
                "phase": "queued",
                "status": "queued",
                "done": 0,
                "total": 0,
                "message": "Queued — waiting for worker",
            },
        )
        if api_key and api_key.strip():
            sp = secrets_path_for(secrets_dir, jid)
            write_secret(sp, api_key=api_key.strip())
            store.update_paths(jid, secret_path=str(sp))
        job = store.get(jid)
        assert job is not None
        return job

    # --- API -----------------------------------------------------------------

    @app.get("/api/health")
    def api_health() -> dict[str, Any]:
        return {
            "ok": True,
            "public_base": base or "/",
            "auth_required": bool(app.state.token),
            "worker_running": bool(
                app.state.worker_thread and app.state.worker_thread.is_alive()
            ),
        }

    @app.get("/api/jobs")
    def api_list_jobs(limit: int = Query(100, ge=1, le=500)) -> list[dict[str, Any]]:
        return [job_to_public(j) for j in store.list_jobs(limit=limit)]

    @app.get("/api/jobs/{job_id}")
    def api_get_job(job_id: str) -> dict[str, Any]:
        job = _resolve(store, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return job_to_public(job)

    @app.get("/api/jobs/{job_id}/progress")
    def api_job_progress(job_id: str) -> dict[str, Any]:
        job = _resolve(store, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        prog = read_progress(job.progress_path) or {
            "job_id": job.id,
            "status": job.status.value,
            "message": job.status.value,
        }
        return prog

    @app.post("/api/test-connection")
    def api_test_connection(
        body: ConnectionTestBody,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        """Probe the *inference* endpoint (model auth), after queue token is accepted."""
        model = body.model.strip()
        if model.startswith("mock/"):
            return {
                "ok": True,
                "code": "endpoint_ok_mock",
                "message": (
                    f"Inference endpoint check skipped for offline mock persona "
                    f"'{model.split('/', 1)[-1]}' (no network call)."
                ),
            }
        extra: dict[str, Any] = {}
        if body.timeout is not None:
            extra["timeout"] = float(body.timeout)
        if body.num_retries is not None:
            extra["num_retries"] = int(body.num_retries)
        try:
            client = make_client(
                model,
                models_yaml=yaml_path,
                api_base=(body.api_base or "").strip() or None,
                api_key=(body.api_key or "").strip() or None,
                extra=extra or None,
            )
            result = client.complete(
                [{"role": "user", "content": "Reply with the single word: pong"}],
                max_tokens=16,
                temperature=0.0,
            )
            text = (result.content or "").strip()
            return {
                "ok": True,
                "code": "endpoint_ok",
                "message": f"Inference endpoint OK — model replied: {text[:200]!r}",
                "preview": text[:200],
            }
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            # Hint common auth failures without swallowing the real error.
            lower = err.lower()
            authish = any(
                k in lower
                for k in (
                    "401",
                    "403",
                    "unauthorized",
                    "forbidden",
                    "invalid api",
                    "authentication",
                    "api key",
                    "apikey",
                    "incorrect api",
                )
            )
            timeoutish = any(
                k in lower for k in ("timeout", "timed out", "deadline", "read timed")
            )
            unknown_provider = "unknown provider" in lower
            if timeoutish:
                hint = (
                    " The model host did not respond in time (down, overloaded, or "
                    "blocked by proxy). This is an inference-endpoint problem — not "
                    "the DSM-AE queue token."
                )
                code = "endpoint_timeout"
            elif unknown_provider:
                hint = (
                    " Gateway rejected the model id. For OpenAI-compatible proxies, "
                    "use the bare model name (e.g. qwen3.6-plus) plus API base URL — "
                    "not hosted_vllm/… unless that gateway expects that prefix."
                )
                code = "endpoint_model_not_routed"
            elif authish:
                hint = (
                    " Check model API base URL and API key — "
                    "this is not the DSM-AE queue token."
                )
                code = "endpoint_auth_or_network_error"
            else:
                hint = ""
                code = "endpoint_error"
            return {
                "ok": False,
                "code": code,
                "message": f"Inference endpoint error: {err}.{hint}",
            }

    @app.post("/api/jobs")
    def api_enqueue(
        body: EnqueueBody,
        _: None = Depends(require_token),
    ) -> dict[str, Any]:
        pack_list = _parse_packs_list(body.packs, body.packs_csv, body.full_suite)
        job = _enqueue_from_fields(
            model=body.model,
            packs=pack_list,
            k=body.k,
            concurrency=body.concurrency,
            rpm=body.rpm,
            priority=body.priority,
            label=body.label,
            api_base=body.api_base,
            api_key=body.api_key,
            timeout=body.timeout,
            num_retries=body.num_retries,
        )
        return job_to_public(job)

    @app.post("/api/jobs/{job_id}/cancel")
    def api_cancel(job_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
        job = _resolve(store, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        if not store.cancel(job.id):
            raise HTTPException(400, f"cannot cancel (status={job.status.value})")
        return job_to_public(store.get(job.id))  # type: ignore[arg-type]

    @app.post("/api/jobs/{job_id}/retry")
    def api_retry(job_id: str, _: None = Depends(require_token)) -> dict[str, Any]:
        job = _resolve(store, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        if not store.retry(job.id):
            raise HTTPException(400, f"cannot retry (status={job.status.value})")
        return job_to_public(store.get(job.id))  # type: ignore[arg-type]

    @app.get("/api/packs")
    def api_packs() -> list[str]:
        return list_packs()

    # --- HTML ----------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        return _html(render_queue_page(store, href, app.state.token is not None, title="DSM-AE"))

    @app.get("/queue", response_class=HTMLResponse)
    def queue_page() -> HTMLResponse:
        return _html(
            render_queue_page(store, href, app.state.token is not None, title="Queue")
        )

    @app.post("/queue")
    def queue_form_post(
        request: Request,
        model: str = Form(...),
        packs: str = Form(""),
        k: int = Form(3),
        concurrency: int = Form(1),
        full_suite: Optional[str] = Form(None),
        priority: int = Form(0),
        label: str = Form(""),
        api_base: str = Form(""),
        api_key: str = Form(""),
        timeout: Optional[float] = Form(None),
        token_field: str = Form("", alias="token"),
    ) -> RedirectResponse:
        expected = app.state.token
        if expected:
            auth = request.headers.get("authorization")
            got = None
            if token_field and token_field.strip():
                got = token_field.strip()
            elif auth and auth.lower().startswith("bearer "):
                got = auth[7:].strip()
            elif request.headers.get("x-dsm-ae-token"):
                got = request.headers.get("x-dsm-ae-token", "").strip()
            elif request.cookies.get("dsm_ae_queue_token"):
                got = request.cookies.get("dsm_ae_queue_token", "").strip()
            if not got:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "code": "queue_token_missing",
                        "message": (
                            "Queue UI authentication required: provide the DSM-AE queue token "
                            "(DSM_AE_QUEUE_TOKEN). This is separate from the model API key."
                        ),
                    },
                )
            if got != expected:
                raise HTTPException(
                    status_code=401,
                    detail={
                        "code": "queue_token_invalid",
                        "message": (
                            "Queue UI authentication failed: incorrect queue token "
                            "(not a model endpoint auth error)."
                        ),
                    },
                )
        pack_list = _parse_packs_list(
            None, packs or None, full_suite is not None and full_suite != ""
        )
        _enqueue_from_fields(
            model=model,
            packs=pack_list,
            k=k,
            concurrency=concurrency,
            rpm=None,
            priority=priority,
            label=label.strip() or None,
            api_base=api_base or None,
            api_key=api_key or None,
            timeout=timeout,
            num_retries=2,
        )
        return RedirectResponse(href("/queue"), status_code=303)

    @app.get("/matrix", response_class=HTMLResponse)
    def matrix_page() -> HTMLResponse:
        # Shell with shared nav + iframe to static matrix (keeps chrome visible).
        return _html(
            render_comparison_page(href, reports_dir, title="Comparison")
        )

    @app.get("/reports-ui", response_class=HTMLResponse)
    def reports_ui() -> HTMLResponse:
        # Primary Reports nav target — app chrome + directory index.
        # Raw files remain at /reports/... via StaticFiles.
        return _html(render_reports_page(href, reports_dir, title="Reports"))

    @app.get("/treatment", response_class=HTMLResponse)
    def treatment_page() -> HTMLResponse:
        return _html(
            render_treatment_page(href, reports_dir, title="Treatment")
        )

    @app.get("/literature", response_class=HTMLResponse)
    def literature_page() -> HTMLResponse:
        return _html(
            render_literature_page(href, reports_dir, title="Literature")
        )

    @app.get("/compaction", response_class=HTMLResponse)
    def compaction_page() -> HTMLResponse:
        return _html(
            render_compaction_page(href, reports_dir, title="Compaction")
        )

    app.mount(
        "/reports",
        StaticFiles(directory=str(reports_dir), html=True),
        name="reports",
    )

    return app


def _resolve(store: JobStore, job_id: str) -> EvalJob | None:
    job = store.get(job_id)
    if job is not None:
        return job
    if len(job_id) < 36:
        matches = [j for j in store.list_jobs(limit=500) if j.id.startswith(job_id)]
        if len(matches) == 1:
            return matches[0]
    return None
