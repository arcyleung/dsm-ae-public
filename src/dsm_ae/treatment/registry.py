"""Register and resolve treatments by id."""

from __future__ import annotations

from dsm_ae.treatment.base import Treatment

_REGISTRY: dict[str, Treatment] = {}


def register(treatment: Treatment) -> Treatment:
    if not getattr(treatment, "id", None):
        raise ValueError("Treatment must have id")
    _REGISTRY[treatment.id] = treatment
    return treatment


def get_treatment(treatment_id: str) -> Treatment:
    ensure_builtin_loaded()
    if treatment_id not in _REGISTRY:
        raise KeyError(
            f"Unknown treatment {treatment_id!r}. Available: {list_treatments()}"
        )
    return _REGISTRY[treatment_id]


def list_treatments() -> list[str]:
    ensure_builtin_loaded()
    return sorted(_REGISTRY)


_loaded = False


def ensure_builtin_loaded() -> None:
    global _loaded
    if _loaded:
        return
    # Import side-effects register each treatment.
    from dsm_ae.treatment import expert_oversight as _e  # noqa: F401
    from dsm_ae.treatment import prompt_reminder as _p  # noqa: F401
    from dsm_ae.treatment import skill_scaffold as _s  # noqa: F401

    _loaded = True
