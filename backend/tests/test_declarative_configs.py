import pytest
from unittest.mock import patch, mock_open
from fastapi.testclient import TestClient
from app.main import app
from app.core.orchestrator.config_loader import ConfigLoader
from app.core.orchestrator.models import IntentType, OrchestrateResponse


def test_config_loader_singleton():
    """ConfigLoader must follow a singleton pattern."""
    loader1 = ConfigLoader()
    loader2 = ConfigLoader()
    assert loader1 is loader2


def test_config_loader_load_yaml():
    """ConfigLoader loads and caches YAML configuration files."""
    loader = ConfigLoader()
    faq = loader.load_yaml("faq.yaml")
    assert isinstance(faq, dict)
    assert "general" in faq

    intents = loader.load_yaml("intents.yaml")
    assert isinstance(intents, dict)
    assert "system_prompt" in intents
    assert "examples" in intents


def test_config_loader_check_faq_matches():
    """check_faq must perform robust keyword matching (case-insensitive, strips punctuation)."""
    loader = ConfigLoader()

    # Exact match
    res1 = loader.check_faq("таможенный сбор")
    assert res1 is not None
    assert "20 000 тенге" in res1

    # Mixed case with punctuation
    res2 = loader.check_faq("СКОЛЬКО СБОР???")
    assert res2 is not None
    assert "20 000 тенге" in res2

    # Another category (limits)
    res3 = loader.check_faq("беспошлинный лимит")
    assert res3 is not None
    assert "1000 евро" in res3


def test_config_loader_check_faq_no_match():
    """check_faq must return None for queries that do not match keywords."""
    loader = ConfigLoader()
    res = loader.check_faq("какие новости на границе?")
    assert res is None


def test_config_loader_fallback_on_corrupted_or_missing():
    """ConfigLoader handles corrupted YAML files gracefully and returns fallbacks."""
    loader = ConfigLoader()

    # Test missing file
    data_missing = loader.load_yaml("missing_file_random.yaml")
    assert data_missing == {}

    # Test default fallback on intents if missing/corrupt
    with patch("builtins.open", side_effect=Exception("Read error")):
        # Clear cache for the test to bypass it
        ConfigLoader._cache.clear()
        config = loader.get_intent_config()
        assert "system_prompt" in config
        assert "examples" in config
        assert len(config["examples"]) > 0

    # Reset cache to be clean
    ConfigLoader._cache.clear()


def test_api_orchestrate_faq_redirect():
    """API orchestrate route must return instant FAQ answers directly without LLM."""
    client = TestClient(app)
    response = client.post(
        "/api/orchestrate",
        data={"text": "Каков лимит беспошлинного ввоза для посылок?"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "question_about_law"
    assert "1000 евро" in data["message"]
    assert data["pipeline_results"] is not None
    assert data["pipeline_results"]["fastpath"] is True
    assert data["pipeline_results"]["source"] == "faq.yaml"
