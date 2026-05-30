from datetime import date
from typing import Optional, List, Any
from pydantic import BaseModel, Field


# ── Law Documents ───────────────────────────────────────────────────────────


class LawDocumentCreate(BaseModel):
    title: str = Field(..., description="Document title, e.g. 'Таможенный кодекс РК'")
    article: str = Field(..., description="Article number, e.g. 'Статья 124'")
    content: str = Field(..., description="Full text content of the article")
    keywords: str = Field(default="", description="Comma-separated keywords")
    effective_date: Optional[date] = Field(
        default=None, description="Date when the law takes effect"
    )


class LawDocumentUpdate(BaseModel):
    title: Optional[str] = Field(default=None)
    article: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    keywords: Optional[str] = Field(default=None)
    effective_date: Optional[date] = Field(default=None)


class LawDocumentResponse(BaseModel):
    id: str
    document_title: str
    article_number: str
    content_quote: str
    keywords: str
    tags: List[str] = Field(default_factory=list)
    effective_date: Optional[date] = None
    status: str = "indexed"


# ── HS Codes ────────────────────────────────────────────────────────────────


class HsCodeCreate(BaseModel):
    hs_code: str = Field(..., description="HS code, e.g. '0101.21.0000'")
    product_name_ru: str = Field(..., description="Product name in Russian")
    duty_rate: float = Field(..., ge=0, description="Duty rate percentage")
    excise_rate: float = Field(default=0.0, ge=0, description="Excise rate percentage")
    recycling_fee: bool = Field(
        default=False, description="Whether subject to recycling fee"
    )
    keywords: str = Field(default="", description="Comma-separated keywords")


class HsCodeUpdate(BaseModel):
    product_name_ru: Optional[str] = Field(default=None)
    duty_rate: Optional[float] = Field(default=None, ge=0)
    excise_rate: Optional[float] = Field(default=None, ge=0)
    recycling_fee: Optional[bool] = Field(default=None)
    keywords: Optional[str] = Field(default=None)


class HsCodeResponse(BaseModel):
    id: str
    hs_code: str
    product_name_ru: str
    product_name_en: str = ""
    duty_rate_percent: float
    excise_rate_percent: float = 0.0
    is_subject_to_recycling_fee: bool = False
    section: str = ""
    group: str = ""
    keywords: str = ""
    status: str = "indexed"


# ── Reindex ─────────────────────────────────────────────────────────────────


class ReindexRequest(BaseModel):
    collection: str = Field(
        ..., description="Collection to reindex: 'laws', 'hs_codes', or 'all'"
    )


class ReindexStatus(BaseModel):
    job_id: str
    status: str  # "running", "completed", "failed"
    progress: str = "0%"  # human-readable progress
    message: str = ""


# ── Audit Log ───────────────────────────────────────────────────────────────


class AuditLogEntry(BaseModel):
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    actor: str = Field(default="admin")
    action: str  # "create", "update", "delete", "reindex"
    entity_type: str  # "law", "hs_code", "collection"
    entity_id: str = ""
    changes: dict = Field(default_factory=dict)
    old_values: Optional[dict] = None
    new_values: Optional[dict] = None


# ── Pagination ──────────────────────────────────────────────────────────────


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    size: int


# ── Error ───────────────────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
