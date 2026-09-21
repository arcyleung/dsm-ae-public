#!/usr/bin/env python3
"""Merge compaction snowball section JSON → tree.json + Compaction tab HTML."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNOW = ROOT / "research-notes" / "compaction"
OUT = ROOT / "reports" / "compaction"


def load_sections() -> tuple[list[dict], list[dict], list[str], list[str]]:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    when: list[str] = []
    sft: list[str] = []
    for p in sorted(SNOW.glob("section-*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for n in data.get("nodes") or []:
            nid = str(n.get("id") or "").strip()
            if not nid:
                continue
            prev = nodes.get(nid)
            if prev is None or int(n.get("depth") or 99) < int(prev.get("depth") or 99):
                nodes[nid] = n
        for e in data.get("edges") or []:
            if e.get("from") and e.get("to"):
                edges.append(e)
        ans = data.get("answers") or {}
        when.extend(str(x) for x in (ans.get("when") or []) if x)
        sft.extend(str(x) for x in (ans.get("sft") or []) if x)
    return list(nodes.values()), edges, when, sft


def main() -> None:
    nodes, edges, when, sft = load_sections()
    OUT.mkdir(parents=True, exist_ok=True)
    findings = SNOW / "FINDINGS.md"
    tree = {
        "as_of": "2026-09-01",
        "process": "research-notes/compaction/PROCESS.md",
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "nodes": nodes,
        "edges": edges,
        "answers": {"when": when, "sft": sft},
    }
    (SNOW / "tree.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    (OUT / "tree.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    html = _html(tree, findings.read_text(encoding="utf-8") if findings.is_file() else "")
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(f"nodes={len(nodes)} edges={len(edges)} when={len(when)} sft={len(sft)}")
    print(f"wrote {OUT / 'index.html'}")


def _esc(s: object) -> str:
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _md_lite(text: str) -> str:
    """Tiny subset: headings, tables, lists, bold, code, paragraphs."""
    if not text.strip():
        return ""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("# "):
            out.append(f"<h1>{_esc(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_esc(line[3:])}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{_esc(line[4:])}</h3>")
        elif line.startswith("|") and i + 1 < len(lines) and set(lines[i + 1].replace("|", "").strip()) <= set("-: "):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            i -= 1
            header = [c.strip() for c in rows[0].strip("|").split("|")]
            body = rows[2:]
            th = "".join(f"<th>{_inline(c)}</th>" for c in header)
            trs = []
            for r in body:
                cells = [c.strip() for c in r.strip("|").split("|")]
                trs.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in cells) + "</tr>")
            out.append(f"<table><tr>{th}</tr>{''.join(trs)}</table>")
        elif line.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            i -= 1
            out.append(f"<ul>{''.join(items)}</ul>")
        elif line.strip() == "":
            pass
        elif line.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(_esc(lines[i]))
                i += 1
            out.append(f"<pre><code>{''.join(x + chr(10) for x in buf)}</code></pre>")
        else:
            out.append(f"<p>{_inline(line)}</p>")
        i += 1
    return "\n".join(out)


def _inline(s: str) -> str:
    import re

    s = _esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _html(tree: dict, findings_md: str) -> str:
    nodes = tree["nodes"]
    children: dict[str, list[str]] = defaultdict(list)
    for e in tree["edges"]:
        children[str(e["from"])].append(str(e["to"]))
    by_id = {str(n["id"]): n for n in nodes}
    roots = [n for n in nodes if int(n.get("depth") or 0) == 0]
    if not roots:
        roots = nodes[:50]
    depths = Counter(int(n.get("depth") or 0) for n in nodes)
    kinds = Counter(str(n.get("kind") or "unknown") for n in nodes)
    loss = Counter(str(n.get("compressed_in_loss") or "unknown") for n in nodes)

    def render_node(nid: str, seen: set[str], depth: int) -> str:
        if nid in seen or depth > 4:
            return ""
        seen.add(nid)
        n = by_id.get(nid) or {"id": nid, "title": nid}
        trig = n.get("trigger") or "unknown"
        loss_v = n.get("compressed_in_loss") or "unknown"
        kids = "".join(render_node(c, seen, depth + 1) for c in children.get(nid, []))
        title = _esc(n.get("title") or n.get("id"))
        url = _esc(n.get("url") or "")
        link = f'<a href="{url}" target="_blank" rel="noopener">{title}</a>' if url else title
        return (
            f'<li data-kind="{_esc(n.get("kind") or "")}" data-trigger="{_esc(trig)}" '
            f'data-loss="{_esc(loss_v)}">'
            f'<span class="kind">{_esc(n.get("kind") or "?")}</span> '
            f'<span class="trig { _esc(trig) }">{_esc(trig)}</span> '
            f'<span class="loss { _esc(loss_v) }">{_esc(loss_v)}</span> {link}'
            f'<span class="meta"> d{int(n.get("depth") or 0)} '
            f'{_esc(n.get("trigger_detail") or "")}</span>'
            + (f"<ul>{kids}</ul>" if kids else "")
            + "</li>"
        )

    tree_html = "".join(render_node(str(r["id"]), set(), 0) for r in roots[:160])

    products = [n for n in nodes if (n.get("kind") or "") in {"product", "blog", "forum"}]
    products.sort(key=lambda n: (int(n.get("depth") or 0), str(n.get("title") or "")))
    prod_rows = "".join(
        "<tr>"
        f"<td>{_esc(n.get('title'))}</td>"
        f"<td>{_esc(n.get('trigger'))}</td>"
        f"<td>{_esc(n.get('trigger_detail'))}</td>"
        f"<td>{_esc(n.get('compressed_in_loss'))}</td>"
        f"<td>{_esc(n.get('notes'))}</td>"
        "</tr>"
        for n in products
        if int(n.get("depth") or 0) == 0 or (n.get("kind") == "product")
    )

    trainers = [
        n
        for n in nodes
        if (n.get("kind") or "") in {"trainer", "paper"}
        and (n.get("compressed_in_loss") or "unknown") != "unknown"
    ]
    trainers.sort(key=lambda n: str(n.get("title") or ""))
    sft_rows = "".join(
        "<tr>"
        f"<td>{_esc(n.get('title'))}</td>"
        f"<td>{_esc(n.get('kind'))}</td>"
        f"<td>{_esc(n.get('training'))}</td>"
        f"<td class='loss { _esc(n.get('compressed_in_loss')) }'>{_esc(n.get('compressed_in_loss'))}</td>"
        f"<td>{_esc(n.get('notes'))}</td>"
        "</tr>"
        for n in trainers
    )

    when_lis = "".join(f"<li>{_esc(x)}</li>" for x in tree.get("answers", {}).get("when") or [])
    sft_lis = "".join(f"<li>{_esc(x)}</li>" for x in tree.get("answers", {}).get("sft") or [])

    findings_html = _md_lite(findings_md) if findings_md else "<p class='note'>FINDINGS.md not written yet.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>DSM-AE compaction snowball</title>
<style>
  body {{ margin: 0; padding: 12px 16px; font: 13px/1.4 system-ui, sans-serif; }}
  h1 {{ font-size: 1.2rem; margin: 0 0 4px; }}
  h2 {{ font-size: 1.05rem; margin: 18px 0 6px; }}
  h3 {{ font-size: 0.95rem; margin: 12px 0 6px; }}
  .meta, .note {{ color: #555; font-size: 12px; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 8px 0 12px; }}
  .stats span {{ background: #f0f0f0; padding: 2px 8px; border-radius: 4px; }}
  .kind, .trig, .loss {{ font: 11px ui-monospace, monospace; padding: 0 4px; }}
  .kind {{ background: #e3f2fd; }}
  .trig.threshold {{ background: #fff3cd; }}
  .trig.semantic {{ background: #c8e6c9; }}
  .trig.manual {{ background: #e1bee7; }}
  .trig.agent_tool {{ background: #bbdefb; }}
  .loss.masked {{ background: #c8e6c9; }}
  .loss.discarded {{ background: #ffcdd2; }}
  .loss.preferred {{ background: #b2dfdb; }}
  .loss.kept_as_context {{ background: #fff3cd; }}
  ul {{ margin: 2px 0 2px 16px; padding: 0; }}
  li {{ margin: 3px 0; }}
  table {{ border-collapse: collapse; font-size: 12px; margin: 6px 0 12px; max-width: 100%; }}
  td, th {{ border: 1px solid #ccc; padding: 3px 6px; vertical-align: top; }}
  th {{ background: #f5f5f5; }}
  #filter {{ margin: 8px 0; min-width: 280px; }}
  pre {{ background: #f6f6f6; padding: 8px; overflow: auto; }}
</style>
</head>
<body>
<h1>Compaction snowball (depth ≤ 3)</h1>
<p class="note">AS_OF 2026-09-01 · seeds = <code>docs/surveys/compaction.md</code> §9
+ named scaffolds/trainers · process in
<code>research-notes/compaction/PROCESS.md</code></p>
<div class="stats">
  <span>nodes {tree['n_nodes']}</span>
  <span>edges {tree['n_edges']}</span>
  <span>d0 {depths.get(0,0)} · d1 {depths.get(1,0)} · d2 {depths.get(2,0)} · d3 {depths.get(3,0)}</span>
  <span>kinds {', '.join(f'{k} {v}' for k,v in kinds.most_common())}</span>
  <span>loss {', '.join(f'{k} {v}' for k,v in loss.most_common())}</span>
</div>

<h2>Q1 — When do scaffolds compact?</h2>
<ul>{when_lis or '<li class="note">Awaiting section agents.</li>'}</ul>
<table>
<tr><th>product / source</th><th>trigger</th><th>detail</th><th>compressed in loss</th><th>notes</th></tr>
{prod_rows or '<tr><td colspan="5">No product nodes yet.</td></tr>'}
</table>

<h2>Q2 — Compressed trajectories in SFT</h2>
<ul>{sft_lis or '<li class="note">Awaiting section agents.</li>'}</ul>
<table>
<tr><th>work</th><th>kind</th><th>training</th><th>compressed_in_loss</th><th>notes</th></tr>
{sft_rows or '<tr><td colspan="5">No trainer/paper loss labels yet.</td></tr>'}
</table>

<h2>Findings</h2>
{findings_html}

<label>Filter kind / trigger / loss <input id="filter" placeholder="product / threshold / masked"/></label>
<h2>Citation tree</h2>
<ul id="tree">{tree_html}</ul>
<script>
const inp = document.getElementById("filter");
inp.addEventListener("input", () => {{
  const q = inp.value.trim().toLowerCase();
  document.querySelectorAll("#tree li").forEach((li) => {{
    const blob = [
      li.getAttribute("data-kind") || "",
      li.getAttribute("data-trigger") || "",
      li.getAttribute("data-loss") || "",
    ].join(" ").toLowerCase();
    li.style.display = !q || blob.includes(q) ? "" : "none";
  }});
}});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
