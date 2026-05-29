from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify-goong-live.py"


def run_verifier(goong_key: str | None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "openai-not-used-by-goong-verifier")
    if goong_key is None:
        env.pop("GOONG_API_KEY", None)
    else:
        env["GOONG_API_KEY"] = goong_key
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )


def test_missing_key_returns_credential_blocked() -> None:
    result = run_verifier(None)

    assert result.returncode == 0
    assert "CONFIG=" in result.stdout
    assert "RESULT=credential_blocked" in result.stdout
    assert "goong_api_key_status" in result.stdout


def test_fake_key_returns_credential_blocked_without_leaking_key() -> None:
    fake_key = "fake-super-secret-goong-key"
    result = run_verifier(fake_key)

    assert result.returncode == 0
    assert "RESULT=credential_blocked" in result.stdout
    assert fake_key not in result.stdout
    assert fake_key not in result.stderr


def test_placeholder_key_returns_credential_blocked_without_leaking_key() -> None:
    placeholder_key = "<replace_me_goong_key>"
    result = run_verifier(placeholder_key)

    assert result.returncode == 0
    assert "RESULT=credential_blocked" in result.stdout
    assert placeholder_key not in result.stdout
    assert placeholder_key not in result.stderr


def test_verifier_uses_goong_api_key_not_stale_google_keys() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "GOONG_API_KEY" in source
    assert "GOOGLE_PLACES_API_KEY" not in source
    assert "GOOGLE_ROUTES_API_KEY" not in source


def test_sanitized_output_has_expected_phase_labels_for_blocked_key() -> None:
    leaked_key = "test-do-not-print-this-goong-key"
    result = run_verifier(leaked_key)

    assert result.returncode == 0
    assert "CONFIG=" in result.stdout
    assert "RESULT=" in result.stdout
    assert "PLACES_RESPONSE=" not in result.stdout
    assert "ROUTES_RESPONSE=" not in result.stdout
    assert leaked_key not in result.stdout + result.stderr
