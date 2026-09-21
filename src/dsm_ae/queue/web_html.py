"""HTML page for the queue UI (kept separate from FastAPI routes)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from dsm_ae.packs.registry import list_packs
from dsm_ae.queue.store import JobStore

Href = Callable[[str], str]


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _configured_base(href: Href) -> str:
    sample = href("/queue")
    if sample.startswith("/") and sample.endswith("/queue"):
        return sample[: -len("/queue")]
    return ""


def render_nav(href: Href, active: str = "") -> str:
    """Shared top nav: Queue | Comparison | Reports | Literature | Compaction | API | Treatment.

    ``active`` is a path key: ``/``, ``/matrix``, ``/reports-ui``, ``/literature``,
    ``/compaction``, ``/docs``, ``/treatment``. API opens in a new tab (Swagger);
    other primary tabs stay in-app so the chrome never disappears.
    """
    items: list[tuple[str, str, bool]] = [
        ("/", "Queue", False),
        ("/matrix", "Comparison", False),
        ("/reports-ui", "Reports", False),
        ("/literature", "Literature", False),
        ("/compaction", "Compaction", False),
        ("/docs", "API", True),
        ("/treatment", "Treatment", False),
    ]
    parts: list[str] = []
    for path, label, blank in items:
        cls = ' class="active"' if path == active else ""
        target = ' target="_blank" rel="noopener"' if blank else ""
        parts.append(
            f'<a href="{href(path)}" data-nav="{_esc(path)}"{cls}{target}>{_esc(label)}</a>'
        )
    return "<nav>\n    " + "\n    ".join(parts) + "\n  </nav>"


def _shared_shell_css() -> str:
    return """
  :root { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
  body { margin: 0; padding: 16px 18px; background: #fafafa; color: #111; }
  h1 { font-size: 1.25rem; margin: 0 0 4px; }
  h2 { font-size: 1.05rem; margin: 18px 0 8px; }
  h3 { font-size: 0.95rem; margin: 14px 0 6px; }
  .meta { color: #555; font-size: 13px; margin: 0 0 12px; }
  nav { margin: 0 0 14px; }
  nav a { margin-right: 12px; color: #0645ad; text-decoration: none; }
  nav a:hover { text-decoration: underline; }
  nav a.active { font-weight: 600; color: #111; text-decoration: none; border-bottom: 2px solid #1565c0; }
  .panel { background: #fff; border: 1px solid #ddd; border-radius: 6px;
            padding: 12px 14px; margin: 0 0 14px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border: 1px solid #e0e0e0; padding: 4px 6px; text-align: left; vertical-align: top; }
  th { background: #f5f5f5; }
  code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
  pre { background: #f6f8fa; border: 1px solid #e0e0e0; border-radius: 4px;
        padding: 10px 12px; overflow: auto; white-space: pre-wrap; }
  .md-body { font-size: 13px; line-height: 1.45; }
  .md-body h1 { font-size: 1.15rem; margin: 0 0 10px; }
  .md-body h2 { font-size: 1.05rem; margin: 14px 0 8px; }
  .md-body p { margin: 0 0 8px; }
  .md-body table { margin: 8px 0 4px; max-width: 720px; }
  .md-body th { font-weight: 600; }
  .md-body tr:nth-child(even) td { background: #fafafa; }
  .hint { color: #666; font-size: 12px; }
  ul.file-list { margin: 0; padding-left: 18px; font-size: 13px; }
  ul.file-list li { margin: 2px 0; }
  /* Comparison embed: no nested viewport — iframe grows to content height so
     only the parent page scrolls (not iframe + inner panels + page). */
  body.comparison-page { padding-bottom: 0; }
  .iframe-wrap {
    border: 0; border-radius: 0; overflow: visible;
    background: transparent; height: auto; min-height: 0;
    margin: 0 -18px; /* flush with viewport edges under shell padding */
  }
  .iframe-wrap iframe {
    width: 100%; height: auto; min-height: 200px;
    border: 0; display: block; vertical-align: top;
  }
  /* Sub-tabs under Comparison: Multi-model | Context Bloat */
  .subtabs {
    display: flex; flex-wrap: wrap; gap: 6px;
    margin: 0 0 10px; padding: 0;
  }
  .subtabs button {
    appearance: none; border: 1px solid #ccc; background: #fff;
    color: #333; font: inherit; font-size: 13px;
    padding: 5px 12px; border-radius: 6px; cursor: pointer;
  }
  .subtabs button:hover { border-color: #1565c0; color: #1565c0; }
  .subtabs button.active {
    background: #e3f2fd; border-color: #1565c0; color: #0d47a1; font-weight: 600;
  }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }
  .help-cmd { background: #f0f4f8; padding: 2px 6px; border-radius: 3px; }
"""


def _nav_base_script() -> str:
    """Client-side public_base detection + data-nav href rewrite (funnel-safe)."""
    return """
<script>
(function () {
  function detectBase() {
    const p = location.pathname || "/";
    if (p === "/dsm-ae" || p.startsWith("/dsm-ae/")) return "/dsm-ae";
    const configured = (document.body.dataset.configuredBase || "").replace(/\\/$/, "");
    if (configured && (p === configured || p.startsWith(configured + "/"))) return configured;
    return "";
  }
  const BASE = detectBase();
  function href(path) {
    if (!path.startsWith("/")) path = "/" + path;
    return BASE + path;
  }
  document.querySelectorAll("a[data-nav]").forEach((a) => {
    a.setAttribute("href", href(a.getAttribute("data-nav") || "/"));
  });
  document.querySelectorAll("a[data-static]").forEach((a) => {
    const p = a.getAttribute("data-static") || "/";
    a.setAttribute("href", href(p));
  });
})();
</script>
"""


def render_queue_page(store: JobStore, href: Href, auth_required: bool, title: str) -> str:
    packs = list_packs()
    pack_checks = "\n".join(
        f'<label class="pack-item"><input type="checkbox" class="pack-cb" value="{_esc(p)}"/>'
        f"<span>{_esc(p)}</span></label>"
        for p in packs
    )
    configured_base = _configured_base(href)
    token_row = ""
    if auth_required:
        token_row = """
        <label>Queue token
          <input type="password" name="token" id="token"
                 placeholder="UI token, not model key"
                 autocomplete="off"/>
        </label>
        <p class="hint" id="token-status" hidden></p>
        """
    nav = render_nav(href, active="/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)} · Eval queue</title>
<style>
  :root {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }}
  body {{ margin: 0; padding: 16px 18px; background: #fafafa; color: #111; }}
  h1 {{ font-size: 1.25rem; margin: 0 0 4px; }}
  h2 {{ font-size: 1.05rem; margin: 18px 0 8px; }}
  .meta {{ color: #555; font-size: 13px; margin: 0 0 12px; }}
  nav {{ margin: 0 0 14px; }}
  nav a {{ margin-right: 12px; color: #0645ad; text-decoration: none; }}
  nav a:hover {{ text-decoration: underline; }}
  nav a.active {{ font-weight: 600; color: #111; text-decoration: none; border-bottom: 2px solid #1565c0; }}
  .panel {{ background: #fff; border: 1px solid #ddd; border-radius: 6px;
            padding: 12px 14px; margin: 0 0 14px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
  th, td {{ border: 1px solid #e0e0e0; padding: 4px 6px; text-align: left; vertical-align: top; }}
  th {{ background: #f5f5f5; }}
  form.enqueue label {{ display: block; margin: 0 0 8px; font-size: 13px; }}
  form.enqueue input[type=text], form.enqueue input[type=number],
  form.enqueue input[type=password], form.enqueue input[type=url] {{
    width: min(480px, 100%); padding: 4px 6px; margin-top: 2px; box-sizing: border-box;
  }}
  form.enqueue button, button.action, .btn {{
    background: #1565c0; color: #fff; border: 0; border-radius: 4px;
    padding: 6px 12px; cursor: pointer; font-size: 13px;
  }}
  button.action {{ background: #555; padding: 2px 8px; font-size: 12px; }}
  button.action:disabled, .btn:disabled {{ opacity: 0.5; cursor: not-allowed; }}
  .btn-test {{ background: #00897b; margin-left: 6px; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
  .hint {{ color: #666; font-size: 12px; }}
  .hint.ok {{ color: #2e7d32; }}
  .hint.err {{ color: #c62828; }}
  .status {{ color: #fff; padding: 1px 6px; border-radius: 3px; font-size: 12px; }}
  .st-queued {{ background: #0288d1; }}
  .st-running {{ background: #f9a825; color: #111; }}
  .st-succeeded {{ background: #2e7d32; }}
  .st-failed {{ background: #c62828; }}
  .st-cancelled {{ background: #757575; }}
  #flash {{ margin: 0 0 10px; font-size: 13px; min-height: 1.2em; }}
  #flash.ok {{ color: #2e7d32; }}
  #flash.err {{ color: #c62828; }}
  #conn-result {{ margin: 4px 0 8px; font-size: 13px; min-height: 1.2em; }}
  #conn-result.ok {{ color: #2e7d32; }}
  #conn-result.err {{ color: #c62828; }}
  .row-inline {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; max-width: 720px; }}
  @media (max-width: 700px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
  fieldset.conn {{ border: 1px solid #ddd; border-radius: 6px; padding: 10px 12px; margin: 0 0 10px; max-width: 720px; }}
  fieldset.conn legend {{ font-size: 13px; font-weight: 600; padding: 0 4px; }}
  .pack-dd {{ position: relative; max-width: 480px; }}
  .pack-toggle {{
    width: 100%; text-align: left; background: #fff; color: #111;
    border: 1px solid #ccc; border-radius: 4px; padding: 6px 8px; cursor: pointer;
  }}
  .pack-panel {{
    display: none; position: absolute; z-index: 20; left: 0; right: 0;
    max-height: 240px; overflow: auto; background: #fff; border: 1px solid #ccc;
    border-radius: 4px; margin-top: 2px; box-shadow: 0 4px 12px rgba(0,0,0,.08);
    padding: 6px;
  }}
  .pack-dd.open .pack-panel {{ display: block; }}
  .pack-item {{ display: flex; align-items: center; gap: 6px; margin: 0 0 4px; font-size: 13px; cursor: pointer; }}
  .pack-item input {{ width: auto; margin: 0; }}
  .pack-actions {{ display: flex; gap: 8px; margin: 0 0 6px; }}
  .pack-actions button {{ background: #eee; color: #333; padding: 2px 8px; font-size: 12px; }}
  .prog {{ font-size: 11px; color: #444; min-width: 120px; }}
  .prog-bar {{ height: 6px; background: #eee; border-radius: 3px; overflow: hidden; margin-top: 2px; max-width: 140px; }}
  .prog-bar > i {{ display: block; height: 100%; background: #1565c0; width: 0%; }}
</style>
</head>
<body data-configured-base="{_esc(configured_base)}">
  <h1>Eval queue</h1>
  <p class="meta">Add a model, choose packs, and run evaluations.</p>
  {nav}
  <div id="flash" role="status" aria-live="polite"></div>

  <div class="panel">
    <h2>Jobs <span id="jobs-updated" class="hint">· Auto-refresh 5s</span></h2>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Status</th><th>Model</th><th>Progress</th><th>Trials</th><th>Packs</th>
          <th>Label</th><th>Created</th><th>Error</th><th></th>
        </tr>
      </thead>
      <tbody id="jobs-body">
        <tr><td colspan="10" style="color:#666">No jobs</td></tr>
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>New evaluation</h2>
    <form class="enqueue" id="enqueue-form" method="post" action="{href("/queue")}">
      {token_row}

      <fieldset class="conn">
        <legend>Model endpoint</legend>
        <div class="grid2">
          <label>Model name
            <input type="text" name="model" id="f-model" required
                   placeholder="gpt-5.6-terra or mock/well_attuned"
                   autocomplete="off" data-persist="model"/>
          </label>
          <label>API base URL
            <input type="url" name="api_base" id="f-api-base"
                   placeholder="https://host/v1"
                   autocomplete="off" data-persist="api_base"/>
          </label>
          <label>API key
            <input type="password" name="api_key" id="f-api-key"
                   placeholder="optional if already configured on the server"
                   autocomplete="off"/>
          </label>
          <label>Timeout (seconds)
            <input type="number" name="timeout" id="f-timeout" value="120" min="5" max="600"
                   data-persist="timeout"/>
          </label>
        </div>
        <p class="hint">Blank = server config or mock/…</p>
        <div class="row-inline">
          <button type="button" class="btn btn-test" id="test-conn-btn">Test connection</button>
          <span id="conn-result" role="status"></span>
        </div>
      </fieldset>

      <label>Packs
        <div class="pack-dd" id="pack-dd">
          <button type="button" class="pack-toggle" id="pack-toggle">Choose packs…</button>
          <div class="pack-panel" id="pack-panel">
            <div class="pack-actions">
              <button type="button" id="pack-all">Select all</button>
              <button type="button" id="pack-none">Clear</button>
            </div>
            {pack_checks}
          </div>
        </div>
      </label>
      <label class="hint" style="display:flex;align-items:center;gap:6px">
        <input type="checkbox" id="f-full-cb" style="width:auto"/> All packs
      </label>

      <div class="grid2">
        <label>Trials
          <input type="number" name="k" id="f-k" value="3" min="1" max="50" data-persist="k"/>
        </label>
        <label>Concurrency
          <input type="number" name="concurrency" id="f-concurrency" value="1" min="1" max="32" data-persist="concurrency"/>
        </label>
        <label>Priority
          <input type="number" name="priority" id="f-priority" value="0" data-persist="priority"/>
        </label>
        <label>Label
          <input type="text" name="label" id="f-label" placeholder="e.g. weekly check" data-persist="label"/>
        </label>
      </div>
      <button type="submit" id="enqueue-btn">Start evaluation</button>
    </form>
  </div>

<script>
(function () {{
  const AUTH_REQUIRED = {json.dumps(auth_required)};
  const STORAGE_KEY = "dsm-ae-queue-form-v2";
  const POLL_MS = 5000;

  function detectBase() {{
    const p = location.pathname || "/";
    if (p === "/dsm-ae" || p.startsWith("/dsm-ae/")) return "/dsm-ae";
    const configured = (document.body.dataset.configuredBase || "").replace(/\\/$/, "");
    if (configured && (p === configured || p.startsWith(configured + "/"))) return configured;
    return "";
  }}
  const BASE = detectBase();
  function href(path) {{
    if (!path.startsWith("/")) path = "/" + path;
    return BASE + path;
  }}
  const API_JOBS = href("/api/jobs");
  const API_TEST = href("/api/test-connection");

  document.querySelectorAll("a[data-nav]").forEach((a) => {{
    a.setAttribute("href", href(a.getAttribute("data-nav") || "/"));
  }});
  const formEl = document.getElementById("enqueue-form");
  if (formEl) formEl.setAttribute("action", href("/queue"));

  const TOKEN_COOKIE = "dsm_ae_queue_token";
  const TOKEN_COOKIE_DAYS = 14;

  function flash(msg, ok) {{
    const el = document.getElementById("flash");
    el.textContent = msg || "";
    el.className = msg ? (ok ? "ok" : "err") : "";
  }}
  function connMsg(msg, ok) {{
    const el = document.getElementById("conn-result");
    el.textContent = msg || "";
    el.className = msg ? (ok ? "ok" : "err") : "";
  }}
  function tokenStatus(msg, ok) {{
    const el = document.getElementById("token-status");
    if (!el) return;
    el.textContent = msg || "";
    el.className = "hint" + (msg ? (ok ? " ok" : " err") : "");
  }}

  function getCookie(name) {{
    const parts = ("; " + document.cookie).split("; " + name + "=");
    if (parts.length !== 2) return "";
    return decodeURIComponent(parts.pop().split(";").shift() || "");
  }}
  function setQueueTokenCookie(value) {{
    if (!value) return;
    const maxAge = TOKEN_COOKIE_DAYS * 24 * 60 * 60;
    // Path must cover funnel prefix and root so both local and /dsm-ae work.
    const path = BASE || "/";
    document.cookie = TOKEN_COOKIE + "=" + encodeURIComponent(value)
      + "; path=" + path
      + "; max-age=" + maxAge
      + "; SameSite=Lax";
    // Also set on / so non-prefixed routes work when dual-accessed.
    if (path !== "/") {{
      document.cookie = TOKEN_COOKIE + "=" + encodeURIComponent(value)
        + "; path=/; max-age=" + maxAge + "; SameSite=Lax";
    }}
  }}
  function getQueueToken() {{
    const el = document.getElementById("token");
    const fromInput = el && el.value ? el.value.trim() : "";
    if (fromInput) return fromInput;
    return (getCookie(TOKEN_COOKIE) || "").trim();
  }}
  function rememberQueueTokenIfPresent() {{
    const t = getQueueToken();
    if (t) {{
      setQueueTokenCookie(t);
      const el = document.getElementById("token");
      if (el && !el.value) el.value = t;
      // Silent cookie persist — no implementation toast.
    }}
  }}
  function authHeaders() {{
    const headers = {{}};
    const tok = getQueueToken();
    if (tok) {{
      headers["Authorization"] = "Bearer " + tok;
      headers["X-DSM-AE-Token"] = tok;
    }}
    return headers;
  }}

  /** Parse FastAPI / fetch errors; distinguish queue token vs inference endpoint. */
  function formatApiError(res, data, context) {{
    const ctx = context || "request";
    const detail = data && data.detail;
    if (res && res.status === 401) {{
      if (detail && typeof detail === "object" && detail.message) {{
        return detail.message;
      }}
      if (typeof detail === "string") {{
        return "Queue UI authentication failed: " + detail
          + " (queue token — not the model API key).";
      }}
      return "Queue UI authentication failed (HTTP 401). "
        + "Enter the DSM-AE queue token (DSM_AE_QUEUE_TOKEN), not the model API key.";
    }}
    if (detail && typeof detail === "object" && detail.message) return detail.message;
    if (typeof detail === "string") return detail;
    if (data && data.message) return data.message;
    if (data && data.ok === false && data.message) return data.message;
    return ctx + " failed" + (res ? " (HTTP " + res.status + ")" : "");
  }}

  const dd = document.getElementById("pack-dd");
  const toggle = document.getElementById("pack-toggle");
  const fullCb = document.getElementById("f-full-cb");

  function selectedPacks() {{
    return Array.from(document.querySelectorAll(".pack-cb:checked")).map((c) => c.value);
  }}
  function updatePackLabel() {{
    if (fullCb.checked) {{ toggle.textContent = "All packs"; return; }}
    const sel = selectedPacks();
    if (!sel.length) toggle.textContent = "Choose packs…";
    else if (sel.length <= 3) toggle.textContent = sel.join(", ");
    else toggle.textContent = sel.length + " packs selected";
  }}
  toggle.addEventListener("click", (ev) => {{ ev.preventDefault(); dd.classList.toggle("open"); }});
  document.addEventListener("click", (ev) => {{ if (!dd.contains(ev.target)) dd.classList.remove("open"); }});
  document.getElementById("pack-all").addEventListener("click", (ev) => {{
    ev.preventDefault();
    document.querySelectorAll(".pack-cb").forEach((c) => {{ c.checked = true; }});
    fullCb.checked = false; updatePackLabel(); persistForm();
  }});
  document.getElementById("pack-none").addEventListener("click", (ev) => {{
    ev.preventDefault();
    document.querySelectorAll(".pack-cb").forEach((c) => {{ c.checked = false; }});
    fullCb.checked = false; updatePackLabel(); persistForm();
  }});
  document.querySelectorAll(".pack-cb").forEach((c) => {{
    c.addEventListener("change", () => {{ fullCb.checked = false; updatePackLabel(); persistForm(); }});
  }});
  fullCb.addEventListener("change", () => {{
    if (fullCb.checked) document.querySelectorAll(".pack-cb").forEach((c) => {{ c.checked = false; }});
    updatePackLabel(); persistForm();
  }});

  function persistForm() {{
    const data = {{}};
    document.querySelectorAll("[data-persist]").forEach((el) => {{
      data[el.getAttribute("data-persist")] = el.type === "checkbox" ? el.checked : el.value;
    }});
    data.packs = selectedPacks();
    data.full_suite = fullCb.checked;
    try {{ sessionStorage.setItem(STORAGE_KEY, JSON.stringify(data)); }} catch (e) {{}}
    // Keep queue token in cookie (not sessionStorage) once entered.
    const tokEl = document.getElementById("token");
    if (tokEl && tokEl.value.trim()) setQueueTokenCookie(tokEl.value.trim());
  }}
  function restoreForm() {{
    let data = null;
    try {{ data = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "null"); }} catch (e) {{}}
    if (data) {{
      document.querySelectorAll("[data-persist]").forEach((el) => {{
        const k = el.getAttribute("data-persist");
        if (!(k in data)) return;
        if (el.type === "checkbox") el.checked = !!data[k];
        else if (data[k] != null) el.value = data[k];
      }});
      if (Array.isArray(data.packs)) {{
        const set = new Set(data.packs);
        document.querySelectorAll(".pack-cb").forEach((c) => {{ c.checked = set.has(c.value); }});
      }}
      fullCb.checked = !!data.full_suite;
    }}
    // Prefer cookie for queue token so the field is filled across visits.
    const tokEl = document.getElementById("token");
    if (tokEl) {{
      const cookieTok = getCookie(TOKEN_COOKIE);
      if (cookieTok) {{
        tokEl.value = cookieTok;
      }}
    }}
    updatePackLabel();
  }}

  function esc(s) {{
    return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
      .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }}
  function badge(status) {{
    return '<span class="status st-' + esc(status) + '">' + esc(status) + "</span>";
  }}
  function progCell(job) {{
    const p = job.progress || null;
    if (!p) {{
      if (job.status === "queued") return '<div class="prog">waiting…</div>';
      if (job.status === "succeeded") return '<div class="prog">100%</div>';
      return '<div class="prog">—</div>';
    }}
    const pct = (p.percent != null) ? p.percent : (p.total ? Math.round(100*(p.done||0)/p.total) : 0);
    const frac = (p.total != null && p.total > 0)
      ? (' ' + (p.done||0) + '/' + p.total)
      : '';
    const harbor = (p.runner === "harbor")
      ? (' · harbor' + (p.current_pack ? (' ' + p.current_pack + (p.current_trial != null ? (' t'+(p.current_trial+1)) : '')) : ''))
      : '';
    return '<div class="prog">' + esc(String(pct)) + '%' + esc(frac) + harbor +
      ' · ' + esc(p.message || "") +
      '<div class="prog-bar"><i style="width:' + pct + '%"></i></div></div>';
  }}

  function renderJobs(jobs) {{
    const tbody = document.getElementById("jobs-body");
    if (!jobs || !jobs.length) {{
      tbody.innerHTML = '<tr><td colspan="10" style="color:#666">No jobs</td></tr>';
      return;
    }}
    tbody.innerHTML = jobs.map((j) => {{
      const packs = (j.packs && j.packs.length) ? j.packs.join(",") : "—";
      let err = j.error || "";
      if (err.length > 100) err = err.slice(0, 100) + "…";
      let actions = "";
      if (j.status === "queued")
        actions = '<button type="button" class="action" data-act="cancel" data-id="'+esc(j.id)+'">cancel</button>';
      else if (j.status === "failed" || j.status === "cancelled")
        actions = '<button type="button" class="action" data-act="retry" data-id="'+esc(j.id)+'" title="Re-queue; finished pack×trials resume from .dsm_ae_ckpt">continue</button>';
      const endpoint = j.api_base ? (' <span class="hint" title="'+esc(j.api_base)+'">↗</span>') : "";
      return "<tr>" +
        '<td><code title="'+esc(j.id)+'">'+esc(j.id.slice(0,8))+"</code></td>" +
        "<td>"+badge(j.status)+"</td>" +
        "<td><code>"+esc(j.model)+"</code>"+endpoint+"</td>" +
        "<td>"+progCell(j)+"</td>" +
        "<td>"+esc(j.k)+"</td>" +
        '<td style="max-width:160px;overflow:hidden;text-overflow:ellipsis">'+esc(packs)+"</td>" +
        "<td>"+esc(j.label||"")+"</td>" +
        '<td style="font-size:11px">'+esc(j.created_at||"")+"</td>" +
        '<td style="font-size:11px;color:#a00">'+esc(err)+"</td>" +
        "<td>"+actions+"</td></tr>";
    }}).join("");
  }}

  async function refreshJobs() {{
    try {{
      const res = await fetch(API_JOBS + "?limit=100", {{ cache: "no-store" }});
      if (!res.ok) throw new Error("HTTP " + res.status);
      renderJobs(await res.json());
      const u = document.getElementById("jobs-updated");
      u.textContent = "· Auto-refresh 5s · " + new Date().toLocaleTimeString();
      u.className = "hint ok";
    }} catch (e) {{
      const u = document.getElementById("jobs-updated");
      u.textContent = "· Auto-refresh failed";
      u.className = "hint err";
    }}
  }}

  async function jobAction(act, id, btn) {{
    if (AUTH_REQUIRED && !getQueueToken()) {{
      flash("Queue token required", false);
      return;
    }}
    if (btn) btn.disabled = true;
    try {{
      const res = await fetch(API_JOBS + "/" + encodeURIComponent(id) + "/" + act, {{
        method: "POST", headers: authHeaders(), credentials: "same-origin",
      }});
      const data = await res.json().catch(() => ({{}}));
      if (!res.ok) {{
        flash(formatApiError(res, data, act), false);
        await refreshJobs(); return;
      }}
      rememberQueueTokenIfPresent();
      flash(act + " ok", true);
      await refreshJobs();
    }} catch (e) {{
      flash(String(e), false); await refreshJobs();
    }} finally {{ if (btn) btn.disabled = false; }}
  }}

  document.getElementById("jobs-body").addEventListener("click", (ev) => {{
    const btn = ev.target.closest("button[data-act]");
    if (!btn) return;
    jobAction(btn.getAttribute("data-act"), btn.getAttribute("data-id"), btn);
  }});

  document.getElementById("test-conn-btn").addEventListener("click", async () => {{
    if (AUTH_REQUIRED && !getQueueToken()) {{
      connMsg("Queue token required", false);
      return;
    }}
    const btn = document.getElementById("test-conn-btn");
    btn.disabled = true;
    const t0 = performance.now();
    connMsg("Testing…", true);
    try {{
      // Cap probe timeout so a dead host does not hang the UI for 120s.
      const formTimeout = parseFloat(document.getElementById("f-timeout").value || "45");
      const body = {{
        model: (document.getElementById("f-model").value || "").trim(),
        api_base: (document.getElementById("f-api-base").value || "").trim() || null,
        api_key: (document.getElementById("f-api-key").value || "").trim() || null,
        timeout: Math.min(Math.max(formTimeout || 45, 5), 45),
        num_retries: 0,
      }};
      if (!body.model) {{ connMsg("Enter a model id", false); return; }}
      const controller = new AbortController();
      const kill = setTimeout(() => controller.abort(), (body.timeout + 10) * 1000);
      let res, data;
      try {{
        res = await fetch(API_TEST, {{
          method: "POST",
          headers: Object.assign({{"Content-Type":"application/json"}}, authHeaders()),
          credentials: "same-origin",
          body: JSON.stringify(body),
          signal: controller.signal,
        }});
        data = await res.json().catch(() => ({{ ok: false, message: res.statusText }}));
      }} finally {{
        clearTimeout(kill);
      }}
      const ms = Math.round(performance.now() - t0);
      if (!res.ok) {{
        connMsg(formatApiError(res, data, "Test connection") + " (" + ms + "ms)", false);
        return;
      }}
      if (data.ok) {{
        rememberQueueTokenIfPresent();
        connMsg((data.message || "Inference endpoint OK") + " (" + ms + "ms)", true);
      }} else {{
        connMsg(
          (data.message
            || "Inference endpoint error (model API base/key) — queue token was accepted.")
            + " (" + ms + "ms)",
          false
        );
      }}
    }} catch (e) {{
      const ms = Math.round(performance.now() - t0);
      const name = (e && e.name) || "";
      if (name === "AbortError") {{
        connMsg("Test timed out (" + ms + "ms)", false);
      }} else {{
        connMsg(String(e) + " (" + ms + "ms)", false);
      }}
    }} finally {{ btn.disabled = false; }}
  }});

  const form = document.getElementById("enqueue-form");
  form.addEventListener("input", persistForm);
  form.addEventListener("change", persistForm);
  form.addEventListener("submit", async (ev) => {{
    ev.preventDefault(); persistForm();
    if (AUTH_REQUIRED && !getQueueToken()) {{
      flash("Queue token required", false);
      return;
    }}
    const btn = document.getElementById("enqueue-btn");
    btn.disabled = true;
    try {{
      const packs = fullCb.checked ? null : selectedPacks();
      const body = {{
        model: (document.getElementById("f-model").value || "").trim(),
        packs: packs && packs.length ? packs : null,
        full_suite: fullCb.checked,
        k: parseInt(document.getElementById("f-k").value || "3", 10),
        concurrency: parseInt(document.getElementById("f-concurrency").value || "1", 10),
        priority: parseInt(document.getElementById("f-priority").value || "0", 10),
        label: ((document.getElementById("f-label").value || "").trim() || null),
        api_base: (document.getElementById("f-api-base").value || "").trim() || null,
        api_key: (document.getElementById("f-api-key").value || "").trim() || null,
        timeout: parseFloat(document.getElementById("f-timeout").value || "120"),
        num_retries: 2,
      }};
      const res = await fetch(API_JOBS, {{
        method: "POST",
        headers: Object.assign({{"Content-Type":"application/json"}}, authHeaders()),
        credentials: "same-origin",
        body: JSON.stringify(body),
      }});
      const data = await res.json().catch(() => ({{}}));
      if (!res.ok) {{
        flash(formatApiError(res, data, "Enqueue"), false);
        return;
      }}
      rememberQueueTokenIfPresent();
      flash("Enqueued " + (data.id || "").slice(0, 8) + " · " + data.model, true);
      document.getElementById("f-label").value = "";
      persistForm();
      await refreshJobs();
    }} catch (e) {{
      flash(String(e), false);
    }} finally {{ btn.disabled = false; }}
  }});

  restoreForm();
  updatePackLabel();
  refreshJobs();
  setInterval(refreshJobs, POLL_MS);
}})();
</script>
</body>
</html>
"""


def _parse_treatment_result_name(name: str) -> tuple[str, str]:
    """Best-effort split of ``model-arm.ext`` report filenames."""
    stem = Path(name).stem
    known_arms = (
        "baseline",
        "prompt_reminder",
        "skill_scaffold",
        "expert_oversight",
    )
    for arm in known_arms:
        if stem.endswith("-" + arm):
            return stem[: -(len(arm) + 1)], arm
    if "-" in stem:
        model, arm = stem.rsplit("-", 1)
        return model, arm
    return stem, "—"


def _is_md_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _is_md_table_sep(line: str) -> bool:
    s = line.strip().strip("|")
    if not s or "|" not in line:
        return False
    cells = [c.strip() for c in s.split("|")]
    return all(c and set(c) <= set("-: ") for c in cells)


def _md_row_cells(line: str) -> list[str]:
    s = line.strip().strip("|")
    return [c.strip() for c in s.split("|")]


def render_simple_markdown(md: str) -> str:
    """Render a small Markdown subset to HTML (headings, paragraphs, GFM tables).

    Used for treatment SUMMARY.md etc. Avoids a markdown dependency; escapes text.
    """
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)

    def flush_para(buf: list[str]) -> None:
        if not buf:
            return
        text = " ".join(x.strip() for x in buf if x.strip())
        if text:
            out.append(f"<p>{_esc(text)}</p>")
        buf.clear()

    para: list[str] = []
    while i < n:
        line = lines[i]
        if not line.strip():
            flush_para(para)
            i += 1
            continue
        if line.startswith("### "):
            flush_para(para)
            out.append(f"<h3>{_esc(line[4:].strip())}</h3>")
            i += 1
            continue
        if line.startswith("## "):
            flush_para(para)
            out.append(f"<h2>{_esc(line[3:].strip())}</h2>")
            i += 1
            continue
        if line.startswith("# "):
            flush_para(para)
            out.append(f"<h1>{_esc(line[2:].strip())}</h1>")
            i += 1
            continue
        if _is_md_table_row(line):
            flush_para(para)
            rows: list[list[str]] = []
            while i < n and _is_md_table_row(lines[i]):
                if not _is_md_table_sep(lines[i]):
                    rows.append(_md_row_cells(lines[i]))
                i += 1
            if not rows:
                continue
            head, *body = rows
            out.append("<table>")
            out.append(
                "<thead><tr>"
                + "".join(f"<th>{_esc(c)}</th>" for c in head)
                + "</tr></thead>"
            )
            out.append("<tbody>")
            for row in body:
                # pad/truncate to header width for ragged rows
                cells = (row + [""] * len(head))[: len(head)]
                out.append(
                    "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in cells) + "</tr>"
                )
            out.append("</tbody></table>")
            continue
        para.append(line)
        i += 1
    flush_para(para)
    return "\n".join(out) if out else ""


def render_treatment_page(href: Href, reports_dir: Path | str, title: str = "Treatment") -> str:
    """Read-only dashboard for registered treatments and trial results."""
    from dsm_ae.treatment import get_treatment, list_treatments

    reports_dir = Path(reports_dir)
    configured_base = _configured_base(href)
    nav = render_nav(href, active="/treatment")

    treatment_rows: list[str] = []
    for tid in list_treatments():
        t = get_treatment(tid)
        treatment_rows.append(
            "<tr>"
            f"<td><code>{_esc(t.id)}</code></td>"
            f"<td>{_esc(t.name)}</td>"
            f"<td>{_esc(t.description or '')}</td>"
            "</tr>"
        )
    treatments_table = (
        "\n".join(treatment_rows)
        if treatment_rows
        else '<tr><td colspan="3" class="hint">No treatments registered</td></tr>'
    )

    treatment_dir = reports_dir / "treatment"
    summary_html = '<p class="hint">No SUMMARY.md under <code>reports/treatment/</code> yet.</p>'
    if (treatment_dir / "SUMMARY.md").is_file():
        raw = (treatment_dir / "SUMMARY.md").read_text(encoding="utf-8", errors="replace")
        rendered = render_simple_markdown(raw)
        summary_html = (
            f'<div class="md-body">{rendered}</div>'
            f'<p class="hint" style="margin-top:8px">'
            f'<a href="{href("/reports/treatment/SUMMARY.md")}" '
            f'data-static="/reports/treatment/SUMMARY.md">Raw SUMMARY.md</a></p>'
        )

    file_rows: list[str] = []
    if treatment_dir.is_dir():
        files = sorted(
            p
            for p in treatment_dir.iterdir()
            if p.is_file() and p.suffix in (".json", ".md") and p.name != "SUMMARY.md"
        )
        # Group by stem so .md + .json share one row when possible
        by_stem: dict[str, dict[str, Path]] = {}
        for p in files:
            by_stem.setdefault(p.stem, {})[p.suffix] = p
        for stem in sorted(by_stem):
            model, arm = _parse_treatment_result_name(stem + ".md")
            links: list[str] = []
            for suf, label in ((".md", "md"), (".json", "json")):
                p = by_stem[stem].get(suf)
                if p:
                    rel = f"/reports/treatment/{p.name}"
                    links.append(
                        f'<a href="{href(rel)}" data-static="{_esc(rel)}">{_esc(label)}</a>'
                    )
            file_rows.append(
                "<tr>"
                f"<td><code>{_esc(model)}</code></td>"
                f"<td><code>{_esc(arm)}</code></td>"
                f"<td>{' · '.join(links)}</td>"
                f"<td><code>reports/treatment/{_esc(stem)}.*</code></td>"
                "</tr>"
            )
    files_table = (
        "\n".join(file_rows)
        if file_rows
        else '<tr><td colspan="4" class="hint">No treatment result files yet</td></tr>'
    )

    work_items: list[str] = []
    luna_root = reports_dir / "work" / "treatment_luna"
    if luna_root.is_dir():
        for d in sorted(luna_root.iterdir()):
            if d.is_dir():
                rel = f"/reports/work/treatment_luna/{d.name}/"
                work_items.append(
                    f'<li><a href="{href(rel)}" data-static="{_esc(rel)}">'
                    f"<code>{_esc(d.name)}</code></a>"
                    f' <span class="hint">reports/work/treatment_luna/{_esc(d.name)}/</span></li>'
                )
    work_html = (
        "<ul class=\"file-list\">\n" + "\n".join(work_items) + "\n</ul>"
        if work_items
        else '<p class="hint">No trajectory dirs under <code>reports/work/treatment_luna/</code>.</p>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)} · DSM-AE</title>
<style>{_shared_shell_css()}</style>
</head>
<body data-configured-base="{_esc(configured_base)}">
  <h1>Treatment</h1>
  <p class="meta">Registered intervention arms and completed trial results.</p>
  {nav}

  <div class="panel">
    <h2>Registered treatments</h2>
    <table>
      <thead><tr><th>ID</th><th>Name</th><th>Description</th></tr></thead>
      <tbody>
        {treatments_table}
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>Trial summary</h2>
    {summary_html}
  </div>

  <div class="panel">
    <h2>Result files</h2>
    <p class="hint">From <code>reports/treatment/</code> (static download via /reports/…).</p>
    <table>
      <thead><tr><th>Model</th><th>Arm</th><th>Links</th><th>Path</th></tr></thead>
      <tbody>
        {files_table}
      </tbody>
    </table>
  </div>

  <div class="panel">
    <h2>Trajectory work dirs</h2>
    {work_html}
  </div>

  <div class="panel">
    <h2>How to run</h2>
    <p class="meta">CLI only for now — this page is a read-only dashboard.</p>
    <ul class="file-list">
      <li>Single arm:
        <code class="help-cmd">dsm-ae diagnose -m &lt;model&gt; --treatment &lt;id&gt; …</code>
        where <code>&lt;id&gt;</code> is one of
        <code>prompt_reminder</code>, <code>skill_scaffold</code>,
        <code>expert_oversight</code> (omit for baseline).
      </li>
      <li>Luna multi-arm trial script:
        <code class="help-cmd">scripts/run_treatment_luna_trial.sh</code>
        (writes <code>reports/treatment/</code> +
        <code>reports/work/treatment_luna/</code>).
      </li>
    </ul>
  </div>
  {_nav_base_script()}
</body>
</html>
"""


def render_reports_page(href: Href, reports_dir: Path | str, title: str = "Reports") -> str:
    """App chrome + directory index of key report areas (static files stay at /reports/)."""
    reports_dir = Path(reports_dir)
    configured_base = _configured_base(href)
    nav = render_nav(href, active="/reports-ui")

    sections: list[tuple[str, str, str]] = [
        ("Comparison matrix", "/matrix", "In-app matrix shell"),
        ("Full static tree", "/reports/", "Raw StaticFiles listing / index.html"),
        ("Queue job reports", "/reports/queue/", "Per-job JSON/MD from the eval queue"),
        ("Treatment results", "/reports/treatment/", "Treatment trial outputs"),
        ("Full-suite reports", "/reports/full-suite/", "Full pack-suite diagnosis runs"),
        ("Work / trajectories", "/reports/work/", "Workspace + trajectory artifacts"),
    ]
    section_items = []
    for label, path, note in sections:
        section_items.append(
            f'<li><a href="{href(path)}" data-static="{_esc(path)}"><strong>{_esc(label)}</strong></a>'
            f' — <code>{_esc(path)}</code>'
            f' <span class="hint">{_esc(note)}</span></li>'
        )

    # Highlight a few top-level report files if present
    top_files: list[str] = []
    if reports_dir.is_dir():
        for name in (
            "dsm-ae-matrix.html",
            "index.html",
            "COMPARISON.md",
            "COVERAGE.md",
        ):
            p = reports_dir / name
            if p.is_file():
                rel = f"/reports/{name}"
                top_files.append(
                    f'<li><a href="{href(rel)}" data-static="{_esc(rel)}">'
                    f"<code>{_esc(name)}</code></a></li>"
                )
        # Also list treatment SUMMARY if present
        if (reports_dir / "treatment" / "SUMMARY.md").is_file():
            rel = "/reports/treatment/SUMMARY.md"
            top_files.append(
                f'<li><a href="{href(rel)}" data-static="{_esc(rel)}">'
                f"<code>treatment/SUMMARY.md</code></a></li>"
            )

    top_html = (
        "<ul class=\"file-list\">\n" + "\n".join(top_files) + "\n</ul>"
        if top_files
        else '<p class="hint">No top-level report files found yet.</p>'
    )

    # Subdirectory overview (shallow count — work/ trees can be huge)
    dir_rows: list[str] = []
    if reports_dir.is_dir():
        for d in sorted(reports_dir.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            try:
                n_entries = sum(1 for _ in d.iterdir())
            except OSError:
                n_entries = 0
            rel = f"/reports/{d.name}/"
            dir_rows.append(
                "<tr>"
                f'<td><a href="{href(rel)}" data-static="{_esc(rel)}"><code>{_esc(d.name)}/</code></a></td>'
                f"<td>{n_entries}</td>"
                f"<td><code>reports/{_esc(d.name)}/</code></td>"
                "</tr>"
            )
    dirs_table = (
        "\n".join(dir_rows)
        if dir_rows
        else '<tr><td colspan="3" class="hint">No report subdirectories</td></tr>'
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)} · DSM-AE</title>
<style>{_shared_shell_css()}</style>
</head>
<body data-configured-base="{_esc(configured_base)}">
  <h1>Reports</h1>
  <p class="meta">Browse diagnosis outputs with app navigation. Downloads stay at
     <code>/reports/…</code>.</p>
  {nav}

  <div class="panel">
    <h2>Quick links</h2>
    <ul class="file-list">
      {"".join(section_items)}
    </ul>
  </div>

  <div class="panel">
    <h2>Featured files</h2>
    {top_html}
  </div>

  <div class="panel">
    <h2>Report directories</h2>
    <table>
      <thead><tr><th>Directory</th><th>Entries</th><th>Path</th></tr></thead>
      <tbody>
        {dirs_table}
      </tbody>
    </table>
  </div>
  {_nav_base_script()}
</body>
</html>
"""


def render_comparison_page(href: Href, reports_dir: Path | str, title: str = "Comparison") -> str:
    """App chrome + tabbed iframes for multi-model matrix and Context Bloat.

    Tabs:
      Multi-model — classic cross-model matrix (``dsm-ae-matrix.html``)
      Context Bloat — baseline vs 50% fill for models with bloat50 runs

    Each iframe is height-matched to its document so the parent page is the only
    vertical scroller (no nested iframe scrollbar).
    """
    reports_dir = Path(reports_dir)
    configured_base = _configured_base(href)
    nav = render_nav(href, active="/matrix")

    matrix = reports_dir / "dsm-ae-matrix.html"
    index = reports_dir / "index.html"
    if matrix.is_file():
        baseline_path = "/reports/dsm-ae-matrix.html"
        baseline_note = "Cross-model matrix (all baseline / suite reports)"
    elif index.is_file():
        baseline_path = "/reports/index.html"
        baseline_note = "Matrix not built yet — showing reports index"
    else:
        baseline_path = ""
        baseline_note = "No matrix HTML yet — run a successful job first"

    bloat_html = reports_dir / "bloat" / "bloat50" / "comparison.html"
    if bloat_html.is_file():
        bloat_path = "/reports/bloat/bloat50/comparison.html"
        bloat_note = (
            "Baseline vs context bloat 50% — metrics from packs with complete "
            "bloat checkpoints (excludes incomplete tool_integrity_tier2 until done)"
        )
    else:
        bloat_path = ""
        bloat_note = (
            "Context Bloat matrix not built yet — run "
            "<code>python scripts/build_bloat_comparison.py</code> after bloat50 jobs"
        )

    exp_html = reports_dir / "experimental-ui" / "index.html"
    if exp_html.is_file():
        exp_path = "/reports/experimental-ui/index.html"
        exp_note = (
            "Experimental gel-style fingerprints — semantic metric groups, "
            "similarity-ordered models (branch experimental-ui). "
            "Rebuild: <code>python scripts/build_experimental_ui.py</code>"
        )
    else:
        exp_path = ""
        exp_note = (
            "Experimental UI not built — run "
            "<code>PYTHONPATH=src python scripts/build_experimental_ui.py</code>"
        )

    def _iframe_panel(
        panel_id: str,
        active: bool,
        note: str,
        embed_path: str,
        iframe_id: str,
        iframe_title: str,
        open_label: str,
    ) -> str:
        act = " active" if active else ""
        if embed_path:
            return f"""
  <div class="tab-panel{act}" id="{_esc(panel_id)}" data-panel="{_esc(panel_id)}">
    <p class="meta">{note}.
      <a href="{href(embed_path)}" data-static="{_esc(embed_path)}" target="_blank" rel="noopener">{_esc(open_label)}</a>
    </p>
    <div class="iframe-wrap">
      <iframe id="{_esc(iframe_id)}" class="matrix-frame" src="{href(embed_path)}"
              title="{_esc(iframe_title)}" scrolling="no"
              loading="{'eager' if active else 'lazy'}"></iframe>
    </div>
  </div>
"""
        return f"""
  <div class="tab-panel{act}" id="{_esc(panel_id)}" data-panel="{_esc(panel_id)}">
    <div class="panel">
      <p>{note}</p>
    </div>
  </div>
"""

    baseline_panel = _iframe_panel(
        "tab-baseline",
        True,
        baseline_note,
        baseline_path,
        "matrix-frame-baseline",
        "DSM-AE multi-model matrix",
        "Open full page",
    )
    bloat_panel = _iframe_panel(
        "tab-bloat",
        False,
        bloat_note,
        bloat_path,
        "matrix-frame-bloat",
        "Context Bloat baseline vs 50%",
        "Open full page",
    )
    exp_panel = _iframe_panel(
        "tab-experimental",
        False,
        exp_note,
        exp_path,
        "matrix-frame-experimental",
        "Experimental electrophoresis-style UI gallery",
        "Open full page",
    )

    body_main = f"""
  <div class="subtabs" role="tablist" aria-label="Comparison views">
    <button type="button" role="tab" data-tab="tab-baseline" class="active"
            aria-selected="true">Multi-model</button>
    <button type="button" role="tab" data-tab="tab-bloat"
            aria-selected="false">Context Bloat</button>
    <button type="button" role="tab" data-tab="tab-experimental"
            aria-selected="false">Experimental</button>
  </div>
  {baseline_panel}
  {bloat_panel}
  {exp_panel}
  <script>
  (function () {{
    function contentHeight(doc) {{
      const b = doc.body;
      const e = doc.documentElement;
      if (!b || !e) return 0;
      return Math.max(
        b.scrollHeight, b.offsetHeight,
        e.scrollHeight, e.offsetHeight, e.clientHeight
      );
    }}

    function wireFrame(iframe) {{
      if (!iframe) return;
      function resize() {{
        try {{
          const doc = iframe.contentDocument || iframe.contentWindow.document;
          if (!doc) return;
          try {{ doc.documentElement.classList.add("embedded-in-shell"); }} catch (e) {{}}
          const h = contentHeight(doc);
          if (h > 0) iframe.style.height = h + "px";
        }} catch (e) {{}}
      }}
      iframe.addEventListener("load", function () {{
        resize();
        try {{
          const doc = iframe.contentDocument || iframe.contentWindow.document;
          if (doc && doc.body && typeof ResizeObserver !== "undefined") {{
            const ro = new ResizeObserver(function () {{ resize(); }});
            ro.observe(doc.body);
            if (doc.documentElement) ro.observe(doc.documentElement);
          }}
          setTimeout(resize, 300);
          setTimeout(resize, 1200);
          setTimeout(resize, 3000);
        }} catch (e) {{}}
      }});
      window.addEventListener("resize", resize);
      iframe._dsmResize = resize;
    }}

    document.querySelectorAll("iframe.matrix-frame").forEach(wireFrame);

    window.addEventListener("message", function (ev) {{
      if (ev.origin !== window.location.origin) return;
      if (ev.data && ev.data.type === "dsm-ae-matrix-resize") {{
        document.querySelectorAll("iframe.matrix-frame").forEach(function (f) {{
          if (f._dsmResize) f._dsmResize();
        }});
      }}
    }});

    const tabs = document.querySelectorAll(".subtabs [data-tab]");
    const panels = document.querySelectorAll(".tab-panel");
    function activate(id) {{
      tabs.forEach(function (btn) {{
        const on = btn.getAttribute("data-tab") === id;
        btn.classList.toggle("active", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
      }});
      panels.forEach(function (p) {{
        p.classList.toggle("active", p.id === id);
      }});
      const panel = document.getElementById(id);
      if (panel) {{
        panel.querySelectorAll("iframe.matrix-frame").forEach(function (f) {{
          if (f._dsmResize) setTimeout(f._dsmResize, 50);
        }});
      }}
      try {{
        const u = new URL(window.location.href);
        const tab =
          id === "tab-bloat" ? "bloat" :
          id === "tab-experimental" ? "experimental" : "baseline";
        u.searchParams.set("tab", tab);
        history.replaceState(null, "", u.pathname + u.search + u.hash);
      }} catch (e) {{}}
    }}
    tabs.forEach(function (btn) {{
      btn.addEventListener("click", function () {{
        activate(btn.getAttribute("data-tab"));
      }});
    }});
    try {{
      const q = new URLSearchParams(window.location.search).get("tab");
      if (q === "bloat") activate("tab-bloat");
      else if (q === "experimental" || q === "exp") activate("tab-experimental");
    }} catch (e) {{}}
  }})();
  </script>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)} · DSM-AE</title>
<style>{_shared_shell_css()}</style>
</head>
<body class="comparison-page" data-configured-base="{_esc(configured_base)}">
  <h1>Comparison</h1>
  {nav}
  {body_main}
  {_nav_base_script()}
</body>
</html>
"""


def render_literature_page(href: Href, reports_dir: Path | str, title: str = "Literature") -> str:
    """Nav chrome + iframe to the snowball tree (reports/literature/index.html)."""
    reports_dir = Path(reports_dir)
    configured_base = _configured_base(href)
    nav = render_nav(href, active="/literature")
    lit = reports_dir / "literature" / "index.html"
    if lit.is_file():
        src = href("/reports/literature/index.html")
        frame = (
            f'<iframe class="lit-frame" src="{_esc(src)}" title="Literature snowball"></iframe>'
        )
        note = "Citation tree from research-notes/snowball (depth ≤ 3)."
    else:
        frame = (
            "<p>No literature tree yet. Run "
            "<code>python scripts/generate_literature_ui.py</code> after snowball sections land.</p>"
        )
        note = "Awaiting section-*.json merge."
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)} · DSM-AE</title>
<style>
{_shared_shell_css()}
  .lit-frame {{ width: 100%; min-height: 80vh; border: 1px solid #ccc; background: #fff; }}
</style>
</head>
<body data-configured-base="{_esc(configured_base)}">
  <h1>Literature</h1>
  {nav}
  <p class="hint">{note}</p>
  {frame}
  {_nav_base_script()}
</body>
</html>
"""


def render_compaction_page(href: Href, reports_dir: Path | str, title: str = "Compaction") -> str:
    """Nav chrome + iframe to the compaction snowball (reports/compaction/index.html)."""
    reports_dir = Path(reports_dir)
    configured_base = _configured_base(href)
    nav = render_nav(href, active="/compaction")
    page = reports_dir / "compaction" / "index.html"
    if page.is_file():
        src = href("/reports/compaction/index.html")
        frame = (
            f'<iframe class="lit-frame" src="{_esc(src)}" title="Compaction snowball"></iframe>'
        )
        note = "When scaffolds compact, and how SFT trainers treat compressed turns."
    else:
        frame = (
            "<p>No compaction survey yet. Run "
            "<code>python scripts/generate_compaction_ui.py</code> after section JSON lands.</p>"
        )
        note = "Awaiting research-notes/compaction/section-*.json merge."
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)} · DSM-AE</title>
<style>
{_shared_shell_css()}
  .lit-frame {{ width: 100%; min-height: 80vh; border: 1px solid #ccc; background: #fff; }}
</style>
</head>
<body data-configured-base="{_esc(configured_base)}">
  <h1>Compaction</h1>
  {nav}
  <p class="hint">{note}</p>
  {frame}
  {_nav_base_script()}
</body>
</html>
"""


