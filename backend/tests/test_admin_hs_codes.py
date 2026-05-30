"""Integration tests for admin HS codes CRUD endpoints.

Tests cover the full lifecycle of HS code entries via the admin API:
create, read, update, delete, duplicate detection, pagination, and search.
"""

import uuid
from typing import Optional

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

ADMIN_KEY = "admin-secret-change-me"
HEADERS = {"X-Admin-Key": ADMIN_KEY}
BASE_URL = "/api/admin/knowledge/hs-codes"


def _unique_id() -> str:
    """Return a short unique hex string for per-test isolation."""
    return uuid.uuid4().hex[:8]


def _unique_hs_code(tag: Optional[str] = None) -> str:
    """Return a deterministic-looking but globally unique HS code."""
    suffix = tag or uuid.uuid4().hex[:8]
    return f"9999.99.{suffix}"


def _create_hs_code(payload: dict) -> dict:
    """Create an HS code entry and return the JSON response (asserts 201)."""
    resp = client.post(BASE_URL, json=payload, headers=HEADERS)
    assert resp.status_code == 201, f"create failed: {resp.text}"
    return resp.json()


# ── Create ──────────────────────────────────────────────────────────────────


def test_create_hs_code_201():
    """POST valid HS code returns 201 with the created entry."""
    tag = _unique_id()
    hsc = _unique_hs_code(tag)
    payload = {
        "hs_code": hsc,
        "product_name_ru": f"Тестовый товар {tag}",
        "duty_rate": 5.0,
    }
    resp = client.post(BASE_URL, json=payload, headers=HEADERS)
    assert resp.status_code == 201
    data = resp.json()
    assert data["hs_code"] == hsc
    assert data["product_name_ru"] == f"Тестовый товар {tag}"
    assert data["duty_rate_percent"] == 5.0
    assert data["excise_rate_percent"] == 0.0
    assert data["id"] and isinstance(data["id"], str)
    assert data["status"] == "indexed"


def test_create_hs_code_duplicate_409():
    """POST the same hs_code twice returns 409 on the second attempt."""
    tag = _unique_id()
    hsc = _unique_hs_code(tag)
    payload = {
        "hs_code": hsc,
        "product_name_ru": f"Дубль товар {tag}",
        "duty_rate": 5.0,
    }
    # First: success
    _create_hs_code(payload)
    # Second: conflict — exact HS code match
    resp = client.post(BASE_URL, json=payload, headers=HEADERS)
    assert resp.status_code == 409
    data = resp.json()
    assert "detail" in data


# ── Read ────────────────────────────────────────────────────────────────────


def test_get_hs_code_200():
    """Create then GET by id returns 200 with the full entry."""
    tag = _unique_id()
    hsc = _unique_hs_code(tag)
    created = _create_hs_code(
        {
            "hs_code": hsc,
            "product_name_ru": f"GetTest товар {tag}",
            "duty_rate": 5.0,
        }
    )
    point_id = created["id"]

    resp = client.get(f"{BASE_URL}/{point_id}", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["hs_code"] == hsc
    assert data["id"] == point_id


def test_get_hs_code_not_found_404():
    """GET a nonexistent point_id returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"{BASE_URL}/{fake_id}", headers=HEADERS)
    assert resp.status_code == 404
    assert "detail" in resp.json()


# ── Update ──────────────────────────────────────────────────────────────────


def test_update_hs_code_200():
    """Create then PUT with partial update returns 200 with updated fields."""
    tag = _unique_id()
    hsc = _unique_hs_code(tag)
    created = _create_hs_code(
        {
            "hs_code": hsc,
            "product_name_ru": f"UpdateTest товар {tag}",
            "duty_rate": 5.0,
        }
    )
    point_id = created["id"]

    update = {"product_name_ru": f"Обновленный товар {tag}", "duty_rate": 10.0}
    resp = client.put(f"{BASE_URL}/{point_id}", json=update, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["product_name_ru"] == f"Обновленный товар {tag}"
    assert data["duty_rate_percent"] == 10.0
    # Unchanged fields remain
    assert data["hs_code"] == hsc
    assert data["status"] == "indexed"


def test_update_hs_code_not_found_404():
    """PUT a nonexistent point_id returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000001"
    update = {"product_name_ru": "Нет такого"}
    resp = client.put(f"{BASE_URL}/{fake_id}", json=update, headers=HEADERS)
    assert resp.status_code == 404
    assert "detail" in resp.json()


# ── Delete ──────────────────────────────────────────────────────────────────


def test_delete_hs_code_204():
    """Create then DELETE returns 204 and the entry is removed."""
    tag = _unique_id()
    hsc = _unique_hs_code(tag)
    created = _create_hs_code(
        {
            "hs_code": hsc,
            "product_name_ru": f"DeleteTest товар {tag}",
            "duty_rate": 5.0,
        }
    )
    point_id = created["id"]

    resp = client.delete(f"{BASE_URL}/{point_id}", headers=HEADERS)
    assert resp.status_code == 204

    # Confirm deletion
    get_resp = client.get(f"{BASE_URL}/{point_id}", headers=HEADERS)
    assert get_resp.status_code == 404


def test_delete_hs_code_not_found_404():
    """DELETE a nonexistent point_id returns 404."""
    fake_id = "00000000-0000-0000-0000-000000000002"
    resp = client.delete(f"{BASE_URL}/{fake_id}", headers=HEADERS)
    assert resp.status_code == 404
    assert "detail" in resp.json()


# ── List / Search ───────────────────────────────────────────────────────────


def test_list_hs_codes_paginated():
    """GET /hs-codes with page and size returns correctly shaped response."""
    resp = client.get(f"{BASE_URL}?page=1&size=10", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "size" in data
    assert data["page"] == 1
    assert data["size"] == 10
    assert isinstance(data["items"], list)


def test_list_hs_codes_search():
    """Create an HS code with a distinct name, then find it via search."""
    tag = _unique_id()
    search_name = f"УникальныйТовар_{tag}"
    hsc = _unique_hs_code(tag)
    _create_hs_code({"hs_code": hsc, "product_name_ru": search_name, "duty_rate": 7.5})

    resp = client.get(f"{BASE_URL}?search={search_name}", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(item["hs_code"] == hsc for item in data["items"])
