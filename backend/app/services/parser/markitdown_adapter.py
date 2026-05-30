"""MarkItDown adapter — unified document-to-Markdown conversion.

Replaces the individual pdf_extractor, excel_parser, and ocr_engine.
Uses microsoft/markitdown for PDF, XLSX, DOCX.
Falls back to Gemini Vision for images and scanned PDFs (no text).
"""

import io
import logging
from typing import Tuple

from markitdown import MarkItDown

logger = logging.getLogger(__name__)

MIN_TEXT_CHARS_FOR_TEXT_PDF = 100


def convert_to_markdown(
    file_bytes: bytes,
    source_type: str,
    mime_type: str = "application/octet-stream",
) -> Tuple[str, bool]:
    """Convert a document to Markdown text.

    Args:
        file_bytes: Raw file content.
        source_type: One of 'pdf', 'xlsx', 'docx', 'image'.
        mime_type: MIME type for format hint.

    Returns:
        (markdown_text, ocr_applied).
        ocr_applied is True when Gemini Vision was used as fallback.
    """
    ext = _source_type_to_ext(source_type)

    if source_type == "image":
        return _ocr_image(file_bytes, mime_type), True

    if source_type in ("pdf", "xlsx", "docx"):
        text = _convert_with_markitdown(file_bytes, ext)
        if not text.strip():
            raise ValueError(
                "MarkItDown returned empty output — document may be corrupted"
            )

        if source_type == "pdf" and len(text.strip()) < MIN_TEXT_CHARS_FOR_TEXT_PDF:
            logger.info(
                "PDF appears to be scanned (<100 chars) — using Gemini Vision OCR"
            )
            return _ocr_pdf_pages(file_bytes), True

        return text, False

    raise ValueError(f"Unsupported source_type for MarkItDown: {source_type}")


def _convert_with_markitdown(file_bytes: bytes, extension: str) -> str:
    """Convert a file using MarkItDown."""
    md = MarkItDown()
    result = md.convert_stream(io.BytesIO(file_bytes), file_extension=extension)
    return result.text_content


def _source_type_to_ext(source_type: str) -> str:
    """Map source_type to file extension expected by MarkItDown."""
    mapping = {
        "pdf": ".pdf",
        "xlsx": ".xlsx",
        "docx": ".docx",
        "image": ".png",
    }
    if source_type not in mapping:
        raise ValueError(f"Unknown source_type: {source_type}")
    return mapping[source_type]


# ── Gemini Vision fallback for images and scanned PDFs ───────────────────────


def _ocr_image(image_bytes: bytes, mime_type: str) -> str:
    """Extract text from an image using Gemini Vision."""
    from app.core.llm.generator import get_generator
    from pydantic import BaseModel, Field

    class OCRText(BaseModel):
        text: str = Field(description="Full extracted text from the image")

    prompt = (
        "Extract ALL text from this document image. "
        "Return the text exactly as it appears, preserving table structure if present. "
        "Output the text in Markdown format (use | tables for tabular data). "
        "Do not add commentary."
    )

    generator = get_generator()
    result = generator.generate_structured(
        prompt=prompt,
        response_schema=OCRText,
        image_bytes=image_bytes,
        image_mime_type=mime_type,
    )
    return result.text


def _ocr_pdf_pages(file_bytes: bytes) -> str:
    """Convert PDF pages to images and OCR each with Gemini Vision.

    Falls back to single-image OCR if pdf2image/poppler is unavailable.
    """
    try:
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(file_bytes, fmt="png")
    except Exception as e:
        logger.warning(f"pdf2image failed (poppler missing?): {e}")
        return _ocr_image(file_bytes, "application/pdf")

    all_text: list[str] = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page_text = _ocr_image(buf.getvalue(), "image/png")
        all_text.append(page_text)

    return "\n\n---\n\n".join(all_text)
