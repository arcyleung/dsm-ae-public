#!/usr/bin/env python3
"""Mine real coding-agent sessions for behavioural-syndrome examples.

Reads (READ-ONLY) the `session_labels_by_gpt55` collection in the
`claude_conversations` MongoDB database, samples long-horizon sessions
stratified by task category, runs cheap surface detectors over the transcript
text, and dumps candidate excerpts for hand-reading.

Nothing here is a measurement. The detectors are recall-oriented string
heuristics whose only job is to shortlist passages for a human to read and
quote. They over- and under-fire in both directions (e.g. "sandbox" as a
project name, "xfail" appearing in pytest *output* rather than in an edit).
Every number in the accompanying survey was confirmed by reading.

Companion document: docs/surveys/2026-09-09-real-session-examples.md

Usage
-----
    # stratified sample -> shortlist file
    python scripts/mine_sessions.py --n 50 --out reports/mined/candidates.md

    # corpus-wide count of one detector
    python scripts/mine_sessions.py --scan --detector scaffold_friction

    # inspect one session
    python scripts/mine_sessions.py --session-id 40b0660e --stats
    python scripts/mine_sessions.py --session-id 40b0660e --grep "requires approval"
    python scripts/mine_sessions.py --session-id 40b0660e --dump | less

    # re-tally the exact hand-read set used in the survey
    python scripts/mine_sessions.py --read-set
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys

import pymongo

MONGO_URI = os.environ.get("DSM_MONGO_URI", "mongodb://localhost:27018/")
DB_NAME = "claude_conversations"
COLL = "session_labels_by_gpt55"

# The corpus query. request_count >= 10 filters one-shot / autocomplete traffic;
# is_rubric_labelling excludes synthetic rubric-generation sessions.
# -> 2192 sessions at time of writing.
BASE_QUERY = {"request_count": {"$gte": 10}, "is_rubric_labelling": False}

# `auth_token` is never read into memory, let alone printed.
PROJECTION = {"auth_token": 0}

FILE_ARG = r"'file_path': '([^']+)'"

# The exact set of sessions hand-read for the 2026-09-09 survey: 50 from the
# stratified sample below, plus 25 pulled by targeted corpus-wide detector scans.
STRATIFIED_SAMPLE = """
49a608cc ced86450 b52e0124 0631b4eb 019e0944 76b77e77 019e2742 8d47f777 d3f9512a 59faced0
6ffcd0c1 68c126d3 5f898580 d6f8e02d 38cb5b63 7df1b2f5 74c8941f 5063f734 8daa1eed a5ae80d2
019e4bf2 07a97d32 019e2d07 019dff83 58db6866 019e2d20 2f626ba2 51482960 30ce6fc8 9aaa976b
d9256216 b62334ee aab4fc63 846c513d e3612d1b 66a0ae83 e805b032 459dbca3 5b8e604b 5b2b84e4
37b86cc8 4cb55fc0 16d1dbe8 6301762d 3e59d13f c83de630 9424e422 1f0fc2c5 4c3261c8 bb0de782
""".split()

TARGETED_FOLLOWUPS = """
40b0660e f4ac2beb e91a3801 da6a0a1d e697a747 0614e0de 9d50bb38 233b7ca4 4aafe802 58de9eb4
47005013 796e0492 705cce7b 2e80fea1 ac514a5c e6732ed7 60306e4e 9c938a8b ade87cb8 e8d15a81
674bed40 019d9bed 5389ff25 c08d001d 01b22d08
""".split()


# --------------------------------------------------------------------------
# redaction
# --------------------------------------------------------------------------

REDACTIONS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "<redacted-key>"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"), "<redacted-token>"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}"), "Bearer <redacted-token>"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "<redacted-email>"),
    (re.compile(r"/(?:home|Users)/[A-Za-z0-9._\-]+"), "/home/<user>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<redacted-host>"),
    (re.compile(r"\b[a-z0-9\-]+\.ts\.net\b"), "<redacted-host>"),
    (re.compile(r"(https?://)?(?:www\.)?github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+"),
     "<redacted-repo-url>"),
    (re.compile(r"/(?:shared_workspace_mfs|scratch_mfs|workspace|testbed|root)/[A-Za-z0-9._\-]+"),
     "<redacted-path>"),
]

# NOTE: redaction here is best-effort, not a guarantee. It catches the shapes that
# recur in this corpus (keys, tokens, emails, home paths, hosts, repo URLs); it does
# NOT catch org names, product names, or people named in prose. ALWAYS read an
# excerpt yourself before pasting it into anything public.


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def body_of(text: str) -> str:
    """Strip the leading system prompt so its boilerplate does not fire detectors.

    The system prompt itself mentions `rm -rf`, `--no-verify`, `pytest.mark.skip`
    and similar in its own guidance; counting those as agent behaviour would
    make every session look destructive.
    """
    i = text.find("\nuser:")
    return text[i:] if i > 0 else text


# --------------------------------------------------------------------------
# detectors -- shortlisting heuristics, NOT measurements
# --------------------------------------------------------------------------

def _max_per_file(body: str, tools: str) -> int:
    counts = collections.Counter(
        m.group(1) for m in re.finditer(rf"\[tool_use (?:{tools}): \{{[^\n]*?{FILE_ARG}", body)
    )
    return max(counts.values()) if counts else 0


def _distinct_files(body: str, tools: str) -> int:
    return len({
        m.group(1) for m in re.finditer(rf"\[tool_use (?:{tools}): \{{[^\n]*?{FILE_ARG}", body)
    })


def _user_turns(body: str):
    for m in re.finditer(r"\nuser: (?!\[tool_result)([^\n]{5,400})", body):
        yield m.group(1)


VERIFY_RE = re.compile(
    r"pytest|npm (?:run )?test|npm run build|cargo (?:test|build)|go test|make test"
    r"|tsc |jest|vitest|ruff|mypy|py_compile|gradle|mvn "
)

DESTRUCTIVE_RE = re.compile(
    r"\[tool_use Bash: \{'command': '[^\n]{0,200}?"
    r"(?:git reset --hard|git checkout -- |git checkout \. |git clean -[fdx]|rm -rf |git push --force)"
)

SCAFFOLD_RE = re.compile(
    r"requires approval|haven't granted it yet|user doesn't want to proceed|User rejected"
    r"|bwrap:|Operation not permitted|Command timed out|String to replace not found"
    r"|File has not been read yet|has been modified since read|429|rate.?limit|Overloaded"
)

SUPPRESS_RE = re.compile(
    r"pytest\.mark\.skip|pytest\.mark\.xfail|@unittest\.skip|\bit\.skip\(|describe\.skip\("
    r"|skipIf|git commit[^\n]*--no-verify"
)

PUSHBACK_RE = re.compile(
    r"(?i:i (?:already )?(?:told|said) you|remember that i said|like i said|as i said"
    r"|i asked you (?:not )?to|again[,:]? (?:i|you)|that.s not what i)"
)

DETECTORS = {
    # our-name -> predicate over the transcript body
    "read_loop":           lambda b: _max_per_file(b, "Read|NotebookRead") >= 8,
    "thrash_edit":         lambda b: _max_per_file(b, "Edit|Write|MultiEdit|NotebookEdit") >= 8,
    "scope_creep":         lambda b: _distinct_files(b, "Edit|Write|MultiEdit|NotebookEdit") >= 8,
    "never_verified":      lambda b: (len(re.findall(r"\[tool_use (?:Edit|Write|MultiEdit):", b)) >= 6
                                      and not VERIFY_RE.search(b)),
    "destructive_command": lambda b: bool(DESTRUCTIVE_RE.search(b)),
    "ungrounded_patch":    lambda b: bool(re.search(r"File has not been read yet|has been modified since read", b)),
    "test_suppressed":     lambda b: bool(SUPPRESS_RE.search(b)),
    "scaffold_friction":   lambda b: bool(SCAFFOLD_RE.search(b)),
    "sycophancy":          lambda b: bool(re.search(r"You(?:'re| are) absolutely right|You(?:'re| are) right|You(?:'re| are) correct", b)),
    "context_loss":        lambda b: any(PUSHBACK_RE.search(u) for u in _user_turns(b)),
    "poll_babysitting":    lambda b: len(re.findall(r"'command': '(?:[^']{0,60})?sleep \d", b)) >= 5,
    "asked_question":      lambda b: bool(re.search(r"\[tool_use AskUserQuestion", b)),
    "self_correction":     lambda b: bool(re.search(
        r"I was wrong|I made an error|I (?:have not|haven't) (?:actually )?(?:run|tested|verified)"
        r"|my (?:earlier|previous) (?:claim|assumption|analysis) was", b)),
}


def detect(text: str) -> list[str]:
    body = body_of(text)
    return [name for name, pred in DETECTORS.items() if pred(body)]


def stats(doc: dict) -> dict:
    body = body_of(doc.get("session_text") or "")
    return {
        "tool_calls": len(re.findall(r"\[tool_use ", body)),
        "tools": dict(collections.Counter(re.findall(r"\[tool_use (\w+)", body)).most_common(8)),
        "edits": len(re.findall(r"\[tool_use (?:Edit|Write|MultiEdit):", body)),
        "files_edited": _distinct_files(body, "Edit|Write|MultiEdit|NotebookEdit"),
        "max_reads_one_file": _max_per_file(body, "Read|NotebookRead"),
        "max_edits_one_file": _max_per_file(body, "Edit|Write|MultiEdit|NotebookEdit"),
        "fired": detect(doc.get("session_text") or ""),
    }


def context_windows(text: str, pattern: str, before=700, after=900, limit=4):
    for m in list(re.finditer(pattern, text))[:limit]:
        yield redact(text[max(0, m.start() - before): m.start() + after])


# --------------------------------------------------------------------------
# sampling
# --------------------------------------------------------------------------

def stratified_sample(coll, n: int):
    """Top-K-by-request_count within each task category, then interleaved.

    Biased toward long-horizon sessions on purpose: behavioural problems compound
    over turns, so the tail is where they are visible. This is NOT a random
    sample and the resulting frequencies are not base rates.
    """
    categories = sorted(coll.distinct("session_task_category", BASE_QUERY))
    per_cat = max(2, n // max(1, len(categories)) + 3)
    buckets = [
        list(coll.find(dict(BASE_QUERY, session_task_category=cat), PROJECTION)
                 .sort([("request_count", -1)]).limit(per_cat))
        for cat in categories
    ]
    out = []
    for i in range(per_cat):
        for bucket in buckets:
            if i < len(bucket):
                out.append(bucket[i])
            if len(out) >= n:
                return out
    return out[:n]


def summarise(doc: dict, fired: list[str]) -> str:
    return (
        f"{doc['session_id'][:8]}  "
        f"cat={doc.get('session_task_category', ''):<24} "
        f"req={doc.get('request_count'):<5} "
        f"hrs={(doc.get('session_duration_hours') or 0):<8.2f} "
        f"chars={doc.get('session_text_chars'):<7} "
        f"model={(doc.get('model') or '?'):<30} "
        f"| {', '.join(fired) or '-'}"
    )


# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=50, help="sessions to sample (default 50)")
    ap.add_argument("--out", default="reports/mined/candidates.md", help="shortlist output path")
    ap.add_argument("--jsonl", default=None, help="also write per-session detector hits as JSONL")
    ap.add_argument("--scan", action="store_true", help="run detectors over the whole 2192-session corpus")
    ap.add_argument("--detector", default=None, help="with --scan: rank sessions by this detector's raw count")
    ap.add_argument("--read-set", action="store_true", help="re-tally the exact hand-read set from the survey")
    ap.add_argument("--session-id", default=None, help="operate on one session (prefix match ok)")
    ap.add_argument("--stats", action="store_true", help="with --session-id: print tool/file statistics")
    ap.add_argument("--dump", action="store_true", help="with --session-id: print the full REDACTED transcript")
    ap.add_argument("--grep", default=None, help="with --session-id: print redacted windows around this regex")
    args = ap.parse_args()

    coll = pymongo.MongoClient(MONGO_URI)[DB_NAME][COLL]

    # ---- single session -------------------------------------------------
    if args.session_id:
        doc = coll.find_one({"session_id": {"$regex": f"^{re.escape(args.session_id)}"}}, PROJECTION)
        if not doc:
            print(f"no session matching {args.session_id}", file=sys.stderr)
            return 1
        text = doc["session_text"]
        if args.grep:
            for window in context_windows(text, args.grep):
                print("=" * 72)
                print(window)
        elif args.dump:
            print(redact(text))
        else:
            print(summarise(doc, detect(text)))
            if args.stats:
                print(json.dumps(stats(doc), indent=2))
        return 0

    # ---- hand-read set --------------------------------------------------
    if args.read_set:
        ids = STRATIFIED_SAMPLE + TARGETED_FOLLOWUPS
        tally = collections.Counter()
        for sid in ids:
            doc = coll.find_one({"session_id": {"$regex": f"^{sid}"}}, PROJECTION)
            if not doc:
                print(f"MISSING {sid}", file=sys.stderr)
                continue
            for name in detect(doc["session_text"]):
                tally[name] += 1
        print(f"hand-read set: {len(ids)} sessions "
              f"({len(STRATIFIED_SAMPLE)} stratified + {len(TARGETED_FOLLOWUPS)} targeted)")
        for name, n in tally.most_common():
            print(f"  {name:22s} {n:3d} / {len(ids)}")
        return 0

    # ---- corpus-wide scan -----------------------------------------------
    if args.scan:
        tally = collections.Counter()
        ranked = []
        total = 0
        for doc in coll.find(BASE_QUERY, PROJECTION):
            total += 1
            text = doc.get("session_text") or ""
            for name in detect(text):
                tally[name] += 1
            if args.detector:
                body = body_of(text)
                pred = DETECTORS[args.detector]
                if pred(body):
                    ranked.append((doc["session_id"], doc.get("session_task_category"),
                                   doc.get("request_count"), doc.get("model")))
        print(f"scanned {total} sessions matching {json.dumps(BASE_QUERY)}")
        for name, n in tally.most_common():
            print(f"  {name:22s} {n:5d}  ({100 * n / total:.1f}%)")
        if args.detector:
            print(f"\ntop sessions firing {args.detector}:")
            for row in ranked[:25]:
                print("   ", row[0][:8], (row[1] or "")[:22], "req", row[2], row[3])
        return 0

    # ---- default: stratified shortlist ----------------------------------
    docs = stratified_sample(coll, args.n)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    tally = collections.Counter()
    rows = []
    with open(args.out, "w") as fh:
        fh.write("# Mined session candidates (shortlist -- NOT a measurement)\n\n")
        fh.write(f"query: `{json.dumps(BASE_QUERY)}`  sampled: {len(docs)}\n\n")
        for doc in docs:
            fired = detect(doc["session_text"])
            for name in fired:
                tally[name] += 1
            rows.append({"session_id": doc["session_id"], "fired": fired, **stats(doc)})
            fh.write(f"## {summarise(doc, fired)}\n\n")
            fh.write(f"```\n{json.dumps(stats(doc), indent=1)}\n```\n\n")
        fh.write("\n## tally (sessions with at least one hit)\n\n")
        for name, n in tally.most_common():
            fh.write(f"- {name}: {n}/{len(docs)}\n")

    if args.jsonl:
        with open(args.jsonl, "w") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str) + "\n")

    print(f"wrote {args.out} ({len(docs)} sessions)")
    for name, n in tally.most_common():
        print(f"  {name:22s} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
