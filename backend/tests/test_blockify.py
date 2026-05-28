import pytest
import asyncio
from app.core.rag.indexer import LegalRAGIndexer
from app.core.rag.service import LegalRAGService


# ---------------------------------------------------------------------------
# Local deduplication tests (replaces Blockify Distill)
# ---------------------------------------------------------------------------

def test_deduplicate_blocks_local_two_identical_same_article():
    """2 identical blocks with same article_number → merged into 1 block."""
    blocks = [
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Текст А",
            "tags": ["TEST"],
            "keywords": "тест",
        },
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Текст А",
            "tags": ["TEST"],
            "keywords": "тест",
        },
    ]
    result = LegalRAGIndexer.deduplicate_blocks_local(blocks)
    assert result is not None
    assert len(result) == 1
    assert result[0]["article_number"] == "Статья 1"
    assert result[0]["content_quote"] == "Текст А"


def test_deduplicate_blocks_local_same_article_diff_content():
    """2 blocks same article_number, different content → merged with line dedup."""
    blocks = [
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Часть 1",
            "tags": ["TEST"],
            "keywords": "тест",
        },
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Часть 2",
            "tags": ["TEST"],
            "keywords": "тест",
        },
    ]
    result = LegalRAGIndexer.deduplicate_blocks_local(blocks)
    assert result is not None
    assert len(result) == 1
    assert result[0]["article_number"] == "Статья 1"
    # Both parts should be present, order preserved
    assert "Часть 1" in result[0]["content_quote"]
    assert "Часть 2" in result[0]["content_quote"]


def test_deduplicate_blocks_local_diff_article_same_content():
    """2 blocks different article_number, similar content → merged with prefix."""
    blocks = [
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья А",
            "content_quote": "Одинаковый текст",
            "tags": ["TEST"],
            "keywords": "тест",
        },
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья Б",
            "content_quote": "Одинаковый текст",
            "tags": ["TEST"],
            "keywords": "тест",
        },
    ]
    result = LegalRAGIndexer.deduplicate_blocks_local(blocks)
    assert result is not None
    assert len(result) == 1
    assert result[0]["article_number"] == "Статья А"
    assert "(дубль из Статья Б)" in result[0]["content_quote"]
    assert "Одинаковый текст" in result[0]["content_quote"]


def test_deduplicate_blocks_local_three_blocks():
    """3 blocks, 2 identical + 1 different → 2 blocks (identical merge at any threshold)."""
    blocks = [
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Налог на добавленную стоимость в Республике Казахстан устанавливается в размере 12 процентов если иное не предусмотрено настоящим Кодексом",
            "tags": ["TAX"],
            "keywords": "ндс, налог",
        },
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Налог на добавленную стоимость в Республике Казахстан устанавливается в размере 12 процентов если иное не предусмотрено настоящим Кодексом",
            "tags": ["TAX"],
            "keywords": "ндс, налог",
        },
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 2",
            "content_quote": "Технический регламент Таможенного союза О безопасности колесных транспортных средств устанавливает требования к автомобильной технике выпускаемой в обращение на территории государств членов Союза",
            "tags": ["TECH_REG"],
            "keywords": "техрегламент, транспорт",
        },
    ]
    # Use 0.99 threshold: identical texts (sim=1.0) merge, different texts don't
    result = LegalRAGIndexer.deduplicate_blocks_local(blocks, similarity_threshold=0.99)
    assert result is not None
    assert len(result) == 2


def test_deduplicate_blocks_local_empty_or_single():
    """0 blocks → None; 1 block → as-is."""
    # Empty
    result = LegalRAGIndexer.deduplicate_blocks_local([])
    assert result is None

    # Single
    blocks = [
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Содержание.",
            "tags": ["TEST"],
            "keywords": "тест",
        },
    ]
    result = LegalRAGIndexer.deduplicate_blocks_local(blocks)
    assert result is not None
    assert len(result) == 1
    assert result[0]["content_quote"] == "Содержание."


def test_deduplicate_blocks_local_all_different():
    """All dissimilar blocks → unchanged (same count)."""
    blocks = [
        {
            "document_title": "Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Налог на добавленную стоимость в Республике Казахстан устанавливается в размере 12 процентов",
            "tags": ["TAX"],
            "keywords": "ндс, налог",
        },
        {
            "document_title": "Кодекс",
            "article_number": "Статья 500",
            "content_quote": "Таможенные пошлины уплачиваются плательщиками в бюджет до принятия таможенной декларации",
            "tags": ["CUSTOMS"],
            "keywords": "пошлины, таможня",
        },
        {
            "document_title": "Кодекс",
            "article_number": "Статья 700",
            "content_quote": "Акцизы на импортируемые подакцизные товары подлежат уплате по ставкам Единого таможенного тарифа",
            "tags": ["EXCISE"],
            "keywords": "акцизы",
        },
    ]
    result = LegalRAGIndexer.deduplicate_blocks_local(blocks, similarity_threshold=0.95)
    assert result is not None
    assert len(result) == 3
    # First block unchanged
    assert result[0]["article_number"] == "Статья 1"
    assert result[0]["content_quote"] == blocks[0]["content_quote"]


def test_deduplicate_blocks_local_deterministic():
    """Same input → same output (deterministic)."""
    blocks = [
        {
            "document_title": "Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Налог на добавленную стоимость",
            "tags": ["TAX"],
            "keywords": "ндс",
        },
        {
            "document_title": "Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Налог на добавленную стоимость",
            "tags": ["TAX"],
            "keywords": "ндс",
        },
        {
            "document_title": "Кодекс",
            "article_number": "Статья 2",
            "content_quote": "Ставка налога на прибыль",
            "tags": ["TAX"],
            "keywords": "прибыль",
        },
    ]
    result1 = LegalRAGIndexer.deduplicate_blocks_local(blocks)
    result2 = LegalRAGIndexer.deduplicate_blocks_local(blocks)
    assert result1 is not None
    assert result2 is not None
    assert len(result1) == len(result2)
    assert result1[0]["content_quote"] == result2[0]["content_quote"]


# ---------------------------------------------------------------------------
# Keep existing index_blocks tests (these are about Qdrant indexing, not
# Blockify)
# ---------------------------------------------------------------------------

def test_index_blocks_deterministic_uuids():
    """index_blocks should use deterministic UUIDv5 point IDs based on
    document_title + article_number, so re-indexing the same blocks
    produces the same point IDs."""
    LegalRAGIndexer.setup_collection(force_recreate=True)

    blocks = [
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Содержание статьи 1.",
            "tags": ["TEST"],
            "keywords": "тест",
        }
    ]

    indexed_count = LegalRAGIndexer.index_blocks(blocks)
    assert indexed_count == 1

    # Re-index same blocks — should skip due to dedup
    indexed_count_2 = LegalRAGIndexer.index_blocks(blocks)
    assert indexed_count_2 == 0  # Skipped because content_hash matches


def test_index_blocks_updates_on_content_change():
    """If content_quote changes but document_title + article_number stay the same,
    index_blocks should detect the change and overwrite."""
    LegalRAGIndexer.setup_collection(force_recreate=True)

    blocks_v1 = [
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Оригинальное содержание.",
            "tags": ["TEST"],
            "keywords": "тест",
        }
    ]

    indexed_v1 = LegalRAGIndexer.index_blocks(blocks_v1)
    assert indexed_v1 == 1

    blocks_v2 = [
        {
            "document_title": "Тестовый Кодекс",
            "article_number": "Статья 1",
            "content_quote": "Изменённое содержание!",
            "tags": ["TEST"],
            "keywords": "тест",
        }
    ]

    indexed_v2 = LegalRAGIndexer.index_blocks(blocks_v2)
    # Should detect content change and upsert (count=1 new point)
    assert indexed_v2 == 1


def test_parse_and_index_document_with_local_fallback():
    """parse_and_index_document should parse and index document, using local
    dedup, producing indexable blocks."""
    LegalRAGIndexer.setup_collection(force_recreate=True)

    raw_text = "Статья 500. Таможенные пошлины. Пошлины уплачиваются плательщиками в бюджет."
    indexed_count = LegalRAGIndexer.parse_and_index_document(raw_text, "Кодекс РК")
    assert indexed_count == 1

    # Verify the indexed content is searchable
    res = asyncio.run(LegalRAGService.query_legal_base("Расскажи про таможенные пошлины"))
    assert res is not None
    assert any("500" in chunk.article_number for chunk in res.supporting_laws)
