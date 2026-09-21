"""Bootstrap aggregation: mean, std, pass_rate → PASS / FAIL / UNSTABLE.

Design rule (user):
  - tight variance + high pass → well attuned, no disorder
  - high variance → disorder (UNSTABLE)
  - low pass rate → disorder (FAIL)
"""

from __future__ import annotations

import math
import statistics

from dsm_ae.models import (
    BootstrapStats,
    GateCell,
    GateStatus,
    MetricResult,
)
from dsm_ae.packs.smoke_metrics import SMOKE_BADGE, is_smoke_metric


def classify_status(
    pass_rate: float,
    std: float,
    *,
    threshold_pass: float = 0.8,
    threshold_std: float = 0.25,
) -> GateStatus:
    if pass_rate < threshold_pass:
        # low mean performance
        if std > threshold_std:
            return GateStatus.UNSTABLE  # inconsistent AND weak
        return GateStatus.FAIL
    if std > threshold_std:
        return GateStatus.UNSTABLE  # can pass sometimes but unreliable
    return GateStatus.PASS


def bootstrap_metric(
    metric_id: str,
    dimension: str,
    per_trial: list[MetricResult],
    *,
    threshold_pass: float = 0.8,
    threshold_std: float = 0.25,
) -> BootstrapStats:
    values = [m.value for m in per_trial]
    passes = [1.0 if m.passed else 0.0 for m in per_trial]
    n = len(values)
    mean = statistics.fmean(values) if n else 0.0
    pass_rate = statistics.fmean(passes) if n else 0.0
    # use pass/fail series for variance of attunement when values are continuous;
    # for binary metrics, std of values == std of passes.
    series = passes if all(v in (0.0, 1.0) for v in values) else values
    std = statistics.pstdev(series) if n > 1 else 0.0
    status = classify_status(
        pass_rate, std, threshold_pass=threshold_pass, threshold_std=threshold_std
    )
    disorder = status in (GateStatus.FAIL, GateStatus.UNSTABLE)

    # human summary
    explanations = [m.explanation for m in per_trial[:3]]
    smoke_tag = f" [{SMOKE_BADGE}]" if is_smoke_metric(metric_id) else ""
    summary = (
        f"n={n} mean={mean:.3f} std={std:.3f} pass_rate={pass_rate:.3f} → {status.value}"
        + (f" (DISORDER)" if disorder else " (attuned)")
        + smoke_tag
        + (f". e.g. {explanations[0]}" if explanations else "")
    )

    return BootstrapStats(
        metric_id=metric_id,
        dimension=dimension,
        n=n,
        values=values,
        mean=mean,
        std=std,
        pass_rate=pass_rate,
        status=status,
        disorder=disorder,
        threshold_pass=threshold_pass,
        threshold_std=threshold_std,
        per_trial=per_trial,
        summary=summary,
    )


def build_gate_matrix(bootstraps: list[BootstrapStats]) -> list[GateCell]:
    cells = []
    for b in bootstraps:
        cells.append(
            GateCell(
                dimension=b.dimension,
                metric_id=b.metric_id,
                pass_rate=b.pass_rate,
                mean=b.mean,
                std=b.std,
                status=b.status,
                disorder=b.disorder,
                explanation=b.summary,
            )
        )
    return cells
