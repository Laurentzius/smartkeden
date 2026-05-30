"""Unit tests for Configuration Service Pydantic schemas."""

import pytest
from datetime import date, timedelta
from pydantic import ValidationError

from app.core.admin.config_schemas import (
    RateVersion,
    RateUpdateRequest,
    RateHistoryResponse,
    RateCurrentResponse,
    RateAtDateResponse,
    RatesAllResponse,
    VALID_RATE_TYPES,
)


class TestRateVersion:
    def test_valid_rate_version(self):
        rv = RateVersion(
            value=0.16,
            effective_date="2026-01-01",
            expiry_date=None,
            version=2,
            created_by="admin",
            created_at="2026-05-30T00:00:00Z",
        )
        assert rv.value == 0.16
        assert rv.effective_date == "2026-01-01"
        assert rv.expiry_date is None
        assert rv.version == 2

    def test_rate_version_with_expiry(self):
        rv = RateVersion(
            value=0.12,
            effective_date="2020-01-01",
            expiry_date="2025-12-31",
            version=1,
            created_by="system",
            created_at="2020-01-01T00:00:00Z",
        )
        assert rv.expiry_date == "2025-12-31"

    def test_rate_version_default_created_by(self):
        rv = RateVersion(
            value=0.16,
            effective_date="2026-01-01",
            version=1,
            created_at="2026-05-30T00:00:00Z",
        )
        assert rv.created_by == "system"


class TestRateUpdateRequest:
    def test_valid_update_request(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        req = RateUpdateRequest(
            value=0.16, effective_date=tomorrow, reason="Annual update"
        )
        assert req.value == 0.16
        assert req.effective_date == tomorrow

    def test_value_below_zero_rejected(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with pytest.raises(ValidationError) as exc_info:
            RateUpdateRequest(value=-0.1, effective_date=tomorrow)
        errors = exc_info.value.errors()
        assert any(
            "greater than or equal to 0" in str(e.get("msg", "")).lower()
            for e in errors
        )

    def test_value_above_one_rejected(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with pytest.raises(ValidationError) as exc_info:
            RateUpdateRequest(value=1.5, effective_date=tomorrow)
        errors = exc_info.value.errors()
        assert any(
            "less than or equal to 1" in str(e.get("msg", "")).lower()
            or "value must be between 0 and 1" in str(e.get("msg", "")).lower()
            for e in errors
        )

    def test_past_effective_date_rejected(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        with pytest.raises(ValidationError) as exc_info:
            RateUpdateRequest(value=0.16, effective_date=yesterday)
        errors = exc_info.value.errors()
        assert any("past" in str(e.get("msg", "")).lower() for e in errors)

    def test_today_effective_date_accepted(self):
        today = date.today().isoformat()
        req = RateUpdateRequest(value=0.16, effective_date=today)
        assert req.effective_date == today

    def test_invalid_date_format_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            RateUpdateRequest(value=0.16, effective_date="not-a-date")
        errors = exc_info.value.errors()
        assert any("ISO format" in str(e.get("msg", "")) for e in errors)

    def test_value_zero_accepted(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        req = RateUpdateRequest(value=0.0, effective_date=tomorrow)
        assert req.value == 0.0

    def test_value_one_accepted(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        req = RateUpdateRequest(value=1.0, effective_date=tomorrow)
        assert req.value == 1.0


class TestRateHistoryResponse:
    def test_empty_history(self):
        resp = RateHistoryResponse(rate_type="import_vat", versions=[])
        assert resp.rate_type == "import_vat"
        assert resp.versions == []

    def test_history_with_versions(self):
        rv = RateVersion(
            value=0.16,
            effective_date="2026-01-01",
            version=2,
            created_at="2026-05-30T00:00:00Z",
        )
        resp = RateHistoryResponse(rate_type="import_vat", versions=[rv])
        assert len(resp.versions) == 1


class TestRateCurrentResponse:
    def test_current_response(self):
        resp = RateCurrentResponse(value=0.16, effective_date="2026-01-01", version=2)
        assert resp.value == 0.16
        assert resp.effective_date == "2026-01-01"
        assert resp.version == 2


class TestRateAtDateResponse:
    def test_at_date_response(self):
        resp = RateAtDateResponse(
            value=0.12,
            effective_date="2020-01-01",
            version=1,
            rate_type="import_vat",
            requested_date="2022-06-15",
        )
        assert resp.rate_type == "import_vat"
        assert resp.requested_date == "2022-06-15"


class TestRatesAllResponse:
    def test_all_rates_response(self):
        resp = RatesAllResponse(
            rates={"import_vat": 0.16, "customs_processing_fee": 20000.0}
        )
        assert resp.rates["import_vat"] == 0.16


class TestValidRateTypes:
    def test_valid_rate_types_contains_expected(self):
        assert "import_vat" in VALID_RATE_TYPES
        assert "mci" in VALID_RATE_TYPES
        assert "customs_processing_fee" in VALID_RATE_TYPES
        assert "recycling_rates" in VALID_RATE_TYPES
        assert "excise_rates" in VALID_RATE_TYPES

    def test_unknown_type_not_in_set(self):
        assert "unknown_type" not in VALID_RATE_TYPES
