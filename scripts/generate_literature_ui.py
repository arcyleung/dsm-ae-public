#!/usr/bin/env python3
"""Merge snowball section JSON → tree.json + Literature tab HTML."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNOW = ROOT / "research-notes" / "snowball"
OUT = ROOT / "reports" / "literature"


def load_sections() -> tuple[list[dict], list[dict]]:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
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
    return list(nodes.values()), edges


def load_clusters() -> dict | None:
    p = SNOW / "unknown-clusters.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> None:
    nodes, edges = load_sections()
    clusters = load_clusters()
    cluster_of: dict[str, str] = {}
    if clusters:
        for c in clusters.get("clusters") or []:
            cid = str(c.get("id") or "")
            for nid in c.get("member_ids") or []:
                cluster_of[str(nid)] = cid
        for n in nodes:
            if (n.get("pack") or "unknown") == "unknown":
                n["cluster"] = cluster_of.get(str(n.get("id")), "")

    OUT.mkdir(parents=True, exist_ok=True)
    tree = {
        "as_of": "2026-08-28",
        "process": "research-notes/snowball/PROCESS.md",
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "nodes": nodes,
        "edges": edges,
    }
    if clusters:
        tree["clusters"] = clusters.get("clusters") or []
        tree["n_unknown"] = clusters.get("n_unknown")
    (SNOW / "tree.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    (OUT / "tree.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")
    if clusters:
        (OUT / "unknown-clusters.json").write_text(
            json.dumps(clusters, indent=2), encoding="utf-8"
        )

    packs = Counter(str(n.get("pack") or "unknown") for n in nodes)
    depths = Counter(int(n.get("depth") or 0) for n in nodes)
    benches = [n for n in nodes if n.get("benchmark_measures") is True]
    unknown = [n for n in nodes if (n.get("pack") or "unknown") == "unknown"]

    html = _html(tree, packs, depths, benches, unknown, clusters)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    print(
        f"nodes={len(nodes)} edges={len(edges)} unknown={len(unknown)} "
        f"benches={len(benches)} clusters={len((clusters or {}).get('clusters') or [])}"
    )
    print(f"wrote {OUT / 'index.html'}")


def _esc(s: object) -> str:
    return (
        str(s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _html(
    tree: dict,
    packs: Counter,
    depths: Counter,
    benches: list,
    unknown: list,
    clusters: dict | None,
) -> str:
    nodes = tree["nodes"]
    children: dict[str, list[str]] = defaultdict(list)
    for e in tree["edges"]:
        children[str(e["from"])].append(str(e["to"]))
    by_id = {str(n["id"]): n for n in nodes}
    roots = [n for n in nodes if int(n.get("depth") or 0) == 0]
    if not roots:
        roots = nodes[:50]

    def render_node(nid: str, seen: set[str], depth: int) -> str:
        if nid in seen or depth > 4:
            return ""
        seen.add(nid)
        n = by_id.get(nid) or {"id": nid, "title": nid, "pack": "unknown"}
        pack = n.get("pack") or "unknown"
        cluster = n.get("cluster") or ""
        bm = n.get("benchmark_measures")
        bm_s = "bench" if bm is True else ("discuss" if bm is False else "unclear")
        kids = "".join(render_node(c, seen, depth + 1) for c in children.get(nid, []))
        title = _esc(n.get("title") or n.get("id"))
        url = _esc(n.get("url") or "")
        link = f'<a href="{url}" target="_blank" rel="noopener">{title}</a>' if url else title
        cluster_attr = f' data-cluster="{_esc(cluster)}"' if cluster else ""
        cluster_chip = (
            f' <span class="cluster">{_esc(cluster)}</span>' if cluster else ""
        )
        return (
            f'<li data-pack="{_esc(pack)}" data-bench="{bm_s}"{cluster_attr}>'
            f'<span class="pack {_esc(pack)}">{_esc(pack)}</span> '
            f'<span class="bm {bm_s}">{bm_s}</span>{cluster_chip} {link}'
            f'<span class="meta"> d{int(n.get("depth") or 0)}'
            f' {_esc(n.get("benchmark_name") or "")}</span>'
            + (f"<ul>{kids}</ul>" if kids else "")
            + "</li>"
        )

    tree_html = "".join(render_node(str(r["id"]), set(), 0) for r in roots[:120])
    pack_rows = "".join(
        f"<tr><td>{_esc(p)}</td><td>{c}</td></tr>" for p, c in packs.most_common()
    )

    cluster_section = ""
    if clusters and clusters.get("clusters"):
        by_id_nodes = {str(n["id"]): n for n in nodes}
        cards = []
        for c in clusters["clusters"]:
            cid = str(c.get("id") or "")
            members = []
            n_bench = 0
            for nid in c.get("member_ids") or []:
                n = by_id_nodes.get(nid) or {}
                if n.get("benchmark_measures") is True:
                    n_bench += 1
                title = _esc(n.get("title") or nid)
                url = _esc(n.get("url") or "")
                link = (
                    f'<a href="{url}" target="_blank" rel="noopener">{title}</a>'
                    if url
                    else title
                )
                bm = n.get("benchmark_measures")
                bm_s = "bench" if bm is True else ("discuss" if bm is False else "unclear")
                members.append(
                    f'<li data-pack="unknown" data-cluster="{_esc(cid)}" data-bench="{bm_s}">'
                    f'<span class="bm {bm_s}">{bm_s}</span> {link}</li>'
                )
            promote = "promote" if cid in {"scheming", "spec_drift"} else "hold"
            closest = _esc(c.get("closest_pack") or "—")
            cards.append(
                f'<article class="card" id="cluster-{_esc(cid)}" data-cluster="{_esc(cid)}">'
                f"<h3>{_esc(c.get('name') or cid)} "
                f'<span class="pack unknown">{_esc(cid)}</span> '
                f'<span class="promo {promote}">{promote}</span></h3>'
                f'<p class="note">{_esc(c.get("rationale"))}</p>'
                f'<p class="meta">n={len(c.get("member_ids") or [])} · '
                f"ships a benchmark {n_bench} · closest existing pack {closest}</p>"
                f'<p class="meta">coverage: {_esc(c.get("benchmark_coverage"))}</p>'
                f'<ul class="members">{"".join(members)}</ul>'
                f"</article>"
            )
        cluster_section = (
            "<h2>Unknown-pool clusters (proposed categories)</h2>"
            "<p class=\"note\">Every unknown node is in exactly one cluster. "
            "<strong>promote</strong> = candidate new DSM-AE pack; "
            "<strong>hold</strong> = real family but not a coding-agent pack yet "
            "(or a meta/harness bucket).</p>"
            f'<div class="cards">{"".join(cards)}</div>'
        )

    n_clusters = len((clusters or {}).get("clusters") or [])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>DSM-AE literature snowball</title>
<style>
  body {{ margin: 0; padding: 12px 16px; font: 13px/1.4 system-ui, sans-serif; }}
  h1 {{ font-size: 1.2rem; margin: 0 0 4px; }}
  h2 {{ font-size: 1.05rem; margin: 18px 0 6px; }}
  h3 {{ font-size: 0.95rem; margin: 0 0 6px; }}
  .meta, .note {{ color: #555; font-size: 12px; }}
  .stats {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 8px 0 12px; }}
  .stats span {{ background: #f0f0f0; padding: 2px 8px; border-radius: 4px; }}
  .pack {{ font: 11px ui-monospace, monospace; background: #e3f2fd; padding: 0 4px; }}
  .pack.unknown {{ background: #fff3cd; }}
  .cluster {{ font: 11px ui-monospace, monospace; background: #f3e5f5; padding: 0 4px; }}
  .bm.bench {{ color: #0a7; font-weight: 600; }}
  .bm.discuss {{ color: #666; }}
  .promo.promote {{ background: #c8e6c9; padding: 0 5px; font-size: 11px; }}
  .promo.hold {{ background: #eee; padding: 0 5px; font-size: 11px; }}
  ul {{ margin: 2px 0 2px 16px; padding: 0; }}
  li {{ margin: 3px 0; }}
  table {{ border-collapse: collapse; font-size: 12px; }}
  td, th {{ border: 1px solid #ccc; padding: 2px 6px; }}
  #filter {{ margin: 8px 0; min-width: 280px; }}
  .cards {{ display: grid; gap: 10px; }}
  .card {{ border: 1px solid #ccc; padding: 8px 10px; background: #fafafa; }}
  .members {{ max-height: 220px; overflow: auto; margin: 6px 0 0 16px; }}
</style>
</head>
<body>
<h1>Literature snowball (depth ≤ 3)</h1>
<p class="note">AS_OF 2026-08-28 · seeds = bibliography + TACT · process in
<code>research-notes/snowball/PROCESS.md</code> · findings in
<code>research-notes/snowball/FINDINGS.md</code></p>
<div class="stats">
  <span>nodes {tree['n_nodes']}</span>
  <span>edges {tree['n_edges']}</span>
  <span>unknown pack {len(unknown)}</span>
  <span>unknown clusters {n_clusters}</span>
  <span>ships a benchmark {len(benches)}</span>
  <span>d0 {depths.get(0,0)} · d1 {depths.get(1,0)} · d2 {depths.get(2,0)} · d3 {depths.get(3,0)}</span>
</div>
<p class="meta">pack = existing DSM-AE indicator (or unknown).
bench = this work operationalizes the behaviour in a suite; discuss = describes only.
cluster = named unknown-pool category.</p>
<label>Filter pack or cluster <input id="filter" placeholder="unknown / scheming / spec_drift"/></label>
{cluster_section}
<h2>Citation tree</h2>
<ul id="tree">{tree_html}</ul>
<h2>Counts by pack</h2>
<table><tr><th>pack</th><th>n</th></tr>{pack_rows}</table>
<script>
const inp = document.getElementById("filter");
inp.addEventListener("input", () => {{
  const q = inp.value.trim().toLowerCase();
  document.querySelectorAll("#tree li, .card, .members li").forEach((el) => {{
    const pack = (el.getAttribute("data-pack") || "").toLowerCase();
    const cluster = (el.getAttribute("data-cluster") || "").toLowerCase();
    const hit = !q || pack.includes(q) || cluster.includes(q);
    el.style.display = hit ? "" : "none";
  }});
}});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
