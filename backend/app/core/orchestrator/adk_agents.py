"""
Google ADK 2.0 Multi-Agent definitions for SmartKeden.

Defines three specialized subagents and one coordinator (supervisor) agent:
  - HSClassifierAgent        (Task mode via output_key)
  - LegalRAGAgent            (Chat mode — conversational)
  - CustomsCalculatorAgent   (Task mode via output_key)
  - KedenCoordinatorAgent    (Supervisor with sub_agents)

Each agent wraps a deterministic core engine from ``app/core/`` via an ADK
tool function — no business logic lives in this module.
"""

import json
import logging
from typing import Optional

from google.adk import Agent
from google.adk.tools import ToolContext
from app.core.calculation.engine import CalculationRequest, CustomsCalculator
from app.core.hs_classifier.classifier import HSCodeClassifier
from app.core.rag.service import LegalRAGService

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────────
#  Tools — thin async wrappers around deterministic core engines
# ────────────────────────────────────────────────────────────────────────


async def classify_hs_code(
    description: str,
    image_bytes: Optional[bytes] = None,
    image_mime_type: str = "image/jpeg",
    tool_context: Optional[ToolContext] = None,
) -> str:
    """Classify a product description into Kazakhstan HS Codes (TH VED EAES).

    Uses vector search + Gemini vision to produce the top candidate codes
    with confidence scores and duty rates.

    Args:
        description: Product description in Russian, Kazakh, or English.
        image_bytes: Optional raw image bytes (base64-encoded) for visual
            product analysis.  Pass ``None`` for text-only classification.
        image_mime_type: MIME type of the image (e.g. ``image/jpeg``,
            `image/png`).  Ignored when *image_bytes* is ``None``.
        tool_context: Optional ADK tool context to extract uploaded file state.
    """

    if tool_context and tool_context.state:
        state_bytes = tool_context.state.get("uploaded_file_bytes")
        state_mime = tool_context.state.get("uploaded_file_mime")
        if state_bytes:
            image_bytes = state_bytes
        if state_mime:
            image_mime_type = state_mime

    result = await HSCodeClassifier.classify(
        description=description,
        image_bytes=image_bytes,
        image_mime_type=image_mime_type,
    )
    return result.model_dump_json(ensure_ascii=False)


async def search_customs_law(
    query: str,
    history: Optional[str] = None,
) -> str:
    """Search the Kazakhstan customs / EAEU legal knowledge base.

    Queries the Qdrant-backed RAG index and synthesises a structured legal
    answer with article citations.

    Args:
        query: Legal question in Russian or Kazakh.
        history: Optional JSON-encoded conversation history (list of
            ``{"role": …, "content": …}`` dicts) for multi-turn context.
    """
    parsed_history = None
    if history:
        try:
            parsed_history = json.loads(history)
        except (json.JSONDecodeError, TypeError):
            pass

    result = await LegalRAGService.query_legal_base(
        query=query,
        history=parsed_history,
    )
    return result.model_dump_json(ensure_ascii=False)


async def calculate_duties(
    invoice_price: float,
    currency: str = "USD",
    transport_to_border: float = 0.0,
    duty_rate_percent: float = 0.0,
    excise_rate_percent: float = 0.0,
    excise_specific_rate: float = 0.0,
    excise_units_count: float = 0.0,
    is_subject_to_recycling_fee: bool = False,
    recycling_fee_base_mci: float = 0.0,
) -> str:
    """Calculate customs duties, taxes and fees for Kazakhstan imports.

    Delegates to the deterministic ``CustomsCalculator`` engine — the LLM
    never guesses financial figures.

    Args:
        invoice_price: Invoice price in the specified *currency*.
        currency: Three-letter currency code (``USD``, ``EUR``, ``RUB``, …).
        transport_to_border: Transport cost to the EAEU / RK border in KZT.
        duty_rate_percent: Ad-valorem customs duty rate in percent.
        excise_rate_percent: Ad-valorem excise rate in percent.
        excise_specific_rate: Specific excise rate in KZT per unit.
        excise_units_count: Number of units subject to the specific excise.
        is_subject_to_recycling_fee: Whether the product is liable for the
            recycling fee (утильсбор).
        recycling_fee_base_mci: MCI (МРП) multiplier for the recycling fee.
    """
    req = CalculationRequest(
        invoice_price=invoice_price,
        currency=currency,
        transport_to_border=transport_to_border,
        duty_rate_percent=duty_rate_percent,
        excise_rate_percent=excise_rate_percent,
        excise_specific_rate=excise_specific_rate,
        excise_units_count=excise_units_count,
        is_subject_to_recycling_fee=is_subject_to_recycling_fee,
        recycling_fee_base_mci=recycling_fee_base_mci,
    )
    result = CustomsCalculator.calculate(req)
    return result.model_dump_json(ensure_ascii=False)


# ────────────────────────────────────────────────────────────────────────
#  Agents
# ────────────────────────────────────────────────────────────────────────

DEFAULT_MODEL: str = "gemini-2.0-flash"

HSClassifierAgent = Agent(
    name="HSClassifierAgent",
    model=DEFAULT_MODEL,
    instruction=(
        "You are an expert Kazakhstan customs HS code classifier (TN VED EAES). "
        "Use the classify_hs_code tool to classify products. "
        "Report the results clearly: the 10-digit HS code, product name in Russian, "
        "duty rate, excise rate, and confidence score. "
        "When the user provides an image alongside a description, pass the image data "
        "to the tool for visual analysis."
    ),
    tools=[classify_hs_code],
    output_key="hs_classification_result",
)

LegalRAGAgent = Agent(
    name="LegalRAGAgent",
    model=DEFAULT_MODEL,
    instruction=(
        "You are Keden Zagerm (Кеден Заңгері), the leading customs legal expert "
        "of the Republic of Kazakhstan and the Eurasian Economic Union (EAES).\n\n"
        "You provide precisely accurate, legally sound, professional, and practically "
        "applicable advice on customs regulation, declaration, goods classification, "
        "and customs payment calculation.\n\n"
        "Rules:\n"
        "- Always cite specific articles, paragraphs, and legal provisions.\n"
        "- Quote key phrases from the law verbatim in quotation marks.\n"
        "- Use the search_customs_law tool to research every legal question.\n"
        "- If the knowledge base lacks a direct regulation, say so clearly and "
        "provide general legal guidance based on fundamental EAES principles.\n"
        "- Maintain conversation context across multiple turns — remember what "
        "the user previously described.\n"
        "- Answer in Russian or Kazakh as the user prefers.\n"
        "- Structure responses as: (1) summary, (2) legal justification with "
        "citations, (3) practical recommendations."
    ),
    tools=[search_customs_law],
)

CustomsCalculatorAgent = Agent(
    name="CustomsCalculatorAgent",
    model=DEFAULT_MODEL,
    instruction=(
        "You are a Kazakhstan customs duties calculator.\n\n"
        "When the user provides product details (HS code, country of origin, "
        "invoice price, currency, transport costs), use the calculate_duties tool "
        "to compute all applicable customs payments.\n\n"
        "Report the complete duty breakdown:\n"
        "1. Customs value (in KZT)\n"
        "2. Customs processing fee\n"
        "3. Customs duty (import duty)\n"
        "4. Excise tax (if applicable)\n"
        "5. Import VAT (12%)\n"
        "6. Recycling fee (if applicable)\n"
        "7. Total payments to be made\n\n"
        "Request any missing required parameters from the user before calculating."
    ),
    tools=[calculate_duties],
    output_key="calculation_result",
)

KedenCoordinatorAgent = Agent(
    name="KedenCoordinatorAgent",
    model=DEFAULT_MODEL,
    instruction=(
        "You are the Keden AI coordinator — a smart Kazakhstan customs assistant.\n\n"
        "Your role is to understand the user's request and delegate it to the "
        "appropriate specialized agent, or handle it directly for simple interactions.\n\n"
        "Routing rules:\n"
        "- Customs laws, regulations, or legal questions → delegate to LegalRAGAgent.\n"
        "- Product classification or HS code lookup → delegate to HSClassifierAgent.\n"
        "- Duty, tax, or customs payment calculation → delegate to "
        "CustomsCalculatorAgent.\n"
        "- Greetings, general chat, or simple queries → respond directly.\n"
        "- Unclear intent → ask clarifying questions.\n\n"
        "Always be helpful, professional, and precise. "
        "When returning results from sub-agents, present them in a clear, "
        "structured format suitable for the user.\n\n"
        "For calculation results, show the full payment breakdown. "
        "For legal queries, cite specific articles. "
        "For HS classification, show the code, product name, and reasoning."
    ),
    sub_agents=[HSClassifierAgent, LegalRAGAgent, CustomsCalculatorAgent],
)

# Public exports
__all__ = [
    "HSClassifierAgent",
    "LegalRAGAgent",
    "CustomsCalculatorAgent",
    "KedenCoordinatorAgent",
    "classify_hs_code",
    "search_customs_law",
    "calculate_duties",
]
