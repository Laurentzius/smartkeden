import pytest
from datetime import datetime, timezone
from pathlib import Path

import app.core.admin.audit_logger as audit_mod
from app.core.admin.audit_logger import AuditLogger


@pytest.fixture(autouse=True)
def _patch_audit_path(monkeypatch, tmp_path: Path) -> None:
    """Redirect _AUDIT_LOG_PATH to a temp file for test isolation."""
    monkeypatch.setattr(audit_mod, "_AUDIT_LOG_PATH", tmp_path / "audit_log.json")


class TestAuditLogger:
    """Audit logger CRUD, pagination, filtering, and value tracking."""

    def test_log_creates_entry(self):
        entry = AuditLogger.log(
            action="create",
            entity_type="law",
            entity_id="law-42",
            changes={"title": "New Tax Law"},
            actor="admin@test.kz",
        )
        assert isinstance(entry, dict)
        assert entry["action"] == "create"
        assert entry["entity_type"] == "law"
        assert entry["entity_id"] == "law-42"
        assert entry["changes"] == {"title": "New Tax Law"}
        assert entry["actor"] == "admin@test.kz"
        assert "timestamp" in entry
        assert entry["old_values"] is None
        assert entry["new_values"] is None

    def test_log_timestamp_is_iso8601(self):
        entry = AuditLogger.log(action="update", entity_type="hs_code", entity_id="8471.30")
        ts = entry["timestamp"]
        # Parse — raises on invalid format
        parsed = datetime.fromisoformat(ts)
        # Must be timezone-aware (UTC)
        assert parsed.tzinfo is not None
        assert parsed.tzinfo.utcoffset(parsed) is not None

    def test_get_logs_returns_entries(self):
        AuditLogger.log(action="create", entity_type="law", entity_id="l1")
        AuditLogger.log(action="create", entity_type="law", entity_id="l2")
        AuditLogger.log(action="create", entity_type="law", entity_id="l3")

        items, total = AuditLogger.get_logs()
        assert total == 3
        assert len(items) == 3
        # Most recent first
        assert items[0]["entity_id"] == "l3"
        assert items[1]["entity_id"] == "l2"
        assert items[2]["entity_id"] == "l1"

    def test_get_logs_pagination(self):
        for i in range(5):
            AuditLogger.log(action="create", entity_type="law", entity_id=f"l{i}")

        page1, total = AuditLogger.get_logs(page=1, size=2)
        assert total == 5
        assert len(page1) == 2
        # page 1 (first page) = most recent 2 items: l4, l3
        assert [e["entity_id"] for e in page1] == ["l4", "l3"]

        page2, total = AuditLogger.get_logs(page=2, size=2)
        assert total == 5
        assert len(page2) == 2
        assert [e["entity_id"] for e in page2] == ["l2", "l1"]

        page3, total = AuditLogger.get_logs(page=3, size=2)
        assert total == 5
        assert len(page3) == 1
        assert page3[0]["entity_id"] == "l0"

    def test_get_logs_filter_entity_type(self):
        AuditLogger.log(action="create", entity_type="law", entity_id="l1")
        AuditLogger.log(action="create", entity_type="hs_code", entity_id="h1")
        AuditLogger.log(action="create", entity_type="law", entity_id="l2")
        AuditLogger.log(action="create", entity_type="hs_code", entity_id="h2")

        items, total = AuditLogger.get_logs(entity_type="law")
        assert total == 2
        assert all(e["entity_type"] == "law" for e in items)

        items, total = AuditLogger.get_logs(entity_type="hs_code")
        assert total == 2
        assert all(e["entity_type"] == "hs_code" for e in items)

    def test_get_logs_filter_action(self):
        AuditLogger.log(action="create", entity_type="law", entity_id="l1")
        AuditLogger.log(action="delete", entity_type="law", entity_id="l2")
        AuditLogger.log(action="create", entity_type="law", entity_id="l3")

        items, total = AuditLogger.get_logs(action="create")
        assert total == 2
        assert all(e["action"] == "create" for e in items)

        items, total = AuditLogger.get_logs(action="delete")
        assert total == 1
        assert items[0]["action"] == "delete"

    def test_log_with_old_new_values(self):
        old = {"rate": 12.0, "name": "Old Name"}
        new = {"rate": 15.0, "name": "New Name"}
        entry = AuditLogger.log(
            action="update",
            entity_type="law",
            entity_id="law-99",
            changes={"rate": {"from": 12.0, "to": 15.0}},
            old_values=old,
            new_values=new,
        )
        assert entry["old_values"] == old
        assert entry["new_values"] == new
        assert entry["changes"] == {"rate": {"from": 12.0, "to": 15.0}}

        # Verify it was persisted
        items, _ = AuditLogger.get_logs(entity_type="law")
        persisted = items[0]
        assert persisted["old_values"] == old
        assert persisted["new_values"] == new
