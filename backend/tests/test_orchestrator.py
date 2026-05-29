import json
import pytest
from app.core.orchestrator.models import IntentType, IntentClassification
from app.core.orchestrator.router import IntentClassifier
from app.core.orchestrator.profile_extractor import ProfileExtractionResult, CustomsProfileAccumulator


# ═══════════════════════════════════════════════════════════════════════════
#  Intent Classification Tests  (unchanged — unit-test the classifier)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_intent_classify_greeting():
    """Greeting messages should be classified as greeting intent."""
    result = await IntentClassifier.classify("Привет!")
    assert result.intent == IntentType.greeting
    assert result.confidence >= 0.7


@pytest.mark.asyncio
async def test_intent_classify_calculation():
    """Messages with calculation keywords should be classified as calculation_request."""
    result = await IntentClassifier.classify("посчитай пошлину на iPhone")
    assert result.intent == IntentType.calculation_request
    assert result.confidence >= 0.7


@pytest.mark.asyncio
async def test_intent_classify_hs_code():
    """Messages requesting HS code classification should route to product_description."""
    result = await IntentClassifier.classify("определи код ТН ВЭД для ноутбука")
    assert result.intent == IntentType.product_description
    assert result.confidence >= 0.7


@pytest.mark.asyncio
async def test_intent_classify_legal_question():
    """Messages about legislation should be classified as question_about_law."""
    result = await IntentClassifier.classify("что говорит закон о таможенной стоимости")
    assert result.intent == IntentType.question_about_law
    assert result.confidence >= 0.7


# ═══════════════════════════════════════════════════════════════════════════
#  Fallback Classifier Tests  (unchanged — deterministic keyword matching)
# ═══════════════════════════════════════════════════════════════════════════


def test_intent_fallback_on_empty():
    """Empty or gibberish messages should be classified as unclear by fallback."""
    result = IntentClassifier._fallback_classify("")
    assert result.intent == IntentType.unclear


def test_fallback_classify_greeting():
    """Fallback classifier should detect greetings."""
    result = IntentClassifier._fallback_classify("здравствуйте")
    assert result.intent == IntentType.greeting


def test_fallback_classify_calculation():
    """Fallback classifier should detect calculation requests."""
    result = IntentClassifier._fallback_classify("сколько будет растаможка")
    assert result.intent == IntentType.calculation_request


def test_fallback_classify_hs():
    """Fallback classifier should detect HS classification requests."""
    result = IntentClassifier._fallback_classify("найди код ТН ВЭД для телефона")
    assert result.intent == IntentType.product_description


# ═══════════════════════════════════════════════════════════════════════════
#  Endpoint Integration Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_orchestrator_endpoint_health(monkeypatch):
    """The orchestrator API endpoint should accept a message and return a response."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    # Force IntentClassifier to reliably return greeting for "Привет!"
    async def _mock_classify_greeting(text: str):
        return IntentClassification(intent=IntentType.greeting, confidence=0.95, reasoning="Mock")

    monkeypatch.setattr(IntentClassifier, "classify", _mock_classify_greeting)

    client = TestClient(app)
    response = client.post("/api/orchestrate", data={"text": "Привет!"})
    data = response.json()
    assert data["intent"] == "greeting"
    assert len(data["message"]) > 0


@pytest.mark.asyncio
async def test_orchestrator_empty_message():
    """Empty messages should return 422 (FastAPI validation: missing required Form field)."""
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/orchestrate", data={"text": ""})
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data

@pytest.mark.asyncio
async def test_orchestrator_multi_turn_flow(monkeypatch):
    """Two sequential API calls — first without history, second with history containing the previous turn."""
    from fastapi.testclient import TestClient
    from app.main import app

    # Force mock embedding (zero vector) to avoid loading the ~390 MB sentence-transformer model
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    # Mock IntentClassifier for deterministic legal routing
    async def _mock_classify_legal(text: str):
        return IntentClassification(intent=IntentType.question_about_law, confidence=0.9, reasoning="Mock")
    monkeypatch.setattr(IntentClassifier, "classify", _mock_classify_legal)
 
    # Mock LegalRAGService to avoid Qdrant/Gemini dependency
    from app.core.rag.service import LegalRAGService, LegalRAGResponse
    async def _mock_legal(query, history=None):
        return LegalRAGResponse(
            query=query,
            answer_synthesis="Согласно статье 422 Налогового кодекса РК, ставка НДС на импорт составляет 12%.",
            supporting_laws=[],
        )
    monkeypatch.setattr(LegalRAGService, "query_legal_base", _mock_legal)

    client = TestClient(app)

    # Turn 1: legal question without history
    resp1 = client.post("/api/orchestrate", data={"text": "Какая ставка НДС на импорт?"})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["message"]) > 0
    # Turn 2: follow-up with history containing the previous Q&A
    resp2 = client.post("/api/orchestrate", data={
        "text": "А какие документы нужны для этого?",
        "history": json.dumps([
            {"role": "user", "content": "Какая ставка НДС на импорт?"},
            {"role": "assistant", "content": data1["message"]}
        ])
    })
    data2 = resp2.json()
    assert len(data2["message"]) > 0


@pytest.mark.asyncio
async def test_orchestrator_calculation_context_chaining(monkeypatch):
    """Verify that calculation requests parse and chain parameters from conversational history."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    # Mock ProfileExtractor to return deterministic extraction results
    from app.core.orchestrator.profile_extractor import ProfileExtractor

    def _mock_extract(history, current_text):
        return ProfileExtractionResult(
            accumulated_profile=CustomsProfileAccumulator(
                invoice_price=5000.0,
                currency="USD",
                duty_rate_percent=10.0,
                is_subject_to_recycling_fee=True,
                hs_code="8543709000",
            ),
            missing_fields=[],
            next_question="Все обязательные параметры собраны. Выполняю расчёт.",
        )

    monkeypatch.setattr(ProfileExtractor, "extract", _mock_extract)

    client = TestClient(app)

    history = [
        {"role": "user", "content": "Определи код ТН ВЭД для телефона"},
        {"role": "assistant", "content": "Рекомендуемый код: 8543709000. Пошлина 10.0%. Требуется утильсбор ♻."}
    ]

    resp = client.post("/api/orchestrate", data={
        "text": "Посчитай пошлину для $5000",
        "history": json.dumps(history)
    })

    assert resp.status_code == 200
    data = resp.json()
    assert "Автоматический расчёт таможенных платежей" in data["message"]
    assert "8543709000" in data["message"]
    assert "пошлины" in data["message"].lower() and "10.0%" in data["message"]
    assert "утильсбор" in data["message"].lower() and "да" in data["message"].lower()

    # Verify structured pipeline_results
    results = data.get("pipeline_results", {})
    assert "calculation_request" in results
    assert "calculation_response" in results

    calc_req = results["calculation_request"]
    assert calc_req["invoice_price"] == 5000.0
    assert calc_req["currency"] == "USD"
    assert calc_req["duty_rate_percent"] == 10.0
    assert calc_req["is_subject_to_recycling_fee"] is True


# ═══════════════════════════════════════════════════════════════════════════
#  ADK 2.0 Multi-Agent Orchestration Tests
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_adk_coordination_rag(monkeypatch):
    """Query about law triggers LegalRAGAgent and returns citations.

    The workflow coordinator_node classifies the intent as question_about_law
    and routes to legal_rag_node, which calls LegalRAGService.query_legal_base().
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    # Mock IntentClassifier for deterministic legal routing
    async def _mock_classify(text: str):
        return IntentClassification(intent=IntentType.question_about_law, confidence=0.9, reasoning="Mock")
    monkeypatch.setattr(IntentClassifier, "classify", _mock_classify)
 
    # Mock LegalRAGService to avoid Qdrant/Gemini dependency
    from app.core.rag.service import LegalRAGService, LegalRAGResponse, LegalChunk
    mock_law = LegalChunk(
        document_title="Таможенный кодекс РК",
        article_number="Статья 104",
        content_quote="Тестовая цитата",
        relevance_score=0.95,
    )

    async def _mock_query_legal_base(query, history=None):
        return LegalRAGResponse(
            query=query,
            answer_synthesis="В соответствии со статьей 104 Таможенного кодекса РК, [тестовый ответ]",
            supporting_laws=[mock_law],
        )

    monkeypatch.setattr(LegalRAGService, "query_legal_base", _mock_query_legal_base)

    client = TestClient(app)
    resp = client.post("/api/orchestrate", data={
        "text": "Какая ставка НДС на импорт?"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "question_about_law"
    assert "тестовый ответ" in data["message"]

    # Verify supporting_laws citation is present in pipeline_results
    results = data.get("pipeline_results", {})
    assert results is not None
    supporting_laws = results.get("supporting_laws", [])
    assert len(supporting_laws) >= 1
    assert supporting_laws[0]["article_number"] == "Статья 104"


@pytest.mark.asyncio
async def test_adk_coordination_hs(monkeypatch):
    """Product description triggers HSClassifierAgent response via hs_classifier_node."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    # Mock IntentClassifier for deterministic HS routing
    async def _mock_classify_hs(text: str):
        return IntentClassification(intent=IntentType.product_description, confidence=0.9, reasoning="Mock")
    monkeypatch.setattr(IntentClassifier, "classify", _mock_classify_hs)
 
    # Mock HSCodeClassifier to avoid Qdrant/Gemini dependency
    from app.core.hs_classifier.classifier import HSCodeClassifier, HSClassificationResponse, HSCodeCandidate
    mock_candidate = HSCodeCandidate(
        hs_code="8543709000",
        product_name_ru="Телефон",
        duty_rate_percent=10.0,
        is_subject_to_recycling_fee=True,
        confidence_score=0.92,
        reasoning="Подходит под описание",
    )

    async def _mock_classify(description, image_bytes=None, image_mime_type="image/jpeg"):
        return HSClassificationResponse(
            product_description=description,
            candidates=[mock_candidate],
            qdrant_backed=False,
        )

    monkeypatch.setattr(HSCodeClassifier, "classify", _mock_classify)

    client = TestClient(app)
    resp = client.post("/api/orchestrate", data={
        "text": "Найди код ТН ВЭД для телефона"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"] == "product_description"
    assert "Телефон" in data["message"]
    assert "8543709000" in data["message"]
    assert "10.0%" in data["message"]

    # Verify candidate data in pipeline_results
    results = data.get("pipeline_results", {})
    assert results is not None
    candidates = results.get("candidates", [])
    assert len(candidates) >= 1
    assert candidates[0]["hs_code"] == "8543709000"


@pytest.mark.asyncio
async def test_adk_chained_workflow(monkeypatch):
    """Coordinated workflow correctly executes HS Classifier node and cascades to Calculator node."""
    # Mock IntentClassifier to route as product_description (triggers HS -> chain -> calc)
    async def _mock_classify_hs(text: str):
        return IntentClassification(intent=IntentType.product_description, confidence=0.9, reasoning="Mock")
    monkeypatch.setattr(IntentClassifier, "classify", _mock_classify_hs)
 
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    # Mock HSCodeClassifier
    from app.core.hs_classifier.classifier import HSCodeClassifier, HSClassificationResponse, HSCodeCandidate
    mock_candidate = HSCodeCandidate(
        hs_code="8517130000",
        product_name_ru="Смартфон",
        duty_rate_percent=10.0,
        is_subject_to_recycling_fee=True,
        confidence_score=0.94,
        reasoning="Мобильный телефон",
    )

    async def _mock_classify(description, image_bytes=None, image_mime_type="image/jpeg"):
        return HSClassificationResponse(
            product_description=description,
            candidates=[mock_candidate],
            qdrant_backed=False,
        )

    monkeypatch.setattr(HSCodeClassifier, "classify", _mock_classify)

    # Mock ProfileExtractor (synchronous — ProfileExtractor.extract is not async)
    from app.core.orchestrator.profile_extractor import ProfileExtractor

    def _mock_extract(history, current_text):
        return ProfileExtractionResult(
            accumulated_profile=CustomsProfileAccumulator(
                invoice_price=12500.0,
                currency="USD",
                duty_rate_percent=10.0,
                is_subject_to_recycling_fee=True,
                hs_code="8517130000",
            ),
            missing_fields=[],
            next_question="Все обязательные параметры собраны. Выполняю расчёт.",
        )

    monkeypatch.setattr(ProfileExtractor, "extract", _mock_extract)

    client = TestClient(app)
    resp = client.post("/api/orchestrate", data={
        "text": "Определи код и посчитай пошлину для смартфона за $12500"
    })
    assert resp.status_code == 200
    data = resp.json()
    # The chained workflow should produce a calculation result
    assert data["intent"] == "calculation_request"
    assert "Автоматический расчёт таможенных платежей" in data["message"]
    assert "8517130000" in data["message"]
    assert "10.0%" in data["message"]

    # Verify structured pipeline results
    results = data.get("pipeline_results", {})
    assert "calculation_request" in results
    assert "calculation_response" in results

    calc_req = results["calculation_request"]
    assert calc_req["invoice_price"] == 12500.0
    assert calc_req["currency"] == "USD"


@pytest.mark.asyncio
async def test_adk_session_history_mapping(monkeypatch):
    """Session history from the API is successfully mapped through the ADK workflow."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    # Mock IntentClassifier for deterministic legal routing
    async def _mock_classify_legal(text: str):
        return IntentClassification(intent=IntentType.question_about_law, confidence=0.9, reasoning="Mock")
    monkeypatch.setattr(IntentClassifier, "classify", _mock_classify_legal)
 
    # Mock LegalRAGService to verify history is forwarded
    from app.core.rag.service import LegalRAGService, LegalRAGResponse

    captured_history = []

    async def _mock_query_legal_base(query, history=None):
        captured_history.append(history)
        return LegalRAGResponse(
            query=query,
            answer_synthesis="Тестовый ответ с историей",
            supporting_laws=[],
        )

    monkeypatch.setattr(LegalRAGService, "query_legal_base", _mock_query_legal_base)

    client = TestClient(app)
    history_payload = [
        {"role": "user", "content": "Какая ставка НДС?"},
        {"role": "assistant", "content": "Ставка НДС составляет 12%"},
    ]

    resp = client.post("/api/orchestrate", data={
        "text": "А какие документы нужны?",
        "history": json.dumps(history_payload),
    })

    assert resp.status_code == 200
    # Verify the workflow passed history to the service
    assert len(captured_history) > 0
    assert captured_history[0] == history_payload


@pytest.mark.asyncio
async def test_adk_error_handling(monkeypatch):
    """Subagent exception is gracefully handled by the endpoint, returning a fallback response.

    When a workflow node raises an exception, the ADK runner propagates it,
    the orchestrate endpoint's try/except catches it and returns the fallback.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)
    # Mock IntentClassifier for deterministic legal routing
    async def _mock_classify_legal(text: str):
        return IntentClassification(intent=IntentType.question_about_law, confidence=0.9, reasoning="Mock")
    monkeypatch.setattr(IntentClassifier, "classify", _mock_classify_legal)
 

    # Force the legal_rag_node to raise by making the service throw
    from app.core.rag.service import LegalRAGService

    async def _mock_error(query, history=None):
        raise RuntimeError("Simulated RAG service failure")

    monkeypatch.setattr(LegalRAGService, "query_legal_base", _mock_error)

    client = TestClient(app)

    # A legal question that the fallback classifier will route to question_about_law
    resp = client.post("/api/orchestrate", data={
        "text": "Какая ставка таможенной пошлины?"
    })
    assert resp.status_code == 200
    data = resp.json()
    # The exception in legal_rag_node is caught by the endpoint handler.
    # The exception in legal_rag_node is caught by the endpoint handler.
    # The response contains a valid intent (either the coordinator's
    # classification or a fallback) — the key invariant is that the
    # endpoint returns 200 and does NOT leak raw error details.
    assert data["intent"] in ("unclear", "question_about_law")
    # Error details are NOT leaked to the user
    assert "Simulated" not in data.get("message", "")
def test_intent_fallback_empty_and_gibberish():
    """Fallback classifier should classify empty and meaningless strings as unclear."""
    empty_result = IntentClassifier._fallback_classify("")
    assert empty_result.intent == IntentType.unclear
    assert empty_result.confidence < 0.7

    gibberish_result = IntentClassifier._fallback_classify("asdkfjh123!@#")
    assert gibberish_result.intent == IntentType.unclear
    assert gibberish_result.confidence < 0.7

    symbols_result = IntentClassifier._fallback_classify("!!!???...")
    assert symbols_result.intent == IntentType.unclear
    assert symbols_result.confidence < 0.7


def test_fallback_classify_edge_keywords():
    """Fallback classifier should correctly classify various edge keyword combinations."""
    # "растаможке" matches "растаможк" in calculation_request block (checked before legal)
    mixed = IntentClassifier._fallback_classify("закон о растаможке iPhone")
    assert mixed.intent == IntentType.calculation_request
    # Pure legal keywords (no overlap with other categories)
    pure_legal = IntentClassifier._fallback_classify("расскажи про законодательство")
    assert pure_legal.intent == IntentType.question_about_law
    # HS code with non-standard phrasing
    hs_variation = IntentClassifier._fallback_classify("подскажи ТН ВЭД для видеокарты")
    assert hs_variation.intent == IntentType.product_description
    # Greeting with extra text
    greeting_extra = IntentClassifier._fallback_classify("привет, у меня вопрос")
    assert greeting_extra.intent == IntentType.greeting
    # Calculation with specific tax keywords
    calc_vat = IntentClassifier._fallback_classify("сколько будет НДС")
    assert calc_vat.intent == IntentType.calculation_request
    # Document upload keywords
    doc_upload = IntentClassifier._fallback_classify("хочу загрузить текст закона")
    assert doc_upload.intent == IntentType.document_upload
async def test_orchestrator_whitespace_only_message():
    """Whitespace-only text should return 400."""
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/orchestrate", data={"text": "   \n\t  "})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_orchestrator_corrupted_history(monkeypatch):
    """Corrupted history JSON should NOT crash the endpoint."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    async def _mock_classify(text: str):
        return IntentClassification(intent=IntentType.greeting, confidence=0.9, reasoning="Mock")
    monkeypatch.setattr(IntentClassifier, "classify", _mock_classify)

    client = TestClient(app)
    response = client.post("/api/orchestrate", data={
        "text": "Привет!",
        "history": "not valid json {{{"
    })
    assert response.status_code == 200
    data = response.json()
    assert len(data["message"]) > 0


@pytest.mark.asyncio
async def test_orchestrator_missing_text_field():
    """Missing text field should return 422 (FastAPI validation)."""
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    response = client.post("/api/orchestrate", data={})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_orchestrator_very_long_text(monkeypatch):
    """Very long text (>2000 chars) should still be processed without crashing."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    async def _mock_classify(text: str):
        return IntentClassification(intent=IntentType.unclear, confidence=0.5, reasoning="Mock")
    monkeypatch.setattr(IntentClassifier, "classify", _mock_classify)

    client = TestClient(app)
    long_text = "A" * 3000
    response = client.post("/api/orchestrate", data={"text": long_text})
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "unclear"


# ═══════════════════════════════════════════════════════════════════════════
#  ProfileExtractor Edge Case Tests
# ═══════════════════════════════════════════════════════════════════════════

from app.core.orchestrator.profile_extractor import ProfileExtractor

def test_profile_extractor_fallback_no_data():
    """Fallback extraction with no parsable data should identify all missing fields."""
    result = ProfileExtractor._fallback_extraction("Привет! Как дела?", history=None)
    assert "invoice_price" in result.missing_fields
    assert "currency" in result.missing_fields
    assert "duty_rate_percent" in result.missing_fields
    assert "Пожалуйста, укажите стоимость" in result.next_question


def test_profile_extractor_fallback_10digit_confusion():
    """Fallback should NOT confuse a 10-digit number with a price."""
    result = ProfileExtractor._fallback_extraction("Код ТН ВЭД 1234567890", history=None)
    assert result.accumulated_profile.hs_code == "1234567890"
    # 10-digit code should NOT be parsed as invoice_price
    assert result.accumulated_profile.invoice_price is None
    assert "invoice_price" in result.missing_fields


def test_profile_extractor_fallback_invalid_price_format():
    """Fallback should handle price formats with commas or words."""
    result = ProfileExtractor._fallback_extraction("Цена пять тысяч долларов", history=None)
    assert result.accumulated_profile.invoice_price is None
    assert "invoice_price" in result.missing_fields



def test_profile_extractor_fallback_multiple_history_turns():
    """Fallback should accumulate data across multiple history turns."""
    from app.core.orchestrator.models import ChatMessage
    # Order matters: reversed iteration processes latest messages first
    history = [
        ChatMessage(role="user", content="ставка пошлины 15%"),
        ChatMessage(role="assistant", content="Принято. Какая цена?"),
        ChatMessage(role="user", content="Цена 5000 USD"),
    ]
    result = ProfileExtractor._fallback_extraction("Посчитай", history=history)
    assert result.accumulated_profile.invoice_price == 5000.0
    assert result.accumulated_profile.currency == "USD"
    assert result.accumulated_profile.duty_rate_percent == 15.0
    assert len(result.missing_fields) == 0
    assert "Все обязательные параметры собраны" in result.next_question