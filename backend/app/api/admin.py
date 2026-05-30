import logging
import uuid
import asyncio
from typing import Optional, Dict

from fastapi import APIRouter, HTTPException, Depends, Query, status

from app.core.admin.auth import verify_admin_key
from app.core.admin.schemas import (
    LawDocumentCreate,
    LawDocumentUpdate,
    LawDocumentResponse,
    HsCodeCreate,
    HsCodeUpdate,
    HsCodeResponse,
    ReindexRequest,
    ReindexStatus,
    PaginatedResponse,
    ErrorResponse,
)
from app.core.admin.audit_logger import AuditLogger
from app.core.rag.indexer import LegalRAGIndexer

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/knowledge",
    tags=["Admin / Knowledge Management"],
    dependencies=[Depends(verify_admin_key)],
)

# ── In-memory reindex job tracking ──────────────────────────────────────────
_reindex_jobs: Dict[str, dict] = {}
_reindex_lock = asyncio.Lock()
REINDEX_TIMEOUT = 3600  # 1 hour


def _log_and_return(
    action: str,
    entity_type: str,
    entity_id: str = "",
    old_values: Optional[dict] = None,
    new_values: Optional[dict] = None,
    changes: Optional[dict] = None,
):
    AuditLogger.log(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_values=old_values,
        new_values=new_values,
        changes=changes,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Law Documents
# ═══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/laws",
    response_model=LawDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
async def create_law(doc: LawDocumentCreate):
    """Create a new legal document article."""
    # Content deduplication check
    dup_id = LegalRAGIndexer.check_content_similarity(
        collection_name=LegalRAGIndexer.COLLECTION_NAME,
        text=f"{doc.article} {doc.content}",
        threshold=0.95,
    )
    if dup_id:
        raise HTTPException(
            status_code=409,
            detail=f"Similar content already exists (ID: {dup_id}). Use PUT to update instead.",
        )

    try:
        point_id = LegalRAGIndexer.create_law_point(doc.model_dump())
    except Exception as exc:
        logger.error("Failed to create law document: %s", exc)
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    created = LegalRAGIndexer.get_law_point(point_id)
    _log_and_return("create", "law", point_id, new_values=created)

    return _law_point_to_response(created)


@router.put("/laws/{point_id}", response_model=LawDocumentResponse)
async def update_law(point_id: str, doc: LawDocumentUpdate):
    """Update an existing legal document article (partial update)."""
    existing = LegalRAGIndexer.get_law_point(point_id)
    if not existing:
        raise HTTPException(
            status_code=404, detail=f"Law document not found: {point_id}"
        )

    old_snapshot = dict(existing)

    # Merge update fields (only non-None)
    update_data = doc.model_dump(exclude_unset=True)

    try:
        LegalRAGIndexer.update_law_point(point_id, update_data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        # Partial update failure: rollback
        logger.error("Failed to update law document %s: %s", point_id, exc)
        try:
            LegalRAGIndexer.update_law_point(point_id, old_snapshot)
        except Exception as rb_exc:
            logger.error("Rollback failed for %s: %s", point_id, rb_exc)
        raise HTTPException(status_code=500, detail="Update failed, rolled back")

    updated = LegalRAGIndexer.get_law_point(point_id)
    _log_and_return(
        "update",
        "law",
        point_id,
        old_values=old_snapshot,
        new_values=updated,
        changes=update_data,
    )

    return _law_point_to_response(updated)


@router.delete("/laws/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_law(point_id: str):
    """Delete a legal document article."""
    existing = LegalRAGIndexer.get_law_point(point_id)
    if not existing:
        raise HTTPException(
            status_code=404, detail=f"Law document not found: {point_id}"
        )

    LegalRAGIndexer.delete_law_point(point_id)
    _log_and_return("delete", "law", point_id, old_values=existing)


@router.get("/laws/{point_id}", response_model=LawDocumentResponse)
async def get_law(point_id: str):
    """Get a single legal document article by ID."""
    point = LegalRAGIndexer.get_law_point(point_id)
    if not point:
        raise HTTPException(
            status_code=404, detail=f"Law document not found: {point_id}"
        )
    return _law_point_to_response(point)


@router.get("/laws", response_model=PaginatedResponse)
async def list_laws(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    """List all legal document articles with pagination."""
    items, total = LegalRAGIndexer.list_law_points(page=page, size=size)
    return PaginatedResponse(
        items=[_law_point_to_response(item) for item in items],
        total=total,
        page=page,
        size=size,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# HS Codes
# ═══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/hs-codes",
    response_model=HsCodeResponse,
    status_code=status.HTTP_201_CREATED,
    responses={409: {"model": ErrorResponse}},
)
async def create_hs_code(entry: HsCodeCreate):
    """Create a new HS code entry."""
    # Check for duplicate HS code
    existing_id = LegalRAGIndexer._hs_id_from_code(entry.hs_code)
    existing = LegalRAGIndexer.get_hs_code_point(existing_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"HS code {entry.hs_code} already exists (ID: {existing_id})",
        )
    # Note: content dedup skipped for HS codes — the HS code itself is the unique key.
    # Cosine-similarity dedup is unreliable with the current embedding model in this domain.

    try:
        point_id = LegalRAGIndexer.create_hs_code_point(entry.model_dump())
    except Exception as exc:
        logger.error("Failed to create HS code: %s", exc)
        raise HTTPException(status_code=503, detail="Embedding service unavailable")

    created = LegalRAGIndexer.get_hs_code_point(point_id)
    _log_and_return("create", "hs_code", point_id, new_values=created)

    return _hs_point_to_response(created)


@router.put("/hs-codes/{point_id}", response_model=HsCodeResponse)
async def update_hs_code(point_id: str, entry: HsCodeUpdate):
    """Update an existing HS code entry (partial update)."""
    existing = LegalRAGIndexer.get_hs_code_point(point_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"HS code not found: {point_id}")

    old_snapshot = dict(existing)
    update_data = entry.model_dump(exclude_unset=True)

    try:
        LegalRAGIndexer.update_hs_code_point(point_id, update_data)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to update HS code %s: %s", point_id, exc)
        try:
            LegalRAGIndexer.update_hs_code_point(point_id, old_snapshot)
        except Exception as rb_exc:
            logger.error("Rollback failed for %s: %s", point_id, rb_exc)
        raise HTTPException(status_code=500, detail="Update failed, rolled back")

    updated = LegalRAGIndexer.get_hs_code_point(point_id)
    _log_and_return(
        "update",
        "hs_code",
        point_id,
        old_values=old_snapshot,
        new_values=updated,
        changes=update_data,
    )

    return _hs_point_to_response(updated)


@router.delete("/hs-codes/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_hs_code(point_id: str):
    """Delete an HS code entry."""
    existing = LegalRAGIndexer.get_hs_code_point(point_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"HS code not found: {point_id}")

    LegalRAGIndexer.delete_hs_code_point(point_id)
    _log_and_return("delete", "hs_code", point_id, old_values=existing)


@router.get("/hs-codes/{point_id}", response_model=HsCodeResponse)
async def get_hs_code(point_id: str):
    """Get a single HS code entry by ID."""
    point = LegalRAGIndexer.get_hs_code_point(point_id)
    if not point:
        raise HTTPException(status_code=404, detail=f"HS code not found: {point_id}")
    return _hs_point_to_response(point)


@router.get("/hs-codes", response_model=PaginatedResponse)
async def list_hs_codes(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str = Query("", description="Search in product name and HS code"),
):
    """List all HS code entries with optional search and pagination."""
    items, total = LegalRAGIndexer.list_hs_code_points(
        page=page, size=size, search=search
    )
    return PaginatedResponse(
        items=[_hs_point_to_response(item) for item in items],
        total=total,
        page=page,
        size=size,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Reindex
# ═══════════════════════════════════════════════════════════════════════════════


@router.post(
    "/reindex", response_model=ReindexStatus, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_reindex(req: ReindexRequest):
    """Trigger a full reindex of one or all collections using temp-collection atomic swap."""
    collection_map = {
        "laws": LegalRAGIndexer.COLLECTION_NAME,
        "hs_codes": LegalRAGIndexer.HS_CODE_COLLECTION_NAME,
    }

    if req.collection == "all":
        targets = list(collection_map.values())
    elif req.collection not in collection_map:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown collection: '{req.collection}'. Use 'laws', 'hs_codes', or 'all'.",
        )
    else:
        targets = [collection_map[req.collection]]

    job_id = str(uuid.uuid4())
    _reindex_jobs[job_id] = {
        "status": "running",
        "progress": "0%",
        "message": f"Reindexing {len(targets)} collection(s)",
    }
    AuditLogger.log(
        action="reindex",
        entity_type="collection",
        entity_id=",".join(targets),
        changes={"collection": req.collection},
    )

    # Launch background reindex
    asyncio.create_task(_run_reindex(job_id, targets))

    return ReindexStatus(
        job_id=job_id,
        status="running",
        progress="0%",
        message=f"Reindex started for {req.collection}",
    )


@router.get("/reindex/{job_id}", response_model=ReindexStatus)
async def get_reindex_status(job_id: str):
    """Check the status of a reindex job."""
    if job_id not in _reindex_jobs:
        raise HTTPException(status_code=404, detail=f"Reindex job not found: {job_id}")
    job = _reindex_jobs[job_id]
    return ReindexStatus(
        job_id=job_id,
        status=job["status"],
        progress=job.get("progress", "0%"),
        message=job.get("message", ""),
    )


async def _run_reindex(job_id: str, targets: list):
    """Background: reindex each collection sequentially."""
    total = len(targets)
    for idx, coll in enumerate(targets):
        _reindex_jobs[job_id]["progress"] = f"{int((idx / total) * 100)}%"
        _reindex_jobs[job_id]["message"] = f"Reindexing {coll}..."
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(LegalRAGIndexer.reindex_collection, coll),
                timeout=REINDEX_TIMEOUT,
            )
            _reindex_jobs[job_id]["message"] = (
                f"{coll}: {result.get('points_indexed', 0)} points indexed"
            )
        except asyncio.TimeoutError:
            _reindex_jobs[job_id]["status"] = "failed"
            _reindex_jobs[job_id]["message"] = f"Timeout reindexing {coll}"
            return
        except Exception as exc:
            _reindex_jobs[job_id]["status"] = "failed"
            _reindex_jobs[job_id]["message"] = f"Failed reindexing {coll}: {exc}"
            return

    _reindex_jobs[job_id]["status"] = "completed"
    _reindex_jobs[job_id]["progress"] = "100%"
    _reindex_jobs[job_id]["message"] = "Reindex complete"


# ═══════════════════════════════════════════════════════════════════════════════
# Audit Log
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/audit", response_model=PaginatedResponse)
async def get_audit_log(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    entity_type: Optional[str] = Query(None, description="Filter by entity type"),
    action: Optional[str] = Query(None, description="Filter by action"),
):
    """View the audit log of all admin operations."""
    items, total = AuditLogger.get_logs(
        page=page, size=size, entity_type=entity_type, action=action
    )
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Response helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _law_point_to_response(pt: dict) -> LawDocumentResponse:
    return LawDocumentResponse(
        id=pt.get("id", ""),
        document_title=pt.get("document_title", ""),
        article_number=pt.get("article_number", ""),
        content_quote=pt.get("content_quote", ""),
        keywords=pt.get("keywords", ""),
        tags=pt.get("tags", []),
        effective_date=pt.get("effective_date"),
        status="indexed",
    )


def _hs_point_to_response(pt: dict) -> HsCodeResponse:
    return HsCodeResponse(
        id=pt.get("id", ""),
        hs_code=pt.get("hs_code", ""),
        product_name_ru=pt.get("product_name_ru", ""),
        product_name_en=pt.get("product_name_en", ""),
        duty_rate_percent=pt.get("duty_rate_percent", 0.0),
        excise_rate_percent=pt.get("excise_rate_percent", 0.0),
        is_subject_to_recycling_fee=pt.get("is_subject_to_recycling_fee", False),
        section=str(pt.get("section", "")),
        group=str(pt.get("group", "")),
        keywords=pt.get("keywords", ""),
        status="indexed",
    )
