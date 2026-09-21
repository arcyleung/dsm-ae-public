from dsm_ae.decision_trees import (
    SYNDROME_TREES,
    GateView,
    evaluate_tree,
    tree_to_mermaid,
)


def test_catalogue_complete():
    assert len(SYNDROME_TREES) >= 20
    for code, tree in SYNDROME_TREES.items():
        assert tree.start in tree.nodes
        assert any(n.kind == "terminal" for n in tree.nodes.values())


def test_all_pass_absent():
    for code, tree in SYNDROME_TREES.items():
        gates = {
            m: GateView(m, "PASS", False, 1.0, 1.0, 0.0)
            for m in tree.linked_metrics
        }
        pw = evaluate_tree(tree, gates)
        assert not pw.present
        assert not pw.not_evaluated


def test_all_fail_present():
    for code, tree in SYNDROME_TREES.items():
        gates = {
            m: GateView(
                m,
                "FAIL",
                True,
                0.0,
                0.0,
                0.0,
                "bad",
                [{"explanation": "x", "evidence": []}],
            )
            for m in tree.linked_metrics
        }
        pw = evaluate_tree(tree, gates)
        assert pw.present


def test_oasd_critical_path():
    tree = SYNDROME_TREES["OASD"]
    gates = {
        "overeager_rate": GateView("overeager_rate", "PASS", False, 1.0, 0.0, 0.0),
        "critical_trap_avoided": GateView(
            "critical_trap_avoided",
            "UNSTABLE",
            True,
            0.5,
            0.5,
            0.5,
            "trap hit",
            [{"explanation": "deleted .env.old", "evidence": [{"kind": "fs", "ref": ".env.old", "detail": "deleted"}]}],
        ),
        "scope_safe": GateView("scope_safe", "PASS", False, 1.0, 1.0, 0.0),
    }
    pw = evaluate_tree(tree, gates)
    assert pw.present and pw.severity == "critical"
    assert any(s.node_id == "crit" and s.branch == "yes" for s in pw.steps)
    assert any("deleted" in e.lower() for s in pw.steps for e in s.evidence_snippets)


def test_mermaid_shows_metric_fan_in():
    """Sub-criteria should appear as nodes feeding decision diamonds."""
    tree = SYNDROME_TREES["TID"]
    mm = tree_to_mermaid(tree)
    assert "flowchart TD" in mm
    for m in tree.linked_metrics:
        assert m in mm
    assert "-- Yes -->" in mm and "-- No -->" in mm
    # polythetic fan-in into any_dis
    assert "task_tool_success" in mm
    assert "Any linked metric DISORDERED" in mm


def test_mermaid_pathway_colors_gates():
    tree = SYNDROME_TREES["TID"]
    gates = {
        "no_tool_hallucination": GateView(
            "no_tool_hallucination", "PASS", False, 1.0, 1.0, 0.0
        ),
        "schema_valid": GateView("schema_valid", "PASS", False, 1.0, 1.0, 0.0),
        "task_tool_success": GateView(
            "task_tool_success", "UNSTABLE", True, 0.67, 0.67, 0.47
        ),
    }
    pw = evaluate_tree(tree, gates)
    mm = tree_to_mermaid(tree, pathway=pw, gates=gates)
    assert "gate_pass" in mm
    assert "gate_unstable" in mm
    assert "classDef taken" in mm
    assert pw.present
