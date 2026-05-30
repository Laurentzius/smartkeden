import pytest

from app.core.rag.indexer import LegalRAGIndexer


pytestmark = pytest.mark.sequential


def _block(article_number: str, content: str) -> dict:
    return {
        "document_title": "Test law",
        "article_number": article_number,
        "content_quote": content,
        "tags": [article_number],
        "keywords": article_number,
    }


def _patch_embeddings(monkeypatch, vectors: dict[str, list[float]]) -> None:
    monkeypatch.setattr("app.core.rag.indexer.LocalEmbeddingModel.is_available", lambda: True)

    def encode(text: str) -> list[float]:
        for marker, vector in vectors.items():
            if marker in text:
                return vector
        return [0.0, 0.0, 1.0]

    monkeypatch.setattr("app.core.rag.indexer.LocalEmbeddingModel.encode", encode)


def test_deduplicate_blocks_local_empty_or_single(monkeypatch):
    _patch_embeddings(monkeypatch, {})

    assert LegalRAGIndexer.deduplicate_blocks_local([]) is None

    single = [_block("A", "single")]
    assert LegalRAGIndexer.deduplicate_blocks_local(single) == single


def test_deduplicate_blocks_local_same_article_merges_unique_lines(monkeypatch):
    _patch_embeddings(
        monkeypatch,
        {
            "part one": [1.0, 0.0, 0.0],
            "part two": [1.0, 0.0, 0.0],
        },
    )

    result = LegalRAGIndexer.deduplicate_blocks_local(
        [_block("A", "part one"), _block("A", "part two")],
        similarity_threshold=0.95,
        max_iterations=1,
    )

    assert result is not None
    assert len(result) == 1
    assert result[0]["article_number"] == "A"
    assert result[0]["content_quote"] == "part one\npart two"


def test_deduplicate_blocks_local_different_articles_adds_duplicate_prefix(monkeypatch):
    _patch_embeddings(
        monkeypatch,
        {
            "first content": [1.0, 0.0, 0.0],
            "second content": [1.0, 0.0, 0.0],
        },
    )

    result = LegalRAGIndexer.deduplicate_blocks_local(
        [_block("A", "first content"), _block("B", "second content")],
        similarity_threshold=0.95,
        max_iterations=1,
    )

    assert result is not None
    assert len(result) == 1
    assert result[0]["article_number"] == "A"
    assert result[0]["content_quote"] == "first content\n---\n(дубль из B)\nsecond content"


def test_deduplicate_blocks_local_keeps_dissimilar_blocks(monkeypatch):
    _patch_embeddings(
        monkeypatch,
        {
            "alpha": [1.0, 0.0, 0.0],
            "beta": [0.0, 1.0, 0.0],
            "gamma": [0.0, 0.0, 1.0],
        },
    )

    blocks = [_block("A", "alpha"), _block("B", "beta"), _block("C", "gamma")]
    result = LegalRAGIndexer.deduplicate_blocks_local(
        blocks,
        similarity_threshold=0.95,
        max_iterations=1,
    )

    assert result == blocks


def test_deduplicate_blocks_local_merges_only_similar_cluster(monkeypatch):
    _patch_embeddings(
        monkeypatch,
        {
            "alpha one": [1.0, 0.0, 0.0],
            "alpha two": [1.0, 0.0, 0.0],
            "unrelated": [0.0, 1.0, 0.0],
        },
    )

    result = LegalRAGIndexer.deduplicate_blocks_local(
        [_block("A", "alpha one"), _block("A", "alpha two"), _block("C", "unrelated")],
        similarity_threshold=0.95,
        max_iterations=1,
    )

    assert result is not None
    assert len(result) == 2
    assert result[0]["content_quote"] == "alpha one\nalpha two"
    assert result[1]["content_quote"] == "unrelated"
