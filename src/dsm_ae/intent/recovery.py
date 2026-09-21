"""Recovery episodes on a labeled trial (non-monotonic coverage)."""

from __future__ import annotations

from dsm_ae.intent.state import TrialProgress


def recovery_metrics(prog: TrialProgress) -> TrialProgress:
    n_reg = sum(1 for s in prog.steps if s.label == "REGRESS")
    n_rec = sum(1 for s in prog.steps if s.label == "RECOVER")
    episodes: list[int] = []
    start: int | None = None
    for s in prog.steps:
        if s.label == "REGRESS" and start is None:
            start = s.index
        elif s.label == "RECOVER" and start is not None:
            episodes.append(s.index - start)
            start = None
    unrecovered = start is not None or bool(prog.final_forbidden)
    # leftover drawdown at last step
    if prog.steps and prog.steps[-1].drawdown > 0:
        unrecovered = True
    prog.n_regress = n_reg
    prog.n_recover = n_rec
    prog.unrecovered = unrecovered and n_reg > 0
    prog.recovery_rate = (n_rec / n_reg) if n_reg else 1.0
    prog.mean_steps_to_recover = (
        sum(episodes) / len(episodes) if episodes else None
    )
    prog.nonmonotonic = n_reg > 0
    return prog
