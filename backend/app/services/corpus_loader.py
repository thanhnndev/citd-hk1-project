"""Corpus loader: reads JSONL, validates rows, chunks content deterministically."""

import hashlib
import json
from pathlib import Path

from app.models.rag import CorpusStats, RAGChunk

# Required fields that every JSONL row must contain
REQUIRED_FIELDS = (
    "id",
    "title",
    "url",
    "domain",
    "source_type",
    "reliability",
    "language",
    "location",
    "cleaned_content",
)

CHUNK_TARGET = 800  # target chunk size in characters
CHUNK_OVERLAP = 200  # overlap between consecutive chunks
HEADING_MAX_LEN = 100  # headings longer than this are treated as body text


def _chunk_id(source_id: str, chunk_index: int) -> str:
    """Deterministic SHA-256 chunk ID from source_id and chunk_index."""
    raw = f"{source_id}:{chunk_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_valid_heading(candidate: str) -> bool:
    """Check if a line looks like a real heading (short, non-noisy)."""
    stripped = candidate.strip()
    if not stripped or len(stripped) > HEADING_MAX_LEN:
        return False
    # Reject lines that are too short to be meaningful headings
    if len(stripped) < 3:
        return False
    return True


def _extract_headings(cleaned_content: str, doc_headings: list[str]) -> list[tuple[int, str]]:
    """Find heading positions in the cleaned_content.

    Returns list of (start_position, heading_text) tuples for headings
    that appear in the content. Falls back to checking doc_headings list.
    """
    heading_positions: list[tuple[int, str]] = []

    # Try to find doc_headings within the cleaned_content
    for heading in doc_headings:
        if not _is_valid_heading(heading):
            continue
        pos = cleaned_content.find(heading)
        if pos >= 0:
            heading_positions.append((pos, heading))

    # Sort by position
    heading_positions.sort(key=lambda x: x[0])
    return heading_positions


def _split_at_headings(cleaned_content: str, headings: list[tuple[int, str]]) -> list[str]:
    """Split content at heading boundaries, producing segments."""
    if not headings:
        return [cleaned_content]

    segments: list[str] = []
    prev_end = 0

    for pos, heading_text in headings:
        # Include text from previous heading up to this one
        segment = cleaned_content[prev_end:pos].strip()
        if segment:
            segments.append(segment)
        prev_end = pos

    # Last segment: from last heading to end
    last_segment = cleaned_content[prev_end:].strip()
    if last_segment:
        segments.append(last_segment)

    return segments if segments else [cleaned_content]


def _split_fixed_size(text: str) -> list[str]:
    """Split text into overlapping fixed-size chunks."""
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + CHUNK_TARGET
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - CHUNK_OVERLAP
        # Avoid infinite loop if text is shorter than overlap
        if start <= (end - CHUNK_TARGET):
            break
    return chunks


def _chunk_segment(segment: str) -> list[str]:
    """Chunk a single segment. If it fits in one chunk, return as-is."""
    if len(segment) <= CHUNK_TARGET:
        return [segment]
    return _split_fixed_size(segment)


def _chunk_document(doc: dict) -> list[RAGChunk]:
    """Chunk a single validated document into RAGChunk objects."""
    source_id = doc["id"]
    cleaned_content = doc.get("cleaned_content", "").strip()

    # Edge case: empty cleaned_content — produce a single empty chunk
    if not cleaned_content:
        return [
            RAGChunk(
                chunk_id=_chunk_id(source_id, 0),
                source_id=source_id,
                title=doc["title"],
                url=doc.get("url"),
                domain=doc["domain"],
                source_type=doc["source_type"],
                reliability=doc["reliability"],
                language=doc["language"],
                location=doc["location"],
                text="",
                chunk_index=0,
                total_chunks=1,
            )
        ]

    # Try heading-aware splitting first
    doc_headings = doc.get("headings", [])
    headings = _extract_headings(cleaned_content, doc_headings)

    if headings:
        segments = _split_at_headings(cleaned_content, headings)
        # Only use heading-based splitting if it produces multiple segments
        if len(segments) > 1:
            all_chunks: list[str] = []
            for segment in segments:
                all_chunks.extend(_chunk_segment(segment))
        else:
            # Heading splitting collapsed to one segment — fall back to fixed-size
            all_chunks = _split_fixed_size(cleaned_content)
    else:
        # No headings — use fixed-size splitting
        all_chunks = _split_fixed_size(cleaned_content)

    # Ensure at least one chunk
    if not all_chunks:
        all_chunks = [cleaned_content]

    total = len(all_chunks)
    return [
        RAGChunk(
            chunk_id=_chunk_id(source_id, i),
            source_id=source_id,
            title=doc["title"],
            url=doc.get("url"),
            domain=doc["domain"],
            source_type=doc["source_type"],
            reliability=doc["reliability"],
            language=doc["language"],
            location=doc["location"],
            text=chunk_text,
            chunk_index=i,
            total_chunks=total,
        )
        for i, chunk_text in enumerate(all_chunks)
    ]


def load_corpus(path: str = "data/tourism_documents.jsonl") -> list[RAGChunk]:
    """Load and chunk the JSONL corpus.

    Args:
        path: Path to the JSONL file.

    Returns:
        List of RAGChunk objects, one per chunk.

    Raises:
        ValueError: If a row is missing required fields or the file is invalid.
        FileNotFoundError: If the path does not exist.
    """
    filepath = Path(path)
    if not filepath.exists():
        raise FileNotFoundError(f"Corpus file not found: {path}")

    all_chunks: list[RAGChunk] = []

    with open(filepath, "r", encoding="utf-8") as f:
        for row_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                doc = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON at row {row_num}: {e}") from e

            # Validate required fields
            missing = [field for field in REQUIRED_FIELDS if field not in doc or doc[field] is None]
            if missing:
                raise ValueError(
                    f"Row {row_num} missing required fields: {', '.join(missing)}"
                )

            # Chunk the document
            doc_chunks = _chunk_document(doc)
            all_chunks.extend(doc_chunks)

    return all_chunks


def get_corpus_stats(chunks: list[RAGChunk]) -> CorpusStats:
    """Compute aggregate statistics about a loaded corpus.

    Args:
        chunks: List of RAGChunk objects from load_corpus().

    Returns:
        CorpusStats with total_docs, total_chunks, avg_chunk_length,
        and source_type/reliability distributions.
    """
    if not chunks:
        return CorpusStats(
            total_docs=0,
            total_chunks=0,
            avg_chunk_length=0.0,
            source_type_distribution={},
            reliability_distribution={},
        )

    total_chunks = len(chunks)
    total_text_length = sum(len(c.text) for c in chunks)
    avg_chunk_length = total_text_length / total_chunks if total_chunks > 0 else 0.0

    # Unique source documents
    source_ids = set(c.source_id for c in chunks)
    total_docs = len(source_ids)

    # Distributions
    source_type_dist: dict[str, int] = {}
    reliability_dist: dict[str, int] = {}
    for c in chunks:
        source_type_dist[c.source_type] = source_type_dist.get(c.source_type, 0) + 1
        reliability_dist[c.reliability] = reliability_dist.get(c.reliability, 0) + 1

    return CorpusStats(
        total_docs=total_docs,
        total_chunks=total_chunks,
        avg_chunk_length=round(avg_chunk_length, 2),
        source_type_distribution=source_type_dist,
        reliability_distribution=reliability_dist,
    )
