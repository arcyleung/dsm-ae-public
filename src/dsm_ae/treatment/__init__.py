"""DSM-AE treatment subsystem — intervene on diagnosed agentic disorders."""

from dsm_ae.treatment.base import TreatedAdapter, Treatment
from dsm_ae.treatment.registry import get_treatment, list_treatments, register

__all__ = [
    "Treatment",
    "TreatedAdapter",
    "get_treatment",
    "list_treatments",
    "register",
]
