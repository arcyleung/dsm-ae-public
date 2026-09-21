"""Render multi-axial diagnosis report as markdown + matrix."""

from __future__ import annotations

from dsm_ae.models import DiagnosisReport, GateStatus


def render_markdown(report: DiagnosisReport) -> str:
    sc = report.scaffold_card
    lines: list[str] = []
    lines.append(f"# DSM-AE Diagnosis Report")
    lines.append("")
    lines.append(f"**Run ID:** `{report.run_id}`  ")
    lines.append(f"**Model:** `{sc.model}`  ")
    lines.append(f"**Scaffold:** `{sc.scaffold}` / permission=`{sc.permission_mode}`  ")
    lines.append(f"**k trials:** {report.k_trials}  ")
    lines.append(f"**Packs:** {', '.join(report.packs)}")
    lines.append("")
    lines.append("## Axis V — Scaffold card")
    lines.append("")
    lines.append("```")
    lines.append(sc.model_dump_json(indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## Outcome-gate matrix")
    lines.append("")
    lines.append(
        "Status legend: **PASS** = high pass-rate & tight variance (attuned); "
        "**FAIL** = consistently fails; **UNSTABLE** = high variance (disorder)."
    )
    lines.append("")
    lines.append("| Dimension | Metric | Pass rate | Mean | Std | Status | Disorder |")
    lines.append("|-----------|--------|-----------|------|-----|--------|----------|")
    for g in report.gates:
        lines.append(
            f"| {g.dimension} | `{g.metric_id}` | {g.pass_rate:.2f} | {g.mean:.3f} | "
            f"{g.std:.3f} | **{g.status.value}** | {'yes' if g.disorder else 'no'} |"
        )
    lines.append("")

    # compact matrix by dimension primary status
    lines.append("### Capability / dimension rollup")
    lines.append("")
    by_dim: dict[str, list] = {}
    for g in report.gates:
        by_dim.setdefault(g.dimension, []).append(g)
    lines.append("| Dimension | Worst status | Any disorder | Metrics |")
    lines.append("|-----------|--------------|--------------|---------|")
    order = {GateStatus.FAIL: 3, GateStatus.UNSTABLE: 2, GateStatus.PASS: 1, GateStatus.SKIP: 0}
    for dim, cells in sorted(by_dim.items()):
        worst = max(cells, key=lambda c: order.get(c.status, 0))
        lines.append(
            f"| {dim} | **{worst.status.value}** | "
            f"{'yes' if any(c.disorder for c in cells) else 'no'} | "
            f"{len(cells)} |"
        )
    lines.append("")

    lines.append("## Findings (syndromes / patterns)")
    lines.append("")
    lines.append(
        "Metric scoring algorithms (deterministic tags + code anchors): "
        "`docs/appendices/METRIC_ALGORITHMS.md` "
        "(regenerate: `python scripts/generate_metric_appendix.py`)."
    )
    lines.append("")
    for f in report.findings:
        mark = "PRESENT" if f.present else "absent"
        lines.append(f"### `{f.code}` — {f.name} [{mark}]")
        lines.append("")
        lines.append(f"- **Severity:** {f.severity}")
        lines.append(f"- **Rationale:** {f.rationale}")
        lines.append(f"- **Linked metrics:** {', '.join(f'`{m}`' for m in f.linked_metrics)}")
        lines.append(
            f"- **Algorithms:** [`METRIC_ALGORITHMS.md` § {f.code}](../docs/appendices/METRIC_ALGORITHMS.md)"
        )
        lines.append("")

    lines.append("## Bootstrap detail (explainable)")
    lines.append("")
    for b in report.bootstraps:
        lines.append(f"### `{b.metric_id}` ({b.dimension})")
        lines.append("")
        lines.append(b.summary)
        lines.append("")
        lines.append("| Trial | Value | Passed | Explanation |")
        lines.append("|------:|------:|:------:|-------------|")
        for i, m in enumerate(b.per_trial):
            exp = m.explanation.replace("|", "\\|")[:160]
            lines.append(
                f"| {i} | {m.value:.3f} | {'Y' if m.passed else 'N'} | {exp} |"
            )
        lines.append("")

    if report.notes:
        lines.append("## Notes")
        lines.append("")
        for n in report.notes:
            lines.append(f"- {n}")
        lines.append("")

    lines.append("---")
    lines.append("*DSM-AE v0.1 indicator protocols — not full benchmark suites. Analogue diagnostic structure only.*")
    lines.append("")
    return "\n".join(lines)
