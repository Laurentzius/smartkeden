"""
Admin Configuration API router.

Read endpoints (no auth):
  GET  /api/admin/config/rates
  GET  /api/admin/config/rates/{rate_type}
  GET  /api/admin/config/rates/{rate_type}/current
  GET  /api/admin/config/rates/{rate_type}/at/{date}

Write endpoints (require X-Admin-Key header):
  PUT     /api/admin/config/rates/{rate_type}
  POST    /api/admin/config/rates/{rate_type}/cancel/{version}
  DELETE  /api/admin/config/rates/{rate_type}/{version}
  GET     /api/admin/config/audit
"""

import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.admin.auth import verify_admin_key
from app.core.admin.config_schemas import (
    RateUpdateRequest,
    RateHistoryResponse,
    RateCurrentResponse,
    RateAtDateResponse,
    RatesAllResponse,
    RateUpdateResponse,
    CancelResponse,
    DeleteResponse,
    AuditPaginatedResponse,
    VALID_RATE_TYPES,
)
from app.core.admin.audit_logger import AuditLogger
from app.core.config_service import config_service

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/config",
    tags=["Admin / Configuration"],
)

# ── Internal helper ──────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Read endpoints (no auth) ─────────────────────────────────────────────────


@router.get("/rates", response_model=RatesAllResponse)
async def get_all_rates():
    """Get all current rates (no auth)."""
    rates = config_service.get_all_current()
    return RatesAllResponse(rates=rates)


@router.get("/rates/{rate_type}", response_model=RateHistoryResponse)
async def get_rate_history(rate_type: str):
    """Get full version history for a specific rate type."""
    if rate_type not in VALID_RATE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown rate_type '{rate_type}'. Valid types: {sorted(VALID_RATE_TYPES)}",
        )
    versions = config_service.get_history(rate_type)
    return RateHistoryResponse(rate_type=rate_type, versions=versions)


@router.get("/rates/{rate_type}/current", response_model=RateCurrentResponse)
async def get_current_rate(rate_type: str):
    """Get the currently active rate for a specific rate type."""
    if rate_type not in VALID_RATE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown rate_type '{rate_type}'. Valid types: {sorted(VALID_RATE_TYPES)}",
        )
    value = config_service.get_rate(rate_type)
    history = config_service.get_history(rate_type)
    if not history:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No versions found for rate_type '{rate_type}'",
        )
    current = history[0]  # newest first
    return RateCurrentResponse(
        value=value,
        effective_date=current.effective_date,
        version=current.version,
    )


@router.get("/rates/{rate_type}/at/{target_date}", response_model=RateAtDateResponse)
async def get_rate_at_date(rate_type: str, target_date: str):
    """Get the rate value valid on a specific date."""
    if rate_type not in VALID_RATE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown rate_type '{rate_type}'. Valid types: {sorted(VALID_RATE_TYPES)}",
        )
    # Validate date format
    try:
        date.fromisoformat(target_date)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="target_date must be in ISO format (YYYY-MM-DD)",
        )
    value = config_service.get_rate(rate_type, declaration_date=target_date)
    history = config_service.get_history(rate_type)
    # Find which version applies to this date
    applicable_version = 0
    applicable_eff = target_date
    for v in history:
        if v.effective_date <= target_date:
            exp = v.expiry_date or "9999-12-31"
            if target_date <= exp:
                applicable_version = v.version
                applicable_eff = v.effective_date
                break
    if applicable_version == 0 and history:
        applicable_version = history[-1].version
        applicable_eff = history[-1].effective_date

    return RateAtDateResponse(
        value=value,
        effective_date=applicable_eff,
        version=applicable_version,
        rate_type=rate_type,
        requested_date=target_date,
    )


# ── Write endpoints (require auth) ───────────────────────────────────────────


@router.put(
    "/rates/{rate_type}",
    response_model=RateUpdateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def update_rate(
    rate_type: str,
    req: RateUpdateRequest,
    admin_key: str = Depends(verify_admin_key),
):
    """Update a rate — creates a new version. Requires X-Admin-Key."""
    if rate_type not in VALID_RATE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown rate_type '{rate_type}'. Valid types: {sorted(VALID_RATE_TYPES)}",
        )

    # Capture old value
    old_value = config_service.get_rate(rate_type, declaration_date=req.effective_date)

    try:
        new_version = config_service.update_rate(
            rate_type=rate_type,
            value=req.value,
            effective_date=req.effective_date,
            reason=req.reason,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    # Log audit event
    AuditLogger.log(
        action="update_rate",
        entity_type=f"config:{rate_type}",
        entity_id=str(new_version.version),
        changes={
            "old_value": old_value,
            "new_value": req.value,
            "effective_date": req.effective_date,
        },
        old_values={"value": old_value, "effective_date": req.effective_date},
        new_values={"value": req.value, "effective_date": req.effective_date},
        actor="admin",
    )

    logger.info(
        "Rate updated: %s v%d → v%d (%.4f, effective %s)",
        rate_type,
        new_version.version - 1,
        new_version.version,
        req.value,
        req.effective_date,
    )

    return RateUpdateResponse(
        rate_type=rate_type,
        version=new_version.version,
        old_value=old_value,
        new_value=req.value,
        effective_date=req.effective_date,
    )


@router.post(
    "/rates/{rate_type}/cancel/{version}",
    response_model=CancelResponse,
)
async def cancel_scheduled_rate(
    rate_type: str,
    version: int,
    admin_key: str = Depends(verify_admin_key),
):
    """Cancel a scheduled (future-dated) rate version. Requires X-Admin-Key."""
    if rate_type not in VALID_RATE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown rate_type '{rate_type}'. Valid types: {sorted(VALID_RATE_TYPES)}",
        )
    try:
        result = config_service.cancel_rate(rate_type, version)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version} not found for rate_type '{rate_type}'",
        )

    AuditLogger.log(
        action="cancel_rate",
        entity_type=f"config:{rate_type}",
        entity_id=str(version),
        actor="admin",
    )

    return CancelResponse(
        status="cancelled",
        rate_type=rate_type,
        version=version,
        message=f"Rate version {version} has been cancelled",
    )


@router.delete(
    "/rates/{rate_type}/{version}",
    response_model=DeleteResponse,
)
async def delete_rate_version(
    rate_type: str,
    version: int,
    admin_key: str = Depends(verify_admin_key),
):
    """Soft-delete a rate version (mark as deprecated). Requires X-Admin-Key."""
    if rate_type not in VALID_RATE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown rate_type '{rate_type}'. Valid types: {sorted(VALID_RATE_TYPES)}",
        )
    try:
        success, warning = config_service.delete_rate(rate_type, version)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Version {version} not found for rate_type '{rate_type}'",
        )

    AuditLogger.log(
        action="delete_rate",
        entity_type=f"config:{rate_type}",
        entity_id=str(version),
        actor="admin",
    )

    return DeleteResponse(
        status="deprecated",
        rate_type=rate_type,
        version=version,
        message="Rate version has been soft-deleted (marked as deprecated)",
        warning=warning,
    )


# ── Audit endpoint (requires auth) ───────────────────────────────────────────


@router.get("/audit", response_model=AuditPaginatedResponse)
async def get_audit_log(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    entity_type: Optional[str] = Query(
        None, description="Filter by entity type (e.g., config:import_vat)"
    ),
    action: Optional[str] = Query(None, description="Filter by action"),
    admin_key: str = Depends(verify_admin_key),
):
    """View the audit log of all configuration changes. Requires X-Admin-Key."""
    items, total = AuditLogger.get_logs(
        page=page,
        size=size,
        entity_type=entity_type,
        action=action,
    )
    return AuditPaginatedResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )
