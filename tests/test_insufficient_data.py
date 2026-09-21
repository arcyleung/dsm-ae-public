"""A syndrome whose packs never ran must not read as "not present".

`evaluate_tree` routes to a `term_ne` terminal when the availability predicate
(`all_available`) is False because the required metrics are absent. That
terminal carries `present=False` like a genuine-absence terminal, so unless it
is flagged, the matrix renders "Not present · none" for a syndrome that was
never measured -- asserting evidence of absence from absence of evidence.
"""

from dsm_ae.decision_trees import SYNDROME_TREES, GateView, evaluate_tree


def _gate(metric_id: str, *, disorder: bool = False) -> GateView:
    return GateView(
        metric_id=metric_id,
        status="PASS",
        disorder=disorder,
        pass_rate=1.0,
        mean=1.0,
        std=0.0,
    )


def _tree_with_availability_node():
    """A tree whose first decision is an `all_available` check."""
    for tree in SYNDROME_TREES.values():
        for node in tree.nodes.values():
            if node.kind == "decision" and node.predicate == "all_available":
                mids = node.metrics or ([node.metric_id] if node.metric_id else [])
                if mids:
                    return tree, mids
    raise AssertionError("no tree uses an all_available gate")


def test_missing_metrics_report_not_evaluated():
    tree, _ = _tree_with_availability_node()
    pw = evaluate_tree(tree, {})
    assert pw.not_evaluated, f"{tree.code} with no gates must be not_evaluated"
    assert not pw.present


def test_present_metrics_do_not_report_not_evaluated():
    """The flag must be specific: a fully-supplied tree still returns a verdict."""
    tree, mids = _tree_with_availability_node()
    gates = {m: _gate(m) for m in mids}
    pw = evaluate_tree(tree, gates)
    assert not pw.not_evaluated, (
        f"{tree.code} had all of {mids} supplied but reported not_evaluated"
    )


def test_every_tree_is_not_evaluated_on_empty_gates():
    """No syndrome may claim absence when nothing was measured."""
    offenders = [
        code
        for code, tree in SYNDROME_TREES.items()
        if not evaluate_tree(tree, {}).not_evaluated
    ]
    assert not offenders, f"syndromes claiming a verdict with no gates: {offenders}"


def test_renderer_labels_missing_finding_as_insufficient_data():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from json_to_html_report import fmt_finding_cell

    text, cls = fmt_finding_cell(None)
    assert text == "Insufficient data"
    assert cls == "not-run"

    text, _ = fmt_finding_cell({"present": False, "severity": "none"})
    assert text.startswith("Not present"), "a real absent finding must still say so"
