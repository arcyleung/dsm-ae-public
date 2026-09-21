#!/usr/bin/env python3
"""Export the four §1.5 real-user sessions into reports/blog/trajectories/.

Skips Appendix A seed pools, rubric/template traces, and empty parses.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "reports" / "blog" / "trajectories"

FEATURED = (
    ("f4ac2beb", "Scenario 1: 185 permission refusals"),
    ("0614e0de", "Scenario 2: tmux → 83 edits / 9 files"),
    ("b52e0124", "Scenario 3: 51-hour sleep 60 loop"),
    ("40b0660e", "Scenario 4: 62 consecutive Edit refusals"),
)

sys.path.insert(0, str(ROOT / "web" / "scripts"))
# reuse parser from deleted generate_blog_ui — inline the small bits
from pathlib import Path as _P

# copy of session_text_to_events from the old generator
_ROLE_SPLIT = re.compile(r"\n(user|assistant): ")


def redact(text: str) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    import mine_sessions

    return mine_sessions.redact(text)


def cut_system(text: str) -> str:
    last = text.rfind("</example>")
    if last >= 0:
        return text[last + len("</example>") :]
    i = text.find("\nuser:")
    return text[i:] if i >= 0 else text


def to_events(text: str, cap: int) -> list[dict]:
    chunk = cut_system(text)
    bits = _ROLE_SPLIT.split("\n" + chunk)
    events: list[dict] = []
    i = 1
    while i + 1 < len(bits) and len(events) < cap:
        role, content = bits[i], bits[i + 1]
        i += 2
        pos = 0
        for m in re.finditer(
            r"\[tool_use (\w+)(?:: (.*?))?\]|\[tool_result:(.*?)(?=\n(?:user|assistant): |\n\[tool_use |\Z)",
            content,
            re.S,
        ):
            prose = content[pos : m.start()].strip()
            if prose and role == "assistant":
                events.append({"type": "message", "role": "assistant", "text": prose[:4000]})
            pos = m.end()
            if m.group(1):
                events.append({
                    "type": "tool_call",
                    "role": "assistant",
                    "tool": m.group(1),
                    "text": (m.group(2) or "")[:2000],
                })
            else:
                events.append({
                    "type": "tool_result",
                    "role": "user",
                    "tool": "result",
                    "text": (m.group(3) or "").strip()[:4000],
                })
            if len(events) >= cap:
                break
        rest = content[pos:].strip()
        if rest and len(events) < cap:
            if role == "user" and rest.startswith("[tool_result"):
                continue
            events.append({"type": "message", "role": role, "text": rest[:4000]})
    return events


def main() -> int:
    import pymongo

    uri = os.environ.get("DSM_MONGO_URI", "mongodb://localhost:27018/")
    client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=3000)
    client.admin.command("ping")
    coll = client["claude_conversations"]["session_labels_by_gpt55"]
    DEST.mkdir(parents=True, exist_ok=True)
    # drop leftover appendix/template jsonl so the viewer cannot pick them up
    for old in DEST.glob("*.jsonl"):
        old.unlink()

    sessions = []
    for prefix, label in FEATURED:
        doc = coll.find_one(
            {"session_id": {"$regex": f"^{re.escape(prefix)}"}},
            {"auth_token": 0},
        )
        if not doc:
            print(f"MISSING {prefix}", file=sys.stderr)
            continue
        events = to_events(redact(doc.get("session_text") or ""), cap=800)
        nonempty = sum(1 for e in events if (e.get("text") or "").strip())
        if nonempty < 5:
            print(f"SKIP empty parse {prefix} n={len(events)} nonempty={nonempty}", file=sys.stderr)
            continue
        fname = f"{prefix}.jsonl"
        with (DEST / fname).open("w", encoding="utf-8") as fh:
            for ev in events:
                fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        sessions.append({
            "id": doc.get("session_id"),
            "short": prefix,
            "label": label,
            "featured": True,
            "n_events": len(events),
            "request_count": doc.get("request_count"),
            "category": doc.get("session_task_category"),
            "model": doc.get("model"),
            "file": fname,
            "truncated": len(events) >= 800,
        })
        print(f"  {prefix} {len(events)} events  {label}")

    index = {"ok": True, "sessions": sessions, "source": "session_labels_by_gpt55"}
    (DEST / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"wrote {len(sessions)} featured sessions → {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
