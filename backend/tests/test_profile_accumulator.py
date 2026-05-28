import pytest
from app.core.orchestrator.models import ChatMessage
from app.core.orchestrator.profile_extractor import ProfileExtractor, CustomsProfileAccumulator, ProfileExtractionResult


def test_profile_extractor_fallback_extraction_price_currency():
    """Verify that regex fallback correctly extracts price and currency."""
    text = "Моя посылка стоит 5000 USD"
    result = ProfileExtractor._fallback_extraction(text, history=None)
    
    assert isinstance(result, ProfileExtractionResult)
    assert result.accumulated_profile.invoice_price == 5000.0
    assert result.accumulated_profile.currency == "USD"
    assert "duty_rate_percent" in result.missing_fields


def test_profile_extractor_fallback_accumulation():
    """Verify that fallback correctly accumulates parameters from history."""
    history = [
        ChatMessage(role="user", content="Код ТН ВЭД 8543709000, пошлина 10%"),
        ChatMessage(role="assistant", content="Рекомендуемый код: 8543709000, пошлина 10%. Требуется утильсбор.")
    ]
    text = "Посчитай для цены $5000"
    result = ProfileExtractor._fallback_extraction(text, history=history)
    
    assert result.accumulated_profile.invoice_price == 5000.0
    assert result.accumulated_profile.currency == "USD"
    assert result.accumulated_profile.duty_rate_percent == 10.0
    assert result.accumulated_profile.hs_code == "8543709000"
    assert result.accumulated_profile.is_subject_to_recycling_fee is True
    assert len(result.missing_fields) == 0


def test_profile_extractor_fallback_missing_fields():
    """Verify that fallback identifies missing fields correctly."""
    text = "Привет!"
    result = ProfileExtractor._fallback_extraction(text, history=None)
    
    assert "invoice_price" in result.missing_fields
    assert "currency" in result.missing_fields
    assert "duty_rate_percent" in result.missing_fields
    assert "Пожалуйста, укажите стоимость" in result.next_question


def test_profile_extractor_mock_llm_behavior(monkeypatch):
    """Verify that the extractor returns structured outputs when using mock client mode."""
    from app.core.vertex_client import GeminiVertexClient
    
    # Force Gemini client mode to mock so we can test the structured response flow safely
    monkeypatch.setattr(GeminiVertexClient, "_client_mode", GeminiVertexClient.MOCK)
    
    text = "Стоимость 12000 EUR, пошлина 5%"
    result = ProfileExtractor.extract(history=None, current_text=text)
    
    assert isinstance(result, ProfileExtractionResult)
    assert isinstance(result.accumulated_profile, CustomsProfileAccumulator)
    assert isinstance(result.missing_fields, list)
    assert isinstance(result.next_question, str)
