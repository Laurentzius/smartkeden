"""Integration tests for the Admin Configuration API."""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.fixture
def client():
    """Return a TestClient for the FastAPI app."""
    # Ensure tests don't use production config DB
    from app.main import app

    return TestClient(app)


@pytest.fixture
def admin_headers():
    """Headers with valid admin API key."""
    return {"X-Admin-Key": settings.ADMIN_API_KEY}


# ── GET /api/admin/config/rates ──────────────────────────────────────────────


class TestGetAllRates:
    def test_get_all_rates(self, client):
        resp = client.get("/api/admin/config/rates")
        assert resp.status_code == 200
        data = resp.json()
        assert "rates" in data
        assert isinstance(data["rates"], dict)


# ── GET /api/admin/config/rates/{rate_type} ──────────────────────────────────


class TestGetRateHistory:
    def test_get_rate_history(self, client):
        resp = client.get("/api/admin/config/rates/import_vat")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rate_type"] == "import_vat"
        assert "versions" in data

    def test_get_rate_history_nonexistent_type(self, client):
        resp = client.get("/api/admin/config/rates/nonexistent")
        assert resp.status_code == 404


# ── GET /api/admin/config/rates/{rate_type}/current ──────────────────────────


class TestGetCurrentRate:
    def test_get_current_rate(self, client):
        resp = client.get("/api/admin/config/rates/import_vat/current")
        assert resp.status_code == 200
        data = resp.json()
        assert "value" in data
        assert "effective_date" in data
        assert "version" in data

    def test_get_current_rate_nonexistent_type(self, client):
        resp = client.get("/api/admin/config/rates/nonexistent/current")
        assert resp.status_code == 404


# ── GET /api/admin/config/rates/{rate_type}/at/{date} ────────────────────────


class TestGetRateAtDate:
    def test_get_rate_at_date(self, client):
        resp = client.get("/api/admin/config/rates/import_vat/at/2022-06-15")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rate_type"] == "import_vat"
        assert data["requested_date"] == "2022-06-15"

    def test_get_rate_at_date_invalid_format(self, client):
        resp = client.get("/api/admin/config/rates/import_vat/at/not-a-date")
        assert resp.status_code == 400

    def test_get_rate_at_date_nonexistent_type(self, client):
        resp = client.get("/api/admin/config/rates/nonexistent/at/2022-06-15")
        assert resp.status_code == 404


# ── PUT /api/admin/config/rates/{rate_type} ──────────────────────────────────


class TestUpdateRateSuccess:
    def test_update_rate_success(self, client, admin_headers):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = {"value": 0.17, "effective_date": tomorrow, "reason": "Test update"}
        resp = client.put(
            "/api/admin/config/rates/import_vat",
            json=payload,
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["rate_type"] == "import_vat"
        assert data["new_value"] == 0.17


class TestUpdateRateUnauthorized:
    def test_update_rate_unauthorized_no_key(self, client):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = {"value": 0.17, "effective_date": tomorrow}
        resp = client.put("/api/admin/config/rates/import_vat", json=payload)
        assert resp.status_code in (401, 422)

    def test_update_rate_unauthorized_wrong_key(self, client):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = {"value": 0.17, "effective_date": tomorrow}
        resp = client.put(
            "/api/admin/config/rates/import_vat",
            json=payload,
            headers={"X-Admin-Key": "wrong-key"},
        )
        assert resp.status_code == 401


class TestUpdateRateNonexistentType:
    def test_update_rate_nonexistent_type_returns_404(self, client, admin_headers):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = {"value": 0.17, "effective_date": tomorrow}
        resp = client.put(
            "/api/admin/config/rates/nonexistent",
            json=payload,
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ── POST /api/admin/config/rates/{rate_type}/cancel/{version} ────────────────


class TestCancelScheduledRate:
    def test_cancel_scheduled_rate(self, client, admin_headers):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        # First create a rate
        payload = {"value": 0.18, "effective_date": tomorrow}
        create_resp = client.put(
            "/api/admin/config/rates/import_vat",
            json=payload,
            headers=admin_headers,
        )
        assert create_resp.status_code == 201
        version = create_resp.json()["version"]

        # Cancel it
        cancel_resp = client.post(
            f"/api/admin/config/rates/import_vat/cancel/{version}",
            headers=admin_headers,
        )
        assert cancel_resp.status_code == 200
        data = cancel_resp.json()
        assert data["status"] == "cancelled"

    def test_cancel_nonexistent_version(self, client, admin_headers):
        resp = client.post(
            "/api/admin/config/rates/import_vat/cancel/9999",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_cancel_requires_auth(self, client):
        resp = client.post("/api/admin/config/rates/import_vat/cancel/1")
        assert resp.status_code in (401, 422)


# ── DELETE /api/admin/config/rates/{rate_type}/{version} ─────────────────────


class TestDeleteRateSoftDelete:
    def test_delete_rate_soft_delete(self, client, admin_headers):
        far_future = (date.today() + timedelta(days=365)).isoformat()
        # Create a rate to delete
        payload = {"value": 0.19, "effective_date": far_future}
        create_resp = client.put(
            "/api/admin/config/rates/import_vat",
            json=payload,
            headers=admin_headers,
        )
        version = create_resp.json()["version"]

        # Delete it
        delete_resp = client.delete(
            f"/api/admin/config/rates/import_vat/{version}",
            headers=admin_headers,
        )
        assert delete_resp.status_code == 200
        data = delete_resp.json()
        assert data["status"] == "deprecated"

    def test_delete_nonexistent_version(self, client, admin_headers):
        resp = client.delete(
            "/api/admin/config/rates/import_vat/9999",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    def test_delete_requires_auth(self, client):
        resp = client.delete("/api/admin/config/rates/import_vat/1")
        assert resp.status_code in (401, 422)


# ── GET /api/admin/config/audit ──────────────────────────────────────────────


class TestAuditLogEndpoint:
    def test_audit_log_requires_auth(self, client):
        resp = client.get("/api/admin/config/audit")
        assert resp.status_code in (401, 422)

    def test_audit_log_with_auth(self, client, admin_headers):
        resp = client.get("/api/admin/config/audit", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
