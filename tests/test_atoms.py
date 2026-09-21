"""Unit tests for trajectory atom mapping, JSD, and floor."""

from __future__ import annotations

from dsm_ae.atoms import (
    atom_from_tool,
    atoms_from_trace,
    auc_roc,
    discriminative_procedures,
    fail_score,
    fingerprint,
    jsd,
    label_trial,
    match_patterns,
    measure_floor,
    ngrams,
    procedure_key,
)
from dsm_ae.atoms import LoadedTrial, build_vocab


def test_atom_from_tool_aliases():
    assert atom_from_tool("read_file") == "read_file"
    assert atom_from_tool("write_file") == "edit"
    assert atom_from_tool("list_dir") == "search_repo"
    assert atom_from_tool("done") == "submit"
    assert atom_from_tool("request_approval") == "gate"
    assert atom_from_tool("shell", {"command": "pytest -q"}) == "run_test"
    assert atom_from_tool("shell", {"command": "ls -la"}) == "search_repo"
    assert atom_from_tool("shell", {"command": "python app.py"}) == "run_code"
    assert atom_from_tool("shell", {"command": "rm -rf tmp"}) == "delete_file"


def test_atoms_from_trace_and_error():
    tr = {
        "tool_calls": [
            {"name": "read_file", "arguments": {"path": "a.txt"}},
            {"name": "write_file", "arguments": {"path": "a.txt"}, "error": "denied"},
            {"name": "done", "arguments": {"message": "3"}},
        ]
    }
    assert atoms_from_trace(tr) == ["read_file", "error", "submit"]


def test_jsd_identical_and_disjoint():
    assert jsd([1, 0], [1, 0]) == 0.0
    d = jsd([1, 0], [0, 1])
    assert abs(d - 1.0) < 1e-9
    mid = jsd([0.5, 0.5], [1.0, 0.0])
    assert 0.0 < mid < 1.0


def test_label_trial_prefers_task_metric():
    scores = [
        {"metric_id": "task_success_cleanup", "passed": False},
        {"metric_id": "scope_safe", "passed": True},
        {"metric_id": "critical_preserved", "passed": True},
    ]
    task, all_ok = label_trial("overeager_mini", scores)
    assert task is False
    assert all_ok is False  # task metric is non-smoke and failed


def test_ngrams_and_fingerprint_roundtrip():
    atoms = ["read_file", "edit", "submit"]
    assert ngrams(atoms, 2) == [("read_file", "edit"), ("edit", "submit")]
    vocab = [procedure_key(("read_file",)), procedure_key(("read_file", "edit"))]
    fp = fingerprint(atoms, vocab, ngram_max=2)
    assert fp == [1.0, 1.0]


def test_discriminative_and_auc_separate_classes():
    def t(tid, atoms, ok):
        return LoadedTrial(
            trial_id=tid,
            model="m",
            pack="overeager_mini",
            source="t",
            atoms=atoms,
            scores=[],
            task_passed=ok,
            all_nonsmoke_passed=ok,
        )

    trials = [
        t("p1", ["read_file", "edit", "submit"], True),
        t("p2", ["read_file", "search_repo", "submit"], True),
        t("f1", ["edit", "delete_file", "submit"], False),
        t("f2", ["edit", "delete_file", "edit"], False),
    ]
    vocab = build_vocab(trials, ngram_max=2, min_count=1)
    disc = discriminative_procedures(trials, vocab, ngram_max=2, k=10)
    assert disc
    top_fail = max(disc, key=lambda r: r.log_odds)
    assert "edit" in top_fail.procedure or "delete_file" in top_fail.procedure
    scores = [fail_score(x.atoms, disc) for x in trials]
    labels = [0 if x.task_passed else 1 for x in trials]
    auc = auc_roc(scores, labels)
    assert auc is not None and auc >= 0.75


def test_match_patterns_edit_before_read():
    assert "edit_before_read" in match_patterns(["edit", "submit"])
    assert "edit_before_read" not in match_patterns(["read_file", "edit", "submit"])


def test_floor_identical_traces_near_zero():
    fp = [[1.0, 0.0, 2.0]] * 20
    pts = measure_floor(fp, sizes=(5,), reps=20, seed=1)
    assert pts and pts[0].mean < 1e-9
