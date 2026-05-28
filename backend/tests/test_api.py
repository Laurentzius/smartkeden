from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_api_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "CustomAI Kazakhstan"

def test_api_calculate():
    payload = {
        "invoice_price": 2000.0,
        "currency": "USD",
        "exchange_rate": 450.0,
        "transport_to_border": 100000.0,
        "duty_rate_percent": 12.0,
        "excise_rate_percent": 0.0,
        "excise_specific_rate": 0.0,
        "excise_units_count": 0.0,
        "is_subject_to_recycling_fee": False
    }
    # Customs Value = 2000 * 450 + 100k = 1,000,000 KZT
    # Fee = 20k
    # Duty = 1,000,000 * 12% = 120k
    # Excise = 0
    # VAT Base = 1M + 20k + 120k = 1,140,000 KZT
    # VAT = 1,140,000 * 12% = 136,800 KZT
    # Total = 20k + 120k + 136,800 = 276,800 KZT
    
    response = client.post("/api/calculate", json=payload)
    assert response.status_code == 200
    data = response.json()
    
    assert data["customs_value_kzt"] == 1000000.0
    assert data["customs_fee_kzt"] == 20000.0
    assert data["customs_duty_kzt"] == 120000.0
    assert data["import_vat_kzt"] == 136800.0
    assert data["total_payments_kzt"] == 276800.0

def test_api_exchange_rates():
    response = client.get("/api/rates")
    assert response.status_code == 200
    data = response.json()
    assert "KZT" in data
    assert "USD" in data

def test_api_specific_rate():
    response = client.get("/api/rates/usd")
    assert response.status_code == 200
    data = response.json()
    assert data["currency"] == "USD"
    assert data["rate_to_kzt"] > 100.0

def test_api_chat_endpoint():
    payload = {"query": "Какая ставка НДС в Казахстане?"}
    response = client.post("/api/chat", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "query" in data
    assert "answer_synthesis" in data
    assert len(data["supporting_laws"]) > 0

def test_api_classify_endpoint():
    # Since description is a form field, we pass form data instead of json payload
    response = client.post("/api/classify", data={"description": "Детские пластиковые конструкторы Lego"})
    assert response.status_code == 200
    data = response.json()
    assert "product_description" in data
    assert "candidates" in data
    assert len(data["candidates"]) > 0
    assert data["candidates"][0]["confidence_score"] > 0.0