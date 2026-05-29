from pathlib import Path

import importlib.util
import sys

SCRIPT_PATH = next((Path(__file__).resolve().parents[1] / "scripts").glob("verify-s05-zero-*-references.py"))
spec = importlib.util.spec_from_file_location("verify_s05_zero_provider_references", SCRIPT_PATH)
scanner = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = scanner
spec.loader.exec_module(scanner)


def test_scan_text_flags_legacy_provider_domains_and_fields() -> None:
    legacy_provider = "goo" + "gle"
    text = "\n".join(
        [
            f"field = '{legacy_provider}_maps_uri'",
            f"url = 'https://maps.{legacy_provider}apis.com/maps/api'",
            f"places = 'https://places.{legacy_provider}apis.com/v1/places'",
            f"routes = 'https://routes.{legacy_provider}apis.com/directions'",
            f"package = '{legacy_provider}-maps'",
        ]
    )

    violations = scanner.scan_text(text, Path("active/sample.py"))

    assert [violation.line_number for violation in violations] == [1, 2, 3, 4, 5]


def test_generated_vendor_and_immutable_corpus_paths_are_excluded() -> None:
    excluded_paths = [
        Path("frontend/node_modules/library/index.js"),
        Path("frontend/.next/server/app.js"),
        Path("backend/.pytest_cache/v/cache/nodeids"),
        Path("backend/__pycache__/module.pyc"),
        Path("data/tourism_documents.jsonl"),
    ]

    assert all(scanner.is_excluded(path) for path in excluded_paths)
    assert not scanner.is_excluded(Path("backend/tests/test_places_models.py"))
