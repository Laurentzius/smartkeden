"""Integration tests: Audit logging for rate changes."""

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
def patched_config(monkeypatch):
    """Patch config_service and audit log paths."""
    data = {
        "rates": {
            "import_vat": [
                {
                    "value": 0.16,
                    "effective_date": "2026-01-01",
                    "expiry_date": None,
                    "version": 2,
                    "created_by": "system",
                    "created_at": "2026-01-01T00:00:00Z",
                },
            ],
            "mci": [],
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

    # Also patch audit log path
    tmp_audit = Path(tempfile.mkdtemp()) / "audit_log.json"
    monkeypatch.setattr("app.core.admin.audit_logger._AUDIT_LOG_PATH", tmp_audit)


class TestRateChangeLogged:
    def test_rate_change_logged(self, patched_config):
        """Updating a rate via API should create an audit log entry."""
        from app.core.admin.audit_logger import AuditLogger
        from fastapi.testclient import TestClient

        from app.main import app
        from app.core.config import settings

        client = TestClient(app)
        admin_headers = {"X-Admin-Key": settings.ADMIN_API_KEY}

        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = {"value": 0.18, "effective_date": tomorrow, "reason": "Audit test"}

        resp = client.put(
            "/api/admin/config/rates/import_vat",
            json=payload,
            headers=admin_headers,
        )
        assert resp.status_code == 201

        # Check audit log
        items, total = AuditLogger.get_logs(entity_type="config:import_vat")
        assert total >= 1
        entry = items[0]
        assert entry["action"] == "update_rate"
        assert entry["entity_type"] == "config:import_vat"

    def test_audit_log_pagination(self, patched_config):
        """Audit log endpoint with pagination should work."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.config import settings

        client = TestClient(app)
        admin_headers = {"X-Admin-Key": settings.ADMIN_API_KEY}

        resp = client.get(
            "/api/admin/config/audit?page=1&size=10",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert data["page"] == 1

    def test_audit_log_filter_by_action(self, patched_config):
        """Audit log can be filtered by action type."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.config import settings

        client = TestClient(app)
        admin_headers = {"X-Admin-Key": settings.ADMIN_API_KEY}

        resp = client.get(
            "/api/admin/config/audit?action=update_rate",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["action"] == "update_rate"
