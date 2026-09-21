"""The ceiling-skip contract.

18 packs were ceilinged on every gate they own across the three k=20 gpt-5.6
runs (reports/ceiling/audit.json) and are skipped by default. These tests pin
the behaviour that skipping narrows the *default run set* only, and never
removes a pack from the registry.
"""

from dsm_ae.packs.registry import CEILING_SKIPPED, PACKS, get_pack, list_packs


def test_skipped_packs_are_still_registered():
    """Skipping is a scheduling decision, not a deletion."""
    for pid in CEILING_SKIPPED:
        assert pid in PACKS, f"{pid} is skipped but not registered"
        assert get_pack(pid) is not None


def test_default_set_excludes_skipped():
    default = set(list_packs())
    assert default.isdisjoint(CEILING_SKIPPED)
    assert default, "default battery must not be empty"


def test_include_skipped_restores_every_pack():
    every = set(list_packs(include_skipped=True))
    assert every == set(PACKS)
    assert every - set(list_packs()) == set(CEILING_SKIPPED)


def test_explicit_selection_still_honours_skipped_ids():
    """Asking for a skipped pack by id must keep working."""
    from dsm_ae.cli import _parse_packs

    pid = sorted(CEILING_SKIPPED)[0]
    assert _parse_packs(pid, full_suite=False) == [pid]


def test_full_suite_flag_respects_include_skipped():
    from dsm_ae.cli import _parse_packs

    lean = _parse_packs(None, full_suite=True)
    full = _parse_packs(None, full_suite=True, include_skipped=True)
    assert set(lean).isdisjoint(CEILING_SKIPPED)
    assert set(full) == set(PACKS)
    assert len(full) > len(lean)
