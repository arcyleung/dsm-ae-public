#!/usr/bin/env python3
"""Mine scrubbed prior-turn seed material for rev2 indicator packs.

READ-ONLY against MongoDB `claude_conversations.session_labels_by_gpt55`.
Writes `fixtures/seeding/prior_turns.json`, which the rev2 packs load instead of
talking to Mongo — Mongo is a dev-box service and the packs must run without it.

Safety model (see src/dsm_ae/packs/seeding.py for the scrubber itself):

  1. Harvest per-session identifiers (account names, project/company names) from
     the WHOLE transcript, so a name that appears in a path in turn 3 is also
     removed from prose in turn 90.
  2. Scrub each turn with the pattern rules + the harvested terms.
  3. AUDIT the scrubbed turn with an independent detector set. Any hit and the
     turn is DROPPED. A scrubber miss therefore degrades to data loss, never to
     a leak. ~96% of candidate turns survive, so dropping is cheap.

Usage
-----
    python scripts/mine_seed_turns.py                      # rebuild the fixture
    python scripts/mine_seed_turns.py --audit-only         # report, write nothing
    python scripts/mine_seed_turns.py --sessions 40 --turns-per-pool 60
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dsm_ae.packs.seeding import (  # noqa: E402
    _STATIC_COMMON,
    harvest_identifiers,
    harvest_rare_terms,
    identifier_components,
    residual_findings,
    scrub_text,
)

MONGO_URI = os.environ.get("DSM_MONGO_URI", "mongodb://localhost:27018/")
DB_NAME = "claude_conversations"
COLL = "session_labels_by_gpt55"

LONG_HORIZON = {
    "request_count": {"$gte": 50},
    "session_text_chars": {"$gte": 50000},
    "is_rubric_labelling": False,
}
PROJECTION = {"auth_token": 0}  # never read the credential field

# The anchor session the user identified: research_experiment, 366 requests,
# 119h, 236KB. Contains 18 numbered checkpoints (checkpoint-1330, -534, ...) and
# ~60 recency-word mentions, and OPENS with the user pointing at a
# knowledge-transfer package left by a *previous* agent — an older artifact that
# is more relevant than the newer ones. A natural recency trap.
ANCHOR_SESSION = "60306e4e-c032-46ad-916d-9ef25f348fa7"

TURN_RE = re.compile(r"^(system|user|assistant):[ \t]?", re.M)

MIN_TURN_CHARS = 80
MAX_TURN_CHARS = 2200

# Pools requested by the rev2 packs. Each maps to a corpus slice.
POOL_SPECS: dict[str, dict] = {
    # artifact-versioning work: checkpoints, runs, datestamped outputs
    "artifact_versioning": {
        "categories": ["research_experiment"],
        "anchor_first": True,
        "require_any": ["checkpoint", "run_", "epoch", "step", "eval", "output_dir"],
    },
    # ordinary unrelated engineering work — the "time passes" filler that is
    # nonetheless real competent agent behaviour
    "mixed_engineering": {
        "categories": [
            "feature_implementation",
            "bugfix",
            "refactoring_maintenance",
            "devops",
            "documentation",
        ],
        "anchor_first": False,
        "require_any": [],
    },
    # work with destructive/irreversible operations in view, for the packs whose
    # constraint is about gates and roles
    "ops_and_cleanup": {
        "categories": ["devops", "bugfix", "refactoring_maintenance"],
        "anchor_first": False,
        "require_any": ["rm ", "delete", "drop", "migrate", "deploy", "docker", "clean"],
    },
}


def split_turns(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    role: str | None = None
    pos = 0
    for m in TURN_RE.finditer(text):
        if role is not None:
            out.append((role, text[pos : m.start()]))
        role = m.group(1)
        pos = m.end()
    if role is not None:
        out.append((role, text[pos:]))
    return out


def build_common_terms(coll, min_sessions: int, df_threshold: int) -> tuple[frozenset[str], int]:
    """Corpus document-frequency allowlist.

    Counts, for each alphabetic identifier component, how many DISTINCT sessions
    it appears in. A component seen across many unrelated sessions is shared
    vocabulary; one confined to a couple of sessions is a name somebody chose.
    Everything below `df_threshold` is treated as a candidate identifier and
    scrubbed by `harvest_rare_terms`.

    This replaces guessing at a wordlist with a measurement over the same corpus
    the seed material comes from.
    """
    df: collections.Counter = collections.Counter()
    n = 0
    for doc in coll.find(LONG_HORIZON, {"session_text": 1}).sort("session_id", 1).limit(min_sessions):
        n += 1
        for comp in identifier_components(doc.get("session_text") or ""):
            df[comp.lower()] += 1

    # Raw DF is not enough on its own. This corpus is ONE organisation's work, so
    # a product that org uses appears in dozens of sessions and crosses any
    # threshold — `featbench` scored df=40+ and was let through as "vocabulary".
    #
    # The fix is a second, independent signal: a word that is real English or
    # real public technical vocabulary is in the system dictionary or in the
    # curated public lists. A token that is corpus-frequent but exists in NEITHER
    # is precisely the shape of an in-house product name. Require both.
    # A token is treated as shared vocabulary if EITHER holds:
    #   (a) it is a real English / curated technical word — safe at any
    #       frequency, because `familiarized` identifies nobody even if it
    #       appears in one session; or
    #   (b) it is corpus-frequent AND not the shape of an in-house name.
    #
    # Requiring (a) AND (b) was wrong: it scrubbed ordinary English that happened
    # to be rare, which gutted the prose. Requiring only (b) was also wrong: this
    # corpus is one organisation, so its own product names clear any DF bar
    # (`featbench` scored df>=40). The union of the two is what works.
    dictionary = _system_dictionary()
    frequent = {t for t, c in df.items() if c >= df_threshold}
    vocabulary = dictionary | _STATIC_COMMON
    # Corpus-frequent tokens that are NOT vocabulary are the suspicious class:
    # keep only those that look like generic technical jargon (short, no
    # CamelCase, no digits) rather than a product name.
    jargon = {t for t in frequent - vocabulary if _looks_like_jargon(t)}
    common = frozenset(vocabulary | jargon)
    rejected = len(frequent - vocabulary - jargon)
    print(
        f"common-terms DF: sessions={n} distinct={len(df)} df>={df_threshold}:{len(frequent)} "
        f"| vocabulary={len(vocabulary)} jargon={len(jargon)} "
        f"rejected={rejected} corpus-frequent non-vocabulary tokens"
    )
    return common, n


def _looks_like_jargon(tok: str) -> bool:
    """Generic technical shorthand (`vllm`, `jsonl`, `sft`) vs a product name.

    Product names in this corpus are compounds or coinages: they are longer, and
    frequently CamelCase. Short all-lowercase alphabetic tokens are far more
    likely to be an ecosystem abbreviation. This is a heuristic, and it errs
    toward scrubbing: anything longer than 8 characters is treated as a name.
    """
    return tok.isalpha() and tok.islower() and len(tok) <= 8


def _system_dictionary() -> frozenset[str]:
    """English + technical vocabulary from the OS word list, if available.

    Falls back to the curated lists alone, which is stricter (more scrubbing),
    never looser — the safe direction for a failure.
    """
    words: set[str] = set()
    for path in ("/usr/share/dict/words", "/usr/share/dict/american-english"):
        f = Path(path)
        if f.is_file():
            try:
                words.update(
                    w.strip().lower()
                    for w in f.read_text(encoding="utf-8", errors="ignore").splitlines()
                    if w.strip() and w.strip().isalpha()
                )
                break
            except OSError:
                pass
    if not words:
        print("  (no system dictionary found — relying on curated lists only)")
    return frozenset(words)


def clean_turns_for_session(
    doc: dict, stats: collections.Counter, common_terms: frozenset[str]
) -> list[dict[str, str]]:
    """Scrub + audit one session's transcript into shippable turns."""
    text = doc.get("session_text") or ""
    terms = harvest_identifiers(text)
    # Names that only ever appear in prose need the rarity signal to be found.
    terms.update(harvest_rare_terms(text, terms, common_terms=common_terms))
    stats["sessions"] += 1
    stats["harvested_terms"] += len(terms)

    kept: list[dict[str, str]] = []
    for role, body in split_turns(text):
        if role == "system":
            continue
        body = body.strip()
        if not (MIN_TURN_CHARS <= len(body) <= MAX_TURN_CHARS):
            continue
        stats["candidates"] += 1
        scrubbed = scrub_text(body, terms)
        findings = residual_findings(scrubbed, terms)
        if findings:
            stats[f"drop:{findings[0][0]}"] += 1
            stats["dropped"] += 1
            continue
        stats["kept"] += 1
        kept.append({"role": role, "content": scrubbed})

    # Enforce strict user/assistant alternation and a user-first start so the
    # excerpt can be spliced into a chat prefix without provider complaints.
    # Audit drops punch holes in the sequence, so MERGE consecutive same-role
    # turns rather than discarding them — that keeps ~3x more real material.
    merged: list[dict[str, str]] = []
    for t in kept:
        if merged and merged[-1]["role"] == t["role"]:
            joined = merged[-1]["content"] + "\n\n" + t["content"]
            merged[-1]["content"] = joined[:6000]
        else:
            merged.append(dict(t))
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    if len(merged) % 2:
        merged.pop()
    return merged


def matches_spec(doc: dict, spec: dict) -> bool:
    cats = spec.get("categories") or []
    if cats and doc.get("session_task_category") not in cats:
        return False
    req = spec.get("require_any") or []
    if req:
        low = (doc.get("session_text") or "")[:200_000].lower()
        if not any(r.lower() in low for r in req):
            return False
    return True


def build(
    sessions_per_pool: int,
    turns_per_pool: int,
    audit_only: bool,
    df_sessions: int,
    df_threshold: int,
) -> dict:
    import pymongo

    client = pymongo.MongoClient(MONGO_URI)
    coll = client[DB_NAME][COLL]

    common_terms, df_n = build_common_terms(coll, df_sessions, df_threshold)
    stats: collections.Counter = collections.Counter()
    pools: dict[str, list[dict]] = {}

    for pool_name, spec in POOL_SPECS.items():
        docs: list[dict] = []
        if spec.get("anchor_first"):
            anchor = coll.find_one({"session_id": ANCHOR_SESSION}, PROJECTION)
            if anchor:
                docs.append(anchor)
        # Deterministic order: sort by session_id so reruns pick the same sessions.
        cursor = coll.find(LONG_HORIZON, PROJECTION).sort("session_id", 1)
        for doc in cursor:
            if len(docs) >= sessions_per_pool:
                break
            if doc.get("session_id") == ANCHOR_SESSION and docs:
                continue
            if matches_spec(doc, spec):
                docs.append(doc)

        entries: list[dict] = []
        for doc in docs:
            turns = clean_turns_for_session(doc, stats, common_terms)
            if len(turns) < 8:
                continue
            entries.append(
                {
                    # Session ids are opaque UUIDs, but they are still corpus
                    # keys — store a short salted digest instead.
                    "pool_id": _pool_id(pool_name, str(doc.get("session_id") or "")),
                    "category": str(doc.get("session_task_category") or ""),
                    "turns": turns[: turns_per_pool * 2],
                    "meta": {
                        "request_count": int(doc.get("request_count") or 0),
                        # Corpus-assigned tags are metadata, so they never pass
                        # through the turn scrubber — but they are free text and
                        # DO carry product names. Audit them the same way.
                        "tags": _safe_tags(doc, common_terms),
                        "is_anchor": doc.get("session_id") == ANCHOR_SESSION,
                        "n_turns": min(len(turns), turns_per_pool * 2),
                    },
                }
            )
        pools[pool_name] = entries
        print(
            f"pool {pool_name:22s} sessions={len(entries):2d} "
            f"turns={sum(len(e['turns']) for e in entries)}"
        )

    print("\n--- scrub audit ---")
    cand = stats["candidates"] or 1
    print(f"sessions scanned : {stats['sessions']}")
    print(f"candidate turns  : {stats['candidates']}")
    print(f"kept             : {stats['kept']} ({stats['kept'] / cand:.1%})")
    print(f"dropped by audit : {stats['dropped']} ({stats['dropped'] / cand:.1%})")
    for k, v in sorted(stats.items()):
        if k.startswith("drop:"):
            print(f"  {k[5:]:18s} {v}")

    payload = {
        "schema": 1,
        "note": (
            "Scrubbed prior-turn seed material for rev2 packs. Built by "
            "scripts/mine_seed_turns.py from a private session corpus; every turn "
            "passed the residual-identifier audit in dsm_ae.packs.seeding. "
            "Do not hand-edit."
        ),
        "audit": {k: v for k, v in sorted(stats.items())},
        "common_terms_meta": {
            "df_sessions": df_n,
            "df_threshold": df_threshold,
            "n_common": len(common_terms),
            "note": (
                "Identifier components appearing in >= df_threshold distinct corpus "
                "sessions are treated as shared vocabulary; everything rarer is "
                "scrubbed as a probable product/company name."
            ),
        },
        "common_terms": sorted(common_terms),
        "pools": pools,
    }
    if audit_only:
        print("\n--audit-only: fixture NOT written")
    return payload


def _safe_tags(doc: dict, common_terms: frozenset[str]) -> list[str]:
    """Keep only task tags that are shared corpus vocabulary.

    A tag like `python` or `docker` describes the work; a tag like `featbench`
    names a product. The same document-frequency test that governs turn text
    governs tags, so the rule is applied once and consistently.
    """
    out: list[str] = []
    for tag in list(doc.get("session_task_tags") or [])[:16]:
        tag = str(tag)
        parts = [p for p in re.split(r"[^A-Za-z0-9]+", tag) if len(p) > 2]
        if parts and all(p.lower() in common_terms for p in parts):
            out.append(tag)
    return out[:10]


def _pool_id(pool_name: str, session_id: str) -> str:
    import hashlib

    digest = hashlib.sha256(f"dsm-ae-seed|{session_id}".encode()).hexdigest()[:8]
    return f"{pool_name}-{digest}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=12, help="source sessions per pool")
    ap.add_argument("--turns-per-pool", type=int, default=40, help="turn PAIRS kept per session")
    ap.add_argument("--audit-only", action="store_true", help="report and write nothing")
    ap.add_argument("--df-sessions", type=int, default=400, help="sessions scanned for the DF allowlist")
    ap.add_argument(
        "--df-threshold",
        type=int,
        default=40,
        help="min distinct sessions for a token to count as shared vocabulary",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "fixtures" / "seeding" / "prior_turns.json",
    )
    args = ap.parse_args()

    payload = build(
        args.sessions, args.turns_per_pool, args.audit_only, args.df_sessions, args.df_threshold
    )
    if args.audit_only:
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    size = args.out.stat().st_size
    print(f"\nwrote {args.out} ({size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
