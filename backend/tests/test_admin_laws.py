"""Integration tests for the admin knowledge base laws endpoints.

Covers full CRUD lifecycle plus auth and pagination.
All endpoints live under /api/admin/knowledge/laws (APIRouter with
Depends(verify_admin_key) applied at the router level).
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.core.rag.indexer import LegalRAGIndexer

client = TestClient(app)
ADMIN_KEY = settings.ADMIN_API_KEY  # default: "admin-secret-change-me"
BASE = "/api/admin/knowledge/laws"


@pytest.fixture(autouse=True)
def _fresh_law_collection():
    """Start each test with a clean Qdrant law collection (in-memory)."""
    LegalRAGIndexer.setup_collection(force_recreate=True)
    yield


def _law_payload(suffix: str, variant: int = 0) -> dict:
    """Build a law payload with unique content to avoid dedup collisions
    (the real embedding model may fire and flag similar content)."""
    contents = [
        "Definition of customs territory and border controls for the EAEU union.",
        "VAT rate applicable to imported goods for commercial resale purposes.",
        "Excise duty calculation methodology for tobacco products and alcohol.",
        "Temporary storage period and procedures for transit declarations.",
        "Customs value determination using transaction value method CIF.",
    ]
    content = contents[variant % len(contents)]
    return {
        "title": f"Admin Test Law {suffix}",
        "article": f"Article {suffix}",
        "content": content,
        "keywords": "test, admin",
    }


# ── Create ──────────────────────────────────────────────────────────────────


class TestCreateLaw:
    def test_create_law_201(self):
        payload = _law_payload("create-201")
        resp = client.post(BASE, json=payload, headers={"X-Admin-Key": ADMIN_KEY})
        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert body["status"] == "indexed"
        assert body["document_title"] == payload["title"]

    def test_create_law_missing_auth_401(self):
        resp = client.post(BASE, json=_law_payload("no-auth"))
        assert resp.status_code == 401

    def test_create_law_invalid_schema_422(self):
        # Missing required field: "title"
        resp = client.post(
            BASE,
            json={"article": "Some Art", "content": "Some content"},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resp.status_code == 422


# ── Read / Get ──────────────────────────────────────────────────────────────


class TestGetLaw:
    def test_get_law_200(self):
        payload = _law_payload("get-200")
        create = client.post(BASE, json=payload, headers={"X-Admin-Key": ADMIN_KEY})
        law_id = create.json()["id"]

        resp = client.get(f"{BASE}/{law_id}", headers={"X-Admin-Key": ADMIN_KEY})
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == law_id
        assert body["document_title"] == payload["title"]
        assert body["article_number"] == payload["article"]

    def test_get_law_not_found_404(self):
        resp = client.get(
            f"{BASE}/00000000-0000-0000-0000-000000000000",
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resp.status_code == 404


# ── Update ──────────────────────────────────────────────────────────────────


class TestUpdateLaw:
    def test_update_law_200(self):
        payload = _law_payload("upd-200")
        create = client.post(BASE, json=payload, headers={"X-Admin-Key": ADMIN_KEY})
        law_id = create.json()["id"]

        resp = client.put(
            f"{BASE}/{law_id}",
            json={"title": "Updated Admin Test Law"},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == law_id
        assert body["document_title"] == "Updated Admin Test Law"

    def test_update_law_not_found_404(self):
        resp = client.put(
            f"{BASE}/00000000-0000-0000-0000-000000000000",
            json={"title": "Nope"},
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resp.status_code == 404


# ── Delete ──────────────────────────────────────────────────────────────────


class TestDeleteLaw:
    def test_delete_law_204(self):
        payload = _law_payload("del-204")
        create = client.post(BASE, json=payload, headers={"X-Admin-Key": ADMIN_KEY})
        law_id = create.json()["id"]

        del_resp = client.delete(f"{BASE}/{law_id}", headers={"X-Admin-Key": ADMIN_KEY})
        assert del_resp.status_code == 204

        # Confirm it is actually gone
        get_resp = client.get(f"{BASE}/{law_id}", headers={"X-Admin-Key": ADMIN_KEY})
        assert get_resp.status_code == 404

    def test_delete_law_not_found_404(self):
        resp = client.delete(
            f"{BASE}/00000000-0000-0000-0000-000000000000",
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resp.status_code == 404


# ── List / Pagination ──────────────────────────────────────────────────────


class TestListLaws:
    def test_list_laws_returns_paginated(self):
        for i in range(3):
            payload = _law_payload(f"list-{i}", variant=i)
            resp = client.post(
                BASE,
                json=payload,
                headers={"X-Admin-Key": ADMIN_KEY},
            )
            assert resp.status_code == 201, f"Create {i} failed: {resp.text}"

        resp = client.get(
            f"{BASE}?page=1&size=2",
            headers={"X-Admin-Key": ADMIN_KEY},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["total"] == 3
        assert body["page"] == 1
        assert body["size"] == 2
