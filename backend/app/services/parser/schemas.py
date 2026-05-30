"""Pydantic models for document parsing — invoice data extraction."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class InvoiceLine(BaseModel):
    """Single product line extracted from an invoice."""

    description: str = Field(description="Product name / description as in invoice")
    quantity: float = Field(description="Number of units", ge=0)
    unit_price: float = Field(description="Price per unit in invoice currency", ge=0)
    total_price: float = Field(description="Line total", ge=0)
    weight_kg: Optional[float] = Field(default=None, description="Weight in kg", ge=0)
    hs_code_hint: Optional[str] = Field(
        default=None, description="HS code if present on invoice"
    )
    price_estimated: bool = Field(
        default=False, description="True when prices were not found (proforma)"
    )


class InvoiceData(BaseModel):
    """Structured invoice fields extracted from a document."""

    invoice_number: Optional[str] = Field(
        default=None, description="Invoice number from document"
    )
    invoice_date: Optional[str] = Field(
        default=None, description="Date in YYYY-MM-DD format"
    )
    seller: Optional[str] = Field(default=None, description="Seller company name")
    buyer: Optional[str] = Field(default=None, description="Buyer company name")
    currency: Optional[str] = Field(
        default=None, description="Invoice currency (USD, EUR, KZT, etc.)"
    )
    items: List[InvoiceLine] = Field(default_factory=list, description="Product lines")


class ProcessingMetadata(BaseModel):
    """Metadata about the extraction process."""

    source_type: str = Field(description="pdf | xlsx | docx | image")
    ocr_applied: bool = Field(
        default=False, description="True when Gemini Vision OCR was used"
    )
    parsed_at: datetime = Field(default_factory=datetime.utcnow)
    original_filename: str = Field(
        description="Original filename, deleted after processing"
    )


class ParseDocumentResponse(BaseModel):
    """Response from the parse-document endpoint."""

    data: InvoiceData
    metadata: ProcessingMetadata
    warnings: List[str] = Field(default_factory=list)


class ParseError(BaseModel):
    """Error response for parse failures."""

    error: str
    error_code: str
    details: Optional[str] = None


class SheetInfo(BaseModel):
    """Metadata about a single Excel sheet."""

    name: str
    row_count: int
    has_data: bool


class ExcelPreviewResponse(BaseModel):
    """Response when an Excel file has multiple sheets — lets the user choose."""

    sheets: List[SheetInfo]
    default_sheet: str


class ConfirmExtractionRequest(BaseModel):
    """User-edited invoice data sent for confirmation."""

    data: InvoiceData
    session_id: str = Field(description="Session ID for temp file tracking")
