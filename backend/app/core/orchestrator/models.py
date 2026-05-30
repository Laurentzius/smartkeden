from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class IntentType(str, Enum):
    question_about_law = "question_about_law"
    product_description = "product_description"
    calculation_request = "calculation_request"
    document_upload = "document_upload"
    greeting = "greeting"
    unclear = "unclear"
    customs_guidance = "customs_guidance"


class IntentClassification(BaseModel):
    intent: IntentType = IntentType.unclear
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasoning: str = ""

    @field_validator("intent", mode="before")
    @classmethod
    def coerce_intent(cls, v: object) -> IntentType:
        if v is None:
            return IntentType.unclear
        if isinstance(v, str):
            try:
                return IntentType(v)
            except ValueError:
                return IntentType.unclear
        if isinstance(v, IntentType):
            return v
        return IntentType.unclear


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role of the speaker: 'user' or 'assistant'")
    content: str = Field(..., description="The raw text content of the message")


class OrchestrateRequest(BaseModel):
    text: str = Field(..., description="User message")
    session_id: Optional[str] = Field(
        None, description="Optional session identifier (reserved for v2)"
    )
    history: Optional[List[ChatMessage]] = Field(
        None, description="Conversational history for multi-turn routing"
    )


class OrchestrateResponse(BaseModel):
    intent: IntentType = Field(..., description="Detected intent")
    message: str = Field(..., description="Response text to show the user")
    pipeline_results: Optional[dict] = Field(
        None, description="Structured results from the invoked pipeline"
    )
    chain_warning: Optional[str] = Field(
        None, description="Warning if a chained step partially failed"
    )


# ── Agentic RAG Customs Guidance models (Section 9 of agentic_rag_customs_clearance_flow.md) ──


class GuidanceMode(str, Enum):
    """Selectable guidance modes for the customs clearance workflow."""
    answer_from_law = "answer_from_law"
    ask_clarifying_questions = "ask_clarifying_questions"
    classify_goods = "classify_goods"
    calculate_payments = "calculate_payments"
    generate_document_checklist = "generate_document_checklist"
    check_restrictions = "check_restrictions"
    astana1_guidance = "astana1_guidance"


class GuidanceRiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CustomsIntakeFacts(BaseModel):
    product_description: Optional[str] = Field(default=None)
    hs_code: Optional[str] = Field(default=None)
    customs_value: Optional[float] = Field(default=None)
    currency: Optional[str] = Field(default=None)
    country_of_origin: Optional[str] = Field(default=None)
    country_of_export: Optional[str] = Field(default=None)
    quantity: Optional[float] = Field(default=None)
    weight_kg: Optional[float] = Field(default=None)
    incoterms: Optional[str] = Field(default=None)
    procedure_code: Optional[str] = Field(default=None)


class GuidancePlan(BaseModel):
    modes: list[GuidanceMode] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    risk_level: GuidanceRiskLevel = Field(default=GuidanceRiskLevel.LOW)


class GuidanceSource(BaseModel):
    source_type: str = Field(default="", description="law|config|rag|classifier|calculator")
    citation: str = Field(default="")
    url: Optional[str] = Field(default=None)
    snippet: Optional[str] = Field(default=None)


class GuidanceDocumentItem(BaseModel):
    name: str = Field(default="")
    required: bool = Field(default=True)
    based_on: Optional[str] = Field(default=None)


class GuidanceRestrictionItem(BaseModel):
    restriction_type: str = Field(default="", description="permit|license|certificate|ban|quota|etc")
    description: str = Field(default="")
    source: Optional[str] = Field(default=None)
    verified: bool = Field(default=False)


class GuidancePaymentEstimate(BaseModel):
    customs_value_kzt: Optional[float] = Field(default=None)
    customs_fee_kzt: Optional[float] = Field(default=None)
    customs_duty_kzt: Optional[float] = Field(default=None)
    vat_base_kzt: Optional[float] = Field(default=None)
    import_vat_kzt: Optional[float] = Field(default=None)
    recycling_fee_kzt: Optional[float] = Field(default=None)
    total_payments_kzt: Optional[float] = Field(default=None)
    formula: Optional[str] = Field(default=None)
    assumptions: list[str] = Field(default_factory=list)


class ComplianceCriticResult(BaseModel):
    approved: bool = Field(default=True)
    blocked_sections: list[str] = Field(default_factory=list)
    downgraded_sections: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CustomsGuidancePayload(BaseModel):
    answer_type: str = Field(default="customs_import_guidance")
    confidence: str = Field(default="low", description="low|medium|high")
    risk_level: str = Field(default="LOW")
    needs_human_review: bool = Field(default=False)
    missing_fields: list[str] = Field(default_factory=list)
    candidate_hs_codes: list[dict] = Field(default_factory=list)
    estimated_payments: Optional[GuidancePaymentEstimate] = Field(default=None)
    required_documents: list[GuidanceDocumentItem] = Field(default_factory=list)
    possible_restrictions: list[GuidanceRestrictionItem] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    sources: list[GuidanceSource] = Field(default_factory=list)
    critic_warnings: list[str] = Field(default_factory=list)
