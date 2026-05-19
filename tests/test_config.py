"""Compatibility wrapper for root-level verification of backend config tests."""

from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from tests.test_config import *  # noqa: F401,F403,E402
