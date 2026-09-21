#!/usr/bin/env python3
"""survey_verify_citation.py -- verify a citation exists via Crossref / arXiv.

WebSearch/WebFetch were unavailable while building
`docs/surveys/2026-09-08-smoke-test-criteria-survey.md`; plain HTTPS to
api.crossref.org and export.arxiv.org works, so this is the verification path
that was actually used. Every source in that survey was checked with this
script; anything it could not confirm was dropped.

Usage:
  python3 scripts/survey_verify_citation.py "Coverage is not strongly correlated"
  python3 scripts/survey_verify_citation.py --file queries.txt
  python3 scripts/survey_verify_citation.py --arxiv "tinyBenchmarks"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "dsm-ae-survey/1.0 (literature verification; mailto:noreply@example.com)"
CROSSREF = "https://api.crossref.org/works"
ARXIV = "https://export.arxiv.org/api/query"


def _get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def crossref(query: str, rows: int = 3):
    q = urllib.parse.urlencode(
        {
            "query.bibliographic": query,
            "rows": rows,
            "select": "DOI,title,author,container-title,issued,type",
        }
    )
    data = json.loads(_get(f"{CROSSREF}?{q}"))
    out = []
    for it in data["message"]["items"]:
        authors = "; ".join(
            f"{a.get('family','')}, {a.get('given','')}".strip(", ")
            for a in it.get("author", [])[:6]
        )
        year = None
        parts = (it.get("issued") or {}).get("date-parts") or [[]]
        if parts and parts[0]:
            year = parts[0][0]
        out.append(
            {
                "title": (it.get("title") or [""])[0],
                "authors": authors,
                "venue": (it.get("container-title") or [""])[0],
                "year": year,
                "doi": it.get("DOI"),
                "type": it.get("type"),
            }
        )
    return out


def arxiv(query: str, rows: int = 3):
    q = urllib.parse.urlencode(
        {"search_query": f'all:"{query}"', "max_results": rows, "start": 0}
    )
    xml = _get(f"{ARXIV}?{q}")
    entries = re.findall(r"<entry>(.*?)</entry>", xml, re.S)
    out = []
    for e in entries:
        def one(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", e, re.S)
            return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""
        out.append(
            {
                "title": one("title"),
                "arxiv_id": one("id").rsplit("/", 1)[-1],
                "published": one("published")[:10],
                "authors": "; ".join(re.findall(r"<name>(.*?)</name>", e))[:300],
            }
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="*")
    ap.add_argument("--file", help="file with one query per line")
    ap.add_argument("--arxiv", action="store_true", help="query arXiv instead")
    ap.add_argument("--rows", type=int, default=3)
    a = ap.parse_args()

    queries = []
    if a.file:
        queries += [l.strip() for l in open(a.file) if l.strip() and not l.startswith("#")]
    if a.query:
        queries.append(" ".join(a.query))
    if not queries:
        ap.error("give a query or --file")

    for q in queries:
        print("=" * 70)
        print("QUERY:", q)
        try:
            hits = arxiv(q, a.rows) if a.arxiv else crossref(q, a.rows)
            if not hits:
                print("  NO HITS -- treat as UNVERIFIED")
            for h in hits:
                print("  " + json.dumps(h, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print("  ERROR:", exc)
        time.sleep(0.6)  # be polite to the public APIs


if __name__ == "__main__":
    main()
