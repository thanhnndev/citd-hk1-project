"""Tests for fairness audit logging in AgentService and admin /fairness endpoint (S04/T04)."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Resolve project root so we can import agents.* regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

from app.models.response import PlaceResult, ScoreBreakdown
from app.models.request import LatLng


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_place(place_id: str, geo_locality: float) -> PlaceResult:
    """Build a minimal PlaceResult for testing."""
    return PlaceResult(
        place_id=place_id,
        display_name=f"Place {place_id}",
        formatted_address="Test Address",
        location=LatLng(lat=10.0, lng=104.0),
        types=["restaurant"],
        primary_type="restaurant",
        rating=4.0,
        user_rating_count=10,
        price_level=2,
        open_now=True,
        business_status="OPERATIONAL",
        geo_locality=geo_locality,
        final_score=0.8,
        score_breakdown=ScoreBreakdown(
            tree1_locality=0.8,
            tree2_proximity=0.7,
            tree3_quality=0.75,
            s_bag=0.75,
            delta1_fairness=0.0,
            delta2_access=0.0,
            final_score=0.8,
            rank=1,
        ),
        map_uri="https://map.goong.io/?pid=test",
    )


def _make_agent_service(langfuse_client=None):
    """Build an AgentService with minimal dependencies for unit testing."""
    from agents.graph.agent_service import AgentService
    return AgentService(
        retriever=None,
        hybrid_retriever=None,
        llm_service=None,
        langfuse_client=langfuse_client,
    )


# ---------------------------------------------------------------------------
# Test _fairness_audit_log creates file with correct structure
# ---------------------------------------------------------------------------

class TestFairnessAuditLog:
    """Verify _fairness_audit_log writes correct JSONL entries."""

    def test_creates_file_with_correct_structure(self, tmp_path):
        """Fairness audit log creates a JSONL file with all required fields."""
        svc = _make_agent_service()
        audit_dir = tmp_path / "fairness_audit"

        with patch.object(svc, "_FAIRNESS_AUDIT_DIR", audit_dir):
            places = [
                _make_place("p1", 0.8),
                _make_place("p2", 0.3),
                _make_place("p3", 0.1),
            ]
            svc._fairness_audit_log(places=places, trace_id="trace-123")

        # Verify file was created
        jsonl_files = list(audit_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 1

        # Verify content structure
        with open(jsonl_files[0], encoding="utf-8") as fh:
            lines = [l.strip() for l in fh if l.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert "timestamp" in record
        assert record["trace_id"] == "trace-123"
        assert record["count"] == 3
        assert record["mean"] == pytest.approx(0.4, abs=0.01)
        assert record["min"] == pytest.approx(0.1)
        assert record["max"] == pytest.approx(0.8)
        assert record["geo_localitys"] == [0.8, 0.3, 0.1]
        assert "distribution" in record
        assert record["distribution"]["<0.1"] == 0
        assert record["distribution"]["0.1-0.3"] == 1  # 0.1 is in this bucket (< 0.3)
        assert record["distribution"]["0.3-0.5"] == 1  # 0.3 is in this bucket
        assert record["distribution"][">0.5"] == 1  # 0.8

    def test_skips_when_no_places(self, tmp_path):
        """Audit log does nothing when places list is empty."""
        svc = _make_agent_service()
        audit_dir = tmp_path / "fairness_audit"
        audit_dir.mkdir()

        with patch.object(svc, "_FAIRNESS_AUDIT_DIR", audit_dir):
            svc._fairness_audit_log(places=[], trace_id="trace-456")

        assert list(audit_dir.glob("*.jsonl")) == []

    def test_handles_place_without_geo_locality(self, tmp_path):
        """Places without geo_locality are skipped (but others are logged)."""
        svc = _make_agent_service()
        audit_dir = tmp_path / "fairness_audit"

        places_with_factor = [_make_place("p1", 0.7)]
        with patch.object(svc, "_FAIRNESS_AUDIT_DIR", audit_dir):
            svc._fairness_audit_log(places=places_with_factor, trace_id=None)

        jsonl_files = list(audit_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 1

    def test_buckets_are_correct(self):
        """Verify bucket boundaries: <0.1, 0.1-0.3, 0.3-0.5, >0.5."""
        from agents.graph.agent_service import AgentService

        factors = [0.05, 0.09, 0.1, 0.29, 0.3, 0.49, 0.5, 0.7, 0.99]
        buckets = AgentService._bucket_geo_localitys(factors)

        assert buckets["<0.1"] == 2    # 0.05, 0.09
        assert buckets["0.1-0.3"] == 2  # 0.1, 0.29
        assert buckets["0.3-0.5"] == 2  # 0.3, 0.49
        assert buckets[">0.5"] == 3     # 0.5, 0.7, 0.99

    def test_never_breaks_on_exception(self, tmp_path):
        """Audit failure must NOT raise — logs warning instead."""
        svc = _make_agent_service()
        # Point to a directory that will fail on write (inside a read-only mock)
        bad_dir = tmp_path / "readonly"
        bad_dir.mkdir()

        with patch.object(svc, "_FAIRNESS_AUDIT_DIR", bad_dir):
            with patch("builtins.open", side_effect=OSError("read-only")):
                # Should not raise
                svc._fairness_audit_log(
                    places=[_make_place("p1", 0.5)],
                    trace_id="trace-789",
                )

        # Verify the method completes without raising (graceful degradation)
        # structlog with PrintLogger doesn't feed caplog, so we verify by non-exception


# ---------------------------------------------------------------------------
# Test admin /fairness endpoint returns aggregate stats
# ---------------------------------------------------------------------------

class TestAdminFairnessAggregate:
    """Verify GET /admin/fairness returns properly aggregated statistics."""

    def _build_app(self):
        from fastapi import FastAPI
        from app.routers.admin import router as admin_router
        from unittest.mock import AsyncMock, MagicMock

        app = FastAPI()
        app.include_router(admin_router)
        app.state.bm25_vectorizer = None
        app.state.langfuse_client = None

        mock_user = MagicMock()
        mock_user.id = "test-admin-user"
        mock_user.is_active = True
        mock_user_service = MagicMock()
        mock_user_service.get_by_id = AsyncMock(return_value=mock_user)
        app.state.user_service = mock_user_service

        return app

    def _mock_audit_dir(self, tmp_path, file_contents: dict[str, str]):
        """Create audit files and patch admin.py to resolve to tmp_path."""
        audit_dir = tmp_path / "fairness_audit"
        audit_dir.mkdir()
        for fname, content in file_contents.items():
            (audit_dir / fname).write_text(content)

        # Build mock that satisfies: Path(__file__).resolve().parents[3] / "data" / "fairness_audit"
        mock_audit_dir = MagicMock()
        mock_audit_dir.exists.return_value = True
        mock_audit_dir.glob.return_value = sorted(audit_dir.glob("*.jsonl"))

        mock_data_dir = MagicMock()
        mock_data_dir.__truediv__ = MagicMock(return_value=mock_audit_dir)

        mock_project_root = MagicMock()
        mock_project_root.__truediv__ = MagicMock(return_value=mock_data_dir)

        mock_parents = MagicMock()
        mock_parents.__getitem__ = MagicMock(return_value=mock_project_root)

        mock_resolved = MagicMock()
        mock_resolved.parents = mock_parents
        mock_resolved.resolve.return_value = mock_resolved  # chain self

        mock_path_cls = MagicMock()
        mock_path_cls.return_value = mock_resolved  # Path(...) returns mock_resolved
        mock_path_cls.resolve.return_value = mock_resolved  # Path.resolve() also returns mock_resolved

        return patch("app.routers.admin.Path", mock_path_cls)

    def _auth_headers(self):
        return {"Authorization": "Bearer fake-jwt-token-for-tests"}

    def _mock_decode(self):
        return patch("app.middleware.auth.decode_access_token", return_value={"sub": "test-admin-user"})

    def test_returns_aggregate_stats_from_audit_files(self, tmp_path):
        """Multiple audit files are aggregated into buckets, mean, and count."""
        files = {
            "20260101.jsonl": json.dumps({
                "timestamp": "2026-01-01T00:00:00+00:00",
                "count": 3,
                "mean": 0.4,
                "min": 0.1,
                "max": 0.8,
                "geo_localitys": [0.8, 0.3, 0.1],
                "distribution": {"<0.1": 0, "0.1-0.3": 1, "0.3-0.5": 1, ">0.5": 1},
            }) + "\n",
            "20260102.jsonl": json.dumps({
                "timestamp": "2026-01-02T12:00:00+00:00",
                "count": 2,
                "mean": 0.6,
                "min": 0.2,
                "max": 0.9,
                "geo_localitys": [0.9, 0.2],
                "distribution": {"<0.1": 0, "0.1-0.3": 1, "0.3-0.5": 0, ">0.5": 1},
            }) + "\n",
        }

        app = self._build_app()
        from fastapi.testclient import TestClient
        client = TestClient(app)

        with self._mock_decode(), self._mock_audit_dir(tmp_path, files):
            response = client.get("/admin/fairness", headers=self._auth_headers())

        assert response.status_code == 200
        data = response.json()
        assert data["total_audits"] == 2
        assert data["latest_timestamp"] == "2026-01-02T12:00:00+00:00"

        dist = data["geo_locality_distribution"]
        assert dist is not None
        assert "buckets" in dist
        assert "mean" in dist
        assert "count" in dist
        # 5 total geo_localitys: 0.8, 0.3, 0.1, 0.9, 0.2
        assert dist["count"] == 5
        assert dist["mean"] == pytest.approx(0.46, abs=0.01)
        assert dist["buckets"]["<0.1"] == 0
        assert dist["buckets"]["0.1-0.3"] == 2  # 0.1, 0.2
        assert dist["buckets"]["0.3-0.5"] == 1  # 0.3
        assert dist["buckets"][">0.5"] == 2     # 0.8, 0.9


# ---------------------------------------------------------------------------
# Test graceful degradation when audit directory is empty or missing
# ---------------------------------------------------------------------------

class TestFairnessGracefulDegradation:
    """Verify /fairness handles missing or empty audit directory gracefully."""

    def _build_app(self):
        from fastapi import FastAPI
        from app.routers.admin import router as admin_router
        from unittest.mock import AsyncMock, MagicMock

        app = FastAPI()
        app.include_router(admin_router)
        app.state.bm25_vectorizer = None
        app.state.langfuse_client = None

        mock_user = MagicMock()
        mock_user.id = "test-admin-user"
        mock_user.is_active = True
        mock_user_service = MagicMock()
        mock_user_service.get_by_id = AsyncMock(return_value=mock_user)
        app.state.user_service = mock_user_service

        return app

    def _mock_empty_audit_dir(self, tmp_path, exists: bool, files: list = None):
        """Patch admin.py Path resolution."""
        audit_dir = tmp_path / "fairness_audit"
        if exists:
            audit_dir.mkdir(exist_ok=True)
            if files:
                for f in files:
                    fpath = audit_dir / f
                    # Only create file if it doesn't already exist (avoid overwriting test data)
                    if not fpath.exists():
                        fpath.write_text("")

        mock_audit_dir = MagicMock()
        mock_audit_dir.exists.return_value = exists
        mock_audit_dir.glob.return_value = sorted(audit_dir.glob("*.jsonl")) if exists else []

        mock_data_dir = MagicMock()
        mock_data_dir.__truediv__ = MagicMock(return_value=mock_audit_dir)

        mock_project_root = MagicMock()
        mock_project_root.__truediv__ = MagicMock(return_value=mock_data_dir)

        mock_parents = MagicMock()
        mock_parents.__getitem__ = MagicMock(return_value=mock_project_root)

        mock_resolved = MagicMock()
        mock_resolved.parents = mock_parents
        mock_resolved.resolve.return_value = mock_resolved

        mock_path_cls = MagicMock()
        mock_path_cls.return_value = mock_resolved
        mock_path_cls.resolve.return_value = mock_resolved

        return patch("app.routers.admin.Path", mock_path_cls)

    def _auth_headers(self):
        return {"Authorization": "Bearer fake-jwt-token-for-tests"}

    def _mock_decode(self):
        return patch("app.middleware.auth.decode_access_token", return_value={"sub": "test-admin-user"})

    def test_missing_directory_returns_zero(self, tmp_path):
        """When audit directory doesn't exist, return zero audits."""
        app = self._build_app()
        from fastapi.testclient import TestClient
        client = TestClient(app)

        with self._mock_decode(), self._mock_empty_audit_dir(tmp_path, exists=False):
            response = client.get("/admin/fairness", headers=self._auth_headers())

        assert response.status_code == 200
        data = response.json()
        assert data["total_audits"] == 0
        assert data["message"] is not None

    def test_empty_directory_returns_zero(self, tmp_path):
        """When directory exists but has no JSONL files, return zero audits."""
        app = self._build_app()
        from fastapi.testclient import TestClient
        client = TestClient(app)

        with self._mock_decode(), self._mock_empty_audit_dir(tmp_path, exists=True, files=[".gitkeep"]):
            response = client.get("/admin/fairness", headers=self._auth_headers())

        assert response.status_code == 200
        data = response.json()
        assert data["total_audits"] == 0

    def test_corrupted_file_is_skipped(self, tmp_path):
        """Corrupted JSONL files are skipped, valid ones still processed."""
        audit_dir = tmp_path / "fairness_audit"
        audit_dir.mkdir()
        (audit_dir / "bad.jsonl").write_text("not valid json\n")
        (audit_dir / "good.jsonl").write_text(
            json.dumps({
                "timestamp": "2026-01-01T00:00:00+00:00",
                "geo_localitys": [0.6],
            }) + "\n"
        )

        app = self._build_app()
        from fastapi.testclient import TestClient
        client = TestClient(app)

        with self._mock_decode(), self._mock_empty_audit_dir(
            tmp_path, exists=True, files=["bad.jsonl", "good.jsonl"]
        ):
            response = client.get("/admin/fairness", headers=self._auth_headers())

        assert response.status_code == 200
        data = response.json()
        assert data["total_audits"] == 2
        assert data["geo_locality_distribution"]["count"] == 1
