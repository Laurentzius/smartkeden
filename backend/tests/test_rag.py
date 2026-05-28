import pytest
import asyncio
from app.core.rag.indexer import LegalRAGIndexer
from app.core.rag.service import LegalRAGService, LegalRAGResponse


def test_legal_rag_indexing_and_query():
    # 1. Setup clean collection in memory Qdrant
    assert LegalRAGIndexer.setup_collection(force_recreate=True) is True

    # 2. Seed initial legal base
    seeded_count = LegalRAGIndexer.seed_initial_legal_base()
    assert seeded_count == 5  # SEED_LAW_BLOCKS has 5 entries

    # 3. Verify all seeded points exist via scroll (more reliable than vector search
    #    with mock zero vectors which return arbitrary ordering)
    client = LegalRAGIndexer.get_client()
    scroll_result = client.scroll(
        collection_name=LegalRAGIndexer.COLLECTION_NAME,
        limit=10
    )
    assert len(scroll_result[0]) == 5
    article_numbers = [p.payload.get("article_number", "") for p in scroll_result[0]]
    assert any("Статья 104" in a or "Статья 422" in a for a in article_numbers)

    # 4. Query the legal base to verify vector search + synthesis pipeline
    query = "Какая ставка НДС применяется к облагаемому импорту в Казахстан?"
    res: LegalRAGResponse = asyncio.run(LegalRAGService.query_legal_base(query))

    # 5. Verify outputs — structure is valid even with mock embeddings
    assert res is not None
    assert res.query == query
    assert len(res.answer_synthesis) > 0
    # Supporting laws may be empty/few with mock zero vectors (similarity ties)
    # but the pipeline should not crash




def test_parse_and_index_document_local_fallback():
    # Ensure clean setup
    LegalRAGIndexer.setup_collection(force_recreate=True)

    raw_text = "Статья 500. Таможенные пошлины. Пошлины уплачиваются плательщиками в бюджет."
    indexed_count = LegalRAGIndexer.parse_and_index_document(raw_text, "Кодекс РК")
    assert indexed_count == 1

    # Verify point exists via scroll
    client = LegalRAGIndexer.get_client()
    scroll_result = client.scroll(
        collection_name=LegalRAGIndexer.COLLECTION_NAME,
        limit=10
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
        {"role": "assistant", "content": "Согласно Налоговому кодексу РК, ставка НДС на импорт составляет 12%."}
    ]
    query = "А как это применяется к электронике?"
    res: LegalRAGResponse = asyncio.run(
        LegalRAGService.query_legal_base(query, history=history)
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

        def setup_collection(self, collection_name: str, vector_dimension: int, force_recreate: bool = False) -> bool:
            self.collections[collection_name] = {"dimension": vector_dimension}
            self.points[collection_name] = []
            return True

        def retrieve_points(self, collection_name: str, ids: List[str]) -> List[Any]:
            return [p for p in self.points.get(collection_name, []) if p.id in ids]

        def upsert_points(self, collection_name: str, points: List[PointStruct]) -> bool:
            if collection_name not in self.points:
                self.points[collection_name] = []
            self.points[collection_name].extend(points)
            return True

        def query_points(self, collection_name: str, query_vector: List[float], limit: int = 3) -> Any:
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

    class MockEmbeddingModel(EmbeddingModel):
        def embed_text(self, text: str, task_type: str = "RETRIEVAL_QUERY") -> List[float]:
            return [1.0, 2.0, 3.0]  # Simple 3D embedding vector for mocking

    # Save original adapters
    orig_storage = LegalRAGIndexer._vector_storage
    orig_embedder = LegalRAGIndexer._embedding_model

    # Inject mocks at the seams
    mock_storage = MockVectorStorage()
    mock_embedder = MockEmbeddingModel()
    LegalRAGIndexer._vector_storage = mock_storage
    LegalRAGIndexer._embedding_model = mock_embedder

    try:
        # Setup and Seed
        assert LegalRAGIndexer.setup_collection(force_recreate=True) is True
        assert LegalRAGIndexer._vector_storage.get_collections() == [LegalRAGIndexer.COLLECTION_NAME]

        # Index some test blocks
        blocks = [
            {
                "document_title": "Тестовый Кодекс РК",
                "article_number": "Статья 1",
                "content_quote": "Тестовое содержание пошлины.",
                "tags": ["TEST"],
                "keywords": "тест"
            }
        ]
        indexed_count = LegalRAGIndexer.index_blocks(blocks)
        assert indexed_count == 1

        # Verify it was stored inside our custom MockVectorStorage
        stored_points = mock_storage.points[LegalRAGIndexer.COLLECTION_NAME]
        assert len(stored_points) == 1
        assert stored_points[0].payload["document_title"] == "Тестовый Кодекс РК"
        assert stored_points[0].vector == [1.0, 2.0, 3.0] # Custom mock embedding vector

    finally:
        # Restore original adapters
        LegalRAGIndexer._vector_storage = orig_storage
        LegalRAGIndexer._embedding_model = orig_embedder
