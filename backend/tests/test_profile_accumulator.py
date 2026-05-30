import pytest
from app.core.orchestrator.models import ChatMessage
from app.core.orchestrator.profile_extractor import (
    ProfileExtractor,
    CustomsProfileAccumulator,
    ProfileExtractionResult,
)


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
        ChatMessage(
            role="assistant",
            content="Рекомендуемый код: 8543709000, пошлина 10%. Требуется утильсбор.",
        ),
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
    from app.core.llm.generator import get_generator, GeminiTextGenerator

    gen = GeminiTextGenerator()
    gen._client_mode = GeminiTextGenerator.MOCK
    gen._initialized = True
    monkeypatch.setattr("app.core.llm.generator._generator", gen)

    text = "Стоимость 12000 EUR, пошлина 5%"
    result = ProfileExtractor.extract(history=None, current_text=text)

    assert isinstance(result, ProfileExtractionResult)
    assert isinstance(result.accumulated_profile, CustomsProfileAccumulator)
    assert isinstance(result.missing_fields, list)
    assert isinstance(result.next_question, str)


def test_profile_extractor_fallback_empty_text():
    """Empty text should return all missing fields without crashing."""
    result = ProfileExtractor._fallback_extraction("", history=None)
    assert isinstance(result, ProfileExtractionResult)
    assert "invoice_price" in result.missing_fields
    assert "currency" in result.missing_fields
    assert "duty_rate_percent" in result.missing_fields


def test_profile_extractor_fallback_special_chars():
    """Special characters and XSS injection should not cause incorrect extraction."""
    text = "<script>alert('xss')</script> цена 5000 USD"
    result = ProfileExtractor._fallback_extraction(text, history=None)
    assert result.accumulated_profile.invoice_price == 5000.0
    assert result.accumulated_profile.currency == "USD"
    assert "duty_rate_percent" in result.missing_fields


def test_profile_extractor_fallback_text_with_no_price():
    """Text with no numeric price should leave invoice_price as None."""
    text = "Расскажи мне про таможенное оформление"
    result = ProfileExtractor._fallback_extraction(text, history=None)
    assert result.accumulated_profile.invoice_price is None
    assert "invoice_price" in result.missing_fields


def test_profile_extractor_fallback_history_with_only_assistant():
    """History with only assistant messages should not crash."""
    history = [
        ChatMessage(
            role="assistant", content="Обратитесь к таможенному брокеру для расчёта."
        ),
    ]
    text = "Что такое пошлина?"
    result = ProfileExtractor._fallback_extraction(text, history=history)
    assert isinstance(result, ProfileExtractionResult)
    assert result.accumulated_profile.invoice_price is None
