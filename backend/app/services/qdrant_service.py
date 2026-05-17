"""Qdrant vector store service placeholder.

Future home of RAG (Retrieval-Augmented Generation) vector operations
against the Qdrant vector database.

Planned responsibilities:
- Index and upsert document embeddings (places, attractions, guides).
- Semantic search via cosine similarity with metadata filtering.
- Hybrid search combining dense (OpenAI embeddings) and sparse (BM25) vectors.
- Collection lifecycle management (create, snapshot, backup).
"""

# TODO: Implement Qdrant client wrapper once S04 (RAG pipeline) begins.
# Expected interface:
#   class QdrantService:
#       async def upsert(self, collection: str, points: list[PointStruct]) -> None: ...
#       async def search(self, collection: str, query_vector: list[float], limit: int = 5) -> list[ScoredPoint]: ...
#       async def ensure_collection(self, collection: str, vector_size: int) -> None: ...
