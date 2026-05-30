"""Pydantic models for the Classification Rules Engine.

Defines schemas for rules, conditions, actions, attributes, and API request/response.
"""

from datetime import date, datetime
from typing import Any, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator

# ── Valid operators and action types ──────────────────────────────────────────

VALID_OPERATORS = frozenset({
    "==", "!=", ">", "<", ">=", "<=",
    "contains", "not_contains", "in", "not_in",
})

VALID_ACTION_TYPES = frozenset({
    "reclassify", "boost", "exclude", "require_info", "warning",
})


# ── Rule Condition ───────────────────────────────────────────────────────────

class RuleCondition(BaseModel):
    """A single atomic condition within a rule."""
    attribute: str = Field(..., description="Attribute name, e.g. 'material_outer'")
    operator: str = Field(..., description="Comparison operator: ==, !=, >, <, contains, in, etc.")
    value: Any = Field(..., description="Value to compare against")

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        if v not in VALID_OPERATORS:
            raise ValueError(f"Invalid operator '{v}'. Must be one of: {sorted(VALID_OPERATORS)}")
        return v


# ── Rule Action ──────────────────────────────────────────────────────────────

class RuleAction(BaseModel):
    """Action to apply when rule conditions match."""
    type: str = Field(..., description="Action type: reclassify, boost, exclude, require_info, warning")
    target_code: str = Field("", description="Target HS code for reclassify/exclude/boost")
    reason: str = Field("", description="Human-readable reason for the action")
    confidence_boost: Optional[float] = Field(None, description="Confidence boost amount (0.0-1.0), for 'boost' action")

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in VALID_ACTION_TYPES:
            raise ValueError(f"Invalid action type '{v}'. Must be one of: {sorted(VALID_ACTION_TYPES)}")
        return v


# ── Classification Rule ──────────────────────────────────────────────────────

class ClassificationRule(BaseModel):
    """Full classification rule as stored in the database."""
    rule_id: str = Field(..., description="Unique rule identifier")
    category_mask: str = Field(..., description="Category mask, e.g. '9503*' or '*'")
    priority: int = Field(default=0, description="Higher = checked first")
    conditions: Union[list[RuleCondition], dict[str, Any]] = Field(
        ..., description="Conditions: list[RuleCondition] (AND), {'all': [...]}, or {'any': [...]}"
    )
    action: RuleAction = Field(..., description="Action to apply when rule matches")
    source: str = Field(..., description="Official document reference")
    effective_date: date = Field(..., description="Date when rule becomes effective")
    expiry_date: Optional[date] = Field(None, description="Date when rule expires")
    created_by: Optional[str] = Field(None, description="Admin who created the rule")
    version: int = Field(default=1, description="Rule version number")
    is_active: bool = Field(default=True, description="Whether the rule is active")
    created_at: Optional[datetime] = Field(None)
    updated_at: Optional[datetime] = Field(None)

    @field_validator("effective_date")
    @classmethod
    def effective_date_not_in_past(cls, v: date, info) -> date:
        """effective_date cannot be in the past on creation (only for new rules)."""
        # We validate only on creation; updates may not pass context
        return v


# ── API Request/Response Models ──────────────────────────────────────────────

class RuleCreateRequest(BaseModel):
    """Request body for creating a new rule."""
    rule_id: str = Field(..., min_length=1, max_length=100, description="Unique rule identifier")
    category_mask: str = Field(..., min_length=1, max_length=20, description="Category mask")
    conditions: Union[list[RuleCondition], dict[str, Any]] = Field(
        ..., description="Conditions: list[RuleCondition] (AND), {'all': [...]}, or {'any': [...]}"
    )
    action: RuleAction = Field(..., description="Action to apply")
    source: str = Field(..., min_length=1, description="Official document reference (required)")
    effective_date: date = Field(..., description="Effective date")
    priority: int = Field(default=0, description="Priority (higher = first)")
    expiry_date: Optional[date] = Field(None, description="Optional expiry date")
    created_by: Optional[str] = Field(None)

    @field_validator("effective_date")
    @classmethod
    def effective_date_not_in_past(cls, v: date) -> date:
        if v < date.today():
            raise ValueError("effective_date cannot be in the past")
        return v

    @field_validator("source")
    @classmethod
    def source_required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source is required")
        return v.strip()


class RuleUpdateRequest(BaseModel):
    """Request body for updating an existing rule."""
    conditions: Optional[Union[list[RuleCondition], dict[str, Any]]] = Field(None)
    action: Optional[RuleAction] = Field(None)
    priority: Optional[int] = Field(None)
    source: Optional[str] = Field(None)
    effective_date: Optional[date] = Field(None)
    expiry_date: Optional[date] = Field(None)


# ── Attribute Schema ─────────────────────────────────────────────────────────

class AttributeSchema(BaseModel):
    """Structured product attributes extracted from text + vision."""
    material_outer: Optional[str] = Field(None, description="Outer material, e.g. 'хлопок', 'пластик'")
    material_filling: Optional[str] = Field(None, description="Filling material, e.g. 'синтепон', 'пух'")
    material_coating: Optional[str] = Field(None, description="Coating material")
    size_cm: Optional[float] = Field(None, description="Size in cm (largest dimension)")
    weight_kg: Optional[float] = Field(None, description="Weight in kg")
    volume_liters: Optional[float] = Field(None, description="Volume in liters")
    has_electronics: Optional[bool] = Field(None, description="Contains electronic components")
    has_sound_module: Optional[bool] = Field(None, description="Has sound-producing module")
    has_movement: Optional[bool] = Field(None, description="Has mechanical movement")
    has_lighting: Optional[bool] = Field(None, description="Has lighting elements")
    brand: Optional[str] = Field(None, description="Brand or manufacturer")
    country_of_origin: Optional[str] = Field(None, description="Country of origin")
    target_audience: Optional[str] = Field(None, description="Target audience, e.g. 'дети', 'взрослые'")
    fur_coverage_percent: Optional[float] = Field(None, description="Natural fur coverage percentage (0-100)")
    textile_percent: Optional[float] = Field(None, description="Textile content percentage (0-100)")
    metal_percent: Optional[float] = Field(None, description="Metal content percentage (0-100)")

    def to_flat_dict(self) -> dict:
        """Return non-None attributes as a flat dict."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


# ── Clarifying Question ──────────────────────────────────────────────────────

class ClarifyingQuestion(BaseModel):
    """A question asked to the user when an attribute is missing."""
    attribute: str = Field(..., description="Attribute name that is missing")
    question: str = Field(..., description="Question text in Russian/Kazakh")

    def model_dump(self, **kwargs) -> dict:
        """Override to ensure snake_case keys for ADK state compatibility."""
        return {"attribute": self.attribute, "question": self.question}


# ── Applied Rule ─────────────────────────────────────────────────────────────

class AppliedRule(BaseModel):
    """Record of a rule that was applied during classification."""
    rule_id: str = Field(..., description="Rule identifier")
    action_type: str = Field(..., description="Type of action applied")
    target_code: str = Field("", description="Target HS code")
    reason: str = Field("", description="Reason for application")


# ── Rules Application Result ─────────────────────────────────────────────────

class RulesApplicationResult(BaseModel):
    """Result of applying classification rules to candidates."""
    candidates: list[dict] = Field(default_factory=list, description="Refined HS code candidates")
    clarifying_questions: list[ClarifyingQuestion] = Field(
        default_factory=list, description="Questions when attributes are missing"
    )
    applied_rules: list[AppliedRule] = Field(
        default_factory=list, description="Rules that were applied"
    )


# ── Rule Test Request ────────────────────────────────────────────────────────

class RuleTestRequest(BaseModel):
    """Request body for testing a rule on example attributes."""
    rule_id: Optional[str] = Field(None, description="Rule ID to test (optional)")
    conditions: Optional[Union[list[RuleCondition], dict[str, Any]]] = Field(
        None, description="Inline conditions to test (if no rule_id)"
    )
    action: Optional[RuleAction] = Field(None, description="Inline action (if no rule_id)")
    attributes: dict[str, Any] = Field(..., description="Test attributes to match against")
    candidates: list[dict] = Field(default_factory=list, description="Test HS code candidates")


# ── Rule Validate Request ────────────────────────────────────────────────────

class RuleValidateRequest(BaseModel):
    """Request body for validating rule syntax."""
    conditions: Union[list[RuleCondition], dict[str, Any]] = Field(
        ..., description="Conditions to validate"
    )
    action: RuleAction = Field(..., description="Action to validate")


# ── Rule Validate Response ───────────────────────────────────────────────────

class RuleValidateResponse(BaseModel):
    """Response for rule validation."""
    valid: bool = Field(..., description="Whether the rule syntax is valid")
    errors: list[str] = Field(default_factory=list, description="Validation error messages")


class RuleResponse(BaseModel):
    """Standard rule response wrapper."""
    rule: ClassificationRule


class RuleListResponse(BaseModel):
    """Paginated list of rules."""
    rules: list[ClassificationRule]
    total: int


class AuditLogListResponse(BaseModel):
    """Paginated audit log response."""
    items: list[dict]
    total: int
