"""Tests for the thin FastAPI eval queue UI."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from dsm_ae.queue.web import create_app


@pytest.fixture
def client(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "dsm-ae-matrix.html").write_text("<html>matrix</html>", encoding="utf-8")
    app = create_app(
        db_path=tmp_path / "q.db",
        reports_dir=reports,
        public_base="/dsm-ae",
        token=None,
        with_worker=False,
    )
    with TestClient(app) as c:
        yield c


def test_health_and_home(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["public_base"] == "/dsm-ae"
    r = client.get("/")
    assert r.status_code == 200
    assert b"eval queue" in r.content.lower()
    # Nav uses data-nav + client-side base detection (works local + funnel).
    assert b'data-nav="/matrix"' in r.content
    assert b'data-nav="/reports-ui"' in r.content
    assert b'data-nav="/treatment"' in r.content
    assert b'data-nav="/literature"' in r.content
    assert b'data-nav="/compaction"' in r.content
    assert b"detectBase" in r.content or b"data-configured-base" in r.content
    assert b"location.reload" not in r.content
    assert b"pack-cb" in r.content  # multi-select packs
    assert b"Test connection" in r.content
    assert b"api_base" in r.content or b"f-api-base" in r.content
    assert b"Auto-refresh 5s" in r.content


def test_literature_tab(client: TestClient):
    r = client.get("/literature")
    assert r.status_code == 200
    assert b"Literature" in r.content
    assert b'data-nav="/literature"' in r.content
    assert b"No literature tree yet" in r.content


def test_literature_tab_embeds_generated_tree(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    lit = reports / "literature"
    lit.mkdir()
    (lit / "index.html").write_text(
        "<html><body>Unknown-pool clusters scheming spec_drift</body></html>",
        encoding="utf-8",
    )
    (reports / "dsm-ae-matrix.html").write_text("<html>matrix</html>", encoding="utf-8")
    app = create_app(
        db_path=tmp_path / "q.db",
        reports_dir=reports,
        public_base="/dsm-ae",
        token=None,
        with_worker=False,
    )
    with TestClient(app) as c:
        r = c.get("/literature")
        assert r.status_code == 200
        assert b"lit-frame" in r.content
        assert b"/reports/literature/index.html" in r.content
        assert b"No literature tree yet" not in r.content
        r = c.get("/reports/literature/index.html")
        assert r.status_code == 200
        assert b"scheming" in r.content
        assert b"spec_drift" in r.content


def test_compaction_tab(client: TestClient):
    r = client.get("/compaction")
    assert r.status_code == 200
    assert b"Compaction" in r.content
    assert b'data-nav="/compaction"' in r.content
    assert b"No compaction survey yet" in r.content


def test_compaction_tab_embeds_generated_tree(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    dest = reports / "compaction"
    dest.mkdir()
    (dest / "index.html").write_text(
        "<html><body>When scaffolds compact LlamaFactory mask_history</body></html>",
        encoding="utf-8",
    )
    (reports / "dsm-ae-matrix.html").write_text("<html>matrix</html>", encoding="utf-8")
    app = create_app(
        db_path=tmp_path / "q.db",
        reports_dir=reports,
        public_base="/dsm-ae",
        token=None,
        with_worker=False,
    )
    with TestClient(app) as c:
        r = c.get("/compaction")
        assert r.status_code == 200
        assert b"lit-frame" in r.content
        assert b"/reports/compaction/index.html" in r.content
        assert b"No compaction survey yet" not in r.content
        r = c.get("/reports/compaction/index.html")
        assert r.status_code == 200
        assert b"LlamaFactory" in r.content


def test_enqueue_list_api(client: TestClient):
    r = client.post(
        "/api/jobs",
        json={"model": "mock/well_attuned", "packs": ["hello_metacog"], "k": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "mock/well_attuned"
    assert body["status"] == "queued"
    jid = body["id"]

    r = client.get("/api/jobs")
    assert r.status_code == 200
    assert any(j["id"] == jid for j in r.json())

    r = client.get(f"/api/jobs/{jid[:8]}")
    assert r.status_code == 200
    assert r.json()["id"] == jid


def test_form_enqueue_and_cancel(client: TestClient):
    r = client.post(
        "/queue",
        data={"model": "mock/overeager", "packs": "hello_metacog", "k": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    jobs = client.get("/api/jobs").json()
    assert any(j["model"] == "mock/overeager" for j in jobs)
    jid = next(j["id"] for j in jobs if j["model"] == "mock/overeager")
    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"


def test_token_required_for_mutate(tmp_path: Path):
    (tmp_path / "reports").mkdir()
    app = create_app(
        db_path=tmp_path / "q.db",
        reports_dir=tmp_path / "reports",
        token="secret",
        with_worker=False,
    )
    with TestClient(app) as c:
        r = c.post("/api/jobs", json={"model": "mock/well_attuned", "k": 1})
        assert r.status_code == 401
        detail = r.json()["detail"]
        assert detail["code"] == "queue_token_missing"
        assert "queue token" in detail["message"].lower()
        assert "not" in detail["message"].lower() or "separate" in detail["message"].lower()

        r = c.post(
            "/api/test-connection",
            json={"model": "mock/well_attuned"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401
        detail = r.json()["detail"]
        assert detail["code"] == "queue_token_invalid"
        assert "incorrect" in detail["message"].lower() or "queue" in detail["message"].lower()
        assert "model" in detail["message"].lower() or "api" in detail["message"].lower()

        r = c.post(
            "/api/jobs",
            json={"model": "mock/well_attuned", "k": 1},
            headers={"Authorization": "Bearer secret"},
        )
        assert r.status_code == 200

        # Cookie auth works without Authorization header
        r = c.post(
            "/api/test-connection",
            json={"model": "mock/well_attuned"},
            cookies={"dsm_ae_queue_token": "secret"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json().get("code", "").startswith("endpoint_ok")


def test_matrix_and_static(client: TestClient):
    # Comparison is an app shell (nav stays visible) embedding the static matrix.
    r = client.get("/matrix", follow_redirects=False)
    assert r.status_code == 200
    body = r.content.lower()
    assert b"comparison" in body
    assert b'data-nav="/"' in r.content  # Queue link
    assert b'data-nav="/treatment"' in r.content
    assert b"iframe" in body
    assert b"/reports/dsm-ae-matrix.html" in r.content
    r = client.get("/reports/dsm-ae-matrix.html")
    assert r.status_code == 200
    assert b"matrix" in r.content


def test_treatment_page(client: TestClient, tmp_path: Path):
    # Seed a treatment result under the fixture reports dir used by client.
    reports = Path(client.app.state.reports_dir)
    tdir = reports / "treatment"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "SUMMARY.md").write_text(
        "# Trial summary\n\n| Arm | Status |\n|-----|--------|\n| baseline | ok |\n",
        encoding="utf-8",
    )
    (tdir / "gpt-test-prompt_reminder.md").write_text("ok", encoding="utf-8")
    (tdir / "gpt-test-prompt_reminder.json").write_text("{}", encoding="utf-8")
    work = reports / "work" / "treatment_luna" / "prompt_reminder"
    work.mkdir(parents=True, exist_ok=True)

    r = client.get("/treatment")
    assert r.status_code == 200
    text = r.text
    assert "Treatment" in text
    assert 'data-nav="/"' in text
    assert 'data-nav="/matrix"' in text
    assert 'data-nav="/reports-ui"' in text
    assert 'data-nav="/treatment"' in text
    # Registered treatment ids
    assert "prompt_reminder" in text
    assert "skill_scaffold" in text
    assert "expert_oversight" in text
    assert "Trial summary" in text
    # SUMMARY.md must render as HTML table, not a raw <pre> code dump
    assert 'class="md-body"' in text
    assert "<table>" in text
    assert "<th>Arm</th>" in text
    assert "<td>baseline</td>" in text
    assert "<td>ok</td>" in text
    assert "<pre>" not in text  # no monospaced markdown dump on this page
    assert "run_treatment_luna_trial" in text
    assert "dsm-ae diagnose" in text
    # public_base prefix on server-rendered links
    assert 'href="/dsm-ae/treatment"' in text or 'data-nav="/treatment"' in text


def test_reports_ui_shell(client: TestClient):
    r = client.get("/reports-ui")
    assert r.status_code == 200
    text = r.text
    assert "Reports" in text
    assert 'data-nav="/"' in text  # Queue
    assert 'data-nav="/treatment"' in text
    assert 'data-nav="/matrix"' in text
    assert "/reports/" in text
    # Still keep raw static tree available
    r2 = client.get("/reports/dsm-ae-matrix.html")
    assert r2.status_code == 200


def test_packs_api(client: TestClient):
    r = client.get("/api/packs")
    assert r.status_code == 200
    packs = r.json()
    assert "hello_metacog" in packs


def test_public_base_prefix_routes_work(client: TestClient):
    """Middleware strips public_base so /dsm-ae/* works without a funnel."""
    r = client.get("/dsm-ae/")
    assert r.status_code == 200
    assert b"eval queue" in r.content.lower()
    r = client.get("/dsm-ae/api/jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    r = client.get("/dsm-ae/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    home = client.get("/").text
    # Client-side detectBase (not a hard-coded API_JOBS string).
    assert "detectBase" in home
    assert 'data-configured-base="/dsm-ae"' in home
    # Server-side nav fallbacks keep links usable before JS runs.
    assert 'href="/dsm-ae/matrix"' in home
    assert 'href="/dsm-ae/reports-ui"' in home
    assert 'href="/dsm-ae/treatment"' in home
    # Prefixed routes for new shells
    r = client.get("/dsm-ae/treatment")
    assert r.status_code == 200
    assert "Treatment" in r.text
    r = client.get("/dsm-ae/reports-ui")
    assert r.status_code == 200
    assert 'data-nav="/treatment"' in r.text
    # Static files still work at root paths
    r = client.get("/reports/dsm-ae-matrix.html")
    assert r.status_code == 200
    # Swagger must point browsers at the funnel-prefixed openapi path.
    docs = client.get("/docs").text
    assert "/dsm-ae/openapi.json" in docs
    r = client.get("/dsm-ae/docs")
    assert r.status_code == 200
    assert "/dsm-ae/openapi.json" in r.text


def test_enqueue_with_connection_and_progress(client: TestClient, tmp_path: Path):
    r = client.post(
        "/api/jobs",
        json={
            "model": "mock/well_attuned",
            "packs": ["hello_metacog"],
            "k": 1,
            "api_base": "https://example.invalid/v1",
            "api_key": "sk-test-not-returned",
            "timeout": 30,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "mock/well_attuned"
    assert body["api_base"] == "https://example.invalid/v1"
    assert body["has_api_key"] is True
    assert "api_key" not in body
    assert "secret_path" not in body
    assert body["progress"] is not None
    assert body["progress"]["status"] == "queued"
    jid = body["id"]
    r = client.get(f"/api/jobs/{jid}/progress")
    assert r.status_code == 200
    assert r.json()["status"] == "queued"


def test_test_connection_mock(client: TestClient):
    r = client.post(
        "/api/test-connection",
        json={"model": "mock/well_attuned"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_worker_writes_progress(tmp_path: Path):
    from dsm_ae.queue.store import JobStore
    from dsm_ae.queue.worker import run_one

    reports = tmp_path / "reports"
    reports.mkdir()
    store = JobStore(tmp_path / "q.db")
    jid = store.enqueue(model="mock/well_attuned", packs=["hello_metacog"], k=1)
    from dsm_ae.queue.progress import progress_path_for, write_progress

    prog = progress_path_for(reports, jid)
    store.update_paths(jid, progress_path=str(prog))
    write_progress(prog, {"job_id": jid, "status": "queued", "message": "q"})
    ok = run_one(
        store,
        worker_id="t",
        reports_dir=reports,
        models_yaml=None,
        rebuild_html=False,
    )
    assert ok is True
    job = store.get(jid)
    assert job is not None and job.status.value == "succeeded"
    from dsm_ae.queue.progress import read_progress

    p = read_progress(job.progress_path)
    assert p is not None
    assert p.get("status") in ("succeeded", "running", "done") or p.get("phase") in (
        "done",
        "scoring",
        "running",
    )


def test_reports_and_matrix_send_no_cache_headers(client: TestClient, tmp_path: Path):
    reports = tmp_path / "reports"
    # client fixture already created reports; re-fetch via app routes on same client
    r = client.get("/matrix")
    assert r.status_code == 200
    cc = r.headers.get("cache-control", "")
    assert "no-store" in cc or "no-cache" in cc
    r = client.get("/reports-ui")
    assert "no-store" in r.headers.get("cache-control", "") or "no-cache" in r.headers.get(
        "cache-control", ""
    )
    r = client.get("/treatment")
    assert "no-store" in r.headers.get("cache-control", "")
    # static matrix file under /reports
    r = client.get("/reports/dsm-ae-matrix.html")
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", "") or "no-cache" in r.headers.get(
        "cache-control", ""
    )
