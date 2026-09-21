from dsm_ae.metric_citations import (
    METRIC_CITATIONS,
    REFERENCES,
    citations_for_metric,
    format_cite_keys,
    references_used,
)


def test_overeager_cites_qu():
    ids = citations_for_metric("overeager_rate")
    assert 1 in ids
    assert format_cite_keys(ids) == ",".join(str(i) for i in sorted(set(ids)))


def test_recency_bias_cites_fang_etal():
    """RBD metrics cite Fang et al. 2025 arXiv:2509.11353 (bib 88)."""
    assert 88 in REFERENCES
    assert "2509.11353" in REFERENCES[88]["text"]
    assert "arxiv.org/abs/2509.11353" in REFERENCES[88]["url"]
    for mid in (
        "capacity_reexplored",
        "consulted_prior_state",
        "recovered_prior_optimum",
        "not_stuck_at_prior_floor",
    ):
        assert 88 in citations_for_metric(mid), mid


def test_all_mapped_refs_exist():
    for metric, ids in METRIC_CITATIONS.items():
        for i in ids:
            assert i in REFERENCES, f"metric {metric} cites missing ref {i}"


def test_references_used_subset():
    used = references_used(["overeager_rate", "erosion_indicator"])
    assert 1 in used and 2 in used
    assert set(used) <= set(REFERENCES)
