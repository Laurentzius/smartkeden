import pytest
from app.core.orchestrator.models import IntentType, IntentClassification
from app.core.orchestrator.router import IntentClassifier


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


@pytest.mark.asyncio
async def test_orchestrator_endpoint_health():
    """The orchestrator API endpoint should accept a message and return a response."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.post("/api/orchestrate", json={"text": "Привет!"})
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "greeting"
    assert len(data["message"]) > 0


@pytest.mark.asyncio
async def test_orchestrator_empty_message():
    """Empty messages should return 400."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.post("/api/orchestrate", json={"text": ""})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_orchestrator_multi_turn_flow(monkeypatch):
    """Two sequential API calls — first without history, second with history containing the previous turn."""
    from fastapi.testclient import TestClient
    from app.main import app

    # Force mock embedding (zero vector) to avoid loading the ~390 MB sentence-transformer model
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    client = TestClient(app)

    # Turn 1: legal question without history
    resp1 = client.post("/api/orchestrate", json={"text": "Какая ставка НДС на импорт?"})
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert len(data1["message"]) > 0

    # Turn 2: follow-up with history containing the previous Q&A
    resp2 = client.post("/api/orchestrate", json={
        "text": "А какие документы нужны для этого?",
        "history": [
            {"role": "user", "content": "Какая ставка НДС на импорт?"},
            {"role": "assistant", "content": data1["message"]}
        ]
    })
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["message"]) > 0
@pytest.mark.asyncio
async def test_orchestrator_calculation_context_chaining(monkeypatch):
    """Verify that calculation requests parse and chain parameters from conversational history."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.local_embeddings import LocalEmbeddingModel
    monkeypatch.setattr(LocalEmbeddingModel, "_available", False)

    client = TestClient(app)

    # Turn 2: User requests calculation, passing conversational history from Turn 1 (where HS code and duty rate were identified)
    history = [
        {"role": "user", "content": "Определи код ТН ВЭД для телефона"},
        {"role": "assistant", "content": "Рекомендуемый код: 8543709000. Пошлина 10.0%. Требуется утильсбор ♻."}
    ]

    resp = client.post("/api/orchestrate", json={
        "text": "Посчитай пошлину для $5000",
        "history": history
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

