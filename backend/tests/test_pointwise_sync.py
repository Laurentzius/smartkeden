import pytest
from app.core.rag.indexer import LegalRAGIndexer


def test_pointwise_id_determinism():
    """Verify that generate_point_id is deterministic and respects content changes."""
    doc_title = "Тестовый Кодекс РК"
    article_number = "Статья 1"
    content_1 = "Первый параграф текста."
    content_2 = "Второй параграф текста."

    id1 = LegalRAGIndexer.generate_point_id(doc_title, article_number, content_1)
    id1_again = LegalRAGIndexer.generate_point_id(doc_title, article_number, content_1)
    id2 = LegalRAGIndexer.generate_point_id(doc_title, article_number, content_2)

    assert id1 == id1_again, "Point ID generation should be deterministic."
    assert id1 != id2, "Different content should generate different point IDs."


def test_pointwise_delta_identical_doc():
    """Verify delta computation on identical document results in 0 added, 0 deleted."""
    # Setup collection
    assert LegalRAGIndexer.setup_collection(force_recreate=True) is True

    doc_title = "Таможенный кодекс"
    blocks = [
        {
            "document_title": doc_title,
            "article_number": "Статья 1",
            "content_quote": "Текст первого блока.",
        },
        {
            "document_title": doc_title,
            "article_number": "Статья 2",
            "content_quote": "Текст второго блока.",
        },
    ]

    # Initial Indexing
    res1 = LegalRAGIndexer.update_document_index(blocks, doc_title)
    assert res1["added"] == 2
    assert res1["deleted"] == 0
    assert res1["unchanged"] == 0

    # Index again with identical document
    res2 = LegalRAGIndexer.update_document_index(blocks, doc_title)
    assert res2["added"] == 0
    assert res2["deleted"] == 0
    assert res2["unchanged"] == 2


def test_pointwise_delta_delete_paragraph():
    """Verify obsolete chunks are deleted when a paragraph is removed."""
    assert LegalRAGIndexer.setup_collection(force_recreate=True) is True

    doc_title = "Закон об Экспорте"
    blocks_initial = [
        {
            "document_title": doc_title,
            "article_number": "Статья 5",
            "content_quote": "Определение экспорта.",
        },
        {
            "document_title": doc_title,
            "article_number": "Статья 6",
            "content_quote": "Правила вывоза товаров.",
        },
    ]

    # First update
    res1 = LegalRAGIndexer.update_document_index(blocks_initial, doc_title)
    assert res1["added"] == 2

    # Second update, removing Article 6
    blocks_updated = [
        {
            "document_title": doc_title,
            "article_number": "Статья 5",
            "content_quote": "Определение экспорта.",
        }
    ]

    res2 = LegalRAGIndexer.update_document_index(blocks_updated, doc_title)
    assert res2["added"] == 0
    assert res2["deleted"] == 1
    assert res2["unchanged"] == 1


def test_pointwise_delta_add_paragraph():
    """Verify new chunks are embedded and upserted when added."""
    assert LegalRAGIndexer.setup_collection(force_recreate=True) is True

    doc_title = "Закон о Налогах"
    blocks_initial = [
        {
            "document_title": doc_title,
            "article_number": "Статья 10",
            "content_quote": "Основные понятия налога.",
        }
    ]

    # First update
    res1 = LegalRAGIndexer.update_document_index(blocks_initial, doc_title)
    assert res1["added"] == 1

    # Second update, adding Article 11 and Article 12
    blocks_updated = [
        {
            "document_title": doc_title,
            "article_number": "Статья 10",
            "content_quote": "Основные понятия налога.",
        },
        {
            "document_title": doc_title,
            "article_number": "Статья 11",
            "content_quote": "Ставка налога 12 процентов.",
        },
        {
            "document_title": doc_title,
            "article_number": "Статья 12",
            "content_quote": "Сроки уплаты налога.",
        },
    ]

    res2 = LegalRAGIndexer.update_document_index(blocks_updated, doc_title)
    assert res2["added"] == 2
    assert res2["deleted"] == 0
    assert res2["unchanged"] == 1


def test_parse_and_index_document_end_to_end():
    """Verify end-to-end integration of parse_and_index_document using pointwise sync."""
    assert LegalRAGIndexer.setup_collection(force_recreate=True) is True

    doc_title = "Кодекс РК о браке"
    raw_text = (
        "Статья 1. Определение брака.\n"
        "Брак - это союз мужчины и женщины.\n"
        "Статья 2. Условия заключения брака.\n"
        "Для заключения брака необходимо согласие."
    )

    # First run: Parses and indexes
    added_count = LegalRAGIndexer.parse_and_index_document(raw_text, doc_title)
    assert added_count > 0

    # Second run with exact same text: 0 points added
    re_added_count = LegalRAGIndexer.parse_and_index_document(raw_text, doc_title)
    assert re_added_count == 0
