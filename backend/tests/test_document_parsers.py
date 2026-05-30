import pytest
from unittest.mock import patch
from app.core.rag.parsers import (
    BaseDocumentParser,
    CodeDocumentParser,
    DecisionDocumentParser,
    TariffTableParser,
    DocumentParserRegistry,
)
from app.core.rag.indexer import LegalRAGIndexer
from app.core.local_embeddings import LocalEmbeddingModel


@pytest.fixture(autouse=True)
def mock_embeddings():
    """Mock the local embedding model encode method to avoid heavy downloads and library mismatches."""
    with patch.object(LocalEmbeddingModel, "encode", return_value=[0.1] * 384) as mock:
        yield mock


def test_registry_resolves_default_parser_on_unknown_type():
    """Registry resolves default parser on unknown type."""
    parser = DocumentParserRegistry.get_parser("unknown_type")
    assert isinstance(parser, CodeDocumentParser)


def test_code_document_parser_splitting():
    """CodeDocumentParser correctly splits by 'Статья'."""
    raw_text = (
        "Статья 1. Общие положения.\n"
        "Это первая статья.\n"
        "Статья 2. Обязанности.\n"
        "Это вторая статья."
    )
    parser = CodeDocumentParser()
    blocks = parser.parse(raw_text, "Таможенный кодекс")

    assert len(blocks) == 2
    assert blocks[0]["article_number"] == "Статья 1"
    assert "Общие положения" in blocks[0]["content_quote"]
    assert "Это первая статья" in blocks[0]["content_quote"]
    assert blocks[1]["article_number"] == "Статья 2"
    assert "Обязанности" in blocks[1]["content_quote"]
    assert "Это вторая статья" in blocks[1]["content_quote"]


def test_decision_document_parser_splitting():
    """DecisionDocumentParser splits by 'Решение', 'Пункт', or numbered clauses."""
    raw_text = (
        "Решение Коллегии ЕЭК № 130.\n"
        "Текст решения.\n"
        "Пункт 1. Первое указание.\n"
        "Текст пункта.\n"
        "2. Второе указание.\n"
        "Еще текст."
    )
    parser = DecisionDocumentParser()
    blocks = parser.parse(raw_text, "Решение 130")

    assert len(blocks) == 3
    assert blocks[0]["article_number"] == "Решение Коллегии ЕЭК № 130"
    assert "Текст решения" in blocks[0]["content_quote"]
    assert blocks[1]["article_number"] == "Пункт 1"
    assert "Первое указание" in blocks[1]["content_quote"]
    assert "Текст пункта" in blocks[1]["content_quote"]
    assert blocks[2]["article_number"] == "2."
    assert "Второе указание" in blocks[2]["content_quote"]


def test_tariff_table_parser_csv_parsing():
    """TariffTableParser parses CSV structured lines."""
    raw_text = (
        "hs_code,name,duty\n"
        "8471300000,Компьютеры портативные,0%\n"
        "8517120000,Смартфоны,5%"
    )
    parser = TariffTableParser()
    blocks = parser.parse(raw_text, "Тарифная сетка")

    assert len(blocks) == 2
    assert blocks[0]["article_number"] == "HS 8471300000"
    assert blocks[0]["hs_code"] == "8471300000"
    assert blocks[0]["name"] == "Компьютеры портативные"
    assert blocks[0]["duty"] == "0%"
    assert "8471300000" in blocks[0]["content_quote"]

    assert blocks[1]["article_number"] == "HS 8517120000"
    assert blocks[1]["hs_code"] == "8517120000"
    assert blocks[1]["name"] == "Смартфоны"
    assert blocks[1]["duty"] == "5%"


def test_tariff_table_parser_corrupt_csv():
    """TariffTableParser gracefully handles corrupt or empty CSV data."""
    raw_text = ""
    parser = TariffTableParser()
    assert parser.parse(raw_text, "Пустая таблица") == []


def test_custom_parser_registration():
    """Verify registry supports registering and retrieving new parsers dynamically."""

    class CustomParser(BaseDocumentParser):
        def parse(self, raw_text: str, doc_title: str):
            return [{"custom": "data"}]

    DocumentParserRegistry.register("custom", CustomParser())
    parser = DocumentParserRegistry.get_parser("custom")
    assert isinstance(parser, CustomParser)
    assert parser.parse("", "") == [{"custom": "data"}]


def test_indexer_integration():
    """parse_and_index_document uses the registered parser."""
    # Setup clean in-memory collection
    LegalRAGIndexer.setup_collection(force_recreate=True)

    # We will index a CSV using "tariff" doc_type
    raw_csv = "hs_code,name,duty\n9999999999,Тестовый Товар,12%"

    indexed_count = LegalRAGIndexer.parse_and_index_document(
        raw_csv, "Интеграционный тест тарифа", doc_type="tariff"
    )

    assert indexed_count == 1
