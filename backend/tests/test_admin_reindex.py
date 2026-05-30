"""Integration tests for admin reindex endpoints.

Router: /api/admin/knowledge/reindex
Auth:   X-Admin-Key header (required on all routes)

These tests validate the HTTP response layer only — reindex jobs run
asynchronously in the background and are not awaited.
"""

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings

client = TestClient(app)
ADMIN_KEY = settings.ADMIN_API_KEY


class TestReindexTrigger:
    """POST /api/admin/knowledge/reindex"""

    def test_reindex_laws_202(self):
        response = client.post(
            "/api/admin/knowledge/reindex",
            json={"collection": "laws"},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "running"
        assert data["progress"] == "0%"

    def test_reindex_hs_codes_202(self):
        response = client.post(
            "/api/admin/knowledge/reindex",
            json={"collection": "hs_codes"},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "running"

    def test_reindex_all_202(self):
        response = client.post(
            "/api/admin/knowledge/reindex",
            json={"collection": "all"},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "running"

    def test_reindex_invalid_collection_400(self):
        response = client.post(
            "/api/admin/knowledge/reindex",
            json={"collection": "invalid"},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "invalid" in data["detail"].lower()

    def test_reindex_requires_auth_401(self):
        """POST without X-Admin-Key header should be rejected."""
        response = client.post(
            "/api/admin/knowledge/reindex",
            json={"collection": "laws"},
        )
        assert response.status_code == 401
        data = response.json()
        assert "detail" in data


class TestReindexStatus:
    """GET /api/admin/knowledge/reindex/{job_id}"""

    def _trigger_reindex(self) -> str:
        """Helper: start a reindex and return the job_id."""
        resp = client.post(
            "/api/admin/knowledge/reindex",
            json={"collection": "laws"},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        return resp.json()["job_id"]

    def test_reindex_status_200(self):
        job_id = self._trigger_reindex()
        response = client.get(
            f"/api/admin/knowledge/reindex/{job_id}",
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("running", "completed", "failed")

    def test_reindex_status_not_found_404(self):
        response = client.get(
            "/api/admin/knowledge/reindex/nonexistent-job-id",
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
