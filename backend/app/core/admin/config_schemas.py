"""Pydantic models for Configuration Service API."""

from datetime import date
from typing import Optional, List, Any
from pydantic import BaseModel, Field, field_validator


# ── Rate Version ─────────────────────────────────────────────────────────────


class RateVersion(BaseModel):
    """A single versioned rate entry in the configuration database."""

    value: float = Field(..., description="Rate value")
    effective_date: str = Field(
        ..., description="Effective date in ISO format (YYYY-MM-DD)"
    )
    expiry_date: Optional[str] = Field(
        None, description="Expiry date in ISO format (YYYY-MM-DD), null if active"
    )
    version: int = Field(..., description="Monotonically increasing version number")
    created_by: str = Field(
        "system", description="Who created this version (admin or system)"
    )
    created_at: str = Field(..., description="Creation timestamp in ISO 8601 format")


class MciRateEntry(BaseModel):
    """MCI rate entry — keyed by year, not by effective_date range."""

    year: int = Field(..., description="Year this MCI value applies to")
    value: float = Field(..., description="MCI value in KZT")
    version: int = Field(1, description="Version number")
    created_by: str = Field("system")
    created_at: str = Field(..., description="Creation timestamp in ISO 8601 format")


# ── Request Schemas ──────────────────────────────────────────────────────────


class RateUpdateRequest(BaseModel):
    """Payload for creating/updating a rate."""

    value: float = Field(
        ..., ge=0.0, le=1.0, description="Rate value (0.0 to 1.0 for percentage rates)"
    )
    effective_date: str = Field(
        ..., description="Effective date in ISO format (YYYY-MM-DD)"
    )
    reason: Optional[str] = Field(
        None, description="Reason for the rate change (for audit trail)"
    )

    @field_validator("effective_date")
    @classmethod
    def effective_date_not_in_past(cls, v: str) -> str:
        """Validate that effective_date is not in the past."""
        try:
            parsed = date.fromisoformat(v)
        except ValueError:
            raise ValueError("effective_date must be in ISO format (YYYY-MM-DD)")
        if parsed < date.today():
            raise ValueError("Effective date cannot be in the past")
        return v

    @field_validator("value")
    @classmethod
    def value_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("Rate value must be between 0 and 1")
        return v


class MciUpdateRequest(BaseModel):
    """Payload for updating an MCI value for a specific year."""

    year: int = Field(..., ge=2000, le=2100)
    value: float = Field(..., ge=0.0)
    reason: Optional[str] = Field(None)


# ── Response Schemas ─────────────────────────────────────────────────────────


class RateHistoryResponse(BaseModel):
    """Full version history for a single rate type."""

    rate_type: str = Field(..., description="Rate type identifier")
    versions: List[RateVersion] = Field(
        default_factory=list, description="All versions, newest first"
    )


class RateCurrentResponse(BaseModel):
    """Current active rate for a single rate type."""

    value: float = Field(..., description="Current rate value")
    effective_date: str = Field(
        ..., description="Effective date of the current version"
    )
    version: int = Field(..., description="Version number of the current version")


class RateAtDateResponse(BaseModel):
    """Rate value valid on a specific date."""

    value: float = Field(..., description="Rate value valid on the given date")
    effective_date: str = Field(
        ..., description="Effective date of the applicable version"
    )
    version: int = Field(..., description="Version number")
    rate_type: str = Field(..., description="Rate type identifier")
    requested_date: str = Field(..., description="The date that was queried")


class RatesAllResponse(BaseModel):
    """All current rates at a glance."""

    rates: dict = Field(..., description="Mapping of rate_type → current value")


class RateUpdateResponse(BaseModel):
    """Response after a successful rate update."""

    rate_type: str
    version: int
    old_value: float
    new_value: float
    effective_date: str
    message: str = "Rate updated successfully"


class CancelResponse(BaseModel):
    """Response after cancelling a scheduled rate."""

    status: str
    rate_type: str
    version: int
    message: str


class DeleteResponse(BaseModel):
    """Response after soft-deleting a rate version."""

    status: str
    rate_type: str
    version: int
    message: str
    warning: Optional[str] = None


class AuditPaginatedResponse(BaseModel):
    """Paginated audit log response."""

    items: List[Any]
    total: int
    page: int
    size: int


class ErrorResponse(BaseModel):
    """Standard error response."""

    detail: str
    error_code: Optional[str] = None


# ── Valid rate types ─────────────────────────────────────────────────────────

VALID_RATE_TYPES = frozenset(
    {
        "import_vat",
        "mci",
        "customs_processing_fee",
        "recycling_rates",
        "excise_rates",
    }
)
