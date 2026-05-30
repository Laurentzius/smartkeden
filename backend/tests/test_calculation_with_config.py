"""Integration tests: Calculation Engine uses ConfigService for rates."""

import json
import tempfile
from pathlib import Path

import pytest

from app.core.calculation.engine import CustomsCalculator, CalculationRequest
from app.core.business_rules import rules


def _mock_config_db(data: dict) -> str:
    tmpdir = Path(tempfile.mkdtemp())
    path = tmpdir / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@pytest.fixture
def patched_config(monkeypatch):
    """Patch config_service to use a temp config DB with known values."""
    data = {
        "rates": {
            "import_vat": [
                {
                    "value": 0.14,
                    "effective_date": "2020-01-01",
                    "expiry_date": None,
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2020-01-01T00:00:00Z",
                },
            ],
            "mci": [
                {
                    "year": 2026,
                    "value": 5000.0,
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2026-01-01T00:00:00Z",
                },
                {
                    "year": 2023,
                    "value": 3500.0,
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2023-01-01T00:00:00Z",
                },
            ],
            "customs_processing_fee": [
                {
                    "value": 25000.0,
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
    # Force fresh singleton
    import app.core.config_service as mod

    mod.ConfigService._instance = None
    return path


class TestCalculationUsesConfigService:
    def test_calculation_uses_config_vat(self, patched_config):
        """Calculation should use the configured VAT rate (14%), not hardcoded (16%)."""
        req = CalculationRequest(
            invoice_price=1000,
            currency="USD",
            exchange_rate=450.0,
            transport_to_border=50000,
            duty_rate_percent=10.0,
        )
        res = CustomsCalculator.calculate(req)
        # VAT = vat_base * 0.14 (from config), not 0.16 (hardcoded)
        expected_vat = res.vat_base_kzt * 0.14
        assert res.import_vat_kzt == round(expected_vat, 2)

    def test_calculation_uses_config_customs_fee(self, patched_config):
        """Calculation should use the configured customs fee (25000), not hardcoded (20000)."""
        req = CalculationRequest(
            invoice_price=1000,
            currency="USD",
            exchange_rate=450.0,
        )
        res = CustomsCalculator.calculate(req)
        assert res.customs_fee_kzt == 25000.0


class TestCalculationWithDeclarationDate:
    def test_calculation_with_historical_vat(self, monkeypatch):
        """When declaration_date is provided, the rate for that date should be used."""
        data = {
            "rates": {
                "import_vat": [
                    {
                        "value": 0.12,
                        "effective_date": "2020-01-01",
                        "expiry_date": "2023-12-31",
                        "version": 1,
                        "created_by": "system",
                        "created_at": "2020-01-01T00:00:00Z",
                    },
                    {
                        "value": 0.16,
                        "effective_date": "2024-01-01",
                        "expiry_date": None,
                        "version": 2,
                        "created_by": "system",
                        "created_at": "2024-01-01T00:00:00Z",
                    },
                ],
                "mci": [
                    {
                        "year": 2023,
                        "value": 3450.0,
                        "version": 1,
                        "created_by": "system",
                        "created_at": "2023-01-01T00:00:00Z",
                    },
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

        req = CalculationRequest(
            invoice_price=1000,
            currency="USD",
            exchange_rate=450.0,
            transport_to_border=50000,
            duty_rate_percent=10.0,
            declaration_date="2022-06-15",
        )
        res = CustomsCalculator.calculate(req)
        # Should use 0.12 (active during 2022), not 0.16
        expected_vat = res.vat_base_kzt * 0.12
        assert res.import_vat_kzt == round(expected_vat, 2)


class TestCalculationFallbackOnConfigFailure:
    def test_calculation_falls_back_on_config_failure(self, monkeypatch):
        """When ConfigService is unavailable, fall back to business_rules.py."""
        monkeypatch.setattr(
            "app.core.config_service._load_config_db",
            lambda: (_ for _ in ()).throw(RuntimeError("simulated failure")),
        )
        import app.core.config_service as mod

        mod.ConfigService._instance = None

        req = CalculationRequest(
            invoice_price=1000,
            currency="USD",
            exchange_rate=450.0,
        )
        res = CustomsCalculator.calculate(req)

        # Falls back to hardcoded: customs fee = 20000
        assert res.customs_fee_kzt == rules.customs_processing_fee_kzt
        # VAT falls back to hardcoded
        expected_vat = res.vat_base_kzt * rules.import_vat_rate
        assert res.import_vat_kzt == round(expected_vat, 2)
