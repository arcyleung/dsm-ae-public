#!/usr/bin/env python3
"""Separate GENUINE task failures from INFRASTRUCTURE artifacts in a run tree.

A reward of 0 means two very different things:

  * the agent tried and the required test really failed   -> genuine signal
  * no test ever ran (emulation/exec failure, timeout)    -> meaningless zero

Reporting the second kind as model performance would fabricate a
language-specific deficit, which is exactly the confound this study exists to
separate from genuine agentic deficits. This script makes the distinction
explicit and auditable.

Run ON THE DGX (or over a pulled run tree):
    python3 triage_rewards.py ~/dsm-dgx/runs
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Repo -> primary language, mirroring src/dsm_ae/harbor/adapter.py.
REPO_LANG = {
    "ansible": "python", "qutebrowser": "python", "internetarchive": "python",
    "gravitational": "go", "flipt-io": "go", "navidrome": "go",
    "future-architect": "go", "element-hq": "typescript",
    "protonmail": "typescript", "nodebb": "javascript", "tutao": "typescript",
}


def language_of(trial: str) -> str:
    # SWE-bench-Pro trials are "instance_<owner>__...__<suffix>"; NL2Repo-Bench
    # trials are "<package>__<suffix>" and are all Python.
    if not trial.startswith("instance_"):
        return "python"  # NL2Repo-Bench
    name = trial.replace("instance_", "", 1).split("__")[0].lower()
    return REPO_LANG.get(name, "unknown")


# Tasks whose expected test names embed a run-dependent assertion count, e.g.
#   'test/api/Suite.ts | api tests (3029 assertions)'
# Exact-name matching cannot match these when the suite shards differently, so a
# 0 reward is NOT evidence the model failed. Detected from tests/config.json.
ASSERTION_COUNT_TASKS = {"instance_tutao__tutanota-5181821"}


def has_assertion_count_grader(trial: str) -> bool:
    return any(trial.startswith(t) for t in ASSERTION_COUNT_TASKS)


def trial_exception(trial_dir: Path) -> tuple[str | None, str]:
    """(exception_type, message) from result.json.

    Harbor records trial-level failures HERE, not in trial.log -- a grep of
    trial.log alone silently misses them.
    """
    f = trial_dir / "result.json"
    if not f.exists():
        return None, ""
    try:
        info = json.loads(f.read_text()).get("exception_info") or {}
    except Exception:
        return None, ""
    return info.get("exception_type"), info.get("exception_message", "") or ""


def classify(trial_dir: Path) -> dict:
    reward_f = trial_dir / "verifier" / "reward.txt"
    out_f = trial_dir / "verifier" / "output.json"

    exc, msg = trial_exception(trial_dir)
    if exc:
        # The trial never produced a scoreable attempt. These are environment
        # failures, not model performance.
        if "exit 137" in msg and "cooling down" not in msg:
            # 137 = 128+9 = SIGKILL. Harbor sometimes labels this
            # ApiRateLimitError, but a genuine quota failure carries
            # "cooling down"/429 in opencode.txt. With none of those, this is
            # the container's cgroup OOM-killing the agent -> raise memory_mb.
            oc = trial_dir / "agent" / "opencode.txt"
            body = ""
            try:
                body = oc.read_text(errors="ignore")[:20000] if oc.exists() else ""
            except Exception:
                body = ""
            if "cooling down" not in body and '"statusCode": 429' not in body:
                verdict = "ARTIFACT_AGENT_OOM_KILLED"
                return {"verdict": verdict, "reward": None, "n_tests": None}
        if "404" in msg and "apt-get" in msg:
            # Stale Debian indexes (e.g. bullseye moved to archive.debian.org)
            # so the agent's own install step dies before it ever runs.
            verdict = "ARTIFACT_APT_404"
        elif exc == "AgentTimeoutError":
            # Two very different things share this exception:
            #  * 0-byte opencode.txt -> the agent never started (startup hang);
            #  * large opencode.txt  -> the agent worked productively and was
            #    truncated by the cap, i.e. the budget is too small for this
            #    task under emulation (raise --agent-timeout-multiplier).
            oc = trial_dir / "agent" / "opencode.txt"
            size = oc.stat().st_size if oc.exists() else 0
            verdict = ("ARTIFACT_AGENT_NEVER_STARTED" if size == 0
                       else "ARTIFACT_TIMEOUT_BUDGET_TOO_SMALL")
        elif exc == "NonZeroAgentExitCodeError":
            # Distinguish upstream model-quota exhaustion (HTTP 429, "cooling
            # down") from a genuine setup/install failure. The 429 case happens
            # mid-run, not during setup, and is a provider capacity limit --
            # not anything the model or the environment did wrong.
            oc = trial_dir / "agent" / "opencode.txt"
            body = ""
            try:
                body = oc.read_text(errors="ignore")[:20000] if oc.exists() else ""
            except Exception:
                body = ""
            if "cooling down" in body or '"statusCode": 429' in body:
                verdict = "ARTIFACT_MODEL_QUOTA_429"
            else:
                verdict = "ARTIFACT_AGENT_EXIT_NONZERO"
        else:
            verdict = f"ARTIFACT_{exc}"
        return {"verdict": verdict, "reward": None, "n_tests": None}

    if not reward_f.exists():
        return {"verdict": "INCOMPLETE", "reward": None, "n_tests": None}

    try:
        reward = float(reward_f.read_text().strip())
    except ValueError:
        return {"verdict": "BAD_REWARD_FILE", "reward": None, "n_tests": None}

    n_tests = None
    if out_f.exists():
        try:
            n_tests = len(json.loads(out_f.read_text()).get("tests", []))
        except Exception:
            n_tests = None

    if reward > 0:
        verdict = "GENUINE_PASS"
    elif n_tests == 0:
        # Zero tests is NOT automatically an artifact. A pytest *collection*
        # error means the agent's own patch broke an import -- that is a real
        # model failure and must stay in the scored set. Only treat zero tests
        # as infrastructure when no collection error is present.
        stdout = trial_dir / "verifier" / "run-script-stdout.txt"
        text = ""
        try:
            text = stdout.read_text(errors="ignore")[-40000:] if stdout.exists() else ""
        except Exception:
            text = ""
        # A qemu-level signal means a native binary the verifier depends on
        # died under emulation (Go runtime, redis-server, ...). Language is
        # irrelevant -- nothing was measured.
        stderr_f = trial_dir / "verifier" / "run-script-stderr.txt"
        err = ""
        try:
            err = stderr_f.read_text(errors="ignore")[-20000:] if stderr_f.exists() else ""
        except Exception:
            err = ""
        if "qemu: uncaught target signal" in err:
            verdict = "ARTIFACT_QEMU_SIGNAL"
        elif any(k in text for k in
                 ("ERROR collecting", "ImportError", "ModuleNotFoundError",
                  "errors during collection")):
            verdict = "GENUINE_FAIL"
        else:
            verdict = "ARTIFACT_NO_TESTS_RAN"
    elif n_tests is None:
        # NL2Repo-Bench computes a fractional reward directly and writes no
        # output.json; a 0 there means tests ran and none passed. SWE-bench-Pro
        # always writes output.json, so a missing one is genuinely suspicious.
        verdict = ("GENUINE_FAIL" if not trial_dir.name.startswith("instance_")
                   else "UNKNOWN_NO_OUTPUT_JSON")
    elif has_assertion_count_grader(trial_dir.name):
        # Tests ran and passed, but the grader's expected name embeds an
        # assertion count that cannot match. Not model performance.
        verdict = "ARTIFACT_GRADER_NAME_MISMATCH"
    else:
        # Tests ran and were named; a 0 here is a real failure.
        verdict = "GENUINE_FAIL"
    return {"verdict": verdict, "reward": reward, "n_tests": n_tests}


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "runs").expanduser()
    rows = []
    for job in sorted(p for p in root.iterdir() if p.is_dir()):
        for trial in sorted(p for p in job.iterdir() if p.is_dir()):
            info = classify(trial)
            inst = None
            rj = trial / "result.json"
            if rj.exists():
                try:
                    inst = json.loads(rj.read_text()).get("task_name")
                except Exception:
                    inst = None
            info.update(job=job.name, trial=trial.name, instance=inst,
                        language=language_of(trial.name))
            rows.append(info)

    if not rows:
        print(f"no trials under {root}")
        return

    print(f"{'verdict':<24} {'lang':<11} {'reward':>8} {'tests':>6}  trial")
    print("-" * 88)
    for r in sorted(rows, key=lambda r: (r["verdict"], r["trial"])):
        rw = "-" if r["reward"] is None else f"{r['reward']:.4f}"
        nt = "-" if r["n_tests"] is None else str(r["n_tests"])
        print(f"{r['verdict']:<24} {r['language']:<11} {rw:>8} {nt:>6}  {r['trial'][:40]}")

    print("\n== counts by verdict ==")
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<24} {v}")

    print("\n== TRUSTWORTHY scoring rate, by language ==")
    print("   (artifacts excluded -- they measured nothing)")
    print("   n = model-ATTEMPTS; instances = distinct problems. Every instance")
    print("   is attempted by both models, so n roughly doubles the sample size.")
    by_lang: dict[str, list[tuple[float, str]]] = {}
    for r in rows:
        if r["verdict"] in ("GENUINE_PASS", "GENUINE_FAIL"):
            # Instance identity must come from result.json's task_name:
            # Harbor TRUNCATES the trial dir name, so several distinct
            # instances collapse to the same prefix (e.g. every openlibrary
            # task becomes "instance_internetarchive__openli"), which
            # undercounts distinct problems.
            inst = r.get("instance") or r["trial"].rsplit("__", 1)[0]
            by_lang.setdefault(r["language"], []).append((r["reward"], inst))
    for lang in sorted(by_lang):
        v = by_lang[lang]
        rewards = [x for x, _ in v]
        n_inst = len({i for _, i in v})
        print(f"  {lang:<12} n={len(v):3d}  instances={n_inst:3d}  "
              f"mean={sum(rewards)/len(rewards):.3f}")

    quarantined = sum(1 for r in rows if r["verdict"].startswith(("ARTIFACT", "UNKNOWN")))
    if quarantined:
        print(f"\n!! {quarantined} trial(s) QUARANTINED -- do not report these as "
              f"model performance (see scripts/dgx/README-runs.md section 9).")


if __name__ == "__main__":
    main()
