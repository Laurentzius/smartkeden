"""ParserService: validate -> MarkItDown extract -> LLM structurize."""

import logging
from pathlib import Path
from typing import Optional, Tuple

from app.services.parser.schemas import (
    InvoiceData,
    InvoiceLine,
)
from app.services.parser.markitdown_adapter import convert_to_markdown

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SUPPORTED_MIMES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "image/png": "image",
    "image/jpeg": "image",
    "image/jpg": "image",
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


# ── File type detection ───────────────────────────────────────────────────────


def detect_source_type(
    filename: str, mime_type: str, file_bytes: bytes
) -> Tuple[str, Optional[str]]:
    """Detect source type from filename and MIME.

    Returns (source_type, error_message).
    source_type is one of: pdf, xlsx, docx, image.
    Returns ("", error_msg) on unsupported format.
    """
    ext = Path(filename).suffix.lower()
    mime_base = mime_type.split(";")[0].strip() if mime_type else ""

    # PDF
    if mime_base == "application/pdf" or ext == ".pdf":
        return "pdf", None

    # Excel
    if (
        mime_base == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        or ext in (".xlsx", ".xlsm")
    ):
        return "xlsx", None

    # Word
    if (
        mime_base
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or ext in (".docx",)
    ):
        return "docx", None

    # Image
    if mime_base in ("image/png", "image/jpeg", "image/jpg") or ext in (
        ".png",
        ".jpg",
        ".jpeg",
    ):
        return "image", None

    return "", (
        f"Неподдерживаемый формат: {ext or mime_base}. "
        f"Поддерживаются PDF, XLSX, DOCX, PNG, JPG."
    )


# ── Extraction dispatcher ─────────────────────────────────────────────────────


async def extract_raw_text(
    source_type: str,
    file_bytes: bytes,
    mime_type: str = "application/octet-stream",
) -> Tuple[str, bool]:
    """Convert document to Markdown via MarkItDown (primary) or Gemini Vision (fallback).

    Returns (markdown_text, ocr_applied).
    """
    return convert_to_markdown(file_bytes, source_type, mime_type)


# ── LLM Structurization ───────────────────────────────────────────────────────


def structurize_invoice(markdown_text: str) -> InvoiceData:
    """Send Markdown-extracted text to an LLM and get structured InvoiceData back.

    Input is Markdown (from MarkItDown or Gemini Vision OCR), which LLMs
    parse more accurately than raw text — especially tables.
    """
    from app.core.llm.generator import get_generator

    prompt = _build_structurization_prompt(markdown_text)

    try:
        generator = get_generator()
        result = generator.generate_structured(
            prompt=prompt,
            response_schema=InvoiceData,
        )
        return result
    except Exception as e:
        logger.error(f"LLM structurization failed: {e}")
        fallback = InvoiceData(
            items=[
                InvoiceLine(
                    description=(
                        f"Failed to parse text. Raw text: {markdown_text[:200]}..."
                    ),
                    quantity=1,
                    unit_price=0,
                    total_price=0,
                    price_estimated=True,
                )
            ]
        )
        return fallback


def _build_structurization_prompt(markdown_text: str) -> str:
    """Build the LLM prompt for invoice structurization from Markdown."""
    return (
        "Extract structured invoice data from the following Markdown text.\n"
        "The text was extracted from a commercial invoice and may contain "
        "Markdown tables — parse them as product line items.\n"
        "\n"
        "Rules:\n"
        "- Output ALL product lines found. Each line = one product item.\n"
        "- If a field is not present, leave it null (omit it from the JSON).\n"
        "- For quantity, unit_price, total_price: use numbers (float). "
        "If a number has commas, replace with dots.\n"
        "- Currency: detect from symbols ($, EUR, KZT) or text (USD, EUR, KZT, RUB). "
        "Output as 3-letter code.\n"
        "- invoice_date: format as YYYY-MM-DD if possible.\n"
        "- If prices are missing (proforma invoice), set price_estimated=true for those lines.\n"
        "- For weight: extract if present, in kg.\n"
        "- hs_code_hint: extract only if a numeric HS code appears on the invoice.\n"
        "- Description should be the product name as written in the invoice, "
        "in original language.\n"
        "\n"
        "Extracted Markdown:\n"
        "---\n"
        f"{markdown_text}\n"
        "---"
    )
