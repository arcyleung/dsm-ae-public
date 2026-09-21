#!/usr/bin/env python3
"""Deterministic, auditable ~10% sample selection for the DGX benchmark runs.

Universes are read from the completed run bundles in evalhub-extract/ (the
instance directory names are urlsafe-base64 of the task id), so the sample is
drawn from exactly the instance set the reference harness ran.

SWE-bench-Pro is stratified by repo using largest-remainder apportionment, so
every one of the 11 repos -- and therefore every language (Python, Go,
TypeScript, JavaScript) -- is represented proportionally with >=1 instance.

Seed is fixed at 42. Output: reports/behaviour-task/sample-manifest.json
"""

from __future__ import annotations

import base64
import json
import os
import random
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTRACT = REPO_ROOT / "evalhub-extract"
SWE_RUN = EXTRACT / "swebenchpro-20260905-z00840601-dd4294bd-01"
# Canonical, case-correct instance ids from ScaleAI/SWE-bench_Pro (test split).
# The run-bundle directory names are lowercased, which the Harbor adapter rejects
# ("Instance not found"), so the canonical list is the authoritative universe.
# Verified: identical 731-instance set as the bundle, case-insensitively.
SWE_IDS_FILE = Path(__file__).resolve().parent / "swebenchpro_instance_ids.txt"
NL2_RUN = EXTRACT / "nl2repobench-notest-20260904-r84451424-5ab80c01-01"
OUT = REPO_ROOT / "reports" / "behaviour-task" / "sample-manifest.json"

SEED = 42
SWE_TARGET = 70   # ~10% of 731
NL2_TARGET = 10   # ~10% of 104

# Primary implementation language per SWE-bench-Pro repo owner.
REPO_LANG = {
    "ansible": ("ansible/ansible", "Python"),
    "internetarchive": ("internetarchive/openlibrary", "Python"),
    "qutebrowser": ("qutebrowser/qutebrowser", "Python"),
    "flipt-io": ("flipt-io/flipt", "Go"),
    "gravitational": ("gravitational/teleport", "Go"),
    "navidrome": ("navidrome/navidrome", "Go"),
    "future-architect": ("future-architect/vuls", "Go"),
    "protonmail": ("ProtonMail/WebClients", "TypeScript"),
    "element-hq": ("element-hq/element-web", "TypeScript"),
    "tutao": ("tutao/tutanota", "TypeScript"),
    "nodebb": ("NodeBB/NodeBB", "JavaScript"),
}


def decode(name: str) -> str:
    return base64.urlsafe_b64decode(name + "===").decode()


def owner_of(task_id: str) -> str:
    # Lowercased so canonical ids (instance_NodeBB__...) key into REPO_LANG.
    return task_id.replace("instance_", "", 1).split("__", 1)[0].lower()


def largest_remainder(counts: dict[str, int], total_target: int) -> dict[str, int]:
    """Apportion total_target across strata proportionally, min 1 each."""
    grand = sum(counts.values())
    exact = {k: v * total_target / grand for k, v in counts.items()}
    alloc = {k: max(1, int(e)) for k, e in exact.items()}
    # Adjust to hit the target exactly, ranked by fractional remainder.
    order = sorted(counts, key=lambda k: (exact[k] - int(exact[k]), counts[k]), reverse=True)
    while sum(alloc.values()) < total_target:
        for k in order:
            if sum(alloc.values()) >= total_target:
                break
            if alloc[k] < counts[k]:
                alloc[k] += 1
    while sum(alloc.values()) > total_target:
        for k in reversed(order):
            if sum(alloc.values()) <= total_target:
                break
            if alloc[k] > 1:
                alloc[k] -= 1
    return alloc


def main() -> None:
    rng = random.Random(SEED)

    # ---- SWE-bench-Pro: stratified by repo ----
    swe_ids = sorted(
        line.strip() for line in SWE_IDS_FILE.read_text().splitlines() if line.strip()
    )
    bundle_ids = {decode(d).lower() for d in os.listdir(SWE_RUN)}
    assert {i.lower() for i in swe_ids} == bundle_ids, (
        "canonical id list diverges from the reference run bundle universe"
    )
    by_repo: dict[str, list[str]] = {}
    for tid in swe_ids:
        by_repo.setdefault(owner_of(tid), []).append(tid)
    counts = {k: len(v) for k, v in by_repo.items()}
    alloc = largest_remainder(counts, SWE_TARGET)

    swe_sample = []
    for owner in sorted(by_repo):
        pool = sorted(by_repo[owner])
        picks = rng.sample(pool, alloc[owner])
        repo, lang = REPO_LANG[owner]
        for tid in sorted(picks):
            swe_sample.append(
                {
                    "instance_id": tid,
                    "repo": repo,
                    "repo_owner": owner,
                    "language": lang,
                    "dir_b64": base64.urlsafe_b64encode(tid.encode()).decode().rstrip("="),
                }
            )

    # ---- NL2Repo-Bench: flat sample ----
    nl2_ids = sorted(decode(d) for d in os.listdir(NL2_RUN))
    nl2_picks = sorted(rng.sample(nl2_ids, NL2_TARGET))
    nl2_sample = [
        {
            "instance_id": t,
            "repo": t,
            "language": "Python",
            "dir_b64": base64.urlsafe_b64encode(t.encode()).decode().rstrip("="),
        }
        for t in nl2_picks
    ]

    def tally(rows, key):
        out: dict[str, int] = {}
        for r in rows:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))

    manifest = {
        "schema_version": "1.0",
        "seed": SEED,
        "selection_method": (
            "SWE-bench-Pro: stratified by repo owner via largest-remainder "
            "apportionment (min 1 per repo), then random.Random(42).sample within "
            "each repo over the sorted instance list. NL2Repo-Bench: "
            "random.Random(42).sample over the sorted instance list. Universes are "
            "the instance sets of the reference run bundles in evalhub-extract/."
        ),
        "models": ["gpt-5.6-terra", "gpt-5.6-luna"],
        "benchmarks": {
            "swebenchpro": {
                "universe_size": len(swe_ids),
                "universe_source": SWE_RUN.name,
                "sample_size": len(swe_sample),
                "sample_fraction": round(len(swe_sample) / len(swe_ids), 4),
                "per_repo_universe": dict(sorted(counts.items())),
                "per_repo_sample": tally(swe_sample, "repo_owner"),
                "per_language_sample": tally(swe_sample, "language"),
                "instances": swe_sample,
            },
            "nl2repobench": {
                "universe_size": len(nl2_ids),
                "universe_source": NL2_RUN.name,
                "sample_size": len(nl2_sample),
                "sample_fraction": round(len(nl2_sample) / len(nl2_ids), 4),
                "per_language_sample": tally(nl2_sample, "language"),
                "instances": nl2_sample,
            },
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"wrote {OUT}")
    print("swebenchpro:", len(swe_sample), "of", len(swe_ids))
    print("  per-repo:", manifest["benchmarks"]["swebenchpro"]["per_repo_sample"])
    print("  per-lang:", manifest["benchmarks"]["swebenchpro"]["per_language_sample"])
    print("nl2repobench:", len(nl2_sample), "of", len(nl2_ids))


if __name__ == "__main__":
    main()
