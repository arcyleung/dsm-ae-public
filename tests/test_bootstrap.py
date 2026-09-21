from dsm_ae.metrics.bootstrap import classify_status, bootstrap_metric
from dsm_ae.models import GateStatus, MetricResult


def _m(val: float, passed: bool) -> MetricResult:
    return MetricResult(
        metric_id="x",
        value=val,
        passed=passed,
        explanation="t",
    )


def test_pass_tight_variance():
    # all pass
    trials = [_m(1.0, True) for _ in range(5)]
    b = bootstrap_metric("x", "x", trials)
    assert b.status == GateStatus.PASS
    assert not b.disorder
    assert b.pass_rate == 1.0
    assert b.std == 0.0


def test_fail_consistent():
    trials = [_m(0.0, False) for _ in range(5)]
    b = bootstrap_metric("x", "x", trials)
    assert b.status == GateStatus.FAIL
    assert b.disorder


def test_unstable_high_variance():
    # alternating pass/fail → high std, pass_rate 0.5
    trials = [_m(1.0, True), _m(0.0, False)] * 3
    b = bootstrap_metric("x", "x", trials, threshold_pass=0.8, threshold_std=0.25)
    assert b.status == GateStatus.UNSTABLE
    assert b.disorder
    assert b.std > 0.25


def test_classify_edges():
    assert classify_status(0.9, 0.1) == GateStatus.PASS
    assert classify_status(0.9, 0.4) == GateStatus.UNSTABLE
    assert classify_status(0.5, 0.1) == GateStatus.FAIL
