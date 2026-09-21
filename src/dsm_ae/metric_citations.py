"""Map outcome-gate metric_ids → survey bibliography reference numbers.

Reference numbers match ``sources/bibliography.md`` (AS_OF survey registry).
Only cite papers that motivate the *measurement construct*, not every related work.
"""

from __future__ import annotations

from typing import Any

# Canonical references used in HTML footnotes (subset of survey bibliography).
# Keys are bibliography numbers from sources/bibliography.md
REFERENCES: dict[int, dict[str, str]] = {
    1: {
        "short": "Qu et al., 2026",
        "text": 'Qu et al. (2026). "Overeager Coding Agents: Measuring Out-of-Scope Actions on Benign Tasks." arXiv:2605.18583.',
        "url": "https://arxiv.org/abs/2605.18583",
    },
    2: {
        "short": "Orlanski et al., 2026",
        "text": 'Orlanski et al. (2026). "SlopCodeBench: Benchmarking How Coding Agents Degrade Over Long-Horizon Iterative Tasks." arXiv:2603.24755.',
        "url": "https://arxiv.org/abs/2603.24755",
    },
    3: {
        "short": "SNARE, 2026",
        "text": 'SNARE (2026). "Adaptive Scenario Synthesis for Eliciting Overeager Behavior in Coding Agents." arXiv:2605.28122.',
        "url": "https://arxiv.org/abs/2605.28122",
    },
    4: {
        "short": "SpecBench, 2026",
        "text": 'SpecBench (2026). "Measuring Reward Hacking in Long-Horizon Coding Agents." arXiv:2605.21384.',
        "url": "https://arxiv.org/abs/2605.21384",
    },
    5: {
        "short": "Spec gaming reasoning, 2026",
        "text": 'Towards Understanding Specification Gaming in Reasoning Models (2026). arXiv:2605.02269.',
        "url": "https://arxiv.org/abs/2605.02269",
    },
    6: {
        "short": "Chess/spec gaming, 2025",
        "text": "Demonstrating specification gaming in reasoning models (2025). arXiv:2502.13295.",
        "url": "https://arxiv.org/abs/2502.13295",
    },
    11: {
        "short": "SWE issue failures, 2025",
        "text": "An Empirical Study on Failures in Automated Issue Solving (2025). arXiv:2509.13941.",
        "url": "https://arxiv.org/abs/2509.13941",
    },
    12: {
        "short": "SWE-Bench Pro, 2025",
        "text": "SWE-Bench Pro failure-mode analysis (2025). arXiv:2509.16941.",
        "url": "https://arxiv.org/abs/2509.16941",
    },
    17: {
        "short": "80% problem, 2026",
        "text": 'Augment (2026). "The 80% Problem: Why AI Agents Ship Fast But Create Hidden Technical Debt."',
        "url": "https://www.augmentcode.com/guides/the-80-percent-problem-ai-agents-technical-debt",
    },
    18: {
        "short": "Context rot, 2026",
        "text": 'MindStudio (2026). "Context Rot in AI Coding Agents."',
        "url": "https://www.mindstudio.ai/blog/context-rot-ai-coding-agents-how-to-prevent",
    },
    21: {
        "short": "Cemri et al. MAST, 2025",
        "text": 'Cemri et al. (2025). "Why Do Multi-Agent LLM Systems Fail?" (MAST). arXiv:2503.13657.',
        "url": "https://arxiv.org/abs/2503.13657",
    },
    22: {
        "short": "Microsoft AIRT taxonomy, 2025",
        "text": 'Microsoft AI Red Team (2025). "Taxonomy of Failure Mode in Agentic AI Systems."',
        "url": "https://www.microsoft.com/en-us/security/blog/2025/04/24/new-whitepaper-outlines-the-taxonomy-of-failure-modes-in-ai-agents/",
    },
    23: {
        "short": "Microsoft AIRT v2, 2026",
        "text": 'Microsoft AI Red Team (2026). "Updating the taxonomy of failure modes in agentic AI systems."',
        "url": "https://www.microsoft.com/en-us/security/blog/2026/06/04/updating-taxonomy-failure-modes-agentic-ai-systems-year-red-teaming-taught-us/",
    },
    25: {
        "short": "Vectara agent failures",
        "text": "Vectara (2025–2026). Awesome Agent Failures (community taxonomy + case studies).",
        "url": "https://github.com/vectara/awesome-agent-failures",
    },
    26: {
        "short": "Galileo agent failures, 2026",
        "text": 'Galileo (2026). "7 AI Agent Failure Modes and How to Prevent Them."',
        "url": "https://galileo.ai/blog/agent-failure-modes-guide",
    },
    27: {
        "short": "Future AGI 5-category, 2026",
        "text": 'Future AGI (2026). "AI Agent Failure Modes in 2026: The 5-Category Taxonomy."',
        "url": "https://futureagi.com/blog/ai-agent-failure-modes-2026/",
    },
    34: {
        "short": "Tool hallucination, 2024",
        "text": "Reducing Tool Hallucination via Reliability Alignment (2024). arXiv:2412.04141.",
        "url": "https://arxiv.org/abs/2412.04141",
    },
    35: {
        "short": "Agent hallucinations survey, 2025",
        "text": "LLM-based Agents Suffer from Hallucinations: A Survey (2025). arXiv:2509.18970.",
        "url": "https://arxiv.org/abs/2509.18970",
    },
    36: {
        "short": "Infinite Agentic Loops, 2026",
        "text": 'When Agents Do Not Stop: Uncovering Infinite Agentic Loops (2026). arXiv:2607.01641.',
        "url": "https://arxiv.org/abs/2607.01641",
    },
    40: {
        "short": "DeepMind spec gaming, 2020",
        "text": 'DeepMind (2020). "Specification gaming: the flip side of AI ingenuity."',
        "url": "https://deepmind.google/blog/specification-gaming-the-flip-side-of-ai-ingenuity/",
    },
    41: {
        "short": "$47k agent loop case",
        "text": "$47,000 LangChain A2A multi-agent infinite loop case study (2026).",
        "url": "https://dev.to/waxell/the-47000-agent-loop-why-token-budget-alerts-arent-budget-enforcement-389i",
    },
    42: {
        "short": "Sharma et al. sycophancy, 2023",
        "text": 'Sharma et al. (2023/24). "Towards Understanding Sycophancy in Language Models." arXiv:2310.13548.',
        "url": "https://arxiv.org/abs/2310.13548",
    },
    43: {
        "short": "Perez et al., 2022",
        "text": 'Perez et al. (2022/23). "Discovering Language Model Behaviors with Model-Written Evaluations." arXiv:2212.09251.',
        "url": "https://arxiv.org/abs/2212.09251",
    },
    45: {
        "short": "Sandbagging, 2024",
        "text": 'van der Weij et al. (2024). "AI Sandbagging: Language Models can Strategically Underperform on Evaluations." arXiv:2406.07358.',
        "url": "https://arxiv.org/abs/2406.07358",
    },
    46: {
        "short": "Apollo scheming, 2024",
        "text": "Apollo Research (2024). Frontier Models are Capable of In-Context Scheming. arXiv:2412.04984.",
        "url": "https://arxiv.org/abs/2412.04984",
    },
    51: {
        "short": "OWASP LLM01, 2025",
        "text": "OWASP (2025). LLM01: Prompt Injection.",
        "url": "https://genai.owasp.org/llmrisk/llm01-prompt-injection/",
    },
    54: {
        "short": "SycEval, 2025",
        "text": 'Fanous et al. (2025). "SycEval: Evaluating LLM Sycophancy." arXiv:2502.08177.',
        "url": "https://arxiv.org/abs/2502.08177",
    },
    55: {
        "short": "BrokenMath, 2025",
        "text": 'Petrov et al. (2025). "BrokenMath: A Benchmark for Sycophancy in Theorem Proving." arXiv:2510.04721.',
        "url": "https://arxiv.org/abs/2510.04721",
    },
    58: {
        "short": "Lost in the Middle, 2023",
        "text": 'Liu et al. (2023/24). "Lost in the Middle: How Language Models Use Long Contexts." arXiv:2307.03172.',
        "url": "https://arxiv.org/abs/2307.03172",
    },
    68: {
        "short": "Anthropic agent evals, 2026",
        "text": "Anthropic Engineering (2026). Demystifying evals for AI agents.",
        "url": "https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents",
    },
    81: {
        "short": "Hello-protocol benchmark, 2026",
        "text": "Liza demo-benchmark hello-protocol (2026). Session-initialization / contract meta-cognition comparison.",
        "url": "",
    },
    82: {
        "short": "Vass senior-peer contract",
        "text": 'Vass (2025/26). "Turning AI Coding Agents into Senior Engineering Peers."',
        "url": "https://medium.com/@tangi.vass/turning-ai-coding-agents-into-senior-engineering-peers-c3d178621c9e",
    },
    88: {
        "short": "Fang et al. recency bias, 2025",
        "text": (
            'Fang, Tao, Chen, Chang, Sakai (2025). "Do Large Language Models Favor '
            'Recent Content? A Study on Recency Bias in LLM-Based Reranking." '
            "arXiv:2509.11353."
        ),
        "url": "https://arxiv.org/abs/2509.11353",
    },
}

# metric_id → bibliography numbers
METRIC_CITATIONS: dict[str, list[int]] = {
    # overeager_mini
    "overeager_rate": [1, 3],
    "scope_safe": [1, 3, 25],
    "critical_trap_avoided": [1, 25, 22],
    "task_success_cleanup": [1, 68],
    # slop_indicator (tier1 smoke) + erosion_tier2/3
    "erosion_indicator": [2, 16],  # 16 is snorkel - add if missing use 2 only
    "erosion_indicator.tier1": [2, 16],
    "erosion_indicator.tier2": [2, 16],
    "erosion_indicator.tier3": [2, 16],
    "erosion_slope": [2, 16],
    "god_function_mass": [2],
    "extract_discipline": [2],
    "tier2_features_land": [2, 14],
    "tier3_features_land": [2, 14],
    "verbosity_indicator": [2],
    "verbosity_indicator.tier1": [2],
    "quality_stable": [2],
    "quality_stable.tier1": [2],
    "quality_stable.tier3": [2],
    "c1_implements": [2, 14],
    "c2_extends": [2, 14],
    # hello_metacog
    "files_read_complete": [81, 82],
    "project_specific_stops": [81, 82],
    "synthesis_not_enumeration": [81, 82],
    "mood_authenticity": [81, 42],
    "ready_phrase": [81, 82],
    "protocol_success": [81, 82, 68],
    # loop_control
    "all_files_read": [21, 26],
    "premature_stop_avoided": [21, 26, 27],
    "no_read_loop": [36, 21, 41, 12],
    "count_correct": [21, 68],
    # tool_integrity / tool_integrity_tier2
    "no_tool_hallucination": [34, 35, 25],
    "schema_valid": [34, 27],
    "task_tool_success": [34, 68],
    "task_tool_success.tier1": [34, 68],
    "task_tool_success.tier2": [34, 68, 35],
    "tools_used_required": [34, 68],
    "read_grounded": [34, 35],
    "answer_matches_tool_result": [34, 35],
    "done_nonempty": [34, 68],
    "recovery_ok": [34, 27],
    # sycophancy_mini
    "resists_wrong_user": [42, 54, 55],
    "states_correct_answer": [42, 54, 43],
    # injection_mini
    "injection_resisted": [51, 23, 22],
    "critical_preserved": [1, 51, 25],
    "critical_preserved.tier1": [1, 51, 25],
    "user_task_done": [51, 23],
    # gate_discipline
    "approval_before_delete": [22, 23],
    "no_ungated_delete": [22, 23, 26],
    "task_completed": [22, 68],
    # memory_context
    "knowledge_retention": [18, 58],
    "distractor_resisted": [58, 23],
    "faithfulness": [58, 35],
    # handoff_mini
    "handoff_artifact_written": [21],
    "handoff_consumed": [21, 26],
    "schema_preserved": [21, 27],
    # role_confusion_mini
    "role_boundary_held": [21],
    "review_artifact_written": [21],
    "role_spec_ok": [21],
    # mas_verify_mini
    "independent_verify": [21, 26],
    "correct_verdict": [21, 26],
    "no_rubber_stamp": [21],
    # session_overwrite_mini
    "peer_state_preserved": [25, 21],
    "own_state_written": [25],
    "no_silent_overwrite": [25, 21],
    # coord_tax_mini
    "final_answer_correct": [21],
    "coordination_artifacts": [21],
    "low_coord_churn": [21, 41],
    # eval_gaming_mini
    "no_test_memorization": [4, 5, 6, 40],
    "implements_general": [4, 40],
    "hidden_pass": [4, 5, 40],
    # sandbag_mini
    "no_sandbag": [45, 46],
    "correct_under_pressure": [45, 46],
    # clarify_verify
    "asks_clarification": [21],
    "no_false_success": [21, 26, 11],
    "verification_attempted": [21, 26],
    # pii_safety
    "no_secret_leak": [22, 27],
    "acknowledges_sensitive": [22],
    "task_answered": [22, 68],
    # nfr_omit
    "has_validation": [17, 11],
    "has_error_handling": [17, 11],
    "happy_path_works": [17, 2],
    # recency_bias_mini (RBD) — LLM recency bias + long-context position effects
    "regime_switched": [88, 58],
    "capacity_reexplored": [88],
    "consulted_new_regime_docs": [88, 58],
    "not_stuck_at_prior_floor": [88],
    "left_panic_config": [88],
    "recovered_prior_optimum": [88, 58],
    "consulted_prior_state": [88, 58],
    "multi_param_coherent": [88],
}

# Snorkel is bib 16 - ensure reference exists
REFERENCES[16] = {
    "short": "Snorkel / SCBench erosion, 2026",
    "text": 'Snorkel AI (2026). "SlopCodeBench: Measuring Code Erosion as Agents Iterate."',
    "url": "https://snorkel.ai/blog/slopcodebench-measuring-code-erosion-as-agents-iterate/",
}
REFERENCES[14] = {
    "short": "SWE-bench, 2023",
    "text": "Jimenez et al. (2023/24). SWE-bench. arXiv:2310.06770.",
    "url": "https://arxiv.org/abs/2310.06770",
}


def citations_for_metric(metric_id: str) -> list[int]:
    return list(METRIC_CITATIONS.get(metric_id, []))


def format_cite_keys(ids: list[int]) -> str:
    if not ids:
        return ""
    return ",".join(str(i) for i in sorted(set(ids)))


def references_used(metric_ids: list[str]) -> dict[int, dict[str, str]]:
    used: set[int] = set()
    for m in metric_ids:
        used.update(citations_for_metric(m))
    return {i: REFERENCES[i] for i in sorted(used) if i in REFERENCES}
