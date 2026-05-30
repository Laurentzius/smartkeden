"""Integration tests for the Admin Rules API.

Tests CRUD endpoints, auth, validation, audit log, and edge cases.
Uses FastAPI TestClient with the shared SQLite database.
"""

import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import engine, Base, SessionLocal
from app.core.models import ClassificationRuleModel, RulesAuditLogModel
from app.core.config import settings

client = TestClient(app)
ADMIN_HEADERS = {"X-Admin-Key": settings.ADMIN_API_KEY}
BAD_HEADERS = {"X-Admin-Key": "wrong-key"}

# Test rule data
VALID_RULE = {
    "rule_id": "test_integration_rule",
    "category_mask": "9503*",
    "priority": 10,
    "conditions": [
        {"attribute": "material_outer", "operator": "==", "value": "пластик"}
    ],
    "action": {
        "type": "boost",
        "target_code": "9503003500",
        "reason": "Test integration rule",
        "confidence_boost": 0.1,
    },
    "source": "Test source document",
    "effective_date": (date.today() + timedelta(days=1)).isoformat(),
}


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Create tables before running tests."""
    Base.metadata.create_all(bind=engine)
    yield


def _cleanup_rule(rule_id: str):
    """Remove a rule from the database."""
    db = SessionLocal()
    try:
        db.query(ClassificationRuleModel).filter(
            ClassificationRuleModel.rule_id == rule_id
        ).delete()
        db.query(RulesAuditLogModel).filter(
            RulesAuditLogModel.rule_id == rule_id
        ).delete()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════
# Create Rule
# ══════════════════════════════════════════════════════════════════════════

class TestCreateRule:
    def test_create_rule_success(self):
        _cleanup_rule("test_integration_rule")
        response = client.post("/api/admin/rules", json=VALID_RULE, headers=ADMIN_HEADERS)
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["rule"]["rule_id"] == "test_integration_rule"
        assert data["rule"]["version"] == 1
        assert data["rule"]["is_active"] is True
        _cleanup_rule("test_integration_rule")

    def test_create_rule_duplicate_returns_409(self):
        _cleanup_rule("test_integration_rule")
        client.post("/api/admin/rules", json=VALID_RULE, headers=ADMIN_HEADERS)
        response = client.post("/api/admin/rules", json=VALID_RULE, headers=ADMIN_HEADERS)
        assert response.status_code == 409
        _cleanup_rule("test_integration_rule")

    def test_create_rule_without_source_returns_422(self):
        payload = {**VALID_RULE, "rule_id": "test_no_source", "source": ""}
        response = client.post("/api/admin/rules", json=payload, headers=ADMIN_HEADERS)
        assert response.status_code == 422

    def test_create_rule_effective_date_in_past_returns_422(self):
        payload = {**VALID_RULE, "rule_id": "test_past_date", "effective_date": "2020-01-01"}
        response = client.post("/api/admin/rules", json=payload, headers=ADMIN_HEADERS)
        assert response.status_code == 422

    def test_create_rule_without_auth_returns_401(self):
        response = client.post("/api/admin/rules", json=VALID_RULE)
        assert response.status_code == 401

    def test_create_rule_with_bad_auth_returns_401(self):
        response = client.post("/api/admin/rules", json=VALID_RULE, headers=BAD_HEADERS)
        assert response.status_code == 401

    def test_create_rule_invalid_condition_operator(self):
        payload = {
            **VALID_RULE,
            "rule_id": "test_bad_op",
            "conditions": [
                {"attribute": "material_outer", "operator": "invalid_op", "value": "пластик"}
            ],
        }
        response = client.post("/api/admin/rules", json=payload, headers=ADMIN_HEADERS)
        assert response.status_code == 422  # Pydantic validation rejects invalid operator

    def test_create_rule_invalid_action_type(self):
        payload = {
            **VALID_RULE,
            "rule_id": "test_bad_action",
            "action": {**VALID_RULE["action"], "type": "invalid_action"},
        }
        response = client.post("/api/admin/rules", json=payload, headers=ADMIN_HEADERS)
        assert response.status_code == 422  # Pydantic validation rejects invalid type


# ══════════════════════════════════════════════════════════════════════════
# Read Rules
# ══════════════════════════════════════════════════════════════════════════

class TestReadRules:
    def test_list_rules(self):
        response = client.get("/api/admin/rules")
        assert response.status_code == 200
        data = response.json()
        assert "rules" in data
        assert "total" in data
        assert isinstance(data["rules"], list)

    def test_list_rules_pagination(self):
        response = client.get("/api/admin/rules?skip=0&limit=5")
        assert response.status_code == 200
        data = response.json()
        assert len(data["rules"]) <= 5

    def test_get_active_rules(self):
        response = client.get("/api/admin/rules/active")
        assert response.status_code == 200
        data = response.json()
        assert "rules" in data

    def test_get_rule_not_found(self):
        response = client.get("/api/admin/rules/nonexistent_rule_id_xyz")
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# Update Rule
# ══════════════════════════════════════════════════════════════════════════

class TestUpdateRule:
    def test_update_rule_success(self):
        _cleanup_rule("test_integration_rule")
        client.post("/api/admin/rules", json=VALID_RULE, headers=ADMIN_HEADERS)
        update = {"priority": 20, "source": "Updated source"}
        response = client.put(
            "/api/admin/rules/test_integration_rule",
            json=update,
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["rule"]["priority"] == 20
        assert data["rule"]["source"] == "Updated source"
        assert data["rule"]["version"] == 2
        _cleanup_rule("test_integration_rule")

    def test_update_nonexistent_rule_returns_404(self):
        response = client.put(
            "/api/admin/rules/nonexistent_xyz",
            json={"priority": 20},
            headers=ADMIN_HEADERS,
        )
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# Delete Rule
# ══════════════════════════════════════════════════════════════════════════

class TestDeleteRule:
    def test_delete_rule_soft_delete(self):
        _cleanup_rule("test_integration_rule")
        client.post("/api/admin/rules", json=VALID_RULE, headers=ADMIN_HEADERS)
        response = client.delete(
            "/api/admin/rules/test_integration_rule", headers=ADMIN_HEADERS
        )
        assert response.status_code == 204
        _cleanup_rule("test_integration_rule")

    def test_delete_nonexistent_rule_returns_404(self):
        response = client.delete(
            "/api/admin/rules/nonexistent_xyz", headers=ADMIN_HEADERS
        )
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# Activate / Deactivate
# ══════════════════════════════════════════════════════════════════════════

class TestActivateDeactivate:
    def test_activate_deactivate_rule(self):
        _cleanup_rule("test_integration_rule")
        client.post("/api/admin/rules", json=VALID_RULE, headers=ADMIN_HEADERS)

        resp = client.post(
            "/api/admin/rules/test_integration_rule/deactivate",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["rule"]["is_active"] is False

        resp = client.post(
            "/api/admin/rules/test_integration_rule/activate",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["rule"]["is_active"] is True
        _cleanup_rule("test_integration_rule")


# ══════════════════════════════════════════════════════════════════════════
# Validate Rule
# ══════════════════════════════════════════════════════════════════════════

class TestValidateRule:
    def test_validate_valid_rule(self):
        payload = {
            "conditions": [
                {"attribute": "material_outer", "operator": "==", "value": "пластик"}
            ],
            "action": {"type": "boost", "target_code": "9503", "reason": "test"},
        }
        response = client.post("/api/admin/rules/validate", json=payload, headers=ADMIN_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["errors"] == []

    def test_validate_invalid_action(self):
        # Invalid action type → Pydantic validation rejects → 422
        payload = {
            "conditions": [
                {"attribute": "material_outer", "operator": "==", "value": "пластик"}
            ],
            "action": {"type": "bad_type", "target_code": "9503", "reason": "test"},
        }
        response = client.post("/api/admin/rules/validate", json=payload, headers=ADMIN_HEADERS)
        assert response.status_code == 422

    def test_validate_invalid_operator(self):
        # Invalid operator → Pydantic validation rejects → 422
        payload = {
            "conditions": [
                {"attribute": "material_outer", "operator": "bad_op", "value": "пластик"}
            ],
            "action": {"type": "boost", "target_code": "9503", "reason": "test"},
        }
        response = client.post("/api/admin/rules/validate", json=payload, headers=ADMIN_HEADERS)
        assert response.status_code == 422


# ══════════════════════════════════════════════════════════════════════════
# Test Rule on Example
# ══════════════════════════════════════════════════════════════════════════

class TestRuleTestEndpoint:
    def test_test_rule_matches(self):
        _cleanup_rule("test_integration_rule")
        client.post("/api/admin/rules", json=VALID_RULE, headers=ADMIN_HEADERS)

        payload = {
            "rule_id": "test_integration_rule",
            "attributes": {"material_outer": "пластик"},
            "candidates": [{"hs_code": "9503001000", "confidence_score": 0.7}],
        }
        response = client.post("/api/admin/rules/test", json=payload, headers=ADMIN_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["matches"] is True
        _cleanup_rule("test_integration_rule")

    def test_test_rule_no_match(self):
        _cleanup_rule("test_integration_rule")
        client.post("/api/admin/rules", json=VALID_RULE, headers=ADMIN_HEADERS)

        payload = {
            "rule_id": "test_integration_rule",
            "attributes": {"material_outer": "дерево"},
        }
        response = client.post("/api/admin/rules/test", json=payload, headers=ADMIN_HEADERS)
        assert response.status_code == 200
        data = response.json()
        assert data["matches"] is False
        _cleanup_rule("test_integration_rule")


# ══════════════════════════════════════════════════════════════════════════
# Audit Log
# ══════════════════════════════════════════════════════════════════════════

class TestAuditLog:
    def test_audit_log_endpoint(self):
        response = client.get("/api/admin/rules/audit")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    def test_audit_log_with_rule_filter(self):
        response = client.get("/api/admin/rules/audit?rule_id=test_integration_rule")
        assert response.status_code == 200
