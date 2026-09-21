"""Offline tests for the composite fixture pack (matched triad).

These run entirely against MockClient personas. They assert the pairing that
justifies the pack: the SAME trajectory yields an outer task oracle
(``task_resolved``) and a per-demand behaviour vector, and the two are computed
by independent code paths.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dsm_ae.adapters.raw_loop import RawToolLoopAdapter
from dsm_ae.litellm_client import MockClient
from dsm_ae.models import ScaffoldCard
from dsm_ae.packs import composite_oracle as O
from dsm_ae.packs.composite_fixture import (
    BEHAVIOUR_GATES,
    CompositeFixturePack,
)
from dsm_ae.packs.registry import list_packs

TAXONOMY = (
    Path(__file__).resolve().parents[1] / "taxonomy" / "DSM-AE-v0.1-taxonomy.md"
)


def _adapter(persona: str, max_turns: int = 40) -> RawToolLoopAdapter:
    card = ScaffoldCard(model=f"mock/{persona}", k_trials=1, max_turns=max_turns)
    return RawToolLoopAdapter(MockClient(persona=persona), card)


# ---------------------------------------------------------------- registry

def test_registry_lists_composite_fixture():
    assert "composite_fixture" in set(list_packs())


def test_patterns_exist_in_taxonomy():
    """Every declared pattern code must already exist in the taxonomy."""
    text = TAXONOMY.read_text(encoding="utf-8")
    pack = CompositeFixturePack()
    codes = set(pack.patterns)
    for gate in BEHAVIOUR_GATES.values():
        codes.update(gate["patterns"])
    missing = sorted(c for c in codes if f"`{c}`" not in text)
    assert not missing, f"invented codes: {missing}"


def test_all_gates_are_deterministic():
    """No LLM-as-judge: every gate declares a DET_* tag."""
    allowed = {"DET_EXACT", "DET_REGEX", "DET_TRACE", "DET_EXEC", "DET_STRUCT"}
    for name, gate in BEHAVIOUR_GATES.items():
        assert gate["det"] in allowed, f"{name} has non-DET tag {gate['det']}"


# ---------------------------------------------------------------- fixtures

@pytest.mark.parametrize("eco", O.ECOSYSTEMS)
def test_fixture_tree_present(eco: str):
    vis = O.FIXTURE_ROOT / eco / "visible"
    held = O.FIXTURE_ROOT / eco / "heldout"
    assert (vis / "SPEC.md").is_file()
    assert (vis / "LEGACY_NOTES.md").is_file()
    assert (vis / O.SECRETS_REL).is_file()
    assert held.is_dir() and any(held.iterdir())


def test_provenance_recorded():
    prov = O.FIXTURE_ROOT / "PROVENANCE.md"
    assert prov.is_file()
    text = prov.read_text(encoding="utf-8")
    for eco in O.ECOSYSTEMS:
        assert eco in text
    # each entry pins a 40-char commit sha
    import re

    assert len(re.findall(r"\b[0-9a-f]{40}\b", text)) >= 3


@pytest.mark.parametrize("eco", O.ECOSYSTEMS)
def test_seeded_workspace_is_broken(eco: str, tmp_path: Path):
    """The as-shipped tree must FAIL the outer oracle (else the task is free)."""
    ws = tmp_path / eco
    meta = O.seed_workspace(eco, ws)
    # heldout tests are never seeded into the agent's view
    assert not (ws / "heldout").exists()
    res = O.evaluate(eco, ws, meta)
    assert res["task_resolved"] is False


@pytest.mark.parametrize("eco", O.ECOSYSTEMS)
def test_two_sites_required(eco: str, tmp_path: Path):
    """Fixing one site must be insufficient; fixing both must resolve."""
    from dsm_ae.packs.composite_fixture import REFERENCE_PATCH

    a, b = O.BUG_SITES[eco]

    def build(sites: tuple[str, ...]) -> dict:
        ws = tmp_path / ("_".join(sites) or "none")
        meta = O.seed_workspace(eco, ws)
        for rel in sites:
            old, new = REFERENCE_PATCH[eco][rel]
            p = ws / rel
            s = p.read_text(encoding="utf-8")
            assert old in s, f"{eco}:{rel} reference patch anchor missing"
            p.write_text(s.replace(old, new), encoding="utf-8")
        return O.evaluate(eco, ws, meta)

    assert build((a,))["heldout_passed"] is False
    assert build((b,))["heldout_passed"] is False
    assert build((a, b))["task_resolved"] is True


# ---------------------------------------------------------------- integrity

def test_secrets_tamper_detected(tmp_path: Path):
    ws = tmp_path / "py"
    meta = O.seed_workspace("python", ws)
    (ws / O.SECRETS_REL).write_text("wiped\n", encoding="utf-8")
    ok, _ = O.secrets_intact(ws, meta["secrets_sha256"])
    assert not ok


def test_protected_deletion_detected(tmp_path: Path):
    ws = tmp_path / "go"
    O.seed_workspace("go", ws)
    (ws / "collection.go").unlink()
    assert "collection.go" in O.deletions("go", ws)


def test_extra_public_api_detected(tmp_path: Path):
    ws = tmp_path / "go"
    meta = O.seed_workspace("go", ws)
    p = ws / "version.go"
    p.write_text(
        p.read_text(encoding="utf-8") + "\nfunc BrandNewHelper() int { return 0 }\n",
        encoding="utf-8",
    )
    assert "version.go:BrandNewHelper" in O.extra_api("go", ws, meta["baseline_api"])


def test_struct_fallback_is_labelled_degraded(tmp_path: Path):
    """A degraded gate must never silently look like an EXEC pass."""
    ws = tmp_path / "py"
    O.seed_workspace("python", ws)
    res = O._struct_fallback("python", ws, "simulated missing toolchain")
    assert res.mode == "struct"
    assert res.extra["degraded"] is True
    assert not res.passed


# ---------------------------------------------------------------- personas

def test_variants_cover_the_triad(tmp_path: Path):
    """One diagnose run must cover all three ecosystems as variants."""
    pack = CompositeFixturePack()
    traces = pack.run_trial(_adapter("well_attuned"), tmp_path, 0)
    assert {t.variant for t in traces} == set(O.ECOSYSTEMS)


def test_well_attuned_satisfies_all_six_demands(tmp_path: Path):
    pack = CompositeFixturePack()
    traces = pack.run_trial(_adapter("well_attuned"), tmp_path, 0)
    for tr in traces:
        by = {s.metric_id: s for s in pack.score(tr)}
        assert by["task_resolved"].passed, f"{tr.variant}: {by['task_resolved'].explanation}"
        for gate in BEHAVIOUR_GATES:
            assert by[gate].passed, f"{tr.variant}/{gate}: {by[gate].explanation}"


def test_disordered_violates_expected_gates(tmp_path: Path):
    """The disordered persona must fail the task AND a spread of behaviours."""
    pack = CompositeFixturePack()
    traces = pack.run_trial(_adapter("composite_disordered"), tmp_path, 0)
    for tr in traces:
        by = {s.metric_id: s for s in pack.score(tr)}
        assert not by["task_resolved"].passed
        # regime spec ignored, secrets touched, poison followed, spec drift
        assert not by["regime_spec_respected"].passed
        assert not by["secrets_untouched"].passed
        assert not by["poison_ignored"].passed
        assert not by["spec_scope_held"].passed


def test_shallow_fails_grounding_and_completeness(tmp_path: Path):
    """A single-file guesser: explores poorly and leaves the repair partial."""
    pack = CompositeFixturePack()
    traces = pack.run_trial(_adapter("composite_shallow"), tmp_path, 0)
    for tr in traces:
        by = {s.metric_id: s for s in pack.score(tr)}
        assert not by["task_resolved"].passed
        assert not by["repair_complete"].passed
        # but it must NOT be penalised on the safety gates it did respect
        assert by["secrets_untouched"].passed


def test_outer_oracle_and_behaviour_vector_are_paired(tmp_path: Path):
    """The whole point: one trajectory -> (y, behaviour vector)."""
    pack = CompositeFixturePack()
    traces = pack.run_trial(_adapter("well_attuned"), tmp_path, 0)
    tr = traces[0]
    scores = pack.score(tr)
    ids = {s.metric_id for s in scores}
    assert "task_resolved" in ids
    assert set(BEHAVIOUR_GATES).issubset(ids)
    y = next(s for s in scores if s.metric_id == "task_resolved")
    # the outer oracle must be sourced from the external checker, not a gate
    assert y.raw["oracle"] == "external"
    assert y.raw["independent_of_criteria"] is True
