from __future__ import annotations

from dsm_ae.packs.base import IndicatorPack
from dsm_ae.packs.clarify_verify import ClarifyVerifyPack
from dsm_ae.packs.composite_fixture import CompositeFixturePack
from dsm_ae.packs.coord_tax_mini import CoordTaxMiniPack
from dsm_ae.packs.eval_gaming_mini import EvalGamingMiniPack
from dsm_ae.packs.gate_discipline import GateDisciplinePack
from dsm_ae.packs.gate_discipline_rev2 import GateDisciplineRev2Pack
from dsm_ae.packs.handoff_mini import HandoffMiniPack
from dsm_ae.packs.hello_metacog import HelloMetacogPack
from dsm_ae.packs.injection_mini import InjectionMiniPack
from dsm_ae.packs.loop_control import LoopControlPack
from dsm_ae.packs.mas_verify_mini import MasVerifyMiniPack
from dsm_ae.packs.memory_context import MemoryContextPack
from dsm_ae.packs.memory_context_rev2 import MemoryContextRev2Pack
from dsm_ae.packs.nfr_omit import NfrOmitPack
from dsm_ae.packs.overeager_mini import OvereagerMiniPack
from dsm_ae.packs.pii_safety import PiiSafetyPack
from dsm_ae.packs.recency_bias_mini import RecencyBiasMiniPack
from dsm_ae.packs.recency_bias_mini_rev2 import RecencyBiasMiniRev2Pack
from dsm_ae.packs.role_confusion_mini import RoleConfusionMiniPack
from dsm_ae.packs.sandbag_mini import SandbagMiniPack
from dsm_ae.packs.session_overwrite_mini import SessionOverwriteMiniPack
from dsm_ae.packs.erosion_tier2 import ErosionTier2Pack
from dsm_ae.packs.erosion_tier3 import ErosionTier3Pack
from dsm_ae.packs.slop_indicator import SlopIndicatorPack
from dsm_ae.packs.spec_drift_mini import SpecDriftMiniPack
from dsm_ae.packs.sycophancy_mini import SycophancyMiniPack
from dsm_ae.packs.tool_integrity import ToolIntegrityPack
from dsm_ae.packs.tool_integrity_tier2 import ToolIntegrityTier2Pack

_PACK_INSTANCES: list[IndicatorPack] = [
    HelloMetacogPack(),
    OvereagerMiniPack(),
    SlopIndicatorPack(),
    ErosionTier2Pack(),
    ErosionTier3Pack(),
    LoopControlPack(),
    ToolIntegrityPack(),
    ToolIntegrityTier2Pack(),
    SycophancyMiniPack(),
    InjectionMiniPack(),
    GateDisciplinePack(),
    MemoryContextPack(),
    HandoffMiniPack(),
    EvalGamingMiniPack(),
    SandbagMiniPack(),
    ClarifyVerifyPack(),
    PiiSafetyPack(),
    NfrOmitPack(),
    RoleConfusionMiniPack(),
    MasVerifyMiniPack(),
    SessionOverwriteMiniPack(),
    CoordTaxMiniPack(),
    RecencyBiasMiniPack(),
    SpecDriftMiniPack(),
    CompositeFixturePack(),
    # rev2: state-seeded variants of packs whose rev1 gates saturate. Kept as
    # separate registrations so rev1 stays available for A/B comparison.
    RecencyBiasMiniRev2Pack(),
    MemoryContextRev2Pack(),
    GateDisciplineRev2Pack(),
]

PACKS: dict[str, IndicatorPack] = {p.id: p for p in _PACK_INSTANCES}

# ---------------------------------------------------------------------------
# Ceiling-skipped packs
# ---------------------------------------------------------------------------
# `scripts/ceiling_audit.py` over the three k=20 gpt-5.6 runs
# (reports/ceiling/audit.json) found 75 of 94 gates at ceiling: every variant
# scores exactly 1.00, so the gate returns the same value whether or not the
# models differ. 18 packs are ceilinged on EVERY gate they own and cannot
# contribute to separating those models.
#
# They are skipped by default to stop spending trials on items that cannot
# discriminate. This is NOT a claim that the packs are wrong. The ceiling was
# measured against gpt-5.6 only, and the construct may still be sound at a
# harder difficulty or against a weaker model -- which is exactly what the
# re-qualification experiment checks.
#
# Re-qualify with:
#     dsm-ae diagnose -m <weaker-model> --include-skipped
# and, if any gate leaves ceiling, delete that pack id from this set.
# Narrowed 2026-09-18 after the gpt-6-astra full battery (k=10, all 28 packs,
# reports/requalify/astra_full_battery.json). Eight of the original eighteen
# produced at least one below-ceiling gate on that model -- several at 0.00 --
# so they were never undemanding, only unchallenged by gpt-5.6, and they are
# back in the default set:
#     coord_tax_mini, gate_discipline, handoff_mini, memory_context,
#     recency_bias_mini, session_overwrite_mini, tool_integrity,
#     tool_integrity_tier2
# The ten below stayed at ceiling on gpt-6-astra as well as on gpt-5.6, which
# is two model families' worth of evidence that the items are too easy.
CEILING_SKIPPED: frozenset[str] = frozenset(
    {
        "eval_gaming_mini",
        "injection_mini",
        "loop_control",
        "mas_verify_mini",
        "nfr_omit",
        "pii_safety",
        "role_confusion_mini",
        "sandbag_mini",
        "slop_indicator",
        "sycophancy_mini",
    }
)


def get_pack(pack_id: str) -> IndicatorPack:
    if pack_id not in PACKS:
        raise KeyError(f"Unknown pack {pack_id!r}. Available: {list(PACKS)}")
    return PACKS[pack_id]


def list_packs(include_skipped: bool = False) -> list[str]:
    """Pack ids to run by default.

    Packs in `CEILING_SKIPPED` are omitted unless `include_skipped` is true.
    Asking for a skipped pack by id still works -- only the default set shrinks.
    """
    if include_skipped:
        return sorted(PACKS)
    return sorted(p for p in PACKS if p not in CEILING_SKIPPED)


def pack_pattern_index() -> dict[str, list[str]]:
    idx: dict[str, list[str]] = {}
    for p in _PACK_INSTANCES:
        for code in p.patterns:
            idx.setdefault(code, []).append(p.id)
    return idx
