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
    if GeminiVertexClient._client_mode == "mock":
        assert res.code == "Демонстрационная строка"
        assert res.duty_rate == 0.9
    else:
        assert len(res.code) > 0
        assert res.duty_rate >= 0

def test_gemini_vertex_client_chat_mock():
    # Arrange
    system = "Вы профессиональный таможенный брокер в Казахстане."
    history = [{"role": "user", "content": "Какие документы нужны для импорта медицинских масок?"}]
    
    # Act
    res = GeminiVertexClient.generate_chat_response(system, history)
    
    # Assert
    if GeminiVertexClient._client_mode == "mock":
        assert "демонстрационный" in res or "Vertex AI" in res
    else:
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
