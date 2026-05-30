"""Unit tests for ConfigService — rate versioning, historical lookups, fallbacks."""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.config_service import ConfigService


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_config_db(data: dict) -> str:
    """Write a temp config.json and return its path."""
    tmpdir = Path(tempfile.mkdtemp())
    path = tmpdir / "config.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@pytest.fixture
def temp_config_path(monkeypatch):
    """Create a temp config.json and patch settings.CONFIG_DB_PATH."""
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
                    "year": 2024,
                    "value": 3692.0,
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2024-01-01T00:00:00Z",
                },
                {
                    "year": 2025,
                    "value": 3932.0,
                    "version": 1,
                    "created_by": "system",
                    "created_at": "2025-01-01T00:00:00Z",
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
    # Force fresh singleton
    import app.core.config_service as mod

    mod.ConfigService._instance = None
    return path


@pytest.fixture
def cs(temp_config_path):
    """Fresh ConfigService instance using temp config."""
    import app.core.config_service as mod

    mod.ConfigService._instance = None
    return ConfigService()


# ── get_rate (current) ───────────────────────────────────────────────────────


class TestGetRateCurrent:
    def test_get_current_vat(self, cs):
        assert cs.get_rate("import_vat") == 0.16

    def test_get_customs_fee(self, cs):
        assert cs.get_rate("customs_processing_fee") == 20000.0

    def test_get_unknown_rate_type_returns_fallback(self, cs):
        val = cs.get_rate("unknown_type")
        assert isinstance(val, float)


# ── get_rate (historical) ────────────────────────────────────────────────────


class TestGetRateHistorical:
    def test_get_rate_on_past_date(self, cs):
        val = cs.get_rate("import_vat", declaration_date="2022-06-15")
        assert val == 0.12

    def test_get_rate_on_future_date(self, cs):
        val = cs.get_rate("import_vat", declaration_date="2026-06-01")
        assert val == 0.16

    def test_get_rate_on_expiry_boundary(self, cs):
        val = cs.get_rate("import_vat", declaration_date="2025-12-31")
        assert val == 0.12

    def test_get_rate_on_effective_boundary(self, cs):
        val = cs.get_rate("import_vat", declaration_date="2026-01-01")
        assert val == 0.16


# ── Missing historical rate → earliest ───────────────────────────────────────


class TestGetRateMissingReturnsEarliest:
    def test_missing_historical_rate_returns_earliest(self, cs):
        val = cs.get_rate("import_vat", declaration_date="2010-01-01")
        assert val == 0.12


# ── Update rate ──────────────────────────────────────────────────────────────


class TestUpdateRateCreatesNewVersion:
    def test_update_creates_version(self, cs):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        new_version = cs.update_rate("import_vat", 0.18, tomorrow, reason="Test update")
        assert new_version.version > 2

    def test_update_increments_version(self, cs):
        t1 = (date.today() + timedelta(days=1)).isoformat()
        t2 = (date.today() + timedelta(days=2)).isoformat()
        v1 = cs.update_rate("import_vat", 0.18, t1)
        v2 = cs.update_rate("import_vat", 0.19, t2)
        assert v2.version == v1.version + 1


class TestUpdateRateAutoAdjustsExpiry:
    def test_auto_adjusts_previous_expiry(self, cs):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        cs.update_rate("import_vat", 0.18, tomorrow)
        history = cs.get_history("import_vat")
        for v in history:
            if v.effective_date == "2026-01-01":
                # The previously active version should have expiry_date set
                if v.version < max(rv.version for rv in history):
                    assert v.expiry_date is not None
                break


class TestUpdateRateAcceptsPastDate:
    def test_config_service_accepts_past_date(self, cs):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        result = cs.update_rate("import_vat", 0.10, yesterday)
        assert result.value == 0.10


class TestUpdateRateAcceptsAnyFloat:
    def test_config_service_accepts_any_float(self, cs):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        result = cs.update_rate("import_vat", 1.5, tomorrow)
        assert result.value == 1.5


# ── MCI ──────────────────────────────────────────────────────────────────────


class TestGetMciByYear:
    def test_get_mci_2026(self, cs):
        assert cs.get_mci(2026) == 4325.0

    def test_get_mci_2024(self, cs):
        assert cs.get_mci(2024) == 3692.0

    def test_get_mci_missing_year_returns_latest(self, cs):
        val = cs.get_mci(2015)
        assert val == 4325.0


# ── Fallback ─────────────────────────────────────────────────────────────────


class TestConfigServiceUnavailableFallback:
    def test_fallback_when_db_is_garbage(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.config_service._load_config_db",
            lambda: (_ for _ in ()).throw(RuntimeError("simulated disk failure")),
        )
        import app.core.config_service as mod

        mod.ConfigService._instance = None
        cs = ConfigService()
        val = cs.get_rate("import_vat")
        from app.core.business_rules import rules

        assert val == rules.import_vat_rate

    def test_fallback_for_mci_on_failure(self, monkeypatch):
        monkeypatch.setattr(
            "app.core.config_service._load_config_db",
            lambda: (_ for _ in ()).throw(RuntimeError("simulated disk failure")),
        )
        import app.core.config_service as mod

        mod.ConfigService._instance = None
        cs = ConfigService()
        val = cs.get_mci(2026)
        assert val == 4325.0


# ── History ──────────────────────────────────────────────────────────────────


class TestGetHistory:
    def test_get_history_returns_all_versions(self, cs):
        history = cs.get_history("import_vat")
        assert len(history) == 2
        assert history[0].version > history[1].version

    def test_get_history_empty_type(self, cs):
        history = cs.get_history("recycling_rates")
        assert history == []


# ── get_all_current ──────────────────────────────────────────────────────────


class TestGetAllCurrent:
    def test_get_all_current(self, cs):
        rates = cs.get_all_current()
        assert isinstance(rates, dict)
        assert "import_vat" in rates
        assert "customs_processing_fee" in rates
        assert "mci" in rates

    def test_get_all_current_has_correct_vat(self, cs):
        rates = cs.get_all_current()
        assert rates["import_vat"] == 0.16


# ── Cancel / Delete ──────────────────────────────────────────────────────────


class TestCancelDeleteEdgeCases:
    def test_cancel_future_rate(self, cs):
        far_future = (date.today() + timedelta(days=365)).isoformat()
        v = cs.update_rate("import_vat", 0.20, far_future)
        result = cs.cancel_rate("import_vat", v.version)
        assert result is not None
        assert result.get("status") == "cancelled"

    def test_cancel_nonexistent_rate(self, cs):
        result = cs.cancel_rate("import_vat", 9999)
        assert result is None

    def test_delete_rate_soft_delete(self, cs):
        far_future = (date.today() + timedelta(days=365)).isoformat()
        v = cs.update_rate("import_vat", 0.25, far_future)
        success, warning = cs.delete_rate("import_vat", v.version)
        assert success
        assert warning is not None

    def test_delete_nonexistent_rate(self, cs):
        success, warning = cs.delete_rate("import_vat", 9999)
        assert not success
        assert warning is None


# ── Singleton ────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_singleton_returns_same_instance(self):
        cs1 = ConfigService()
        cs2 = ConfigService()
        assert cs1 is cs2


# ── _find_version_for_date ───────────────────────────────────────────────────


class TestFindVersionForDate:
    def test_find_version_between_dates(self):
        versions = [
            {
                "value": 0.12,
                "effective_date": "2020-01-01",
                "expiry_date": "2025-12-31",
                "version": 1,
            },
            {
                "value": 0.16,
                "effective_date": "2026-01-01",
                "expiry_date": None,
                "version": 2,
            },
        ]
        result = ConfigService._find_version_for_date(versions, date(2023, 6, 15))
        assert result is not None
        assert result["value"] == 0.12

    def test_find_version_returns_none_before_all(self):
        versions = [
            {
                "value": 0.16,
                "effective_date": "2026-01-01",
                "expiry_date": None,
                "version": 2,
            },
        ]
        result = ConfigService._find_version_for_date(versions, date(2010, 1, 1))
        assert result is None

    def test_find_version_on_boundary(self):
        versions = [
            {
                "value": 0.12,
                "effective_date": "2020-01-01",
                "expiry_date": "2025-12-31",
                "version": 1,
            },
            {
                "value": 0.16,
                "effective_date": "2026-01-01",
                "expiry_date": None,
                "version": 2,
            },
        ]
        result = ConfigService._find_version_for_date(versions, date(2025, 12, 31))
        assert result is not None
        assert result["value"] == 0.12
