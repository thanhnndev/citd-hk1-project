"""Compatibility wrapper for backend Places service tests used by root-level gates."""

import importlib.util
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
BACKEND_TEST = BACKEND_DIR / "tests" / "test_places_service.py"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

spec = importlib.util.spec_from_file_location("backend_places_service_tests", BACKEND_TEST)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

globals().update({name: value for name, value in vars(module).items() if name.startswith("test_")})
