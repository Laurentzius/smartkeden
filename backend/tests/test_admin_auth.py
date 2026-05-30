"""Tests for the admin auth middleware (verify_admin_key dependency)."""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# Use any protected endpoint under /api/admin/knowledge — auth fires before the handler
_PROTECTED_URL = "/api/admin/knowledge/reindex/nonexistent-job"


def test_valid_admin_key_passes():
    """Valid X-Admin-Key header should pass the auth dependency."""
    response = client.get(
        _PROTECTED_URL,
        headers={"X-Admin-Key": "admin-secret-change-me"},
    )
    # Auth passes → handler runs → 404 (job not found), definitely not 401
    assert response.status_code != 401


def test_missing_admin_key_returns_401():
    """Missing X-Admin-Key header should return 401."""
    response = client.get(_PROTECTED_URL)
    assert response.status_code == 401


def test_invalid_admin_key_returns_401():
    """Wrong X-Admin-Key header should return 401."""
    response = client.get(
        _PROTECTED_URL,
        headers={"X-Admin-Key": "invalid-key"},
    )
    assert response.status_code == 401


def test_empty_admin_key_returns_401():
    """Empty X-Admin-Key header should return 401 (not x_admin_key → True)."""
    response = client.get(
        _PROTECTED_URL,
        headers={"X-Admin-Key": ""},
    )
    assert response.status_code == 401
