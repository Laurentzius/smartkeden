"""Integration tests: RAG Service references Config Service for rates."""

import json
import tempfile
from pathlib import Path

import pytest


def _mock_config_db(data: dict) -> str:
    tmpdir = Path(tempfile.mkdtemp())
    path = tmpdir / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@pytest.fixture
def patched_config(monkeypatch):
    """Patch config_service to use a temp config DB."""
    data = {
        "rates": {
            "import_vat": [
                {
                    "value": 0.16,
                    "effective_date": "2026-01-01",
                    "expiry_date": None,
                    "version": 2,
                    "created_by": "system",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            ],
            "mci": [
                {
                    "year": 2026,
                    "value": 4325.0,
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            ],
            "customs_processing_fee": [
                {
                    "value": 20000.0,
                    "effective_date": "2020-01-01",
                    "expiry_date": None,
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2020-01-01T00:00:00Z",
                }
            ],
            "recycling_rates": [],
            "excise_rates": [],
        }
    }
    path = _mock_config_db(data)
    monkeypatch.setattr(
        "app.core.config_service._resolve_config_path", lambda: Path(path)
    )
    import app.core.config_service as mod

    mod.ConfigService._instance = None
    return path


class TestRAGReferencesConfigForRates:
    def test_get_current_rates_returns_dict(self, patched_config):
        """RAG Service get_current_rates() should return a dict from ConfigService."""
        from app.core.rag.service import LegalRAGService
        from app.core.rag.seams import (
            QdrantVectorStorageAdapter,
            LocalEmbeddingModelAdapter,
        )
        from app.core.llm.generator import get_generator

        svc = LegalRAGService(
            vector_storage=QdrantVectorStorageAdapter(),
            embedding_model=LocalEmbeddingModelAdapter(),
            text_generator=get_generator(),
        )
        rates = svc.get_current_rates()
        assert isinstance(rates, dict)
        assert rates.get("import_vat") == 0.16
        assert rates.get("customs_processing_fee") == 20000.0
        assert rates.get("mci") == 4325.0

    def test_get_current_rates_handles_failure(self, monkeypatch):
        """get_current_rates() returns fallback values when ConfigService fails."""
        monkeypatch.setattr(
            "app.core.config_service._load_config_db",
            lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")),
        )
        import app.core.config_service as mod

        mod.ConfigService._instance = None

        from app.core.rag.service import LegalRAGService
        from app.core.rag.seams import (
            QdrantVectorStorageAdapter,
            LocalEmbeddingModelAdapter,
        )
        from app.core.llm.generator import get_generator

        svc = LegalRAGService(
            vector_storage=QdrantVectorStorageAdapter(),
            embedding_model=LocalEmbeddingModelAdapter(),
            text_generator=get_generator(),
        )
        rates = svc.get_current_rates()
        # ConfigService.get_all_current() returns fallback values on failure
        assert isinstance(rates, dict)
        assert "import_vat" in rates
        # Fallback import_vat = business_rules.import_vat_rate = 0.16
        assert rates["import_vat"] == 0.16
