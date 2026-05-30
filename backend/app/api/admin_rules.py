"""Admin API router for Classification Rules management.

Provides CRUD endpoints for classification rules, rule testing,
validation, audit log access, and activation/deactivation.

All write endpoints require X-Admin-Key header authentication.
"""

import json
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.admin.auth import verify_admin_key
from app.core.database import get_db, SessionLocal
from app.core.models import ClassificationRuleModel, RulesAuditLogModel
from app.core.classification.rule_models import (
    ClassificationRule as ClassificationRulePydantic,
    RuleCreateRequest,
    RuleUpdateRequest,
    RuleTestRequest,
    RuleValidateRequest,
    RuleValidateResponse,
    RuleResponse,
    RuleListResponse,
    AuditLogListResponse,
    RuleAction,
    RuleCondition,
    VALID_OPERATORS,
    VALID_ACTION_TYPES,
)
from app.core.classification.rules_engine import RulesEngine

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/rules",
    tags=["Admin / Classification Rules"],
)


# ── Helpers ──────────────────────────────────────────────────────────────

def _orm_to_pydantic(row: ClassificationRuleModel) -> ClassificationRulePydantic:
    """Convert SQLAlchemy ORM row to Pydantic model."""
    return ClassificationRulePydantic(
        rule_id=row.rule_id,
        category_mask=row.category_mask,
        priority=row.priority,
        conditions=row.conditions,
        action=RuleAction(**row.action) if isinstance(row.action, dict) else row.action,
        source=row.source,
        effective_date=row.effective_date.date() if hasattr(row.effective_date, 'date') else row.effective_date,
        expiry_date=row.expiry_date.date() if row.expiry_date and hasattr(row.expiry_date, 'date') else row.expiry_date,
        created_by=row.created_by,
        version=row.version,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _log_audit(
    db: Session,
    rule_id: str,
    action: str,
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
) -> None:
    """Log a CRUD operation to the audit table."""
    try:
        entry = RulesAuditLogModel(
            rule_id=rule_id,
            action=action,
            attributes=json.dumps({"old": old_values, "new": new_values}, default=str) if old_values or new_values else None,
        )
        db.add(entry)
        db.commit()
    except Exception:
        logger.exception("Failed to log audit for rule %s (non-blocking)", rule_id)


def _validate_conditions(conditions) -> list[str]:
    """Validate conditions structure. Returns list of error messages."""
    errors = []

    def _check_condition(c: dict) -> list[str]:
        errs = []
        if not isinstance(c, dict):
            return ["Condition must be a dict"]
        if "attribute" not in c:
            errs.append("Condition missing 'attribute'")
        if "operator" not in c:
            errs.append("Condition missing 'operator'")
        elif c["operator"] not in VALID_OPERATORS:
            errs.append(f"Invalid operator '{c['operator']}'. Must be one of: {sorted(VALID_OPERATORS)}")
        if "value" not in c:
            errs.append("Condition missing 'value'")
        return errs

    # Normalize: convert Pydantic models to dicts
    if hasattr(conditions, 'model_dump'):
        conditions = conditions.model_dump()
    elif isinstance(conditions, list):
        conditions = [c.model_dump() if hasattr(c, 'model_dump') else c for c in conditions]

    if isinstance(conditions, list):
        for i, c in enumerate(conditions):
            if isinstance(c, dict) and "attribute" in c:
                errors.extend([f"Condition {i}: {e}" for e in _check_condition(c)])
            elif isinstance(c, dict) and ("all" in c or "any" in c):
                errors.extend(_validate_conditions(c))
            else:
                errors.append(f"Condition {i}: invalid format")
    elif isinstance(conditions, dict):
        if "all" in conditions:
            errors.extend(_validate_conditions(conditions["all"]))
        elif "any" in conditions:
            errors.extend(_validate_conditions(conditions["any"]))
        elif "attribute" in conditions:
            # Single condition as a dict
            errors.extend(_check_condition(conditions))
        else:
            errors.append("Conditions dict must have 'all', 'any', or condition keys")

    return errors


def _validate_action(action: dict) -> list[str]:
    """Validate action structure. Returns list of error messages."""
    # Normalize: convert Pydantic model to dict
    if hasattr(action, 'model_dump'):
        action = action.model_dump()
    errors = []
    if not isinstance(action, dict):
        return ["Action must be a dict"]
    if "type" not in action:
        errors.append("Action missing 'type'")
    elif action["type"] not in VALID_ACTION_TYPES:
        errors.append(f"Invalid action type '{action['type']}'. Must be one of: {sorted(VALID_ACTION_TYPES)}")
    return errors


# ══════════════════════════════════════════════════════════════════════════
# Read Endpoints (no auth required for GET)
# ══════════════════════════════════════════════════════════════════════════

@router.get("", response_model=RuleListResponse)
async def list_rules(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List all classification rules with pagination."""
    total = db.query(ClassificationRuleModel).count()
    rows = (
        db.query(ClassificationRuleModel)
        .order_by(ClassificationRuleModel.priority.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    rules = [_orm_to_pydantic(r) for r in rows]
    return RuleListResponse(rules=rules, total=total)


@router.get("/active", response_model=RuleListResponse)
async def get_active_rules(db: Session = Depends(get_db)):
    """Get only active rules (is_active=true and not expired)."""
    today = date.today()
    rows = (
        db.query(ClassificationRuleModel)
        .filter(
            ClassificationRuleModel.is_active == True,
            ClassificationRuleModel.effective_date <= today,
            (
                (ClassificationRuleModel.expiry_date == None)
                | (ClassificationRuleModel.expiry_date >= today)
            ),
        )
        .order_by(ClassificationRuleModel.priority.desc())
        .all()
    )
    rules = [_orm_to_pydantic(r) for r in rows]
    return RuleListResponse(rules=rules, total=len(rules))


@router.get("/audit", response_model=AuditLogListResponse)
async def get_audit_log(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    rule_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """View the rules audit log."""
    query = db.query(RulesAuditLogModel)
    if rule_id:
        query = query.filter(RulesAuditLogModel.rule_id == rule_id)
    total = query.count()
    rows = (
        query
        .order_by(RulesAuditLogModel.timestamp.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "rule_id": r.rule_id,
            "action": r.action,
            "product_description": r.product_description,
            "attributes": r.attributes,
            "old_candidates": r.old_candidates,
            "new_candidates": r.new_candidates,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "session_id": r.session_id,
        })
    return AuditLogListResponse(items=items, total=total)


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(rule_id: str, db: Session = Depends(get_db)):
    """Get a single rule by ID."""
    row = (
        db.query(ClassificationRuleModel)
        .filter(ClassificationRuleModel.rule_id == rule_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    return RuleResponse(rule=_orm_to_pydantic(row))


# ══════════════════════════════════════════════════════════════════════════
# Write Endpoints (require X-Admin-Key)
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
# Write Endpoints (require X-Admin-Key)
# ══════════════════════════════════════════════════════════════════════════

@router.post("", status_code=status.HTTP_201_CREATED, response_model=RuleResponse)
async def create_rule(
    request: RuleCreateRequest,
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Create a new classification rule."""
    # Check for duplicate rule_id
    existing = (
        db.query(ClassificationRuleModel)
        .filter(ClassificationRuleModel.rule_id == request.rule_id)
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Rule ID already exists")

    # Validate conditions and action
    cond_errors = _validate_conditions(request.conditions)
    act_errors = _validate_action(request.action.model_dump())
    all_errors = cond_errors + act_errors
    if all_errors:
        raise HTTPException(
            status_code=400,
            detail={"message": "Validation failed", "errors": all_errors},
        )

    # Create ORM row
    now = datetime.now(timezone.utc)
    row = ClassificationRuleModel(
        rule_id=request.rule_id,
        category_mask=request.category_mask,
        priority=request.priority,
        conditions=request.conditions if isinstance(request.conditions, dict)
        else [c.model_dump() for c in request.conditions],
        action=request.action.model_dump(),
        source=request.source,
        effective_date=datetime.combine(request.effective_date, datetime.min.time()),
        expiry_date=datetime.combine(request.expiry_date, datetime.min.time()) if request.expiry_date else None,
        created_by=request.created_by,
        version=1,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    _log_audit(db, request.rule_id, "created", new_values={
        "category_mask": request.category_mask,
        "priority": request.priority,
        "source": request.source,
    })

    return RuleResponse(rule=_orm_to_pydantic(row))


@router.put("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: str,
    request: RuleUpdateRequest,
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Update an existing classification rule."""
    row = (
        db.query(ClassificationRuleModel)
        .filter(ClassificationRuleModel.rule_id == rule_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    old_values = {
        "conditions": row.conditions,
        "action": row.action,
        "priority": row.priority,
        "source": row.source,
    }

    # Apply updates
    if request.conditions is not None:
        cond_errors = _validate_conditions(request.conditions)
        if cond_errors:
            raise HTTPException(status_code=400, detail={"message": "Validation failed", "errors": cond_errors})
        row.conditions = request.conditions if isinstance(request.conditions, dict) else [c.model_dump() for c in request.conditions]

    if request.action is not None:
        act_errors = _validate_action(request.action.model_dump())
        if act_errors:
            raise HTTPException(status_code=400, detail={"message": "Validation failed", "errors": act_errors})
        row.action = request.action.model_dump()

    if request.priority is not None:
        row.priority = request.priority

    if request.source is not None:
        if not request.source.strip():
            raise HTTPException(status_code=422, detail="Source is required")
        row.source = request.source

    if request.effective_date is not None:
        row.effective_date = datetime.combine(request.effective_date, datetime.min.time())

    if request.expiry_date is not None:
        row.expiry_date = datetime.combine(request.expiry_date, datetime.min.time())

    row.version += 1
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    _log_audit(db, rule_id, "updated", old_values=old_values, new_values={
        "conditions": row.conditions,
        "action": row.action,
        "priority": row.priority,
        "source": row.source,
    })

    return RuleResponse(rule=_orm_to_pydantic(row))


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Soft-delete a rule (sets is_active=False)."""
    row = (
        db.query(ClassificationRuleModel)
        .filter(ClassificationRuleModel.rule_id == rule_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    old_is_active = row.is_active
    row.is_active = False
    row.updated_at = datetime.now(timezone.utc)
    db.commit()

    _log_audit(db, rule_id, "deleted", old_values={"is_active": old_is_active}, new_values={"is_active": False})


@router.post("/{rule_id}/activate", response_model=RuleResponse)
async def activate_rule(
    rule_id: str,
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Activate a rule."""
    row = (
        db.query(ClassificationRuleModel)
        .filter(ClassificationRuleModel.rule_id == rule_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    row.is_active = True
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    _log_audit(db, rule_id, "activated")
    return RuleResponse(rule=_orm_to_pydantic(row))


@router.post("/{rule_id}/deactivate", response_model=RuleResponse)
async def deactivate_rule(
    rule_id: str,
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Deactivate a rule."""
    row = (
        db.query(ClassificationRuleModel)
        .filter(ClassificationRuleModel.rule_id == rule_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")

    row.is_active = False
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)

    _log_audit(db, rule_id, "deactivated")
    return RuleResponse(rule=_orm_to_pydantic(row))


# ══════════════════════════════════════════════════════════════════════════
# Test & Validation Endpoints
# ══════════════════════════════════════════════════════════════════════════

@router.post("/test")
async def test_rule(
    request: RuleTestRequest,
    admin_key: str = Depends(verify_admin_key),
    db: Session = Depends(get_db),
):
    """Test a rule on example product attributes.

    Returns whether the rule matches and what the result would be.
    """
    rules_engine = RulesEngine(db_session=db)

    if request.rule_id:
        # Load rule from DB
        row = (
            db.query(ClassificationRuleModel)
            .filter(ClassificationRuleModel.rule_id == request.rule_id)
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Rule not found")
        rule = _orm_to_pydantic(row)
    elif request.conditions and request.action:
        # Use inline rule
        rule = ClassificationRulePydantic(
            rule_id="test_rule",
            category_mask="*",
            priority=0,
            conditions=request.conditions,
            action=request.action,
            source="inline test",
            effective_date=date.today(),
            is_active=True,
        )
    else:
        raise HTTPException(status_code=400, detail="Either rule_id or conditions+action must be provided")

    # Test match
    match_result = rules_engine.check_rule_match(rule, request.attributes)

    # Apply if matches
    result_candidates = request.candidates
    if match_result is True and request.candidates:
        result = rules_engine.apply_rules(
            candidates=request.candidates,
            attributes=request.attributes,
            rules=[rule],
        )
        result_candidates = result.candidates

    return {
        "rule_id": rule.rule_id,
        "matches": match_result is True,
        "missing_attribute": match_result if isinstance(match_result, str) else None,
        "input_candidates": request.candidates,
        "output_candidates": result_candidates,
    }


@router.post("/validate", response_model=RuleValidateResponse)
async def validate_rule(
    request: RuleValidateRequest,
    admin_key: str = Depends(verify_admin_key),
):
    """Validate rule syntax without creating it.

    Checks conditions structure and action validity.
    """
    errors = []

    # Validate conditions
    cond_errors = _validate_conditions(request.conditions)
    errors.extend(cond_errors)

    # Validate action
    act_errors = _validate_action(request.action.model_dump())
    errors.extend(act_errors)

    return RuleValidateResponse(
        valid=len(errors) == 0,
        errors=errors,
    )
