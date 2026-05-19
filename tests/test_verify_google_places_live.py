from __future__ import annotations

import os
import subprocess
import sys


def run_verifier(key: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GOOGLE_PLACES_API_KEY"] = key
    return subprocess.run(
        [sys.executable, "scripts/verify-google-places-live.py"],
        check=False,
        cwd=os.getcwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
    )


def test_google_places_live_verifier_blank_key_is_credential_blocked() -> None:
    result = run_verifier("")

    assert result.returncode == 0
    assert "google_places_api_key_status\": \"missing" in result.stdout
    assert "RESULT=credential_blocked" in result.stdout


def test_google_places_live_verifier_fake_key_is_redacted() -> None:
    fake_key = "fake-secret-do-not-print"
    result = run_verifier(fake_key)

    assert result.returncode == 0
    assert "google_places_api_key_status\": \"fake" in result.stdout
    assert "RESULT=credential_blocked" in result.stdout
    assert fake_key not in result.stdout
    assert fake_key not in result.stderr
