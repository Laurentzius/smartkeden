import re
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from langfuse import observe, propagate_attributes
from app.core.config import settings

from app.core.orchestrator.models import (
    IntentType,
    IntentClassification,
    OrchestrateRequest,
    OrchestrateResponse,
    ChatMessage,
)
from app.core.orchestrator.profile_extractor import ProfileExtractor
from app.core.vertex_client import GeminiVertexClient
from app.core.rag.service import LegalRAGService
from app.core.hs_classifier.classifier import HSCodeClassifier
from app.core.calculation.engine import CustomsCalculator, CalculationRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orchestrate", tags=["Orchestrator"])


class IntentClassifier:
    """
    Classifies user intent using Gemini structured output with few-shot examples.
    Six supported intents: question_about_law, product_description, calculation_request,
    document_upload, greeting, unclear.
    """

    @classmethod
    @observe(name="IntentClassifier.classify")
    async def classify(cls, text: str) -> IntentClassification:
        """
        Uses Gemini structured output to classify user message intent.
        In mock/dev mode, returns a simple keyword-based fallback.
        """
        from app.core.orchestrator.config_loader import ConfigLoader
        config = ConfigLoader().get_intent_config()
        examples = config.get("examples", [])
        system_prompt = config.get("system_prompt", "Classify the user's customs-related message into exactly one intent.")

        examples_str = "\n".join(
            f'- "{q}" → {i}' for q, i in examples
        )

        prompt = (
            f"{system_prompt}\n\n"
            f"Examples:\n{examples_str}\n\n"
            f"User message: \"{text}\"\n\n"
            f"Respond with intent, confidence (0.0-1.0), and brief reasoning."
        )

        try:
            result: IntentClassification = GeminiVertexClient.generate_structured_content(
                prompt=prompt,
                response_schema=IntentClassification,
            )
            # If Gemini returns unclear, try keyword fallback first
            if result.intent == IntentType.unclear:
                fallback = cls._fallback_classify(text)
                if fallback.intent != IntentType.unclear:
                    logger.info(f"Gemini returned unclear, overridden by keyword fallback: {fallback.intent}")
                    result = fallback

            # If confidence is too low, downgrade to unclear
            if result.confidence < 0.7:
                result.intent = IntentType.unclear

            if settings.LANGFUSE_ENABLED:
                try:
                    from langfuse import get_client
                    get_client().update_current_span(
                        output={"intent": result.intent.value, "confidence": result.confidence}
                    )
                except Exception as lf_err:
                    logger.warning(f"Failed to update classification span: {lf_err}")

            return result
        except Exception as e:
            logger.warning(f"Gemini intent classification failed, using fallback: {e}")
            return cls._fallback_classify(text)

    @classmethod
    def _fallback_classify(cls, text: str) -> IntentClassification:
        """Keyword-based fallback when Gemini is unavailable."""
        text_lower = text.lower()

        # Greeting keywords
        if any(w in text_lower for w in ["привет", "здравствуйте", "здрасте", "hi", "hello"]):
            return IntentClassification(intent=IntentType.greeting, confidence=0.9, reasoning="Greeting keywords detected")

        # Calculation keywords
        if any(w in text_lower for w in ["пошлин", "растаможк", "ндс", "платеж", "калькуляци", "сколько"]):
            return IntentClassification(intent=IntentType.calculation_request, confidence=0.8, reasoning="Calculation keywords detected")

        # HS code classification keywords
        if any(w in text_lower for w in ["тн вэд", "hs", "код", "классифициру", "товар"]):
            return IntentClassification(intent=IntentType.product_description, confidence=0.8, reasoning="HS code keywords detected")

        # Document upload keywords
        if any(w in text_lower for w in ["загрузи", "документ", "текст закон"]):
            return IntentClassification(intent=IntentType.document_upload, confidence=0.8, reasoning="Document upload keywords detected")

        # Legal question keywords
        if any(w in text_lower for w in ["ставк", "закон", "кодекс", "статья", "норм"]):
            return IntentClassification(intent=IntentType.question_about_law, confidence=0.75, reasoning="Legal question keywords detected")

        return IntentClassification(intent=IntentType.unclear, confidence=0.5, reasoning="No matching keywords")


from abc import ABC, abstractmethod

class IntentHandler(ABC):
    """Abstract seam for orchestrator intent handling."""
    @abstractmethod
    async def handle(self, text: str, history: Optional[List[ChatMessage]] = None) -> OrchestrateResponse:
        pass

class GreetingHandler(IntentHandler):
    """Concrete handler for greeting intent."""
    async def handle(self, text: str, history: Optional[List[ChatMessage]] = None) -> OrchestrateResponse:
        return OrchestrateResponse(
            intent=IntentType.greeting,
            message=(
                "👋 Здравствуйте! Я — Кеден Көмекшісі (CustomAI Kazakhstan).\n\n"
                "Я могу помочь вам:\n"
                "• **Консультация по законодательству** — вопросы о ТК РК, Налоговом кодексе\n"
                "• **Классификация товаров** — подбор кода ТН ВЭД\n"
                "• **Расчёт таможенных платежей** — пошлины, НДС, акзисы, утильсбор\n\n"
                "Напишите ваш вопрос!"
            ),
        )

class DocumentUploadHandler(IntentHandler):
    """Concrete handler for document upload intent."""
    async def handle(self, text: str, history: Optional[List[ChatMessage]] = None) -> OrchestrateResponse:
        return OrchestrateResponse(
            intent=IntentType.document_upload,
            message=(
                "Для загрузки документа отправьте текст закона или нормативного акта, "
                "и я проиндексирую его в базе знаний. "
                "Поддерживаются тексты в формате: статьи, разделы, параграфы."
            ),
        )

class UnclearHandler(IntentHandler):
    """Concrete handler for unclear/fallback intents."""
    async def handle(self, text: str, history: Optional[List[ChatMessage]] = None) -> OrchestrateResponse:
        return OrchestrateResponse(
            intent=IntentType.unclear,
            message=(
                "Я не совсем понял ваш запрос. Пожалуйста, уточните:\n\n"
                "• **Вопрос о законодательстве** — \"Какая ставка НДС?\"\n"
                "• **Классификация товара** — \"Определи код для телефона\"\n"
                "• **Расчёт платежей** — \"Посчитай пошлину\"\n"
                "• **Загрузить закон** — \"Загрузи новый текст\""
            ),
        )

class LegalRAGHandler(IntentHandler):
    """Concrete handler for question_about_law intent using LegalRAGService."""
    async def handle(self, text: str, history: Optional[List[ChatMessage]] = None) -> OrchestrateResponse:
        history_dicts: list[dict[str, str]] = []
        if history:
            history_dicts = [{"role": msg.role, "content": msg.content} for msg in history]
        rag_result = await LegalRAGService.query_legal_base(text, history=history_dicts)
        return OrchestrateResponse(
            intent=IntentType.question_about_law,
            message=rag_result.answer_synthesis,
            pipeline_results={"supporting_laws": [law.model_dump() for law in rag_result.supporting_laws]},
        )

class HSClassificationHandler(IntentHandler):
    """Concrete handler for product_description intent using HSCodeClassifier."""
    async def handle(self, text: str, history: Optional[List[ChatMessage]] = None) -> OrchestrateResponse:
        hs_result = await HSCodeClassifier.classify(description=text)
        msg_lines = [f"**Товар:** {hs_result.product_description}"]
        if hs_result.qdrant_backed:
            msg_lines.append("_Результаты подтверждены поиском в базе кодов ТН ВЭД._")
        else:
            msg_lines.append("_Поиск в базе кодов недоступен, использованы знания модели._")
        msg_lines.append("\n**Кандидаты:**")
        for c in hs_result.candidates:
            recycle = "♻ Утильсбор" if c.is_subject_to_recycling_fee else ""
            msg_lines.append(f"- {c.hs_code} ({c.product_name_ru}) — пошлина {c.duty_rate_percent}% {recycle}")
            msg_lines.append(f"  *{c.reasoning[:150]}*")
        return OrchestrateResponse(
            intent=IntentType.product_description,
            message="\n".join(msg_lines),
            pipeline_results={"candidates": [c.model_dump() for c in hs_result.candidates]},
        )

class CustomsCalculationHandler(IntentHandler):
    """Concrete handler for calculation_request intent. Uses stateful Pydantic parameter accumulation."""
    async def handle(self, text: str, history: Optional[List[ChatMessage]] = None) -> OrchestrateResponse:
        try:
            # Dynamic stateful parameter extraction across turns using LLM/structured outputs
            extraction = ProfileExtractor.extract(history, text)
            profile = extraction.accumulated_profile
            
            # If all required parameters (price, currency, duty_rate_percent) are available, run the math calculation
            if (profile.invoice_price is not None and profile.invoice_price > 0.0 and
                profile.currency is not None and profile.duty_rate_percent is not None):
                
                from app.core.calculation.engine import CustomsCalculator, CalculationRequest
                
                is_recycling = bool(profile.is_subject_to_recycling_fee)
                calc_req = CalculationRequest(
                    invoice_price=profile.invoice_price,
                    currency=profile.currency,
                    duty_rate_percent=profile.duty_rate_percent,
                    transport_to_border=profile.transport_to_border or 0.0,
                    is_subject_to_recycling_fee=is_recycling,
                    recycling_fee_base_mci=50.0 if is_recycling else 0.0,
                )
                res = CustomsCalculator.calculate(calc_req)
                
                msg = (
                    f"📊 **Автоматический расчёт таможенных платежей (на основе накопленного контекста):**\n\n"
                    f"• **Стоимость инвойса:** {profile.invoice_price:,.2f} {profile.currency}\n"
                )
                if profile.hs_code:
                    msg += f"• **Код ТН ВЭД:** {profile.hs_code}\n"
                msg += (
                    f"• **Ставка пошлины:** {profile.duty_rate_percent}%\n"
                    f"• **Утильсбор:** {'Да' if is_recycling else 'Нет'}\n"
                )
                if profile.weight_kg:
                    msg += f"• **Вес товара:** {profile.weight_kg} кг\n"
                if profile.transport_to_border:
                    msg += f"• **Доставка до границы:** {profile.transport_to_border:,.2f} KZT\n"
                
                msg += (
                    f"\n**Результаты расчёта в KZT:**\n"
                    f"- Таможенная стоимость: {res.customs_value_kzt:,.2f} KZT\n"
                    f"- Таможенный сбор (фиксированный): {res.customs_fee_kzt:,.2f} KZT\n"
                    f"- Импортная пошлина: {res.customs_duty_kzt:,.2f} KZT\n"
                    f"- База НДС: {res.vat_base_kzt:,.2f} KZT\n"
                    f"- НДС на импорт (12%): {res.import_vat_kzt:,.2f} KZT\n"
                )
                if is_recycling:
                    msg += f"- Утильсбор: {res.recycling_fee_kzt:,.2f} KZT\n"
                msg += f"\n🔥 **Итого к уплате:** {res.total_payments_kzt:,.2f} KZT\n"
                
                # Gather chained parameters to inform the user what was pulled from context
                chained_fields = []
                if profile.hs_code:
                    chained_fields.append(f"код ТН ВЭД {profile.hs_code}")
                if profile.duty_rate_percent > 0.0:
                    chained_fields.append(f"пошлина {profile.duty_rate_percent}%")
                if is_recycling:
                    chained_fields.append("утильсбор")
                if profile.weight_kg:
                    chained_fields.append(f"вес {profile.weight_kg} кг")
                if profile.transport_to_border:
                    chained_fields.append(f"доставка до границы {profile.transport_to_border:,.2f} KZT")
                
                chain_warning_msg = None
                if chained_fields:
                    chain_warning_msg = "Накопленные параметры: " + ", ".join(chained_fields)
                
                return OrchestrateResponse(
                    intent=IntentType.calculation_request,
                    message=msg,
                    pipeline_results={
                        "calculation_request": calc_req.model_dump(),
                        "calculation_response": res.model_dump()
                    },
                    chain_warning=chain_warning_msg
                )
            
            # If parameters are still missing, continue the collection loop
            return OrchestrateResponse(
                intent=IntentType.calculation_request,
                message=extraction.next_question,
                pipeline_results={
                    "accumulated_profile": profile.model_dump(),
                    "missing_fields": extraction.missing_fields
                }
            )
        except Exception as exc:
            logger.error(f"Accumulator calculation handler failed: {exc}", exc_info=True)
            return OrchestrateResponse(
                intent=IntentType.calculation_request,
                message="Извините, произошла ошибка при обработке параметров расчета. Попробуйте ввести данные заново.",
            )

class IntentHandlerRegistry:
    """Registry managing IntentType mappings to their corresponding handler seams."""
    _handlers: dict[IntentType, IntentHandler] = {
        IntentType.greeting: GreetingHandler(),
        IntentType.document_upload: DocumentUploadHandler(),
        IntentType.unclear: UnclearHandler(),
        IntentType.question_about_law: LegalRAGHandler(),
        IntentType.product_description: HSClassificationHandler(),
        IntentType.calculation_request: CustomsCalculationHandler()
    }

    @classmethod
    def get_handler(cls, intent: IntentType) -> IntentHandler:
        return cls._handlers.get(intent, cls._handlers[IntentType.unclear])

    @classmethod
    def register(cls, intent: IntentType, handler: IntentHandler):
        cls._handlers[intent] = handler

@observe(name="dispatch_intent")
async def dispatch_intent(
    intent: IntentType, text: str, history: Optional[List[ChatMessage]] = None
) -> OrchestrateResponse:
    """Routes the classified intent to the correct handler and returns the result."""
    handler = IntentHandlerRegistry.get_handler(intent)
    try:
        return await handler.handle(text, history=history)
    except Exception as e:
        logger.error(f"Handler for intent {intent} failed: {e}")
        return OrchestrateResponse(
            intent=intent,
            message="Извините, при обработке вашего запроса произошла техническая ошибка. Попробуйте ещё раз.",
            chain_warning=f"Handler error: {str(e)}"
        )


@router.post("", response_model=OrchestrateResponse)
@observe(name="orchestrate")
async def orchestrate(req: OrchestrateRequest):
    """
    Main orchestrator endpoint. Accepts a user message, classifies intent,
    and routes to the appropriate pipeline.
    """
    if not req.text or not req.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Пожалуйста, напишите ваш вопрос или загрузите файл.",
        )

    text = req.text.strip()
    sess_id = req.session_id or ""

    # Check FAQ early fastpath
    from app.core.orchestrator.config_loader import ConfigLoader
    faq_answer = ConfigLoader().check_faq(text)
    if faq_answer:
        logger.info("FAQ fastpath match found. Bypassing LLM/Vector.")
        return OrchestrateResponse(
            intent=IntentType.question_about_law,
            message=faq_answer,
            pipeline_results={
                "fastpath": True,
                "source": "faq.yaml",
                "reasoning": "Static keyword match"
            }
        )

    async def _run():
        # 1. Classify intent
        classification = await IntentClassifier.classify(text)
        logger.info(f"Classified intent: {classification.intent} (confidence: {classification.confidence:.2f})")

        if settings.LANGFUSE_ENABLED:
            try:
                from langfuse import get_client
                get_client().update_current_span(
                    metadata={"intent": classification.intent.value, "confidence": classification.confidence}
                )
            except Exception as lf_err:
                logger.warning(f"Failed to update orchestrate span metadata: {lf_err}")

        # 2. Dispatch to pipeline
        response = await dispatch_intent(classification.intent, text, history=req.history)
        return response

    if settings.LANGFUSE_ENABLED and sess_id:
        with propagate_attributes(session_id=sess_id, tags=[settings.GEMINI_MODEL_ID]):
            return await _run()
    else:
        return await _run()
