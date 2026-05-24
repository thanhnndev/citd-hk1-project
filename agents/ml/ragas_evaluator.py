"""RAGAS evaluation pipeline for measuring RAG quality metrics.

Computes Faithfulness, Answer Relevancy, Context Precision, and Context Recall
against eval_dataset.jsonl using ragas 0.4.3 API.

Observability:
    structlog events:
        - ragas.eval.started (dataset_size)
        - ragas.eval.completed (scores, latency)
        - ragas.eval.blocked (reason=credential_missing)
        - ragas.eval.failed (error_type)
    Results persisted to data/eval_results/ as timestamped JSON.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# ragas 0.4.3 imports — guarded for graceful degradation
# ---------------------------------------------------------------------------
_RAGAS_IMPORT_ERROR: str | None = None
_RAGAS_AVAILABLE = False

try:
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.embeddings import embedding_factory
    from ragas.llms import llm_factory
    from ragas.llms.base import BaseRagasLLM, LLMResult
    from ragas.metrics.collections import (
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )
    from ragas.metrics._answer_relevance import AnswerRelevancy

    _RAGAS_AVAILABLE = True
except ImportError as exc:
    _RAGAS_IMPORT_ERROR = str(exc)

# Default metric names used in result dicts
_ALL_METRIC_NAMES = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
]


# ---------------------------------------------------------------------------
# Document corpus lookup
# ---------------------------------------------------------------------------

def _build_context_lookup(
    corpus_path: str | Path,
) -> dict[str, str]:
    """Build {source_id: concatenated_text} from tourism_documents.jsonl."""
    lookup: dict[str, list[str]] = {}
    path = Path(corpus_path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            sid = doc.get("source_id", "")
            text = doc.get("text", "")
            if sid and text:
                lookup.setdefault(sid, []).append(text)
    return {k: " ".join(v) for k, v in lookup.items()}


# ---------------------------------------------------------------------------
# RAGASEvaluator
# ---------------------------------------------------------------------------

class RAGASEvaluator:
    """Run RAGAS evaluation against a JSONL dataset.

    Parameters
    ----------
    openai_api_key : str | None
        OpenAI API key. When absent, evaluate() returns credential_blocked.
    metrics : list[str] | None
        Metric names to compute. Defaults to all four.
    corpus_path : str | Path | None
        Path to tourism_documents.jsonl for context look-up.
    """

    def __init__(
        self,
        openai_api_key: str | None = None,
        metrics: list[str] | None = None,
        corpus_path: str | Path | None = None,
    ) -> None:
        self.openai_api_key = openai_api_key
        self.metric_names = metrics or _ALL_METRIC_NAMES
        self.corpus_path = corpus_path

    # -- public ----------------------------------------------------------------

    def evaluate(self, dataset_path: str) -> dict:
        """Run RAGAS evaluation and return structured results.

        Returns
        -------
        dict
            When API key is missing: ``{"verdict": "credential_blocked", …}``
            Otherwise: ``{"verdict": "completed", "metrics": {…}, …}``
        """
        if not self.openai_api_key:
            self._log_blocked("OPENAI_API_KEY not set")
            return {
                "verdict": "credential_blocked",
                "metrics": {},
                "reason": "OPENAI_API_KEY not set",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        if not _RAGAS_AVAILABLE:
            self._log_blocked(f"ragas not importable: {_RAGAS_IMPORT_ERROR}")
            return {
                "verdict": "credential_blocked",
                "metrics": {},
                "reason": f"ragas not available: {_RAGAS_IMPORT_ERROR}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        start = time.monotonic()
        logger.info("ragas.eval.started", dataset_path=dataset_path)

        try:
            # Build dataset
            samples = self._load_samples(dataset_path)
            dataset = EvaluationDataset(samples=samples)
            dataset_size = len(samples)

            # Create LLM and embeddings via ragas factories
            from openai import AsyncOpenAI, OpenAI

            sync_client = OpenAI(api_key=self.openai_api_key)
            async_client = AsyncOpenAI(api_key=self.openai_api_key)

            llm = llm_factory(
                model="gpt-4o-mini",
                client=sync_client,
            )
            embeddings = embedding_factory(
                model="text-embedding-ada-002",
                client=async_client,
            )

            # Build metrics list (needs the InstructorLLM)
            metrics_list = self._build_metrics(llm, embeddings)

            result = evaluate(
                dataset=dataset,
                metrics=metrics_list,
                llm=llm,
                embeddings=embeddings,
                raise_exceptions=False,
            )

            latency = time.monotonic() - start
            scores = self._extract_scores(result)

            result_dict = {
                "verdict": "completed",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "dataset_size": dataset_size,
                "dataset_path": str(dataset_path),
                "metrics_requested": self.metric_names,
                "aggregate_scores": scores.get("aggregate", {}),
                "per_question_scores": scores.get("per_question", []),
                "latency_seconds": round(latency, 2),
            }

            # Persist to disk
            saved_path = self._save_results(result_dict)
            result_dict["saved_to"] = str(saved_path)

            logger.info(
                "ragas.eval.completed",
                aggregate_scores=scores.get("aggregate", {}),
                latency=latency,
            )
            return result_dict

        except Exception as exc:
            logger.error("ragas.eval.failed", error_type=type(exc).__name__)
            return {
                "verdict": "failed",
                "metrics": {},
                "reason": f"{type(exc).__name__}: {exc}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    # -- internals -------------------------------------------------------------

    def _load_samples(self, dataset_path: str) -> list[SingleTurnSample]:
        """Load eval_dataset.jsonl and map to SingleTurnSample list."""
        corpus_lookup = _build_context_lookup(self.corpus_path or "")

        samples: list[SingleTurnSample] = []
        path = Path(dataset_path)
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                question = row.get("question", "")
                ground_truth = row.get("ground_truth", "")
                source_ids = row.get("source_ids", [])

                # Build retrieved contexts from corpus
                retrieved_contexts: list[str] = []
                for sid in source_ids:
                    if sid in corpus_lookup:
                        retrieved_contexts.append(corpus_lookup[sid])

                sample = SingleTurnSample(
                    user_input=question,
                    reference=ground_truth,
                    retrieved_contexts=retrieved_contexts if retrieved_contexts else None,
                )
                samples.append(sample)

        return samples

    def _build_metrics(self, llm: Any, embeddings: Any | None = None) -> list:
        """Instantiate requested ragas metric objects.

        ragas 0.4.3 requires InstructorLLM (from llm_factory) for all
        collection metrics.
        """
        metric_map = {
            "faithfulness": lambda: Faithfulness(llm=llm),
            "answer_relevancy": lambda: AnswerRelevancy(
                llm=llm, embeddings=embeddings
            ),
            "answer_relevance": lambda: AnswerRelevancy(  # alias
                llm=llm, embeddings=embeddings
            ),
            "context_precision": lambda: ContextPrecision(llm=llm),
            "context_recall": lambda: ContextRecall(llm=llm),
        }
        result = []
        for name in self.metric_names:
            factory = metric_map.get(name)
            if factory is None:
                logger.warning(
                    "ragas.metric.unknown",
                    metric_name=name,
                    available=list(metric_map.keys()),
                )
                continue
            result.append(factory())
        return result

    def _extract_scores(self, result: Any) -> dict:
        """Extract aggregate and per-question scores from evaluate result."""
        aggregate: dict[str, float] = {}
        per_question: list[dict] = []

        # ragas 0.4.3 returns an object with .to_pandas() method
        try:
            if hasattr(result, "to_pandas"):
                df = result.to_pandas()
                for col in df.columns:
                    if col in _ALL_METRIC_NAMES:
                        vals = df[col].dropna()
                        if len(vals) > 0:
                            aggregate[col] = round(float(vals.mean()), 4)

                for _, row_data in df.iterrows():
                    entry = {}
                    for col in _ALL_METRIC_NAMES:
                        if col in row_data:
                            val = row_data[col]
                            if val is not None:
                                entry[col] = round(float(val), 4)
                    per_question.append(entry)

            elif hasattr(result, "scores"):
                # Fallback: raw scores attribute
                for metric_name in _ALL_METRIC_NAMES:
                    if metric_name in result.scores:
                        vals = result.scores[metric_name]
                        if vals:
                            aggregate[metric_name] = round(
                                sum(vals) / len(vals), 4
                            )
        except Exception:
            logger.warning("ragas.score.extract.failed")

        return {"aggregate": aggregate, "per_question": per_question}

    def _save_results(self, result_dict: dict) -> Path:
        """Persist result JSON to data/eval_results/."""
        out_dir = Path("data/eval_results")
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"eval_{ts}.json"
        out_path = out_dir / filename

        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(result_dict, fh, indent=2, ensure_ascii=False)

        return out_path

    def _log_blocked(self, reason: str) -> None:
        """Log credential-blocked event."""
        logger.info("ragas.eval.blocked", reason=reason)
