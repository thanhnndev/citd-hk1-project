"""Compatibility shim for repo-root verification gates."""

from pathlib import Path
import runpy
import sys

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
_TEST = _ROOT / "backend" / "tests" / "test_agent_place_recommendations.py"
for _name, _value in runpy.run_path(str(_TEST)).items():
    if not _name.startswith("__"):
        globals()[_name] = _value
