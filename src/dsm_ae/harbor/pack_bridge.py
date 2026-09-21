"""Bridge DSM-AE IndicatorPack ↔ Harbor verifier I/O.

Task 1 scope only: workspace prep (fixtures side), score (load scores.json or
run mock trial), write Harbor reward.json. No docker, no harbor_runs layout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.litellm_client import MockClient
from dsm_ae.models import MetricResult, ScaffoldCard, TrialTrace
from dsm_ae.packs.registry import get_pack
from dsm_ae.trajectory_store import (
    litellm_log_path,
    save_trial_artifacts,
    trajectory_dir,
)


def _make_mock_adapter(persona: str = "well_attuned") -> RawToolLoopAdapter:
    """Create offline adapter using MockClient for tests / fallback scoring."""
    card = ScaffoldCard(
        model=f"mock/{persona}",
        k_trials=1,
        max_turns=16,
        temperature=0.0,
    )
    return RawToolLoopAdapter(MockClient(persona=persona), card)


def _make_live_adapter(
    model: str,
    *,
    models_yaml: Path | str | None = None,
    max_turns: int = 16,
) -> RawToolLoopAdapter:
    """Create live LiteLLM adapter from models.yaml routing."""
    from dsm_ae.litellm_client import make_client

    yaml_path = Path(models_yaml) if models_yaml else Path("models.yaml")
    card = ScaffoldCard(
        model=model,
        k_trials=1,
        max_turns=max_turns,
        temperature=0.0,
        extra={"models_yaml": str(yaml_path) if yaml_path.is_file() else None},
    )
    client = make_client(
        model,
        models_yaml=yaml_path if yaml_path.is_file() else None,
    )
    return RawToolLoopAdapter(client, card)


def _get_persona(work_root: Path, pack_id: str, trial_index: int) -> str:
    """Retrieve persona recorded by prepare, default well_attuned."""
    meta = work_root / f".harbor_meta_{pack_id}__t{trial_index}" / "persona.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            p = data.get("mock_persona") or data.get("persona")
            if isinstance(p, str) and p:
                return p
        except Exception:
            pass
    return "well_attuned"


def prepare_workspace(
    pack_id: str, work_root: Path, trial_index: int = 0, **kwargs: Any
) -> Path:
    """Create pack trial workspace under work_root (fixtures metadata only; no LLM).

    Records mock_persona (if given) for score_workspace fallback.
    Returns the canonical trial dir (using __t naming for consistency with trajectories).
    """
    pack = get_pack(pack_id)  # validate early
    root = Path(work_root)
    root.mkdir(parents=True, exist_ok=True)

    persona = kwargs.get("mock_persona") or kwargs.get("persona") or "well_attuned"
    meta_dir = root / f".harbor_meta_{pack_id}__t{trial_index}"
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "persona.json").write_text(
        json.dumps({"mock_persona": persona}), encoding="utf-8"
    )

    # Ensure trajectories root (scores load path)
    (root / "trajectories").mkdir(parents=True, exist_ok=True)

    # Return a trial-named dir (per brief sketch); actual pack ws created on run
    trial_dir = root / f"{pack_id}__t{trial_index}"
    trial_dir.mkdir(parents=True, exist_ok=True)
    return trial_dir


def _metrics_dict_from_results(results: list[MetricResult]) -> dict[str, Any]:
    """Convert list[MetricResult] -> metric_id -> dict with value/passed/..."""
    out: dict[str, Any] = {}
    for m in results:
        # Use model_dump for full fidelity; callers expect .get("value") etc
        d = m.model_dump(mode="json")
        out[m.metric_id] = d
    return out


def score_workspace(
    pack_id: str,
    work_root: Path,
    trial_index: int = 0,
    *,
    model: str | None = None,
    models_yaml: Path | str | None = None,
    force_rerun: bool = False,
) -> dict[str, Any]:
    """Score workspace for pack/trial.

    Prefer: load from trajectories/{pack}__t{i}/scores.json (real MetricResult rows)
    unless ``force_rerun``.

    Else: run a trial:
      - if ``model`` is set and not ``mock/*`` → live LiteLLM via models.yaml
      - else mock trial (persona from prepare or default)

    Returns dict[metric_id, {value, passed, explanation, ...}]
    """
    root = Path(work_root)
    tdir = trajectory_dir(root, pack_id, trial_index)
    scores_path = tdir / "scores.json"

    if scores_path.is_file() and not force_rerun:
        try:
            rows = json.loads(scores_path.read_text(encoding="utf-8"))
            if isinstance(rows, list) and rows:
                metrics: dict[str, Any] = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    mid = row.get("metric_id")
                    if not mid:
                        continue
                    # strip internal _ keys for cleaner dict, keep core fields
                    clean = {k: v for k, v in row.items() if not k.startswith("_")}
                    metrics[mid] = clean
                if metrics:
                    return metrics
        except Exception:
            # fall through to re-score
            pass

    pack = get_pack(pack_id)
    live = bool(model) and not str(model).startswith("mock/")
    if live:
        yaml_path = models_yaml or root.joinpath("models.yaml")
        # also try cwd / repo models.yaml
        if not Path(str(yaml_path)).is_file():
            for cand in (Path("models.yaml"), Path.cwd() / "models.yaml"):
                if cand.is_file():
                    yaml_path = cand
                    break
        adapter = _make_live_adapter(str(model), models_yaml=yaml_path)
    else:
        persona = _get_persona(root, pack_id, trial_index)
        adapter = _make_mock_adapter(persona)

    # run_trial takes the *per-pack* work dir (diagnose uses root/pack_id)
    pack_work = root / pack_id
    items: list[tuple[str, TrialTrace, list[MetricResult]]] = []
    call_log = litellm_log_path(root, pack_id, trial_index)
    call_log.parent.mkdir(parents=True, exist_ok=True)
    try:
        if call_log.is_file():
            call_log.unlink()
    except OSError:
        pass
    client = getattr(adapter, "client", None)
    if client is not None and hasattr(client, "set_call_log"):
        client.set_call_log(call_log)
    try:
        traces = pack.run_trial(adapter, pack_work, trial_index)
        for tr in traces:
            scores = pack.score(tr)
            items.append((pack_id, tr, scores))
    except Exception as e:
        kind = "live" if live else "mock"
        fail = MetricResult(
            metric_id="protocol_success",
            value=0.0,
            passed=False,
            explanation=f"{kind} run failed in score_workspace: {e}",
        )
        return {fail.metric_id: fail.model_dump(mode="json")}
    finally:
        if client is not None and hasattr(client, "set_call_log"):
            try:
                client.set_call_log(None)
            except Exception:
                pass

    if items:
        try:
            save_trial_artifacts(root, pack_id, trial_index, items)
        except Exception:
            # best effort; scoring still succeeds
            pass
        # return from first (typical) trace's scores; dict form
        _pid, _tr, sc = items[0]
        return _metrics_dict_from_results(sc)

    return {}


def write_reward(metrics: dict[str, Any], path: Path) -> None:
    """Write Harbor-compatible reward.json.

    Top level: only floats.
      - primary_pass: 1.0 or 0.0 (all passed?)
      - each metric_id with "." -> "_" , value as float (if numeric)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def _get(m: Any, key: str, default: Any = None) -> Any:
        if isinstance(m, dict):
            return m.get(key, default)
        return getattr(m, key, default) if hasattr(m, key) else default

    passed_flags = []
    for m in metrics.values():
        p = _get(m, "passed")
        if p is not None:
            passed_flags.append(bool(p))
    primary = 1.0 if (passed_flags and all(passed_flags)) else 0.0

    out: dict[str, float] = {"primary_pass": primary}

    for mid, m in metrics.items():
        val = _get(m, "value")
        if isinstance(val, (int, float)):
            key = str(mid).replace(".", "_")
            out[key] = float(val)

    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
