#!/usr/bin/env python3
"""LLM-based failure attribution over Harbor trajectories.

Implements the *LLM Reasoning-Based Attribution* paradigm from Wang et al.,
"A Survey for LLM Agent Trajectory Analysis: From Failure Attribution to
Enhancement" (docs/papers/), §4.2.2 — the Who&When "all-at-once" prompting
strategy, adapted to single-agent SWE trajectories.

CALIBRATION, READ BEFORE TRUSTING ANY OUTPUT
--------------------------------------------
The survey reports step-level attribution accuracy of **25-52%** on Who&When
and **~33%** on TraceElephant (§4.2.5), with agent-level "significantly
higher" than step-level and some methods scoring *below random*. Our
trajectories are hand-crafted-system-like (long, variable), which the survey
notes is the harder regime.

So: these labels are **hypotheses to be validated**, not ground truth. The
localizer's step index is a candidate, and the honest reporting unit is
agreement-with-something-independent, not the label itself. Two cheap checks
this script supports:

  * `--repeat N` relabels each trajectory N times; self-consistency is an
    upper bound on reliability. If the model cannot agree with itself, the
    label carries nothing.
  * agreement with deterministic sentinels (`dsm_ae.harbor.steps`) is
    computed in the report — a converging independent signal.

Label schema (a/b/c per the supervisor's spec, aligned to the survey's
taxonomic perspectives):
  a) WHERE  — failure step index and/or execution phase (task-execution phase)
  b) WHAT   — free-text behavioural observations (agent capability module)
  c) WHY    — behavioural vs knowledge limitation (the actionability question)

Usage:
    python3 scripts/localize_failures.py --limit 20 --dry-run
    python3 scripts/localize_failures.py --source swebenchpro --failed-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dsm_ae.harbor import iter_runs, scoreable_only  # noqa: E402
from dsm_ae.harbor.steps import PHASES, sentinels, summarize, trends  # noqa: E402

MODEL = "gpt-5.6-sol"
MAX_STEPS_IN_PROMPT = 120
MAX_CHARS_PER_STEP = 400

SYSTEM = """You are a failure-attribution analyst for LLM coding agents.

You are given the tool-call trajectory of an agent attempting a software task,
and the ground-truth outcome (resolved or not). Your job is to localize WHERE
the run went wrong and characterise WHY.

Definition of the failure step (follow this precisely): the EARLIEST step at
which the agent took a WRONG ACTION that was never subsequently undone.

This is recoverability-aware in one direction only: if the agent made a
mistake at step 5 and then FIXED it at step 12, step 5 is not the failure
step. But if the mistake at step 5 was never corrected, the failure step is
5 — NOT the last step of the run.

CRITICAL — the last step is almost never the right answer. "The run ended
without succeeding" is true of every failed trajectory and carries no
information. You must point at a SPECIFIC ACTION (or a specific omission at a
specific point) that a competent agent would have done differently. If you
genuinely cannot localize one, return null for failure_step and say so in
resolution_rationale — that is a valid and useful answer.

Ask yourself: "if I could edit exactly one step of this trajectory, which one
would I change?" That step is the answer.

Return STRICT JSON, no prose outside it:

{
  "failure_step": <int index or null>,
  "failure_phase": "plan_stage" | "explore_stage" | "implementation_stage" | "verify_stage" | null,
  "confidence": <float 0-1>,
  "observations": [
    "<specific behavioural observation, e.g. 'never checks exit codes of bash calls'>",
    "..."
  ],
  "resolution": "behavioural" | "knowledge" | "unclear",
  "resolution_rationale": "<one sentence>"
}

Guidance:
- "behavioural": the agent had the information/ability but mismanaged the
  process (skipped verification, thrashed, ignored an error, stopped early).
  Correcting the behaviour would plausibly resolve the task.
- "knowledge": the agent lacked domain/codebase knowledge to solve it at all.
  Better process would not have saved it.
- "unclear": genuinely cannot tell from the trace. Use it rather than guessing.
- observations must be SPECIFIC and about process, not restatements of the
  outcome. Bad: "the agent failed the task". Good: "chains many commands with
  && so one flaky step aborts the rest".
- If the run SUCCEEDED, still report observations (they may describe risky
  process that happened to work), set failure_step and failure_phase to null.
- Do NOT default failure_step to the final step. A label at or near the last
  index will be treated as a non-answer unless the decisive wrong action
  genuinely occurred there (e.g. the agent submitted while a test was red).
- Prefer an EARLY, specific step over a late, vague one.
"""


def _endpoint() -> tuple[str, str]:
    """Read base/key for MODEL from models.yaml without a yaml dependency."""
    p = Path(__file__).resolve().parents[1] / "models.yaml"
    txt = p.read_text()
    block = re.search(
        rf"- model_name:\s*{re.escape(MODEL)}\b(.*?)(?=\n- model_name:|\Z)", txt, re.S
    )
    if not block:
        raise SystemExit(f"{MODEL} not found in models.yaml")
    b = block.group(1)
    base = re.search(r"api_base:\s*(\S+)", b)
    key = re.search(r"api_key:\s*(\S+)", b)
    if not (base and key):
        raise SystemExit(f"api_base/api_key missing for {MODEL}")
    return base.group(1).rstrip("/"), key.group(1)


def render_trajectory(t) -> str:
    """Compact, step-indexed rendering. Indices match tool_calls positions."""
    tr = trends(t)
    lines = [
        f"TASK: {t.task_name}",
        f"REPO: {t.repo}  LANGUAGE: {t.language}  HARNESS: {t.harness}",
        f"OUTCOME: {'RESOLVED' if t.success else 'NOT RESOLVED'} (reward={t.reward})",
        f"TOTAL STEPS: {tr.n_calls}",
        "",
        "TASK PROMPT (truncated):",
        (t.task_prompt or "")[:1200],
        "",
        "TRAJECTORY (step_index | atom | tool | detail):",
    ]
    calls = t.tool_calls
    idxs = list(range(len(calls)))
    if len(idxs) > MAX_STEPS_IN_PROMPT:
        head = idxs[: MAX_STEPS_IN_PROMPT // 2]
        tail = idxs[-MAX_STEPS_IN_PROMPT // 2 :]
        idxs = head + [-1] + tail
    from dsm_ae.harbor.instruments import _atom, _cmd, _path

    for i in idxs:
        if i == -1:
            lines.append(f"  ... [{len(calls) - MAX_STEPS_IN_PROMPT} steps elided] ...")
            continue
        tc = calls[i]
        detail = _path(tc) or _cmd(tc) or ""
        err = " ERROR" if tc.get("error") else ""
        res = str(tc.get("result") or "")[:120].replace("\n", " ")
        lines.append(
            f"  {i} | {_atom(tc)} | {tc.get('name','')}{err} | "
            f"{detail[:120]} -> {res[:MAX_CHARS_PER_STEP]}"
        )
    return "\n".join(lines)


def call_model(base: str, key: str, prompt: str, timeout: int = 300) -> dict[str, Any]:
    body = json.dumps(
        {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
        }
    ).encode()
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    txt = data["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise ValueError("no JSON in response")
    return json.loads(m.group(0))


def validate(lab: dict[str, Any], n_steps: int) -> dict[str, Any]:
    """Coerce and bound the label; record anything the model got wrong."""
    issues = []
    fs = lab.get("failure_step")
    if fs is not None:
        try:
            fs = int(fs)
            if not (0 <= fs < n_steps):
                issues.append(f"failure_step {fs} out of range [0,{n_steps})")
                fs = None
        except (TypeError, ValueError):
            issues.append("failure_step not an int")
            fs = None
    ph = lab.get("failure_phase")
    if ph is not None and ph not in PHASES:
        issues.append(f"unknown phase {ph!r}")
        ph = None
    res = lab.get("resolution")
    if res not in ("behavioural", "knowledge", "unclear"):
        issues.append(f"unknown resolution {res!r}")
        res = "unclear"
    obs = lab.get("observations") or []
    if not isinstance(obs, list):
        obs = [str(obs)]
    return {
        "failure_step": fs,
        "failure_phase": ph,
        "confidence": lab.get("confidence"),
        "observations": [str(o)[:400] for o in obs][:8],
        "resolution": res,
        "resolution_rationale": str(lab.get("resolution_rationale") or "")[:400],
        "schema_issues": issues,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path("evalhub-extract"))
    ap.add_argument("--out", type=Path, default=Path("reports/attribution/labels.jsonl"))
    ap.add_argument("--source", default="swebenchpro")
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--failed-only", action="store_true")
    ap.add_argument("--repeat", type=int, default=1,
                    help="relabel each trial N times to measure self-consistency")
    ap.add_argument("--rpm", type=float, default=6.0)
    ap.add_argument("--dry-run", action="store_true",
                    help="render prompts and exit; makes no API calls")
    args = ap.parse_args(argv)

    trials = []
    for run, ts in iter_runs(args.root):
        for t in scoreable_only(ts):
            if args.source and t.source != args.source:
                continue
            if args.failed_only and t.success:
                continue
            trials.append(t)
    trials.sort(key=lambda t: t.trial_name)
    if args.limit:
        trials = trials[: args.limit]
    print(f"trials to label: {len(trials)}  (repeat={args.repeat})")

    if args.dry_run:
        if trials:
            print("\n--- sample prompt ---")
            print(render_trajectory(trials[0])[:2500])
        return 0

    base, key = _endpoint()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    done: set[tuple[str, int]] = set()
    if args.out.exists():
        for line in args.out.read_text().splitlines():
            try:
                r = json.loads(line)
                done.add((r["trial_name"], r.get("rep", 0)))
            except Exception:
                pass
        print(f"resuming: {len(done)} labels already present")

    delay = 60.0 / max(args.rpm, 0.1)
    n_ok = n_err = 0
    with args.out.open("a") as fh:
        for t in trials:
            for rep in range(args.repeat):
                if (t.trial_name, rep) in done:
                    continue
                prompt = render_trajectory(t)
                try:
                    raw = call_model(base, key, prompt)
                    lab = validate(raw, len(t.tool_calls))
                    n_ok += 1
                except (urllib.error.URLError, ValueError, KeyError, TimeoutError) as e:
                    lab = {"error": f"{type(e).__name__}: {e}"[:300]}
                    n_err += 1
                rec = {
                    "trial_name": t.trial_name,
                    "task_name": t.task_name,
                    "rep": rep,
                    "harness": t.harness,
                    "language": t.language,
                    "success": t.success,
                    "n_steps": len(t.tool_calls),
                    "localizer": MODEL,
                    **lab,
                    "sentinels": [
                        {"kind": s.kind, "step": s.step, "phase": s.phase}
                        for s in sentinels(t)
                    ],
                }
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                if (n_ok + n_err) % 10 == 0:
                    print(f"  {n_ok} ok / {n_err} err")
                time.sleep(delay)
    print(f"done: {n_ok} ok, {n_err} errors -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
