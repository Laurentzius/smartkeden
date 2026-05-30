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
