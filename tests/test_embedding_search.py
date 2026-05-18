"""Compatibility entrypoint for embedding search tests.

The canonical tests live under backend/tests because they import backend app
modules directly. This wrapper keeps repository-root pytest invocations aligned
with the backend test path used by the GSD verification gate.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

_ROOT_DIR = Path(__file__).resolve().parents[1]
_BACKEND_DIR = _ROOT_DIR / "backend"
_TEST_FILE = _BACKEND_DIR / "tests" / "test_embedding_search.py"

if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_spec = spec_from_file_location("backend_embedding_search_tests", _TEST_FILE)
if _spec is None or _spec.loader is None:
    raise ImportError(f"Unable to load {_TEST_FILE}")

_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name, _value in vars(_module).items():
    if _name.startswith("test_") or _name.startswith("Test"):
        globals()[_name] = _value
