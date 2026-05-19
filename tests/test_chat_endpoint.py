"""Compatibility shim for repo-root verification gates."""

from pathlib import Path
import os
import runpy
import sys

# Mirror backend/tests/conftest.py for repo-root compatibility gates.
os.environ["OPENAI_API_KEY"] = "fake-test-key"
os.environ["GOOGLE_PLACES_API_KEY"] = ""
os.environ["GOOGLE_ROUTES_API_KEY"] = ""

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "backend"))
_TEST = _ROOT / "backend" / "tests" / "test_chat_endpoint.py"
for _name, _value in runpy.run_path(str(_TEST)).items():
    if not _name.startswith("__"):
        globals()[_name] = _value
