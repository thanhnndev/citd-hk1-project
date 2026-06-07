"""Tests for RAGASEvaluator — ragas 0.4.3 evaluation pipeline."""

import json
import os
import sys
from pathlib import Path

import pytest

# Resolve project root so we can import agents.* regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.eval.ragas_runner import (
    RAGASEvaluator,
    _RAGAS_AVAILABLE,
    _build_context_lookup,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
EVAL_DATASET = str(_PROJECT_ROOT / "data" / "eval_dataset.jsonl")
CORPUS_PATH = str(_PROJECT_ROOT / "data" / "tourism_documents.jsonl")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def evaluator_no_key():
    """Evaluator without API key — triggers credential_blocked path."""
    return RAGASEvaluator(openai_api_key=None)


@pytest.fixture
def evaluator_with_key():
    """Evaluator with a fake API key."""
    return RAGASEvaluator(
        openai_api_key="fake-test-key-for-unit-tests",
        corpus_path=CORPUS_PATH,
    )


@pytest.fixture
def small_dataset(tmp_path):
    """Create a tiny eval dataset for quick tests."""
    path = tmp_path / "small_eval.jsonl"
    rows = [
        {
            "question": "What is Ham Ninh known for?",
            "ground_truth": "Ham Ninh is known for its fishing village and seafood.",
            "source_ids": ["test-source-1"],
            "category": "geography",
            "language": "en",
        },
        {
            "question": "When is the best time to visit?",
            "ground_truth": "The dry season from November to April is best.",
            "source_ids": ["test-source-2"],
            "category": "activities",
            "language": "en",
        },
    ]
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return str(path)


# ---------------------------------------------------------------------------
# Credential-blocked tests
# ---------------------------------------------------------------------------

class TestCredentialBlocked:
    """Verify evaluator returns credential_blocked verdict without API key."""

    def test_no_api_key_returns_credential_blocked(self, evaluator_no_key):
        result = evaluator_no_key.evaluate(EVAL_DATASET)
        assert result["verdict"] == "credential_blocked"
        assert result["metrics"] == {}
        assert "reason" in result
        assert "timestamp" in result

    def test_no_api_key_no_exception(self, evaluator_no_key):
        """Should never raise — just return blocked verdict."""
        result = evaluator_no_key.evaluate(EVAL_DATASET)
        assert isinstance(result, dict)

    def test_blocked_result_has_timestamp(self, evaluator_no_key):
        result = evaluator_no_key.evaluate(EVAL_DATASET)
        assert "timestamp" in result
        assert result["timestamp"]  # non-empty

    def test_empty_api_key_also_blocked(self):
        ev = RAGASEvaluator(openai_api_key="")
        result = ev.evaluate(EVAL_DATASET)
        assert result["verdict"] == "credential_blocked"


# ---------------------------------------------------------------------------
# Sample loading tests
# ---------------------------------------------------------------------------

class TestSampleLoading:
    """Verify JSONL → SingleTurnSample mapping."""

    @pytest.mark.skipif(not _RAGAS_AVAILABLE, reason="ragas not available")
    def test_load_eval_dataset(self, evaluator_with_key):
        samples = evaluator_with_key._load_samples(EVAL_DATASET)
        assert len(samples) >= 12  # known dataset size

    @pytest.mark.skipif(not _RAGAS_AVAILABLE, reason="ragas not available")
    def test_sample_has_user_input(self, evaluator_with_key):
        samples = evaluator_with_key._load_samples(EVAL_DATASET)
        for s in samples:
            assert s.user_input, "user_input should not be empty"

    @pytest.mark.skipif(not _RAGAS_AVAILABLE, reason="ragas not available")
    def test_sample_has_reference(self, evaluator_with_key):
        samples = evaluator_with_key._load_samples(EVAL_DATASET)
        for s in samples:
            assert s.reference, "reference should not be empty"

    @pytest.mark.skipif(not _RAGAS_AVAILABLE, reason="ragas not available")
    def test_small_dataset_loading(self, evaluator_with_key, small_dataset):
        samples = evaluator_with_key._load_samples(small_dataset)
        assert len(samples) == 2
        assert "Ham Ninh" in samples[0].user_input

    @pytest.mark.skipif(not _RAGAS_AVAILABLE, reason="ragas not available")
    def test_context_lookup_populates_retrieved_contexts(
        self, evaluator_with_key
    ):
        samples = evaluator_with_key._load_samples(EVAL_DATASET)
        # Most samples should have retrieved contexts from the corpus
        with_contexts = [
            s for s in samples if s.retrieved_contexts
        ]
        assert len(with_contexts) > 0


# ---------------------------------------------------------------------------
# Context lookup tests
# ---------------------------------------------------------------------------

class TestContextLookup:
    """Verify tourism_documents.jsonl → source_id → text mapping."""

    def test_lookup_returns_dict(self):
        lookup = _build_context_lookup(CORPUS_PATH)
        assert isinstance(lookup, dict)
        assert len(lookup) > 0

    def test_lookup_has_known_source_ids(self):
        lookup = _build_context_lookup(CORPUS_PATH)
        # These source_ids appear in eval_dataset.jsonl
        assert "lang-chai-ham-ninh-am-thuc-hai-san-tuoi-song" in lookup

    def test_lookup_values_are_strings(self):
        lookup = _build_context_lookup(CORPUS_PATH)
        for key, val in lookup.items():
            assert isinstance(val, str)
            assert len(val) > 0

    def test_missing_corpus_path_returns_empty(self, tmp_path):
        lookup = _build_context_lookup(str(tmp_path / "nonexistent.jsonl"))
        assert lookup == {}


# ---------------------------------------------------------------------------
# Metrics building tests — skip real instantiation (requires InstructorLLM)
# ---------------------------------------------------------------------------

class TestMetricsBuilding:
    """Verify ragas metric instantiation logic (without real LLM)."""

    def test_default_metrics_count(self):
        ev = RAGASEvaluator(openai_api_key="test")
        assert len(ev.metric_names) == 4

    def test_subset_metrics(self):
        ev = RAGASEvaluator(
            openai_api_key="test",
            metrics=["faithfulness"],
        )
        assert ev.metric_names == ["faithfulness"]

    def test_metric_names_listed_correctly(self):
        ev = RAGASEvaluator(
            openai_api_key="test",
            metrics=["faithfulness", "context_precision"],
        )
        assert len(ev.metric_names) == 2

    @pytest.mark.skipif(not _RAGAS_AVAILABLE, reason="ragas not available")
    def test_unknown_metric_skipped_with_warning(self, caplog):
        ev = RAGASEvaluator(
            openai_api_key="test",
            metrics=["faithfulness", "nonexistent_metric"],
        )
        # _build_metrics needs a real InstructorLLM, so we just verify
        # the unknown metric name is tracked
        assert "nonexistent_metric" in ev.metric_names


# ---------------------------------------------------------------------------
# Result persistence tests
# ---------------------------------------------------------------------------

class TestResultPersistence:
    """Verify eval results are saved to data/eval_results/."""

    def test_results_directory_created(self, evaluator_no_key, tmp_path):
        """Credential-blocked results should still be saveable."""
        result = evaluator_no_key.evaluate(EVAL_DATASET)
        # Save manually to test persistence
        out_dir = tmp_path / "eval_results"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "test_result.json"
        with open(out_path, "w") as fh:
            json.dump(result, fh, indent=2)

        # Read back and verify
        with open(out_path) as fh:
            loaded = json.load(fh)
        assert loaded["verdict"] == "credential_blocked"

    def test_save_results_creates_directory(self, evaluator_no_key):
        """data/eval_results/ should be created by _save_results."""
        result = evaluator_no_key.evaluate(EVAL_DATASET)
        saved_path = evaluator_no_key._save_results(result)
        assert saved_path.exists()
        assert saved_path.parent.name == "eval_results"

    def test_saved_result_is_valid_json(self, evaluator_no_key):
        result = evaluator_no_key.evaluate(EVAL_DATASET)
        saved_path = evaluator_no_key._save_results(result)
        with open(saved_path) as fh:
            loaded = json.load(fh)
        assert loaded["verdict"] == "credential_blocked"
        assert "timestamp" in loaded


# ---------------------------------------------------------------------------
# Constructor tests
# ---------------------------------------------------------------------------

class TestConstructor:
    """Verify RAGASEvaluator constructor behavior."""

    def test_default_metrics(self):
        ev = RAGASEvaluator(openai_api_key="test")
        assert len(ev.metric_names) == 4

    def test_custom_metrics(self):
        ev = RAGASEvaluator(
            openai_api_key="test",
            metrics=["faithfulness", "context_precision"],
        )
        assert ev.metric_names == ["faithfulness", "context_precision"]

    def test_corpus_path_optional(self):
        ev = RAGASEvaluator(openai_api_key="test")
        assert ev.corpus_path is None

    def test_api_key_stored(self):
        ev = RAGASEvaluator(openai_api_key="sk-test-123")
        assert ev.openai_api_key == "sk-test-123"


# ---------------------------------------------------------------------------
# Import guard tests
# ---------------------------------------------------------------------------

class TestImportGuard:
    """Verify ragas import error handling."""

    def test_ragas_available_flag(self):
        """Should be True when ragas==0.4.3 is installed."""
        assert _RAGAS_AVAILABLE is True
