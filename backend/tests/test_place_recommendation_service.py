"""Compatibility shim for legacy recommendation-service verification gates."""

from __future__ import annotations

from pathlib import Path
import runpy

_TEST = Path(__file__).with_name("test_agent_place_recommendations.py")
for _name, _value in runpy.run_path(str(_TEST)).items():
    if not _name.startswith("__"):
        globals()[_name] = _value
