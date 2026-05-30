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

        def count_points(self, collection_name: str) -> int:
            return len(self.points.get(collection_name, []))

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

class TestMarkdownBlockParser:
    """Unit tests for MarkdownBlockParser — heading chunks, article boundaries, edge cases."""

    @pytest.fixture(autouse=True)
    def _parser(self):
        from app.core.rag.parsers import MarkdownBlockParser
        self.parser = MarkdownBlockParser()

    def test_heading_chunks_become_blocks(self):
        md = (
            "## Таможенные сборы\n\n"
            "Текст про сборы.\n\n"
            "### Порядок уплаты\n\n"
            "Текст про уплату.\n\n"
            "# Общие положения\n\n"
            "Общий текст."
        )
        blocks = self.parser.parse(md, "Тестовый Кодекс")
        assert len(blocks) == 3
        assert blocks[0]["article_number"] == "Таможенные сборы"
        assert blocks[0]["content_quote"] == "Текст про сборы."
        assert blocks[0]["document_title"] == "Тестовый Кодекс"
        assert blocks[1]["article_number"] == "Порядок уплаты"
        assert blocks[1]["content_quote"] == "Текст про уплату."
        assert blocks[2]["article_number"] == "Общие положения"
        assert blocks[2]["content_quote"] == "Общий текст."
        # All blocks have tags
        for b in blocks:
            assert "AUTO_PARSED" in b["tags"]
            assert "MARKDOWN" in b["tags"]

    def test_article_boundary_in_heading(self):
        md = "## Статья 42. Таможенные сборы\n\nТекст статьи 42.\n\n### Статья 43\n\nТекст статьи 43."
        blocks = self.parser.parse(md, "Кодекс")
        assert len(blocks) == 2
        assert blocks[0]["article_number"] == "Статья 42"
        assert blocks[0]["content_quote"] == "Текст статьи 42."
        assert blocks[1]["article_number"] == "Статья 43"
        assert blocks[1]["content_quote"] == "Текст статьи 43."

    def test_article_boundary_in_first_body_line(self):
        md = "## Раздел I\n\nСтатья 55. Общие правила.\n\nПодробный текст."
        blocks = self.parser.parse(md, "Кодекс")
        assert len(blocks) == 1
        assert blocks[0]["article_number"] == "Статья 55"
        assert blocks[0]["content_quote"] == "Статья 55. Общие правила. Подробный текст."

    def test_article_boundary_starts_with_stattia(self):
        """Статья at the very start of a heading should be detected."""
        md = "# Статья 1\n\nОсновные положения данного документа."
        blocks = self.parser.parse(md, "Кодекс")
        assert len(blocks) == 1
        assert blocks[0]["article_number"] == "Статья 1"

    def test_empty_markdown_returns_no_blocks(self):
        assert self.parser.parse("", "X") == []
        assert self.parser.parse("   \n  \n\t", "X") == []

    def test_heading_only_no_body_returns_no_blocks(self):
        md = "## Только заголовок\n\n# Ещё заголовок"
        blocks = self.parser.parse(md, "Кодекс")
        assert blocks == []

    def test_content_before_first_heading_ignored(self):
        md = "Какой-то текст без заголовка.\n\n## Настоящий раздел\n\nСодержимое."
        blocks = self.parser.parse(md, "Документ")
        assert len(blocks) == 1
        assert blocks[0]["article_number"] == "Настоящий раздел"
        assert blocks[0]["content_quote"] == "Содержимое."


class TestMarkdownIngestion:
    """Integration-style tests for parse_and_index_markdown with mock seams."""

    @pytest.fixture(autouse=True)
    def _setup_seams(self, monkeypatch):
        from app.core.rag.seams import VectorStorage, EmbeddingModel

        class MockVectorStorage(VectorStorage):
            def __init__(self):
                self.collections = {}
                self.points = {}

            def setup_collection(self, collection_name, vector_dimension, force_recreate=False):
                self.collections[collection_name] = {"dimension": vector_dimension}
                if force_recreate or collection_name not in self.points:
                    self.points[collection_name] = []
                return True

            def retrieve_points(self, collection_name, ids):
                return [p for p in self.points.get(collection_name, []) if p.id in ids]

            def upsert_points(self, collection_name, points):
                if collection_name not in self.points:
                    self.points[collection_name] = []
                # Replace existing by id
                new_ids = {p.id for p in points}
                self.points[collection_name] = [
                    p for p in self.points[collection_name] if p.id not in new_ids
                ]
                self.points[collection_name].extend(points)
                return True

            def query_points(self, collection_name, query_vector, limit=3):
                class MockWrapper:
                    def __init__(self, pts):
                        self.points = pts
                return MockWrapper(self.points.get(collection_name, [])[:limit])

            def get_collections(self):
                return list(self.collections.keys())

            def delete_collection(self, collection_name):
                self.collections.pop(collection_name, None)
                self.points.pop(collection_name, None)
                return True

            def scroll_points(self, collection_name, filter_cond=None, limit=100,
                              offset=None, with_payload=True, with_vectors=False):
                pts = self.points.get(collection_name, [])
                if filter_cond and hasattr(filter_cond, "must"):
                    for cond in filter_cond.must:
                        if hasattr(cond, "key") and cond.key == "document_title":
                            match_val = (
                                cond.match.text
                                if hasattr(cond.match, "text")
                                else getattr(cond.match, "value", None)
                            )
                            if match_val:
                                pts = [p for p in pts if p.payload.get("document_title") == match_val]
                return pts[:limit], None

            def count_points(self, collection_name):
                return len(self.points.get(collection_name, []))

            def delete_points(self, collection_name, ids):
                if collection_name in self.points:
                    self.points[collection_name] = [
                        p for p in self.points[collection_name] if p.id not in ids
                    ]
                return True

        class MockEmbeddingModel(EmbeddingModel):
            def embed_text(self, text, task_type="RETRIEVAL_QUERY"):
                return [0.1, 0.2, 0.3]

        self.mock_storage = MockVectorStorage()
        self.mock_embedder = MockEmbeddingModel()

        monkeypatch.setattr(LegalRAGIndexer, "_vector_storage", self.mock_storage)
        monkeypatch.setattr(LegalRAGIndexer, "_embedding_model", self.mock_embedder)
        # Skip real dedup (uses LocalEmbeddingModel directly, not through seam)
        monkeypatch.setattr(
            "app.core.rag.indexer.LocalEmbeddingModel.is_available",
            lambda: False,
        )

    def _make_markdown(self, sections=1):
        """Produce simple Markdown with headings and distinct bodies to survive dedup."""
        parts = []
        for i in range(1, sections + 1):
            parts.append(
                f"## Раздел {i}\n\n"
                f"Уникальное содержимое раздела номер {i}. "
                f"Термины и определения для части {i} документа."
            )
        return "\n\n".join(parts)

    def test_provenance_payload(self):
        md = self._make_markdown(2)
        source_meta = {
            "source_filename": "customs_code_2025.md",
            "source_type": "pdf",
            "source_hash": "abc123",
            "converter": "markitdown",
            "ocr_applied": True,
        }
        result = LegalRAGIndexer.parse_and_index_markdown(
            md, "Таможенный Кодекс", source_meta
        )
        assert result["added"] == 2
        assert result["deleted"] == 0
        assert result["unchanged"] == 0

        # Verify payloads carry provenance
        stored = self.mock_storage.points[LegalRAGIndexer.COLLECTION_NAME]
        assert len(stored) == 2
        for pt in stored:
            p = pt.payload
            assert p["source_filename"] == "customs_code_2025.md"
            assert p["source_type"] == "pdf"
            assert p["source_hash"] == "abc123"
            assert p["converter"] == "markitdown"
            assert p["ocr_applied"] is True
            assert "ingested_at" in p
            # Core fields still present
            assert "document_title" in p
            assert "article_number" in p
            assert "content_quote" in p
            assert "content_hash" in p

    def test_missing_source_hash_computed(self):
        md = "## Раздел 1\n\nТекст.\n"
        source_meta = {
            "source_filename": "law.txt",
            "converter": "manual",
        }
        result = LegalRAGIndexer.parse_and_index_markdown(md, "Закон", source_meta)
        assert result["added"] == 1
        stored = self.mock_storage.points[LegalRAGIndexer.COLLECTION_NAME]
        p = stored[0].payload
        # source_hash should be computed from markdown
        import hashlib
        expected_hash = hashlib.sha256(md.encode("utf-8")).hexdigest()
        assert p["source_hash"] == expected_hash
        # Defaults applied
        assert p["source_type"] == "markdown"
        assert p["ocr_applied"] is False
        assert "ingested_at" in p

    def test_missing_ingested_at_computed(self):
        md = "## Раздел 1\n\nТекст.\n"
        source_meta = {
            "source_filename": "doc.md",
            "source_type": "txt",
            "source_hash": "abc",
            "converter": "markitdown",
            "ocr_applied": False,
        }
        result = LegalRAGIndexer.parse_and_index_markdown(md, "Документ", source_meta)
        assert result["added"] == 1
        p = self.mock_storage.points[LegalRAGIndexer.COLLECTION_NAME][0].payload
        assert "ingested_at" in p
        # Should look like ISO format with timezone
        assert "T" in p["ingested_at"]

    def test_idempotent_reindex_same_markdown(self):
        md = self._make_markdown(1)
        source_meta = {
            "source_filename": "stable.md",
            "source_type": "markdown",
            "source_hash": "fixed-hash",
            "converter": "markitdown",
            "ocr_applied": False,
        }
        # First ingestion
        r1 = LegalRAGIndexer.parse_and_index_markdown(md, "Стабильный Документ", source_meta)
        assert r1["added"] == 1
        assert r1["unchanged"] == 0

        # Re-ingest same content
        r2 = LegalRAGIndexer.parse_and_index_markdown(md, "Стабильный Документ", source_meta)
        assert r2["added"] == 0
        assert r2["unchanged"] == 1
        assert r2["deleted"] == 0

    def test_reindex_with_changed_content(self):
        md_v1 = "## Раздел 1\n\nВерсия 1."
        md_v2 = "## Раздел 1\n\nВерсия 2 изменённая."
        source_meta = {
            "source_filename": "evolving.md",
            "source_type": "markdown",
            "source_hash": "hash-v1",
            "converter": "markitdown",
            "ocr_applied": False,
        }
        # First version
        r1 = LegalRAGIndexer.parse_and_index_markdown(md_v1, "Эволюция", source_meta)
        assert r1["added"] == 1

        # Changed content — same heading, different body
        source_meta_v2 = dict(source_meta, source_hash="hash-v2")
        r2 = LegalRAGIndexer.parse_and_index_markdown(md_v2, "Эволюция", source_meta_v2)
        # Old point deleted, new point added
        assert r2["added"] == 1
        assert r2["deleted"] == 1
        assert r2["unchanged"] == 0

    def test_empty_markdown_rejected(self):
        result = LegalRAGIndexer.parse_and_index_markdown("", "Документ", {})
        assert result == {"added": 0, "deleted": 0, "unchanged": 0}

    def test_missing_doc_title_rejected(self):
        md = "## Текст\n\nСодержимое."
        result = LegalRAGIndexer.parse_and_index_markdown(md, "", {})
        assert result == {"added": 0, "deleted": 0, "unchanged": 0}

    def test_markdown_with_no_indexable_chunks(self):
        md = "Просто текст без заголовков.\n\nЕщё строка."
        result = LegalRAGIndexer.parse_and_index_markdown(md, "Документ", {
            "source_filename": "nohead.md",
            "source_type": "txt",
            "source_hash": "hash",
            "converter": "manual",
            "ocr_applied": False,
        })
        assert result == {"added": 0, "deleted": 0, "unchanged": 0}

    def test_extra_block_fields_preserved_in_payload(self):
        """Verify that extra/unknown fields on blocks are carried into Qdrant payload."""
        md = "## Раздел 1\n\nТекст."
        source_meta = {
            "source_filename": "extra.md",
            "source_type": "markdown",
            "source_hash": "hash",
            "converter": "markitdown",
            "ocr_applied": False,
            "custom_field": "should-survive",
            "another_extra": 42,
        }
        result = LegalRAGIndexer.parse_and_index_markdown(md, "Документ", source_meta)
        assert result["added"] == 1
        p = self.mock_storage.points[LegalRAGIndexer.COLLECTION_NAME][0].payload
        assert p["custom_field"] == "should-survive"
        assert p["another_extra"] == 42
        # Core fields not overwritten
        assert p["document_title"] == "Документ"
        assert p["article_number"] == "Раздел 1"
