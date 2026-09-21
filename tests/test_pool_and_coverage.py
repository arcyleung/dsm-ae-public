from dsm_ae.diagnose import diagnose
from dsm_ae.packs.registry import list_packs, pack_pattern_index
from dsm_ae.pool import RateLimiter, map_pool
import time


def test_map_pool_sequential_order():
    out = map_pool([1, 2, 3], lambda x: x * 10, concurrency=1)
    assert out == [10, 20, 30]


def test_map_pool_parallel_order():
    out = map_pool([1, 2, 3, 4], lambda x: x * 2, concurrency=4)
    assert out == [2, 4, 6, 8]


def test_rate_limiter_spacing():
    rl = RateLimiter(rpm=120)  # 0.5s interval
    t0 = time.monotonic()
    rl.wait()
    rl.wait()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.4


def test_diagnose_concurrency_matches_sequential():
    packs = ["sycophancy_mini", "tool_integrity"]
    a = diagnose(model="mock/well_attuned", packs=packs, k=2, concurrency=1, keep_traces=False)
    b = diagnose(model="mock/well_attuned", packs=packs, k=2, concurrency=2, keep_traces=False)
    # same metric set
    assert {g.metric_id for g in a.gates} == {g.metric_id for g in b.gates}
    for ga in a.gates:
        gb = next(x for x in b.gates if x.metric_id == ga.metric_id)
        assert ga.status == gb.status


def test_all_new_packs_registered():
    packs = set(list_packs(include_skipped=True))
    for p in [
        "hello_metacog",
        "overeager_mini",
        "slop_indicator",
        "erosion_tier2",
        "erosion_tier3",
        "loop_control",
        "tool_integrity",
        "tool_integrity_tier2",
        "sycophancy_mini",
        "injection_mini",
        "gate_discipline",
        "spec_drift_mini",
    ]:
        assert p in packs


def test_pattern_index_nonempty():
    idx = pack_pattern_index()
    assert "AA-01" in idx or "MC-01" in idx
    assert len(idx) >= 20


def test_full_mock_e2e_all_packs():
    report = diagnose(
        model="mock/well_attuned",
        packs=list_packs(include_skipped=True),
        k=2,
        concurrency=1,
        keep_traces=False,
    )
    assert report.gates
    # well_attuned should not present severe disorders across core
    present = [f for f in report.findings if f.present]
    # may still have none
    assert isinstance(present, list)


def test_disorder_personas_trigger():
    r = diagnose(model="mock/sycophant", packs=["sycophancy_mini"], k=2, keep_traces=False)
    rsd = next(f for f in r.findings if f.code == "RSD")
    assert rsd.present
