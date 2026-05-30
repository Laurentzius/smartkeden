import json
import threading
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from pathlib import Path


_AUDIT_LOG_PATH = Path(__file__).resolve().parents[3] / "data" / "audit_log.json"
_lock = threading.Lock()


class AuditLogger:
    """File-based audit logging for admin operations.

    Thread-safe writes to ``backend/data/audit_log.json``.
    Each entry includes timestamp, actor, action, entity_type, entity_id, and changes.
    """

    @staticmethod
    def _ensure_file() -> None:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not _AUDIT_LOG_PATH.exists():
            _AUDIT_LOG_PATH.write_text("[]", encoding="utf-8")

    @staticmethod
    def log(
        action: str,
        entity_type: str,
        entity_id: str = "",
        changes: Optional[Dict[str, Any]] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        actor: str = "admin",
    ) -> dict:
        """Append an audit log entry and return it."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "changes": changes or {},
            "old_values": old_values,
            "new_values": new_values,
        }
        with _lock:
            AuditLogger._ensure_file()
            try:
                raw = _AUDIT_LOG_PATH.read_text(encoding="utf-8").strip()
                logs: list = json.loads(raw) if raw else []
            except (json.JSONDecodeError, FileNotFoundError):
                logs = []
            logs.append(entry)
            _AUDIT_LOG_PATH.write_text(
                json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return entry

    @staticmethod
    def get_logs(
        page: int = 1,
        size: int = 50,
        entity_type: Optional[str] = None,
        action: Optional[str] = None,
    ) -> tuple:
        """Read paginated audit log entries. Returns (items, total)."""
        with _lock:
            AuditLogger._ensure_file()
            try:
                raw = _AUDIT_LOG_PATH.read_text(encoding="utf-8").strip()
                logs: list = json.loads(raw) if raw else []
            except (json.JSONDecodeError, FileNotFoundError):
                return [], 0

        # Filter
        filtered = logs
        if entity_type:
            filtered = [e for e in filtered if e.get("entity_type") == entity_type]
        if action:
            filtered = [e for e in filtered if e.get("action") == action]

        # Most recent first
        filtered.reverse()

        total = len(filtered)
        start = (page - 1) * size
        items = filtered[start : start + size]

        return items, total
