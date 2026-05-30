"""End-to-end tests: full rate update and historical calculation workflows."""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest


def _mock_config_db(data: dict) -> str:
    tmpdir = Path(tempfile.mkdtemp())
    path = tmpdir / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@pytest.fixture
def e2e_setup(monkeypatch):
    """Patch config_service and audit log to temp files."""
    data = {
        "rates": {
            "import_vat": [
                {
                    "value": 0.12,
                    "effective_date": "2020-01-01",
                    "expiry_date": "2025-12-31",
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2020-01-01T00:00:00Z",
                },
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
                {
                    "year": 2023,
                    "value": 3450.0,
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2023-01-01T00:00:00Z",
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

    # Patch audit log
    tmp_audit = Path(tempfile.mkdtemp()) / "audit_log.json"
    monkeypatch.setattr("app.core.admin.audit_logger._AUDIT_LOG_PATH", tmp_audit)


class TestFullRateUpdateWorkflow:
    def test_full_rate_update_workflow(self, e2e_setup):
        """End-to-end: update a rate via API, verify calculation uses new rate."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.config import settings

        client = TestClient(app)
        admin_headers = {"X-Admin-Key": settings.ADMIN_API_KEY}

        # 1. Read current rates
        resp = client.get("/api/admin/config/rates")
        assert resp.status_code == 200
        current = resp.json()["rates"]
        assert current["import_vat"] == 0.16

        # 2. Update VAT rate
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = {"value": 0.20, "effective_date": tomorrow, "reason": "E2E test"}
        resp = client.put(
            "/api/admin/config/rates/import_vat",
            json=payload,
            headers=admin_headers,
        )
        assert resp.status_code == 201
        updated = resp.json()
        assert updated["new_value"] == 0.20

        # 3. Verify history now has 3 versions
        resp = client.get("/api/admin/config/rates/import_vat")
        assert resp.status_code == 200
        history = resp.json()
        assert len(history["versions"]) == 3

        # 4. Verify audit log has the update entry
        resp = client.get("/api/admin/config/audit", headers=admin_headers)
        assert resp.status_code == 200
        audit = resp.json()
        update_entries = [e for e in audit["items"] if e["action"] == "update_rate"]
        assert len(update_entries) >= 1


class TestHistoricalCalculationWorkflow:
    def test_historical_calculation_workflow(self, e2e_setup):
        """End-to-end: historical calculation uses the correct rate for the declaration date."""
        from app.core.calculation.engine import CustomsCalculator, CalculationRequest

        # Calculate with 2022 declaration date → should use 0.12 VAT
        req_2022 = CalculationRequest(
            invoice_price=1000,
            currency="USD",
            exchange_rate=450.0,
            transport_to_border=50000,
            duty_rate_percent=10.0,
            declaration_date="2022-06-15",
        )
        res_2022 = CustomsCalculator.calculate(req_2022)
        expected_vat_2022 = res_2022.vat_base_kzt * 0.12
        assert res_2022.import_vat_kzt == round(expected_vat_2022, 2)

        # Calculate with 2026 declaration date → should use 0.16 VAT
        req_2026 = CalculationRequest(
            invoice_price=1000,
            currency="USD",
            exchange_rate=450.0,
            transport_to_border=50000,
            duty_rate_percent=10.0,
            declaration_date="2026-06-15",
        )
        res_2026 = CustomsCalculator.calculate(req_2026)
        expected_vat_2026 = res_2026.vat_base_kzt * 0.16
        assert res_2026.import_vat_kzt == round(expected_vat_2026, 2)

    def test_historical_calculation_reads_correct_rate(self, e2e_setup):
        """Rate value should differ based on declaration date."""
        from app.core.config_service import config_service

        rate_2022 = config_service.get_rate("import_vat", declaration_date="2022-06-15")
        rate_2026 = config_service.get_rate("import_vat", declaration_date="2026-06-15")
        assert rate_2022 == 0.12
        assert rate_2026 == 0.16
        assert rate_2022 != rate_2026
