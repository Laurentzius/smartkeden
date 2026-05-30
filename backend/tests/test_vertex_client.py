from app.core.vertex_client import GeminiVertexClient
from pydantic import BaseModel, Field


class HSCandidate(BaseModel):
    code: str = Field(..., description="10-digit HS code")
    reasoning: str = Field(..., description="Justification")
    duty_rate: float = Field(..., description="Import duty percent")


def test_gemini_vertex_client_mock_mode():
    # Arrange
    prompt = "Опиши код ТН ВЭД для детских игрушек из пластика"

    # Act
    res = GeminiVertexClient.generate_structured_content(prompt, HSCandidate)

    # Assert
    assert res is not None
    assert isinstance(res, HSCandidate)
    from app.core.llm.generator import get_generator, GeminiTextGenerator

    gen = get_generator()
    if gen._client_mode == GeminiTextGenerator.MOCK:
        assert res.code == "mock"
        assert res.duty_rate == 0.0
    else:
        assert len(res.code) > 0
        assert res.duty_rate >= 0


def test_gemini_vertex_client_chat_mock():
    # Arrange
    system = "Вы профессиональный таможенный брокер в Казахстане."
    history = [
        {
            "role": "user",
            "content": "Какие документы нужны для импорта медицинских масок?",
        }
    ]

    # Act
    res = GeminiVertexClient.generate_chat_response(system, history)

    # Assert
    assert len(res) > 0


def test_gemini_vertex_client_embedding_mock():
    """get_text_embedding should return a vector with the expected dimension.
    Priority: Gemini API → Vertex AI → local model → mock zeros.
    In test mode (no API key), the path falls through to local model (384-dim, non-zero)
    or mock zeros if sentence-transformers is unavailable."""
    # Arrange
    text = "Налог на добавленную стоимость"
    # Act
    vec = GeminiVertexClient.get_text_embedding(text)
    # Assert
    assert isinstance(vec, list)
    assert len(vec) == 384  # settings.EMBEDDING_DIMENSION
    # When local model is available → non-zero values
    # When only mock path → all zeros


def test_gemini_vertex_client_real_sdk_mock():
    # Arrange
    from unittest.mock import MagicMock
    import json
    from app.core.llm.generator import get_generator, set_generator, GeminiTextGenerator

    # Mock the client structures
    mock_client = MagicMock()
    mock_response = MagicMock()
    # Setup response content conforming to HSCandidate schema
    candidate_data = {
        "code": "8517130000",
        "reasoning": "Mocked SDK response for testing",
        "duty_rate": 10.0,
    }
    mock_response.text = json.dumps(candidate_data)
    # Mocking usage metadata
    mock_usage = MagicMock()
    mock_usage.prompt_token_count = 120
    mock_usage.candidates_token_count = 45
    mock_response.usage_metadata = mock_usage
    # Set the mock client return value
    mock_client.models.generate_content.return_value = mock_response
    # Create generator with mock client
    mock_gen = GeminiTextGenerator()
    mock_gen._client = mock_client
    mock_gen._client_mode = GeminiTextGenerator.API_KEY
    mock_gen._initialized = True
    orig = get_generator()
    set_generator(mock_gen)
    try:
        # Act
        res = GeminiVertexClient.generate_structured_content(
            prompt="Test prompt", response_schema=HSCandidate
        )
        # Assert
        assert isinstance(res, HSCandidate)
        assert res.code == "8517130000"
        assert res.duty_rate == 10.0
        assert res.reasoning == "Mocked SDK response for testing"
        # Verify the generate_content call structure
        mock_client.models.generate_content.assert_called_once()
        call_kwargs = mock_client.models.generate_content.call_args[1]
        assert "model" in call_kwargs
        assert "contents" in call_kwargs
        assert "config" in call_kwargs
    finally:
        # Restore original state
        set_generator(orig)
