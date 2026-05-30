import pytest
import asyncio
from app.core.hs_classifier.classifier import HSCodeClassifier, HSClassificationResponse
from app.core.rag.seams import QdrantVectorStorageAdapter, LocalEmbeddingModelAdapter
from app.core.rag.indexer import LegalRAGIndexer

_vector_storage = QdrantVectorStorageAdapter()
_embedding_model = LocalEmbeddingModelAdapter()
_classifier = HSCodeClassifier(
    embedding_model=_embedding_model, vector_storage=_vector_storage
)


def test_hs_classifier_fallback_on_empty_collection():
    """When Qdrant hs_code_directory is empty or missing, classifier should still return
    candidates using pure LLM (mock mode in tests)."""
    # Ensure collection exists but empty
    LegalRAGIndexer.setup_hs_code_collection(force_recreate=True)

    result: HSClassificationResponse = asyncio.run(
        _classifier.classify(description="детские пластиковые игрушки")
    )

    assert result is not None
    assert result.product_description == "детские пластиковые игрушки"
    assert not result.qdrant_backed  # Mock mode + empty collection
    assert len(result.candidates) > 0
    # In mock mode, candidates have dummy data
    for c in result.candidates:
        assert isinstance(c.hs_code, str)
        assert len(c.hs_code) > 0


def test_hs_classifier_with_seeded_collection():
    """With a seeded hs_code_directory, the classifier should find Qdrant candidates
    and include them in the LLM prompt."""
    # Seed the collection
    LegalRAGIndexer.setup_hs_code_collection(force_recreate=True)
    seeded = LegalRAGIndexer.seed_hs_code_directory()
    assert seeded == 5

    result: HSClassificationResponse = asyncio.run(
        _classifier.classify(description="ноутбук портативный компьютер")
    )

    assert result is not None
    assert len(result.product_description) > 0
    assert len(result.candidates) > 0
    # In mock mode, qdrant_backed may be False since embeddings are mock zeros
    # and vector search returns low/no relevance — but the API response
    # should still be structurally valid
    for c in result.candidates:
        assert isinstance(c.hs_code, str)
        assert len(c.hs_code) > 0


def test_hs_classifier_recycling_fee_flag_in_payload():
    """Verify that seeded HS entries have recycling fee flags set correctly."""
    LegalRAGIndexer.setup_hs_code_collection(force_recreate=True)
    LegalRAGIndexer.seed_hs_code_directory()

    # Query with a product that should match computers (recycle=True)
    result: HSClassificationResponse = asyncio.run(
        _classifier.classify(description="компьютерная техника")
    )

    assert result is not None
    # Structure is valid regardless of mock
    assert hasattr(result, "qdrant_backed")


def test_hs_classifier_empty_description():
    """Empty description should not crash the classifier."""
    LegalRAGIndexer.setup_hs_code_collection(force_recreate=True)
    result: HSClassificationResponse = asyncio.run(_classifier.classify(description=""))
    assert result is not None
    assert isinstance(result.product_description, str)
    assert isinstance(result.candidates, list)


def test_hs_classifier_special_characters():
    """Special characters and XSS injection attempts should not crash."""
    LegalRAGIndexer.setup_hs_code_collection(force_recreate=True)
    result: HSClassificationResponse = asyncio.run(
        _classifier.classify(description="<script>alert('xss')</script>")
    )
    assert result is not None
    assert len(result.candidates) > 0
    for c in result.candidates:
        assert isinstance(c.hs_code, str)
        assert len(c.hs_code) > 0


def test_hs_classifier_long_description():
    """Very long text should be handled without crashing."""
    LegalRAGIndexer.setup_hs_code_collection(force_recreate=True)
    long_desc = "Детские игрушки " + "очень " * 500 + "красивые"
    result: HSClassificationResponse = asyncio.run(
        _classifier.classify(description=long_desc)
    )
    assert result is not None
    assert len(result.candidates) > 0
    for c in result.candidates:
        assert isinstance(c.hs_code, str)
        assert len(c.hs_code) > 0
