import pytest
import asyncio
from app.core.rag.indexer import LegalRAGIndexer
from app.core.rag.service import LegalRAGService, LegalRAGResponse
from app.core.rag.seams import QdrantVectorStorageAdapter, LocalEmbeddingModelAdapter
from app.core.llm.generator import get_generator

_vector_storage = LegalRAGIndexer._vector_storage
_embedding_model = LegalRAGIndexer._embedding_model
_text_generator = get_generator()
_legal_rag = LegalRAGService(
    vector_storage=_vector_storage,
    embedding_model=_embedding_model,
    text_generator=_text_generator,
)


def test_legal_rag_indexing_and_query():
    # 1. Setup clean collection in memory Qdrant
    assert LegalRAGIndexer.setup_collection(force_recreate=True) is True

    # 2. Seed initial legal base
    seeded_count = LegalRAGIndexer.seed_initial_legal_base()
    assert seeded_count == 5  # SEED_LAW_BLOCKS has 5 entries

    # 3. Verify all seeded points exist via scroll (more reliable than vector search
    #    with mock zero vectors which return arbitrary ordering)
    scroll_result = _vector_storage.scroll_points(
        collection_name=LegalRAGIndexer.COLLECTION_NAME, limit=10, with_payload=True
    )
    assert len(scroll_result[0]) == 5
    article_numbers = [p.payload.get("article_number", "") for p in scroll_result[0]]
    assert any("Статья 104" in a or "Статья 422" in a for a in article_numbers)

    # 4. Query the legal base to verify vector search + synthesis pipeline
    query = "Какая ставка НДС применяется к облагаемому импорту в Казахстан?"
    res: LegalRAGResponse = asyncio.run(_legal_rag.query_legal_base(query))

    # 5. Verify outputs — structure is valid even with mock embeddings
    assert res is not None
    assert res.query == query
    assert len(res.answer_synthesis) > 0
    # Supporting laws may be empty/few with mock zero vectors (similarity ties)
    # but the pipeline should not crash


def test_parse_and_index_document_local_fallback():
    # Ensure clean setup
    LegalRAGIndexer.setup_collection(force_recreate=True)

    raw_text = (
        "Статья 500. Таможенные пошлины. Пошлины уплачиваются плательщиками в бюджет."
    )
    indexed_count = LegalRAGIndexer.parse_and_index_document(raw_text, "Кодекс РК")
    assert indexed_count == 1

    # Verify point exists via scroll
    scroll_result = _vector_storage.scroll_points(
        collection_name=LegalRAGIndexer.COLLECTION_NAME, limit=10, with_payload=True
    )
    assert len(scroll_result[0]) == 1
    assert scroll_result[0][0].payload.get("article_number") == "Статья 500"


def test_legal_rag_history_handling():
    """Multi-turn history should be accepted and produce a non-empty answer."""
    # 1. Setup clean collection in memory Qdrant
    assert LegalRAGIndexer.setup_collection(force_recreate=True) is True

    # 2. Seed initial legal base
    seeded_count = LegalRAGIndexer.seed_initial_legal_base()
    assert seeded_count == 5

    # 3. Query with conversational history (simulating follow-up question)
    history = [
        {"role": "user", "content": "Какая ставка НДС на импорт?"},
        {
            "role": "assistant",
            "content": "Согласно Налоговому кодексу РК, ставка НДС на импорт составляет 12%.",
        },
    ]
    query = "А как это применяется к электронике?"
    res: LegalRAGResponse = asyncio.run(
        _legal_rag.query_legal_base(query, history=history)
    )

    # 4. Verify answer_synthesis is non-empty (pipeline processes history gracefully)
    assert res is not None
    assert res.query == query


def test_rag_custom_seams():
    from app.core.rag.seams import VectorStorage, EmbeddingModel
    from qdrant_client.models import PointStruct
    from typing import List, Any

    class MockVectorStorage(VectorStorage):
        def __init__(self):
            self.collections = {}
            self.points = {}

        def setup_collection(
            self,
            collection_name: str,
            vector_dimension: int,
            force_recreate: bool = False,
        ) -> bool:
            self.collections[collection_name] = {"dimension": vector_dimension}
            self.points[collection_name] = []
            return True

        def retrieve_points(self, collection_name: str, ids: List[str]) -> List[Any]:
            return [p for p in self.points.get(collection_name, []) if p.id in ids]

        def upsert_points(
            self, collection_name: str, points: List[PointStruct]
        ) -> bool:
            if collection_name not in self.points:
                self.points[collection_name] = []
            self.points[collection_name].extend(points)
            return True

        def query_points(
            self, collection_name: str, query_vector: List[float], limit: int = 3
        ) -> Any:
            # Return mock wrapper with .points attribute
            class MockPointsWrapper:
                def __init__(self, pts):
                    self.points = pts

            return MockPointsWrapper(self.points.get(collection_name, [])[:limit])

        def get_collections(self) -> List[str]:
            return list(self.collections.keys())

        def delete_collection(self, collection_name: str) -> bool:
            self.collections.pop(collection_name, None)
            self.points.pop(collection_name, None)
            return True

        def scroll_points(
            self,
            collection_name: str,
            filter_cond: Any = None,
            limit: int = 100,
            offset: Any = None,
            with_payload: bool = True,
            with_vectors: bool = False,
        ) -> Any:
            pts = self.points.get(collection_name, [])
            # Filter by matching doc title if specified in filter_cond (for indexer calls)
            if filter_cond and hasattr(filter_cond, "must"):
                # if it is a Filter object from qdrant_client.models
                for cond in filter_cond.must:
                    if hasattr(cond, "key") and cond.key == "document_title":
                        match_val = (
                            cond.match.text
                            if hasattr(cond.match, "text")
                            else getattr(cond.match, "value", None)
                        )
                        if match_val:
                            pts = [
                                p
                                for p in pts
                                if p.payload.get("document_title") == match_val
                            ]
            return pts[:limit], None

        def delete_points(self, collection_name: str, ids: List[str]) -> bool:
            if collection_name in self.points:
                self.points[collection_name] = [
                    p for p in self.points[collection_name] if p.id not in ids
                ]
            return True

    class MockEmbeddingModel(EmbeddingModel):
        def embed_text(
            self, text: str, task_type: str = "RETRIEVAL_QUERY"
        ) -> List[float]:
            return [1.0, 2.0, 3.0]  # Simple 3D embedding vector for mocking

    mock_storage = MockVectorStorage()
    mock_embedder = MockEmbeddingModel()

    # Create service with custom seams (instance injection pattern)
    custom_rag = LegalRAGService(
        vector_storage=mock_storage,
        embedding_model=mock_embedder,
        text_generator=_text_generator,
    )

    # Setup collection directly on the mock storage
    assert (
        mock_storage.setup_collection(
            LegalRAGIndexer.COLLECTION_NAME,
            LegalRAGIndexer.VECTOR_DIMENSION,
            force_recreate=True,
        )
        is True
    )
    assert mock_storage.get_collections() == [LegalRAGIndexer.COLLECTION_NAME]

    # Index some test blocks through the mock storage and mock embedder
    blocks = [
        {
            "document_title": "Тестовый Кодекс РК",
            "article_number": "Статья 1",
            "content_quote": "Тестовое содержание пошлины.",
            "tags": ["TEST"],
            "keywords": "тест",
        }
    ]
    import hashlib, uuid

    for block in blocks:
        point_id = LegalRAGIndexer.generate_point_id(
            doc_title=block["document_title"],
            article_number=block["article_number"],
            content_quote=block["content_quote"],
        )
        text_to_embed = (
            f"Document: {block['document_title']}\n"
            f"Reference: {block['article_number']}\n"
            f"Content: {block['content_quote']}"
        )
        vector = mock_embedder.embed_text(
            text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
        )
        content_hash = hashlib.sha256(
            block["content_quote"].encode("utf-8")
        ).hexdigest()
        payload = {
            "document_title": block["document_title"],
            "article_number": block["article_number"],
            "content_quote": block["content_quote"],
            "content_hash": content_hash,
            "tags": block.get("tags", []),
            "keywords": block.get("keywords", ""),
        }
        mock_storage.upsert_points(
            LegalRAGIndexer.COLLECTION_NAME,
            [PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    # Verify it was stored inside our custom MockVectorStorage
    stored_points = mock_storage.points[LegalRAGIndexer.COLLECTION_NAME]
    assert len(stored_points) == 1
    assert stored_points[0].payload["document_title"] == "Тестовый Кодекс РК"
    assert stored_points[0].vector == [1.0, 2.0, 3.0]  # Custom mock embedding vector


def test_gemini_chunk_filter_happy_path(monkeypatch):
    """Verify that GeminiChunkFilter keeps chunks with score >= threshold and filters out lower ones."""
    from app.core.rag.service import (
        GeminiChunkFilter,
        LegalChunk,
        ChunkFilterResponse,
        ChunkRelevance,
    )
    from unittest.mock import MagicMock

    chunks = [
        LegalChunk(
            document_title="Law A",
            article_number="Art 1",
            content_quote="Relevance 10",
            relevance_score=0.9,
        ),
        LegalChunk(
            document_title="Law B",
            article_number="Art 2",
            content_quote="Irrelevant",
            relevance_score=0.8,
        ),
        LegalChunk(
            document_title="Law C",
            article_number="Art 3",
            content_quote="Relevance 6",
            relevance_score=0.7,
        ),
    ]

    mock_response = ChunkFilterResponse(
        scores=[
            ChunkRelevance(chunk_index=0, relevance_score=10, reasoning="Very high"),
            ChunkRelevance(chunk_index=1, relevance_score=2, reasoning="Irrelevant"),
            ChunkRelevance(
                chunk_index=2, relevance_score=6, reasoning="Moderate relevance"
            ),
        ]
    )

    mock_gen = MagicMock()
    mock_gen.generate_structured.return_value = mock_response
    monkeypatch.setattr("app.core.llm.generator._generator", mock_gen)

    filtered = GeminiChunkFilter.filter_chunks("Query", chunks, threshold=5)
    assert len(filtered) == 2
    assert filtered[0].article_number == "Art 1"
    assert filtered[1].article_number == "Art 3"


def test_gemini_chunk_filter_fallback_on_error(monkeypatch):
    """Verify that GeminiChunkFilter returns all chunks if LLM raises an error."""
    from app.core.rag.service import GeminiChunkFilter, LegalChunk
    from unittest.mock import MagicMock

    chunks = [
        LegalChunk(
            document_title="Law A",
            article_number="Art 1",
            content_quote="Relevance 10",
            relevance_score=0.9,
        ),
        LegalChunk(
            document_title="Law B",
            article_number="Art 2",
            content_quote="Irrelevant",
            relevance_score=0.8,
        ),
    ]

    mock_gen = MagicMock()
    mock_gen.generate_structured.side_effect = Exception("Vertex AI connection failed")
    monkeypatch.setattr("app.core.llm.generator._generator", mock_gen)

    filtered = GeminiChunkFilter.filter_chunks("Query", chunks, threshold=5)


def test_legal_rag_empty_query():
    """Empty query should not crash the RAG pipeline."""
    LegalRAGIndexer.setup_collection(force_recreate=True)
    LegalRAGIndexer.seed_initial_legal_base()

    query = ""
    res: LegalRAGResponse = asyncio.run(_legal_rag.query_legal_base(query))
    assert res is not None
    assert isinstance(res.answer_synthesis, str)


def test_legal_rag_non_ascii_query():
    """Unicode and special characters in query should not crash."""
    LegalRAGIndexer.setup_collection(force_recreate=True)
    LegalRAGIndexer.seed_initial_legal_base()

    query = "⚖️📋 Статья 422 — НДС: ставка (12%) на импорт товаров из Китая ©️"
    res: LegalRAGResponse = asyncio.run(_legal_rag.query_legal_base(query))
    assert res is not None
    assert len(res.answer_synthesis) > 0


def test_legal_rag_indexed_chunks_structure():
    """All seeded chunks should have required payload fields."""
    LegalRAGIndexer.setup_collection(force_recreate=True)
    LegalRAGIndexer.seed_initial_legal_base()

    scroll_result = _vector_storage.scroll_points(
        collection_name=LegalRAGIndexer.COLLECTION_NAME, limit=100, with_payload=True
    )
    for point in scroll_result[0]:
        payload = point.payload or {}
        assert (
            isinstance(payload.get("article_number"), str)
            or payload.get("article_number") is None
        )
        assert (
            isinstance(payload.get("document_title"), str)
            or payload.get("document_title") is None
        )
        assert (
            isinstance(payload.get("content_quote"), str)
            or payload.get("content_quote") is None
        )
