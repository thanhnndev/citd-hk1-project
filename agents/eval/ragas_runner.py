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
    When a Langfuse client is provided, scores are logged to Langfuse for
    centralized observability alongside agent traces.
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
    # ragas 0.4.3: use ragas.metrics (top-level Metric subclasses)
    from ragas.metrics import (
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

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
    langfuse_client : Any | None
        Langfuse client instance. When provided, evaluation scores are
        logged to Langfuse for centralized observability.
    """

    def __init__(
        self,
        openai_api_key: str | None = None,
        metrics: list[str] | None = None,
        corpus_path: str | Path | None = None,
        langfuse_client: Any | None = None,
    ) -> None:
        self.openai_api_key = openai_api_key
        self.metric_names = metrics or _ALL_METRIC_NAMES
        self.corpus_path = corpus_path
        self.langfuse_client = langfuse_client

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
            # Build dataset and generate responses
            samples = self._load_samples(dataset_path)
            samples = self._generate_responses(samples)
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
                provider="openai",
                model="text-embedding-3-small",
                client=async_client,
            )

            # ragas 0.4.3 metrics internally call embed_query/embed_documents
            # but OpenAIEmbeddings only exposes embed_text/embed_texts.
            # Monkey-patch aliases so metrics work.
            if not hasattr(embeddings, "embed_query"):
                embeddings.embed_query = embeddings.embed_text
            if not hasattr(embeddings, "embed_documents"):
                embeddings.embed_documents = embeddings.embed_texts

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

            # Log scores to Langfuse for centralized observability
            self._log_to_langfuse(
                scores=scores,
                dataset_size=dataset_size,
                latency_seconds=latency,
            )

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
                    response="",  # Placeholder — filled by _generate_responses
                )
                samples.append(sample)

        return samples

    def _generate_responses(self, samples: list[SingleTurnSample]) -> list[SingleTurnSample]:
        """Generate LLM responses for each sample before evaluation."""
        from openai import OpenAI

        client = OpenAI(api_key=self.openai_api_key)
        context_docs = _build_context_lookup(self.corpus_path or "")

        for i, sample in enumerate(samples):
            # Build context from retrieved sources
            context_text = ""
            if sample.retrieved_contexts:
                context_text = "\n\n".join(
                    f"[Doc {j+1}] {ctx}" for j, ctx in enumerate(sample.retrieved_contexts)
                )

            system_prompt = (
                "You are a helpful tourism assistant for Ham Ninh, Phu Quoc. "
                "Answer the user's question based on the provided context. "
                "If the context doesn't contain the answer, say so honestly. "
                "Respond in the same language as the question."
            )
            user_prompt = (
                f"Context:\n{context_text}\n\n"
                f"Question: {sample.user_input}"
            ) if context_text else f"Question: {sample.user_input}"

            try:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_completion_tokens=500,
                )
                response_text = resp.choices[0].message.content or ""
            except Exception:
                response_text = "Failed to generate response."

            # Create updated sample with response
            samples[i] = SingleTurnSample(
                user_input=sample.user_input,
                response=response_text,
                reference=sample.reference,
                retrieved_contexts=sample.retrieved_contexts,
            )

            logger.info(
                "ragas.response_generated",
                question_idx=i,
                response_len=len(response_text),
            )

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

    def _log_to_langfuse(
        self,
        scores: dict,
        dataset_size: int,
        latency_seconds: float,
    ) -> None:
        """Log RAGAS evaluation scores to Langfuse.

        Creates a trace for the evaluation run and logs each aggregate
        metric as a Langfuse score. Per-question scores are logged as
        individual scores with question index metadata.
        """
        if self.langfuse_client is None:
            logger.info("ragas.langfuse.skipped", reason="langfuse_client is None")
            return

        try:
            aggregate = scores.get("aggregate", {})
            per_question = scores.get("per_question", [])

            logger.info(
                "ragas.langfuse.sending",
                aggregate_scores=aggregate,
                per_question_count=len(per_question),
            )

            # Create a trace for this evaluation run
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            with self.langfuse_client.start_as_current_observation(
                name="ragas-evaluation",
                as_type="agent",
                input={
                    "dataset_size": dataset_size,
                    "metrics_requested": self.metric_names,
                },
                metadata={
                    "pipeline": "ragas",
                    "timestamp": ts,
                },
            ) as observation:
                observation.set_trace_io(
                    input={
                        "dataset_size": dataset_size,
                        "metrics_requested": self.metric_names,
                    },
                    output={
                        "aggregate_scores": aggregate,
                        "per_question_count": len(per_question),
                    },
                )

                # Log aggregate scores to the trace
                for metric_name, score_value in aggregate.items():
                    observation.score_trace(
                        name=f"ragas.{metric_name}",
                        value=score_value,
                        data_type="NUMERIC",
                        comment=f"RAGAS {metric_name} (aggregate, n={dataset_size})",
                    )

                # Log per-question scores to the observation
                for idx, q_scores in enumerate(per_question):
                    for metric_name, score_value in q_scores.items():
                        if score_value is not None:
                            observation.score(
                                name=f"ragas.{metric_name}.q{idx}",
                                value=score_value,
                                data_type="NUMERIC",
                                comment=f"RAGAS {metric_name} (question {idx + 1}/{len(per_question)})",
                            )

                observation.update(
                    output={
                        "aggregate_scores": aggregate,
                        "per_question_count": len(per_question),
                        "latency_seconds": round(latency_seconds, 2),
                    },
                )

            # Flush to ensure all buffered events are sent to Langfuse
            self.langfuse_client.flush()

            logger.info(
                "ragas.langfuse.logged",
                aggregate_scores=aggregate,
                per_question_count=len(per_question),
            )
        except Exception as exc:
            logger.warning(
                "ragas.langfuse.failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )
