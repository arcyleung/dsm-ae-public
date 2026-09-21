"""Semantic ordering of DSM-AE metrics and syndromes for experimental UIs.

Groups place related indicators in adjacent rows (e.g. multi-agent handoff
metrics near coordination tax) so the matrix reads as behavioural blocks
rather than alphabetical soup.
"""

from __future__ import annotations

# Ordered groups: (group_id, display_label, metric_ids in preferred order)
METRIC_GROUPS: list[tuple[str, str, list[str]]] = [
    (
        "agency_scope",
        "Agency & scope (OASD / GDD)",
        [
            "task_success_cleanup",
            "scope_safe",
            "critical_trap_avoided",
            "overeager_rate",
            "approval_before_delete",
            "no_ungated_delete",
            "task_completed",
        ],
    ),
    (
        "tool_integrity",
        "Tool integrity & grounding (TID)",
        [
            "no_tool_hallucination",
            "schema_valid",
            "tools_used_required",
            "read_grounded",
            "answer_matches_tool_result",
            "done_nonempty",
            "recovery_ok",
            "task_tool_success",
            "task_tool_success.tier1",
            "task_tool_success.tier2",
        ],
    ),
    (
        "planning_control",
        "Planning & control (PCD)",
        [
            "all_files_read",
            "premature_stop_avoided",
            "no_read_loop",
            "count_correct",
        ],
    ),
    (
        "metacog_contract",
        "Meta-cognition / contract (MCD · SC-35)",
        [
            "files_read_complete",
            "project_specific_stops",
            "synthesis_not_enumeration",
            "mood_authenticity",
            "ready_phrase",
            "protocol_success",
        ],
    ),
    (
        "memory_recency",
        "Memory, context & recency (MEM · RBD)",
        [
            "knowledge_retention",
            "distractor_resisted",
            "faithfulness",
            "regime_switched",
            "capacity_reexplored",
            "consulted_new_regime_docs",
            "not_stuck_at_prior_floor",
            "left_panic_config",
            "recovered_prior_optimum",
            "consulted_prior_state",
            "multi_param_coherent",
        ],
    ),
    (
        "social_alignment",
        "Social / alignment (RSD · SBG · CVF)",
        [
            "resists_wrong_user",
            "states_correct_answer",
            "no_sandbag",
            "correct_under_pressure",
            "asks_clarification",
            "no_false_success",
            "verification_attempted",
        ],
    ),
    (
        "security",
        "Security & injection (XPI · PII)",
        [
            "injection_resisted",
            "critical_preserved",
            "critical_preserved.tier1",
            "user_task_done",
            "no_secret_leak",
            "acknowledges_sensitive",
            "task_answered",
        ],
    ),
    (
        "coding_quality",
        "Coding quality / slop (ISDS · NFR · EGD)",
        [
            "c1_implements",
            "c2_extends",
            "erosion_indicator",
            "erosion_indicator.tier1",
            "erosion_indicator.tier2",
            "erosion_indicator.tier3",
            "erosion_slope",
            "verbosity_indicator",
            "verbosity_indicator.tier1",
            "quality_stable",
            "quality_stable.tier1",
            "quality_stable.tier3",
            "god_function_mass",
            "extract_discipline",
            "tier2_features_land",
            "tier3_features_land",
            "has_validation",
            "has_error_handling",
            "happy_path_works",
            "no_test_memorization",
            "implements_general",
            "hidden_pass",
        ],
    ),
    (
        "multi_agent",
        "Multi-agent (MAH · MRC · MVF · CSO · CTX)",
        [
            "handoff_artifact_written",
            "schema_preserved",
            "handoff_consumed",
            "role_boundary_held",
            "review_artifact_written",
            "role_spec_ok",
            "independent_verify",
            "correct_verdict",
            "no_rubber_stamp",
            "peer_state_preserved",
            "own_state_written",
            "no_silent_overwrite",
            "final_answer_correct",
            "coordination_artifacts",
            "low_coord_churn",
        ],
    ),
]

# Syndrome order mirrors metric groups (for syndrome matrix)
SYNDROME_ORDER: list[str] = [
    "OASD",
    "GDD",
    "TID",
    "PCD",
    "MCD",
    "SC-35",
    "MEM",
    "RBD",
    "RSD",
    "SBG",
    "CVF",
    "XPI",
    "PII",
    "ISDS",
    "NFR",
    "EGD",
    "MAH",
    "MRC",
    "MVF",
    "CSO",
    "CTX",
]


def ordered_metrics(metrics: list[str]) -> list[tuple[str | None, str | None, str]]:
    """Return rows as (group_id|None, group_label|None, metric_id).

    Group header rows have metric_id == '' and non-None group_label.
    Metrics not in any group appear under 'other' at the end.
    """
    remaining = set(metrics)
    out: list[tuple[str | None, str | None, str]] = []
    for gid, label, members in METRIC_GROUPS:
        present = [m for m in members if m in remaining]
        if not present:
            continue
        out.append((gid, label, ""))  # header
        for m in present:
            out.append((gid, None, m))
            remaining.discard(m)
    if remaining:
        out.append(("other", "Other / ungrouped", ""))
        for m in sorted(remaining):
            out.append(("other", None, m))
    return out


def ordered_syndromes(codes: list[str]) -> list[str]:
    rank = {c: i for i, c in enumerate(SYNDROME_ORDER)}
    return sorted(codes, key=lambda c: (rank.get(c, 999), c))
