#!/usr/bin/env python3
"""Slice reports/dsm-ae-matrix.html into JSON the Vue matrix components consume."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from dsm_ae.metric_citations import citations_for_metric, references_used  # noqa: E402
DEFAULT_HTML = ROOT / "reports" / "dsm-ae-matrix.html"
DEFAULT_OUT = ROOT / "reports" / "matrix" / "vue-data.json"


EXCLUDED_MODELS = frozenset()


def _models_from_thead(table) -> list[str]:
    return [
        th.get("data-model") or th.get_text(strip=True)
        for th in table.select("thead th.model")
    ]


def _syndrome_rows(table, models: list[str]) -> list[dict]:
    rows = []
    for tr in table.select("tbody tr"):
        th = tr.find("th")
        if not th:
            continue
        link = th.find("a")
        name = (link or th).get_text(" ", strip=True)
        sid = ""
        if link and link.get("href", "").startswith("#syndrome-"):
            sid = link["href"].split("#syndrome-", 1)[1]
        cells = []
        for td in tr.find_all("td"):
            cells.append({
                "model": td.get("data-model"),
                "status": (td.get("data-status") or "").upper(),
                "severity": td.get("data-sev"),
                "text": td.get_text(" ", strip=True),
                "tip": td.get("data-tip") or td.get("aria-label") or "",
            })
        rows.append({"id": sid, "name": name, "cells": cells})
    return rows


def _metric_rows(table) -> list[dict]:
    rows = []
    for tr in table.select("tbody tr"):
        th = tr.find("th")
        if not th:
            continue
        code = th.find("code")
        mid = code.get_text(strip=True) if code else th.get_text(" ", strip=True)
        cells = []
        for td in tr.find_all("td"):
            style = td.get("style") or ""
            color = ""
            m = re.search(r"background-color:\s*([^;]+)", style)
            if m:
                color = m.group(1).strip()
            fg = "#fff" if "color:#fff" in style.replace(" ", "") else "#111"
            cells.append({
                "model": td.get("data-model"),
                "status": (td.get("data-status") or "").upper(),
                "pass": _int(td.get("data-pass")),
                "n": _int(td.get("data-n")),
                "std": td.get("data-std"),
                "label": td.get_text(" ", strip=True),
                "tip": td.get("data-tip") or "",
                "color": color,
                "fg": fg,
            })
        rows.append({
            "id": mid,
            "cites": sorted(set(citations_for_metric(mid))),
            "cells": cells,
        })
    return rows


def _int(v):
    try:
        return int(v) if v is not None and v != "" else None
    except ValueError:
        return None


def _trees(soup) -> list[dict]:
    out = []
    for det in soup.select("details.syndrome"):
        sid = (det.get("id") or "").replace("syndrome-", "")
        summary = det.find("summary")
        strong = summary.find("strong") if summary else None
        code = strong.get_text(strip=True) if strong else sid
        name = ""
        if summary:
            raw = summary.get_text(" ", strip=True)
            name = raw.split("—", 1)[-1].split(code, 1)[-1].strip()
            # chips already in summary text; pull structured
        chips = []
        for chip in det.select("summary .chip"):
            chips.append({
                "model": chip.get("data-model"),
                "cls": " ".join(chip.get("class", [])),
                "text": chip.get_text(strip=True),
            })
        desc_el = det.select_one(".flow-desc")
        src = det.select_one("script.mermaid-src")
        mermaid = src.get_text() if src else ""
        out.append({
            "id": sid or code,
            "code": code,
            "name": name[:160],
            "desc": desc_el.get_text(" ", strip=True) if desc_el else "",
            "chips": chips,
            "mermaid": mermaid.strip(),
        })
    return out


def extract(html_path: Path) -> dict:
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8", errors="replace"), "html.parser")
    syn_h = soup.find(id="syndrome-matrix")
    met_h = soup.find(id="metric-results")
    syn_table = syn_h.find_next("table") if syn_h else None
    met_table = met_h.find_next("table") if met_h else None
    models = [m for m in _models_from_thead(syn_table or met_table) if m not in EXCLUDED_MODELS]
    keep = set(models)
    metrics = _metric_rows(met_table) if met_table else []
    for row in metrics:
        row["cells"] = [c for c in row.get("cells") or [] if c.get("model") in keep]
    syndromes = _syndrome_rows(syn_table, models) if syn_table else []
    for row in syndromes:
        row["cells"] = [c for c in row.get("cells") or [] if c.get("model") in keep]
    trees = []
    for t in _trees(soup):
        t["chips"] = [c for c in t.get("chips") or [] if c.get("model") in keep]
        trees.append(t)
    refs = references_used([m["id"] for m in metrics])
    return {
        "models": models,
        "syndromes": syndromes,
        "metrics": metrics,
        "trees": trees,
        "references": [
            {"id": i, "text": meta.get("text") or "", "url": meta.get("url") or ""}
            for i, meta in refs.items()
        ],
        "source": str(html_path.relative_to(ROOT)),
    }


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HTML
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    if not src.is_file():
        print(f"missing {src}", file=sys.stderr)
        return 1
    data = extract(src)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(
        f"wrote {dest}  models={len(data['models'])} "
        f"syndromes={len(data['syndromes'])} metrics={len(data['metrics'])} "
        f"trees={len(data['trees'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
