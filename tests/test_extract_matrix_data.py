"""Extractor turns dsm-ae-matrix.html into Vue payload."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parents[1] / "web" / "scripts" / "extract_matrix_data.py"
_spec = importlib.util.spec_from_file_location("extract_matrix_data", _MOD)
assert _spec and _spec.loader
ext = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ext)

HTML = Path(__file__).resolve().parents[1] / "reports" / "dsm-ae-matrix.html"


def test_extract_has_three_sections() -> None:
    if not HTML.is_file():
        return
    data = ext.extract(HTML)
    assert len(data["models"]) >= 2
    assert data["syndromes"]
    assert data["metrics"]
    assert data["trees"]
    assert data["syndromes"][0]["cells"]
    assert any(t["mermaid"].startswith("flowchart") for t in data["trees"])
