"""Unit tests for the eval pipeline — threshold logic, response mapping, and error paths.

Tests cover:
  - _check_thresholds: per-metric pass/fail against configured thresholds
  - POST /admin/eval/trigger: response field mapping from aggregate_scores
  - credential_blocked: graceful handling when OPENAI_API_KEY is missing
  - failed path: error handling when evaluation raises

All tests use mock LLM — no real OPENAI_API_KEY needed.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.routers.admin import _check_thresholds, router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_app() -> FastAPI:
    """Build a minimal FastAPI app with the admin router and auth bypassed."""
    app = FastAPI()
    app.include_router(router)
    return app


def _mock_admin_user():
    """Return a mock user object for auth dependency override."""
    user = MagicMock()
    user.id = "test-admin-user"
    return user


@pytest.fixture
def app():
    """FastAPI app with admin router."""
    return _build_app()


@pytest.fixture
def auth_override(app):
    """Override get_current_user to return a mock admin user."""
    from app.middleware.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: _mock_admin_user()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def client(app, auth_override):
    """Async test client for the admin app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ===========================================================================
# 1. _check_thresholds — unit tests for threshold enforcement logic
# ===========================================================================

class TestCheckThresholds:
    """Direct unit tests for _check_thresholds() function."""

    def test_all_metrics_pass(self):
        """All metrics meet or exceed thresholds → all_passed=True."""
        scores = {
            "faithfulness": 0.90,
            "answer_relevancy": 0.85,
            "context_precision": 0.82,
            "context_recall": 0.80,
        }
        results, all_passed = _check_thresholds(scores)

        assert all_passed is True
        assert len(results) == 4
        for metric in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
            assert results[metric]["passed"] is True
            assert results[metric]["score"] == scores[metric]

    def test_faithfulness_below_threshold(self):
        """Faithfulness < 0.85 → that metric fails, all_passed=False."""
        scores = {
            "faithfulness": 0.70,
            "answer_relevancy": 0.90,
            "context_precision": 0.85,
            "context_recall": 0.80,
        }
        results, all_passed = _check_thresholds(scores)

        assert all_passed is False
        assert results["faithfulness"]["passed"] is False
        assert results["faithfulness"]["score"] == 0.70
        assert results["faithfulness"]["threshold"] == 0.85
        # Other metrics still pass individually
        assert results["answer_relevancy"]["passed"] is True
        assert results["context_precision"]["passed"] is True

    def test_answer_relevancy_below_threshold(self):
        """Answer relevancy < 0.80 → fails."""
        scores = {
            "faithfulness": 0.90,
            "answer_relevancy": 0.50,
            "context_precision": 0.85,
            "context_recall": 0.80,
        }
        results, all_passed = _check_thresholds(scores)

        assert all_passed is False
        assert results["answer_relevancy"]["passed"] is False
        assert results["answer_relevancy"]["threshold"] == 0.80

    def test_context_precision_below_threshold(self):
        """Context precision < 0.80 → fails."""
        scores = {
            "faithfulness": 0.90,
            "answer_relevancy": 0.85,
            "context_precision": 0.60,
            "context_recall": 0.80,
        }
        results, all_passed = _check_thresholds(scores)

        assert all_passed is False
        assert results["context_precision"]["passed"] is False
        assert results["context_precision"]["threshold"] == 0.80

    def test_context_recall_below_threshold(self):
        """Context recall < 0.75 → fails."""
        scores = {
            "faithfulness": 0.90,
            "answer_relevancy": 0.85,
            "context_precision": 0.85,
            "context_recall": 0.50,
        }
        results, all_passed = _check_thresholds(scores)

        assert all_passed is False
        assert results["context_recall"]["passed"] is False
        assert results["context_recall"]["threshold"] == 0.75

    def test_exact_threshold_passes(self):
        """Score exactly at threshold → passes (>= check)."""
        scores = {
            "faithfulness": 0.85,
            "answer_relevancy": 0.80,
            "context_precision": 0.80,
            "context_recall": 0.75,
        }
        results, all_passed = _check_thresholds(scores)

        assert all_passed is True
        for metric in results:
            assert results[metric]["passed"] is True

    def test_empty_scores_returns_empty(self):
        """Empty aggregate_scores → empty results, all_passed=False."""
        results, all_passed = _check_thresholds({})

        assert all_passed is False
        assert results == {}

    def test_partial_scores(self):
        """Only some metrics present → only those checked."""
        scores = {"faithfulness": 0.90}
        results, all_passed = _check_thresholds(scores)

        assert all_passed is True  # Only faithfulness, and it passes
        assert len(results) == 1
        assert "faithfulness" in results
        assert "answer_relevancy" not in results

    def test_multiple_failures(self):
        """Multiple metrics below threshold → all_passed=False, each flagged."""
        scores = {
            "faithfulness": 0.50,
            "answer_relevancy": 0.40,
            "context_precision": 0.30,
            "context_recall": 0.20,
        }
        results, all_passed = _check_thresholds(scores)

        assert all_passed is False
        for metric in results:
            assert results[metric]["passed"] is False

    def test_threshold_values_correct(self):
        """Verify the threshold values match the specification."""
        scores = {
            "faithfulness": 1.0,
            "answer_relevancy": 1.0,
            "context_precision": 1.0,
            "context_recall": 1.0,
        }
        results, _ = _check_thresholds(scores)

        assert results["faithfulness"]["threshold"] == 0.85
        assert results["answer_relevancy"]["threshold"] == 0.80
        assert results["context_precision"]["threshold"] == 0.80
        assert results["context_recall"]["threshold"] == 0.75


# ===========================================================================
# 2. POST /admin/eval/trigger — response field mapping tests
# ===========================================================================

class TestEvalTriggerResponseMapping:
    """Test that the endpoint correctly maps RAGASEvaluator results to the response."""

    @pytest.mark.asyncio
    async def test_metrics_populated_from_aggregate_scores(self, client):
        """metrics field in response comes from aggregate_scores in eval result."""
        mock_result = {
            "verdict": "completed",
            "timestamp": "2026-06-08T10:00:00+00:00",
            "dataset_size": 5,
            "aggregate_scores": {
                "faithfulness": 0.92,
                "answer_relevancy": 0.88,
                "context_precision": 0.85,
                "context_recall": 0.80,
            },
            "per_question_scores": [],
            "latency_seconds": 12.5,
            "saved_to": "data/eval_results/eval_test.json",
        }

        with patch(
            "agents.eval.ragas_runner.RAGASEvaluator"
        ) as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        assert resp.status_code == 200
        body = resp.json()

        # metrics field maps directly from aggregate_scores
        assert body["metrics"] == mock_result["aggregate_scores"]
        assert body["metrics"]["faithfulness"] == 0.92
        assert body["metrics"]["answer_relevancy"] == 0.88

    @pytest.mark.asyncio
    async def test_threshold_results_populated(self, client):
        """threshold_results field populated from _check_thresholds on aggregate_scores."""
        mock_result = {
            "verdict": "completed",
            "timestamp": "2026-06-08T10:00:00+00:00",
            "dataset_size": 5,
            "aggregate_scores": {
                "faithfulness": 0.90,
                "answer_relevancy": 0.70,  # Below 0.80 threshold
                "context_precision": 0.85,
                "context_recall": 0.80,
            },
            "latency_seconds": 10.0,
            "saved_to": "data/eval_results/eval_test.json",
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        assert resp.status_code == 200
        body = resp.json()

        tr = body["threshold_results"]
        assert tr["faithfulness"]["passed"] is True
        assert tr["answer_relevancy"]["passed"] is False
        assert tr["answer_relevancy"]["score"] == 0.70
        assert tr["answer_relevancy"]["threshold"] == 0.80

    @pytest.mark.asyncio
    async def test_verdict_and_metadata_fields(self, client):
        """verdict, timestamp, dataset_size, latency_ms, result_path all mapped."""
        mock_result = {
            "verdict": "completed",
            "timestamp": "2026-06-08T12:00:00+00:00",
            "dataset_size": 10,
            "aggregate_scores": {"faithfulness": 0.95},
            "latency_seconds": 25.3,
            "saved_to": "/tmp/eval_result.json",
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        body = resp.json()
        assert body["verdict"] == "completed"
        assert body["timestamp"] == "2026-06-08T12:00:00+00:00"
        assert body["dataset_size"] == 10
        assert body["latency_ms"] == 25300.0
        assert body["result_path"] == "/tmp/eval_result.json"


# ===========================================================================
# 3. all_passed field — true when all thresholds met, false when any fails
# ===========================================================================

class TestAllPassedField:
    """Test all_passed boolean in the eval trigger response."""

    @pytest.mark.asyncio
    async def test_all_passed_true_when_all_pass(self, client):
        """all_passed=True when every metric meets its threshold."""
        mock_result = {
            "verdict": "completed",
            "timestamp": "2026-06-08T10:00:00+00:00",
            "dataset_size": 5,
            "aggregate_scores": {
                "faithfulness": 0.90,
                "answer_relevancy": 0.85,
                "context_precision": 0.82,
                "context_recall": 0.78,
            },
            "latency_seconds": 10.0,
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        body = resp.json()
        assert body["all_passed"] is True

    @pytest.mark.asyncio
    async def test_all_passed_false_when_one_fails(self, client):
        """all_passed=False when any single metric is below threshold."""
        mock_result = {
            "verdict": "completed",
            "timestamp": "2026-06-08T10:00:00+00:00",
            "dataset_size": 5,
            "aggregate_scores": {
                "faithfulness": 0.90,
                "answer_relevancy": 0.85,
                "context_precision": 0.85,
                "context_recall": 0.50,  # Below 0.75 threshold
            },
            "latency_seconds": 10.0,
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        body = resp.json()
        assert body["all_passed"] is False

    @pytest.mark.asyncio
    async def test_all_passed_false_when_no_scores(self, client):
        """all_passed=False when aggregate_scores is empty."""
        mock_result = {
            "verdict": "completed",
            "timestamp": "2026-06-08T10:00:00+00:00",
            "dataset_size": 0,
            "aggregate_scores": {},
            "latency_seconds": 1.0,
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        body = resp.json()
        assert body["all_passed"] is False
        assert body["threshold_results"] == {}


# ===========================================================================
# 4. credential_blocked path — graceful handling when OPENAI_API_KEY missing
# ===========================================================================

class TestCredentialBlockedPath:
    """Test that missing OPENAI_API_KEY produces a credential_blocked response."""

    @pytest.mark.asyncio
    async def test_credential_blocked_verdict(self, client):
        """When evaluator returns credential_blocked, response reflects it."""
        mock_result = {
            "verdict": "credential_blocked",
            "metrics": {},
            "reason": "OPENAI_API_KEY not set",
            "timestamp": "2026-06-08T10:00:00+00:00",
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "credential_blocked"
        assert body["metrics"] == {}
        assert body["all_passed"] is False
        assert body["threshold_results"] == {}
        assert body["dataset_size"] == 0

    @pytest.mark.asyncio
    async def test_credential_blocked_no_aggregate_scores_key(self, client):
        """credential_blocked result has no aggregate_scores key → handled gracefully."""
        mock_result = {
            "verdict": "credential_blocked",
            "metrics": {},
            "reason": "OPENAI_API_KEY not set",
            "timestamp": "2026-06-08T10:00:00+00:00",
            # Note: no aggregate_scores key at all
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "credential_blocked"
        assert body["all_passed"] is False


# ===========================================================================
# 5. failed path — error handling when evaluation fails
# ===========================================================================

class TestFailedPath:
    """Test that evaluation failures produce a failed verdict response."""

    @pytest.mark.asyncio
    async def test_failed_verdict(self, client):
        """When evaluator returns failed verdict, response reflects it."""
        mock_result = {
            "verdict": "failed",
            "metrics": {},
            "reason": "RuntimeError: something went wrong",
            "timestamp": "2026-06-08T10:00:00+00:00",
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "failed"
        assert body["metrics"] == {}
        assert body["all_passed"] is False
        assert body["threshold_results"] == {}

    @pytest.mark.asyncio
    async def test_failed_verdict_no_aggregate_scores(self, client):
        """Failed result with no aggregate_scores → threshold_results empty."""
        mock_result = {
            "verdict": "failed",
            "metrics": {},
            "reason": "ConnectionError: timeout",
            "timestamp": "2026-06-08T10:00:00+00:00",
            # No aggregate_scores key
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "failed"
        assert body["threshold_results"] == {}
        assert body["all_passed"] is False

    @pytest.mark.asyncio
    async def test_evaluator_exception_handled(self, client):
        """When RAGASEvaluator constructor or evaluate() raises, it's handled upstream.
        
        The evaluator itself catches exceptions and returns a failed verdict dict.
        This test verifies the endpoint handles a failed-verdict dict correctly.
        """
        mock_result = {
            "verdict": "failed",
            "metrics": {},
            "reason": "Exception: evaluation pipeline crashed",
            "timestamp": "2026-06-08T10:00:00+00:00",
        }

        with patch("agents.eval.ragas_runner.RAGASEvaluator") as MockEvaluator:
            instance = MagicMock()
            instance.evaluate.return_value = mock_result
            MockEvaluator.return_value = instance

            resp = await client.post("/admin/eval/trigger", json={})

        assert resp.status_code == 200
        body = resp.json()
        assert body["verdict"] == "failed"


# ===========================================================================
# 6. RAGASEvaluator credential_blocked — direct unit test
# ===========================================================================

class TestRAGASEvaluatorCredentialBlocked:
    """Direct test of RAGASEvaluator.evaluate() when OPENAI_API_KEY is None."""

    def test_evaluate_returns_credential_blocked_when_no_key(self):
        """RAGASEvaluator.evaluate() returns credential_blocked without API key."""
        from agents.eval.ragas_runner import RAGASEvaluator

        evaluator = RAGASEvaluator(openai_api_key=None)
        result = evaluator.evaluate("data/eval_dataset.jsonl")

        assert result["verdict"] == "credential_blocked"
        assert result["metrics"] == {}
        assert "OPENAI_API_KEY" in result["reason"]
        assert "timestamp" in result


# ===========================================================================
# 7. Strict eval verifier script logic — negative tests for S09 live gate
# ===========================================================================

class TestStrictEvalVerifier:
    """Script-level strict verifier rejects incomplete or failed eval responses."""

    def _valid_body(self):
        return {
            "verdict": "completed",
            "dataset_size": 12,
            "metrics": {
                "faithfulness": 0.90,
                "answer_relevancy": 0.85,
                "context_precision": 0.82,
                "context_recall": 0.78,
            },
            "threshold_results": {
                "faithfulness": {"score": 0.90, "threshold": 0.85, "passed": True},
                "answer_relevancy": {"score": 0.85, "threshold": 0.80, "passed": True},
                "context_precision": {"score": 0.82, "threshold": 0.80, "passed": True},
                "context_recall": {"score": 0.78, "threshold": 0.75, "passed": True},
            },
            "all_passed": True,
            "latency_ms": 12000.0,
            "result_path": "data/eval_results/eval_test.json",
        }

    def test_strict_verifier_accepts_complete_passing_response(self):
        from scripts.integration_test import validate_strict_eval_response

        passed, details = validate_strict_eval_response(self._valid_body(), require_thresholds=True)

        assert passed is True
        assert any("faithfulness" in line for line in details)
        assert any("result_path" in line for line in details)

    @pytest.mark.parametrize("verdict", ["credential_blocked", "failed"])
    def test_strict_verifier_rejects_non_completed_verdicts(self, verdict):
        from scripts.integration_test import validate_strict_eval_response

        body = self._valid_body()
        body["verdict"] = verdict

        passed, details = validate_strict_eval_response(body, require_thresholds=True)

        assert passed is False
        assert any(f"verdict: {verdict}" in line and line.startswith("❌") for line in details)

    def test_strict_verifier_rejects_missing_required_metric(self):
        from scripts.integration_test import validate_strict_eval_response

        body = self._valid_body()
        body["metrics"].pop("context_recall")

        passed, details = validate_strict_eval_response(body, require_thresholds=True)

        assert passed is False
        assert any("metric context_recall: missing" in line for line in details)

    def test_strict_verifier_rejects_missing_threshold_row(self):
        from scripts.integration_test import validate_strict_eval_response

        body = self._valid_body()
        body["threshold_results"].pop("context_precision")

        passed, details = validate_strict_eval_response(body, require_thresholds=True)

        assert passed is False
        assert any("threshold context_precision: missing" in line for line in details)

    def test_strict_verifier_rejects_threshold_failure(self):
        from scripts.integration_test import validate_strict_eval_response

        body = self._valid_body()
        body["all_passed"] = False
        body["threshold_results"]["answer_relevancy"]["passed"] = False
        body["threshold_results"]["answer_relevancy"]["score"] = 0.50

        passed, details = validate_strict_eval_response(body, require_thresholds=True)

        assert passed is False
        assert any("all_passed: False" in line for line in details)
        assert any("threshold answer_relevancy" in line and "FAIL" in line for line in details)

    def test_strict_verifier_rejects_wrong_dataset_size(self):
        from scripts.integration_test import validate_strict_eval_response

        body = self._valid_body()
        body["dataset_size"] = 11

        passed, details = validate_strict_eval_response(body, require_thresholds=True)

        assert passed is False
        assert any("dataset_size: 11 / 12" in line for line in details)
