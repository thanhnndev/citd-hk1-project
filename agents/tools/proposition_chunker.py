"""Proposition chunker: splits markdown docs and entity JSONs into atomic propositions."""

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Metadata extraction helpers
# ──────────────────────────────────────────────────────────────────────────────

_FRONTmatter_RE = re.compile(r"^---\n(.+?)\n---\n", re.DOTALL)
_URL_RE = re.compile(r"https?://[^\s<>\"]+")


def _parse_frontmatter(raw: str) -> dict[str, Any]:
    """Parse YAML-like frontmatter block between --- markers."""
    m = _FRONTmatter_RE.match(raw)
    if not m:
        return {}
    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, raw_val = line.partition(":")
        key = key.strip()
        val = raw_val.strip().strip('"').strip("'")
        if val.startswith("[") and val.endswith("]"):
            val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",")]
        meta[key] = val
    return meta


def _chunk_id(source_id: str, proposition_index: int) -> str:
    """Deterministic SHA-256 chunk ID."""
    data = f"{source_id}:{proposition_index}".encode()
    return hashlib.sha256(data).hexdigest()[:32]


# ──────────────────────────────────────────────────────────────────────────────
# Sentence / proposition extraction
# ──────────────────────────────────────────────────────────────────────────────

# Matches sentence terminators but preserves abbreviations (Mr., Dr., etc.)
_SENT_RE = re.compile(
    r"(?<=[.!?])\s+(?=[A-ZÀÁẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬĐÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨĐÒÓỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÙÚỦŨỤƯỨỪỬỮỰÝỲỶỸỴ])",
    re.UNICODE,
)

# Whitespace/newline normaliser
_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, filter empty/short results."""
    raw = _SENT_RE.split(text)
    out: list[str] = []
    for s in raw:
        s = _normalize(s)
        if s and len(s) > 10:
            out.append(s)
    return out


def _to_propositions(paragraph: str) -> list[str]:
    """
    Convert a paragraph into a list of atomic propositions.
    - Short paragraphs → single proposition
    - Longer text → split by sentence boundaries
    - Each output is one self-contained fact/statement.
    """
    p = _normalize(paragraph)
    if not p or len(p) < 20:
        return []
    sentences = _split_sentences(p)
    if len(sentences) <= 2:
        return [p] if len(p) > 20 else []
    return [s for s in sentences if len(s) > 15]


def _detect_language(title: str, text: str) -> str:
    """Heuristic ISO 639-1 language detection (vi vs en)."""
    sample = (title + " " + text)[:500]
    vietnamese_chars = len(re.findall(r"[àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơớiởỡợùúủũụưừứửữựỳýỷỹỵ]", sample, re.I))
    total = len(re.findall(r"[a-zA-Zàáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơớiởỡợùúủũụưừứửữựỳýỷỹỵ]", sample, re.I))
    return "vi" if (total > 0 and vietnamese_chars / total > 0.15) else "en"


# ──────────────────────────────────────────────────────────────────────────────
# Core chunker class
# ──────────────────────────────────────────────────────────────────────────────

class PropositionChunker:
    """
    Reads markdown docs and entity JSON files, emits atomic proposition chunks
    matching the RAGChunk schema.
    """

    DOMAIN = "tourism"
    DEFAULT_LOCATION = "Hàm Ninh, Phú Quốc"

    def __init__(self, docs_dir: Path | str, entities_dir: Path | str) -> None:
        self.docs_dir = Path(docs_dir)
        self.entities_dir = Path(entities_dir)

    # ------------------------------------------------------------------
    # Markdown → propositions
    # ------------------------------------------------------------------

    def _extract_md_propositions(self, file_path: Path) -> list[dict[str, Any]]:
        """Parse one markdown file, return list of chunk dicts."""
        raw = file_path.read_text(encoding="utf-8")
        meta = _parse_frontmatter(raw)

        content = _FRONTmatter_RE.sub("", raw).strip()
        # Strip markdown headings / blockquotes to get plain sentences
        lines = content.splitlines()
        body_lines: list[str] = []
        for line in lines:
            line = line.lstrip("#").lstrip(">").lstrip("*").strip()
            line = re.sub(r"!\[[^\]]*\]\([^\)]+\)", "", line)  # drop images
            line = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", line)  # links → text
            line = re.sub(r"\s*[-*#]+$", "", line).strip()
            if line:
                body_lines.append(line)

        body_text = " ".join(body_lines)
        if not body_text.strip():
            return []

        propositions = _to_propositions(body_text)
        source_id = file_path.stem  # filename without extension
        title = meta.get("title", source_id)
        language = meta.get("language") or _detect_language(title, body_text)

        chunks: list[dict[str, Any]] = []
        for idx, prop_text in enumerate(propositions):
            chunks.append(
                {
                    "chunk_id": _chunk_id(source_id, idx),
                    "source_id": source_id,
                    "title": meta.get("title", title),
                    "url": meta.get("source_url") or "",
                    "domain": meta.get("source_domain") or self.DOMAIN,
                    "source_type": meta.get("source_type", "blog"),
                    "reliability": meta.get("reliability", "medium"),
                    "language": language,
                    "location": meta.get("location") or self.DEFAULT_LOCATION,
                    "topic": meta.get("topic", ""),
                    "text": prop_text,
                    "chunk_index": idx,
                    "total_chunks": len(propositions),
                }
            )
        return chunks

    def chunk_markdown_files(self) -> list[dict[str, Any]]:
        """Recursively find all .md files and emit proposition chunks."""
        all_chunks: list[dict[str, Any]] = []
        pattern = "**/*.md"
        for path in sorted(self.docs_dir.glob(pattern)):
            chunks = self._extract_md_propositions(path)
            if chunks:
                logger.debug("chunked_md", path=str(path), count=len(chunks))
                all_chunks.extend(chunks)
        return all_chunks

    # ------------------------------------------------------------------
    # Entity JSON → propositions
    # ------------------------------------------------------------------

    def _entity_to_propositions(
        self, file_path: Path, entity_type: str
    ) -> list[dict[str, Any]]:
        """Parse an entity JSON file and emit proposition chunks."""
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("entity_parse_error", path=str(file_path), error=str(exc))
            return []

        all_chunks: list[dict[str, Any]] = []
        source_id = file_path.stem  # e.g. "culture_history"

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        else:
            return []

        for item in items:
            if entity_type == "culture_history":
                chunks = self._culture_history_chunk(item, source_id)
            elif entity_type == "restaurants":
                chunks = self._restaurant_chunk(item, source_id)
            else:
                chunks = self._generic_entity_chunk(item, source_id, entity_type)
            all_chunks.extend(chunks)

        return all_chunks

    def _culture_history_chunk(
        self, item: dict[str, Any], source_id: str
    ) -> list[dict[str, Any]]:
        """Extract propositions from a culture/history topic block."""
        topic_name = item.get("topic_name", "")
        claims = item.get("claims", [])
        chunks: list[dict[str, Any]] = []

        for idx, claim_entry in enumerate(claims):
            if not isinstance(claim_entry, dict):
                continue
            claim_text = claim_entry.get("claim", "")
            if not claim_text or len(claim_text) < 15:
                continue

            prop_id = _chunk_id(f"{source_id}:{topic_name}", idx)

            # The claim text may contain multiple sentences – split conservatively
            sentences = _split_sentences(claim_text)
            if len(sentences) == 1:
                props = [claim_text]
            else:
                props = [s for s in sentences if len(s) > 15]

            for p_idx, prop_text in enumerate(props):
                chunks.append(
                    {
                        "chunk_id": _chunk_id(prop_id, p_idx),
                        "source_id": f"{source_id}:{topic_name}",
                        "title": topic_name,
                        "url": claim_entry.get("source_url") or "",
                        "domain": "tourism",
                        "source_type": "knowledge_base",
                        "reliability": claim_entry.get("reliability", "medium"),
                        "language": "vi",
                        "location": self.DEFAULT_LOCATION,
                        "topic": "văn hóa - lịch sử",
                        "text": prop_text,
                        "chunk_index": p_idx,
                        "total_chunks": len(props),
                    }
                )
        return chunks

    def _restaurant_chunk(
        self, item: dict[str, Any], source_id: str
    ) -> list[dict[str, Any]]:
        """Extract propositions from a restaurant entity."""
        entity_name = item.get("entity_name", "")
        review_snippets = item.get("review_snippets", [])
        menu_items = item.get("menu_items", [])
        sources = item.get("sources", [])
        url = sources[0] if sources else ""
        confidence = item.get("confidence", "medium")
        chunks: list[dict[str, Any]] = []

        propositions: list[tuple[str, str]] = []

        # Name proposition
        if entity_name:
            propositions.append((entity_name, "Tên địa điểm ẩm thực"))

        # Address proposition
        address = item.get("address", "")
        if address:
            propositions.append(
                (f"{entity_name} có địa chỉ tại {address}.", "Địa chỉ")
            )

        # Menu proposition
        if menu_items:
            food_list = ", ".join(menu_items)
            propositions.append(
                (
                    f"{entity_name} phục vụ các món: {food_list}.",
                    "Thực đơn",
                )
            )

        # Review proposition
        review = item.get("review_summary", "")
        if review:
            propositions.append((review, "Đánh giá tổng quan"))

        # Review snippets
        for snippet in review_snippets:
            if len(snippet) > 30:
                propositions.append((snippet, "Đánh giá chi tiết"))

        # Price info proposition
        price = item.get("price_range", "")
        if price and len(price) > 10:
            propositions.append((price, "Giá cả"))

        # Create chunks
        entity_source_id = f"{source_id}:{entity_name}"
        for p_idx, (prop_text, prop_type) in enumerate(propositions):
            prop_id = _chunk_id(f"{entity_source_id}:prop", p_idx)
            chunks.append(
                {
                    "chunk_id": prop_id,
                    "source_id": entity_source_id,
                    "title": entity_name,
                    "url": url,
                    "domain": "tourism",
                    "source_type": "restaurant",
                    "reliability": confidence,
                    "language": "vi",
                    "location": address or self.DEFAULT_LOCATION,
                    "topic": "ẩm thực",
                    "text": prop_text,
                    "chunk_index": p_idx,
                    "total_chunks": len(propositions),
                }
            )
        return chunks

    def _generic_entity_chunk(
        self, item: dict[str, Any], source_id: str, entity_type: str
    ) -> list[dict[str, Any]]:
        """Fallback for unknown entity formats."""
        text = item.get("text") or item.get("description") or item.get("content", "")
        if not text or len(text) < 15:
            return []
        entity_id = item.get("id", source_id)
        prop_id = _chunk_id(entity_id, 0)
        return [
            {
                "chunk_id": prop_id,
                "source_id": entity_id,
                "title": item.get("name") or entity_id,
                "url": item.get("source_url") or "",
                "domain": "tourism",
                "source_type": entity_type,
                "reliability": item.get("reliability", "medium"),
                "language": "vi",
                "location": self.DEFAULT_LOCATION,
                "topic": item.get("topic", ""),
                "text": text,
                "chunk_index": 0,
                "total_chunks": 1,
            }
        ]

    def chunk_all(self) -> list[dict[str, Any]]:
        """Main entry point: chunk markdown docs + all entity JSON files."""
        chunks: list[dict[str, Any]] = []

        # Markdown
        chunks.extend(self.chunk_markdown_files())

        # Entity JSONs
        entity_map = {
            "culture_history.json": "culture_history",
            "restaurants.json": "restaurants",
        }
        for fname, etype in entity_map.items():
            fpath = self.entities_dir / fname
            if fpath.exists():
                chunks.extend(self._entity_to_propositions(fpath, etype))
                logger.debug("chunked_entity", path=str(fpath), etype=etype)

        return chunks