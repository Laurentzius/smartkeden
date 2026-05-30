"""FastAPI router for document parsing — POST /api/workspace/parse-document."""

import logging
import shutil
import tempfile
import time
import hashlib
from datetime import datetime
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from app.services.parser.schemas import (
    ProcessingMetadata,
)
from app.services.parser.service import (
    MAX_FILE_SIZE,
    detect_source_type,
    extract_raw_text,
    structurize_invoice,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["Document Parsing"])


# ── Temp file management ──────────────────────────────────────────────────────

TEMP_UPLOAD_DIR = Path(tempfile.gettempdir()) / "smartkeden_uploads"


def _ensure_temp_dir() -> Path:
    """Create and return the temp upload directory."""
    TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_UPLOAD_DIR


def _save_temp_file(session_id: str, file_bytes: bytes, filename: str) -> Path:
    """Save uploaded bytes to a temp file scoped to a session."""
    session_dir = _ensure_temp_dir() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    filepath = session_dir / filename
    filepath.write_bytes(file_bytes)
    return filepath


def _cleanup_session(session_id: str) -> None:
    """Delete all temp files for a session."""
    session_dir = _ensure_temp_dir() / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir, ignore_errors=True)
        logger.info(f"Cleaned up session temp dir: {session_dir}")


# ── Periodic cleanup (best-effort) ────────────────────────────────────────────


async def _cleanup_old_sessions(max_age_seconds: int = 1800) -> None:
    """Remove session dirs older than max_age_seconds (30 min default)."""
    try:
        base = _ensure_temp_dir()
        now = time.time()
        for entry in base.iterdir():
            if entry.is_dir():
                try:
                    mtime = entry.stat().st_mtime
                    if now - mtime > max_age_seconds:
                        shutil.rmtree(entry, ignore_errors=True)
                except OSError:
                    pass
    except Exception:
        pass  # best-effort


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/parse-document")
async def parse_document(
    file: UploadFile = File(...),
    session_id: str = Form(default_factory=lambda: uuid.uuid4().hex),
    sheet_name: Optional[str] = Form(None),
) -> JSONResponse:
    """Upload and parse an invoice document (PDF, XLSX, JPG, PNG).

    Returns structured InvoiceData with processing metadata.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Файл не выбран.")

    # Read file bytes (check size while reading)
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой (>10 МБ). Максимальный размер: {MAX_FILE_SIZE // (1024 * 1024)} МБ.",
        )
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Файл пустой.")

    mime_type = file.content_type or ""

    # Detect source type
    source_type, error = detect_source_type(file.filename, mime_type, file_bytes)
    if error:
        raise HTTPException(status_code=400, detail=error)

    # Save temp file for potential reprocessing
    _save_temp_file(session_id, file_bytes, file.filename)

    # Extract raw text
    start_time = time.time()
    try:
        raw_text, ocr_applied = await extract_raw_text(
            source_type, file_bytes, mime_type
        )
    except Exception as e:
        logger.error(f"Extraction failed for {file.filename}: {e}")
        raise HTTPException(
            status_code=422,
            detail=f"Не удалось распознать текст: {str(e)}",
        )

    parse_time_ms = int((time.time() - start_time) * 1000)

    if not raw_text or not raw_text.strip():
        raise HTTPException(
            status_code=422,
            detail="Не удалось распознать текст. Возможно, документ пустой или низкого качества.",
        )

    # Structurize via LLM
    try:
        invoice_data = structurize_invoice(raw_text)
    except Exception as e:
        logger.error(f"Structurization failed: {e}")
        raise HTTPException(
            status_code=422,
            detail="Не удалось разобрать инвойс. Попробуйте загрузить более чёткое изображение.",
        )

    # Build warnings
    warnings: list[str] = []
    has_estimated = any(item.price_estimated for item in invoice_data.items)
    if has_estimated:
        warnings.append("Цена не указана для некоторых позиций. Укажите вручную.")
    if not invoice_data.invoice_number:
        date_part = invoice_data.invoice_date or datetime.utcnow().strftime("%Y%m%d")
        hash_part = hashlib.md5(raw_text.encode()).hexdigest()[:6]
        invoice_data.invoice_number = f"INV-{date_part}-{hash_part}"
        warnings.append("Номер инвойса не найден — сгенерирован автоматически.")

    # Build metadata
    metadata = ProcessingMetadata(
        source_type=source_type,
        ocr_applied=ocr_applied,
        original_filename=file.filename,
    )

    logger.info(
        f"Parsed {file.filename} ({source_type}) in {parse_time_ms}ms — "
        f"items={len(invoice_data.items)}, ocr={ocr_applied}"
    )
    return JSONResponse(
        content={
            "data": invoice_data.model_dump(),
            "metadata": metadata.model_dump(mode="json"),
            "warnings": warnings,
        }
    )


@router.post("/parse-document/confirm")
async def confirm_extraction(
    data: str = Form(...),
    session_id: str = Form(...),
) -> dict:
    """User confirms the extracted data (with edits applied).

    Cleans up the temp file after confirmation.
    Returns the confirmed data for workspace injection.
    """
    # Cleanup temp files
    _cleanup_session(session_id)

    # Parse JSON data from form field
    try:
        import json as _json

        parsed = _json.loads(data)
    except _json.JSONDecodeError:
        raise HTTPException(
            status_code=400,
            detail="Некорректный формат данных.",
        )

    # Re-validate
    try:
        from app.services.parser.schemas import InvoiceData

        validated = InvoiceData.model_validate(parsed)
        return {
            "status": "confirmed",
            "data": validated.model_dump(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Некорректные данные: {str(e)}",
        )


@router.post("/parse-document/cleanup")
async def cleanup_session(session_id: str = Form(...)) -> dict:
    """Explicitly clean up temp files for a session."""
    _cleanup_session(session_id)
    return {"status": "cleaned"}
