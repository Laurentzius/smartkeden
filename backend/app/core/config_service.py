"""
Configuration Service — centralized, versioned rate storage.

Thread-safe JSON file storage at ``backend/data/config.json``.
Falls back to ``business_rules.py`` hardcoded defaults when the config DB
is unavailable.
"""

import json
import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.admin.config_schemas import (
    RateVersion,
    VALID_RATE_TYPES,
)

logger = logging.getLogger(__name__)


# ── Lock for thread-safe file reads/writes ───────────────────────────────────

_config_lock = threading.Lock()


def _resolve_config_path() -> Path:
    """Resolve the config DB path relative to the backend root."""
    p = Path(settings.CONFIG_DB_PATH)
    if not p.is_absolute():
        # Resolve relative to the backend package root
        # __file__ = .../backend/app/core/config_service.py
        # parents[2] = .../backend
        backend_root = Path(__file__).resolve().parents[2]
        p = backend_root / p
    return p


# ── Private helpers ──────────────────────────────────────────────────────────


def _load_config_db() -> dict:
    """Load the entire config DB from disk.  Returns an empty structure on failure."""
    path = _resolve_config_path()
    try:
        if not path.exists():
            logger.warning("config.json not found at %s; returning empty DB", path)
            return {"rates": {}}
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"rates": {}}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load config DB from %s: %s", path, exc)
        return {"rates": {}}


def _save_config_db(data: dict) -> bool:
    """Atomically write the config DB to disk.  Returns True on success."""
    path = _resolve_config_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to temp file then rename for atomicity
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError as exc:
        logger.error("Failed to save config DB to %s: %s", path, exc)
        return False


def _date_from_str(d: Optional[str]) -> Optional[date]:
    """Parse an ISO date string; returns None on failure or None input."""
    if d is None:
        return None
    try:
        return date.fromisoformat(d)
    except (ValueError, TypeError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── ConfigService ────────────────────────────────────────────────────────────


class ConfigService:
    """Singleton service for versioned customs configuration rates.

    All public methods acquire the ``_config_lock`` so concurrent calls
    are serialised — last write wins for updates.
    """

    _instance: Optional["ConfigService"] = None
    _initialised: bool = False

    def __new__(cls) -> "ConfigService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ── Read operations ──────────────────────────────────────────────────

    def get_rate(self, rate_type: str, declaration_date: Optional[str] = None) -> float:
        """Return the rate value for *rate_type* active on *declaration_date*.

        If *declaration_date* is None, the current date is used.
        Falls back to ``business_rules.py`` when the config DB is unavailable.
        """
        try:
            with _config_lock:
                db = _load_config_db()
                rates = db.get("rates", {})

            if rate_type not in rates:
                logger.warning(
                    "Unknown rate_type '%s'; valid types: %s",
                    rate_type,
                    sorted(VALID_RATE_TYPES),
                )
                return self._fallback_rate(rate_type)

            versions: list = rates[rate_type]
            if not versions:
                logger.info(
                    "No versions configured for rate_type '%s'; returning fallback",
                    rate_type,
                )
                return self._fallback_rate(rate_type)

            # MCI entries are keyed by year, not by date range
            if rate_type == "mci":
                return self._fallback_rate(rate_type)

            target = (
                _date_from_str(declaration_date) if declaration_date else date.today()
            )

            # Find the version whose effective_date ≤ target ≤ expiry_date
            matched = self._find_version_for_date(versions, target)
            if matched is not None:
                return matched.get("value", self._fallback_rate(rate_type))

            # No matching version — return earliest available
            logger.warning(
                "No rate version covers %s for '%s'; returning earliest available",
                target.isoformat(),
                rate_type,
            )
            earliest = min(
                versions,
                key=lambda v: _date_from_str(v.get("effective_date")) or date.max,
            )
            return earliest.get("value", self._fallback_rate(rate_type))

        except Exception as exc:
            logger.error(
                "ConfigService.get_rate(%s, %s) failed: %s; using fallback",
                rate_type,
                declaration_date,
                exc,
            )
            return self._fallback_rate(rate_type)

    def get_mci(self, year: int) -> float:
        """Return the MCI value for the given *year*.  Falls back on failure."""
        try:
            with _config_lock:
                db = _load_config_db()
                mci_entries = db.get("rates", {}).get("mci", [])

            for entry in mci_entries:
                if entry.get("year") == year:
                    return float(entry["value"])

            logger.warning("No MCI entry for year %d; returning latest available", year)
            if mci_entries:
                latest = max(mci_entries, key=lambda e: e.get("year", 0))
                return float(latest["value"])
            return self._fallback_rate("mci")

        except Exception as exc:
            logger.error(
                "ConfigService.get_mci(%d) failed: %s; using fallback", year, exc
            )
            return self._fallback_rate("mci")

    def get_history(self, rate_type: str) -> List[RateVersion]:
        """Return all versions for *rate_type*, newest first."""
        with _config_lock:
            db = _load_config_db()
            versions = db.get("rates", {}).get(rate_type, [])
        result = [
            RateVersion(
                value=v.get("value"),
                effective_date=v.get("effective_date", ""),
                expiry_date=v.get("expiry_date"),
                version=v.get("version", 0),
                created_by=v.get("created_by", "system"),
                created_at=v.get("created_at", ""),
            )
            for v in versions
        ]
        result.sort(key=lambda rv: rv.version, reverse=True)
        return result

    def get_all_current(self) -> Dict[str, float]:
        """Return a dict mapping each rate_type → current active value."""
        result: Dict[str, float] = {}
        today = date.today()
        try:
            with _config_lock:
                db = _load_config_db()
                rates = db.get("rates", {})

            for rate_type, versions in rates.items():
                if rate_type == "mci":
                    # Use the latest year
                    if versions:
                        latest = max(versions, key=lambda e: e.get("year", 0))
                        result[rate_type] = float(latest["value"])
                    else:
                        result[rate_type] = self._fallback_rate("mci")
                elif versions:
                    matched = self._find_version_for_date(versions, today)
                    if matched:
                        result[rate_type] = float(matched["value"])
                    else:
                        # Earliest available
                        earliest = min(
                            versions,
                            key=lambda v: (
                                _date_from_str(v.get("effective_date")) or date.max
                            ),
                        )
                        result[rate_type] = float(earliest["value"])
                else:
                    result[rate_type] = self._fallback_rate(rate_type)
        except Exception as exc:
            logger.error("ConfigService.get_all_current() failed: %s", exc)
            for rt in VALID_RATE_TYPES:
                result[rt] = self._fallback_rate(rt)
        return result

    # ── Write operations ─────────────────────────────────────────────────

    def update_rate(
        self,
        rate_type: str,
        value: float,
        effective_date: str,
        reason: Optional[str] = None,
    ) -> RateVersion:
        """Create a new rate version.

        Returns the newly created ``RateVersion``.
        Auto-adjusts the ``expiry_date`` of the previously active version
        to the day before *effective_date*.
        """
        with _config_lock:
            db = _load_config_db()
            rates = db.setdefault("rates", {})
            versions: list = rates.setdefault(rate_type, [])

            # Determine next version number
            next_version = 1
            if versions:
                next_version = max(v.get("version", 0) for v in versions) + 1

            # Auto-adjust expiry of the version that would overlap
            new_eff_date = _date_from_str(effective_date)
            if new_eff_date:
                for v in versions:
                    v_exp = _date_from_str(v.get("expiry_date"))
                    v_eff = _date_from_str(v.get("effective_date"))
                    # If this version is currently active (no expiry or future expiry)
                    # and its effective_date ≤ new effective_date, set its expiry
                    if v_eff and v_eff < new_eff_date:
                        is_active = v_exp is None or v_exp >= date.today()
                        if is_active and (v_exp is None or v_exp >= new_eff_date):
                            # Set expiry to the day before new effective date
                            prev_day = (
                                new_eff_date.replace(day=new_eff_date.day - 1)
                                if new_eff_date.day > 1
                                else new_eff_date.replace(
                                    month=new_eff_date.month - 1, day=28
                                )
                                if new_eff_date.month > 1
                                else new_eff_date.replace(
                                    year=new_eff_date.year - 1, month=12, day=31
                                )
                            )
                            # Actually, let's just use the day before:
                            from datetime import timedelta

                            prev_day = new_eff_date - timedelta(days=1)
                            v["expiry_date"] = prev_day.isoformat()

            now_iso = _now_iso()
            entry: Dict[str, Any] = {
                "value": value,
                "effective_date": effective_date,
                "expiry_date": None,
                "version": next_version,
                "created_by": "admin",
                "created_at": now_iso,
            }
            versions.append(entry)

            if not _save_config_db(db):
                raise RuntimeError("Failed to persist config DB")

        return RateVersion(
            value=entry["value"],
            effective_date=entry["effective_date"],
            expiry_date=entry.get("expiry_date"),
            version=entry["version"],
            created_by=entry["created_by"],
            created_at=entry["created_at"],
        )

    def cancel_rate(self, rate_type: str, version: int) -> Optional[dict]:
        """Cancel a scheduled (future) rate version by marking it as cancelled.

        Returns the updated entry dict or None if not found.
        """
        with _config_lock:
            db = _load_config_db()
            versions: list = db.get("rates", {}).get(rate_type, [])
            target = None
            for v in versions:
                if v.get("version") == version:
                    target = v
                    break
            if target is None:
                return None

            # Only cancel if the effective_date is in the future (scheduled)
            eff = _date_from_str(target.get("effective_date"))
            if eff and eff <= date.today():
                raise ValueError(
                    f"Cannot cancel version {version}: effective_date {target['effective_date']} "
                    "is not in the future"
                )

            target["expiry_date"] = target.get("effective_date")  # mark as cancelled
            target["status"] = "cancelled"

            if not _save_config_db(db):
                raise RuntimeError("Failed to persist config DB")
        return dict(target)

    def delete_rate(self, rate_type: str, version: int) -> Tuple[bool, Optional[str]]:
        """Soft-delete a rate version (mark as deprecated).

        Returns (success, warning_message).  Warning is set when the version
        might be referenced by historical calculations.
        """
        with _config_lock:
            db = _load_config_db()
            versions: list = db.get("rates", {}).get(rate_type, [])
            target = None
            for v in versions:
                if v.get("version") == version:
                    target = v
                    break
            if target is None:
                return False, None

            # Soft-delete: mark as deprecated
            target["status"] = "deprecated"
            warning = (
                "This version may be referenced by historical calculations. "
                "It has been soft-deleted (marked as deprecated) and remains "
                "in the database for audit purposes."
            )

            if not _save_config_db(db):
                raise RuntimeError("Failed to persist config DB")
        return True, warning

    # ── Private helpers ──────────────────────────────────────────────────

    @staticmethod
    def _find_version_for_date(versions: list, target: date) -> Optional[dict]:
        """Find the version whose effective_date ≤ target ≤ expiry_date."""
        for v in sorted(
            versions, key=lambda x: _date_from_str(x.get("effective_date")) or date.min
        ):
            eff = _date_from_str(v.get("effective_date"))
            exp = _date_from_str(v.get("expiry_date"))
            if eff is None:
                continue
            if eff > target:
                continue
            if exp is not None and exp < target:
                continue
            return v
        return None

    @staticmethod
    def _fallback_rate(rate_type: str) -> float:
        """Return the hardcoded fallback rate from ``business_rules.py``."""
        from app.core.business_rules import rules

        mapping = {
            "import_vat": rules.import_vat_rate,
            "customs_processing_fee": rules.customs_processing_fee_kzt,
            "mci": 4325.0,  # current MCI as fallback
            "recycling_rates": 0.0,
            "excise_rates": 0.0,
        }
        return mapping.get(rate_type, 0.0)


# ── Module-level singleton ───────────────────────────────────────────────────

config_service = ConfigService()
