import re
import json
import logging
from typing import List, Optional, Any

from fastapi import APIRouter, HTTPException, Form, File, UploadFile
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

# ── ADK 2.0 imports ────────────────────────────────────────────────────
from google.adk.workflow import Workflow, Edge, START, node
from google.adk.sessions import InMemorySessionService
from google.adk import Runner
from google.genai import types as genai_types

# Agents and tools from the separate definition module.
# They are available for future LLM-based delegation; the workflow
# function nodes below call the deterministic core services directly
# to avoid requiring live Gemini credentials in all environments.
from app.core.orchestrator.adk_agents import (
    HSClassifierAgent,
    LegalRAGAgent,
    CustomsCalculatorAgent,
    KedenCoordinatorAgent,
    classify_hs_code,
    search_customs_law,
    calculate_duties,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orchestrate", tags=["Orchestrator"])

# ════════════════════════════════════════════════════════════════════════
#  IntentClassifier  (kept unchanged — used by the workflow coordinator)
# ════════════════════════════════════════════════════════════════════════

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

# ════════════════════════════════════════════════════════════════════════
#  Workflow helper functions
# ════════════════════════════════════════════════════════════════════════

def _extract_text_from_node_input(node_input: Any) -> str:
    """Extract the plain-text user message from a genai Content or fallback."""
    if isinstance(node_input, genai_types.Content):
        parts = getattr(node_input, "parts", []) or []
        texts = []
        for p in parts:
            if hasattr(p, "text") and p.text:
                texts.append(p.text)
        return " ".join(texts).strip()
    if isinstance(node_input, str):
        return node_input.strip()
    if isinstance(node_input, dict):
        return (node_input.get("text") or "").strip()
    return str(node_input).strip() if node_input else ""

async def _handle_broker_interception(text_lower: str) -> Optional[OrchestrateResponse]:
    """Smart interception for broker registry lookup."""
    try:
        from app.core.database import SessionLocal
        from app.services.kgd_registry import KGDRegistryService
        detected_city = None
        for city in ["астана", "алматы", "актау", "караганда", "шымкент", "атырау"]:
            if city in text_lower:
                detected_city = city.capitalize()
                break
        db = SessionLocal()
        try:
            KGDRegistryService.seed_initial_brokers(db)
            brokers = KGDRegistryService.search_brokers(db, city=detected_city)
            if brokers:
                city_suffix = f" в городе {detected_city}" if detected_city else ""
                msg = f"\U0001f50d **Результаты поиска таможенных брокеров{city_suffix}** в реестре КГД РК:\n\n"
                for b in brokers:
                    msg += (
                        f"\U0001f3e2 **{b.company_name}**\n"
                        f"\u2022 Лицензия: \u2116{b.license_number}\n"
                        f"\u2022 БИН: {b.bin_number or 'Не указан'}\n"
                        f"\u2022 Город: {b.city}\n"
                        f"\u2022 Адрес: {b.address or 'Не указан'}\n"
                        f"\u2022 Контакты: {b.contacts or 'Не указаны'}\n"
                        f"\u2022 Рейтинг: \u2b50 {b.rating:.1f}/5.0\n\n"
                    )
                return OrchestrateResponse(
                    intent=IntentType.question_about_law,
                    message=msg,
                    pipeline_results={"brokers": [b.license_number for b in brokers]}
                )
            else:
                city_str = f" в городе {detected_city}" if detected_city else ""
                return OrchestrateResponse(
                    intent=IntentType.question_about_law,
                    message=f"\u274c В реестре КГД РК не найдено лицензированных таможенных брокеров{city_str}.",
                    pipeline_results={"brokers": []}
                )
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Broker interceptor failed: {e}", exc_info=True)
        return None

async def _handle_trois_interception(text: str) -> Optional[OrchestrateResponse]:
    """Smart interception for TROIS intellectual property registry."""
    try:
        from app.core.database import SessionLocal
        from app.services.kgd_registry import KGDRegistryService
        brand_match = re.search(r"['\"\u00ab\u201c]([^'\"\u00bb\u201d]+)['\"\u00bb\u201d]", text)
        brand_name = brand_match.group(1) if brand_match else None
        if not brand_name:
            words = text.split()
            for w in words:
                clean_w = w.strip("'\"\u00ab\u00bb\u201c\u201d.,!?")
                if clean_w.lower() not in [
                    "зарегистрирован", "ли", "товарный", "знак", "в", "реестре",
                    "троис", "республики", "казахстан", "бренд", "торговая", "марка"
                ]:
                    brand_name = clean_w
                    break
        if brand_name:
            db = SessionLocal()
            try:
                from app.core.models import TROISRegistry
                if db.query(TROISRegistry).count() == 0:
                    sample_brands = [
                        TROISRegistry(
                            trademark_name="Apple",
                            right_holder="Apple Inc. (Купертино, США)",
                            authorized_importers="ТОО 'Apple Kazakhstan', ТОО 'ASBIS Kazakhstan'",
                            unauthorized_importers_action="Приостановление выпуска товаров на 10 рабочих дней",
                            registry_number="001/TROIS-2024",
                            valid_until=None
                        ),
                        TROISRegistry(
                            trademark_name="Samsung",
                            right_holder="Samsung Electronics Co., Ltd. (Сувон, Корея)",
                            authorized_importers="ТОО 'Samsung Electronics Central Eurasia'",
                            unauthorized_importers_action="Приостановление выпуска товаров",
                            registry_number="002/TROIS-2024",
                            valid_until=None
                        )
                    ]
                    db.add_all(sample_brands)
                    db.commit()
                    logger.info("Seeded initial sample TROIS trademarks")
                trademark = KGDRegistryService.check_trois_trademark(db, brand_name)
                if trademark:
                    msg = (
                        f"\U0001f6e1\ufe0f **Объект интеллектуальной собственности найден в реестре ТРОИС РК!**\n\n"
                        f"\u2022 **Товарный знак:** \u00ab{trademark.trademark_name}\u00bb\n"
                        f"\u2022 **Регистрационный номер:** {trademark.registry_number}\n"
                        f"\u2022 **Правообладатель:** {trademark.right_holder}\n"
                        f"\u2022 **Авторизованные импортеры:** {trademark.authorized_importers or 'Не указаны'}\n"
                        f"\u2022 **Меры таможенного контроля:** {trademark.unauthorized_importers_action or 'Приостановление выпуска'}\n"
                    )
                    return OrchestrateResponse(
                        intent=IntentType.question_about_law,
                        message=msg,
                        pipeline_results={"trois_record": trademark.registry_number}
                    )
                else:
                    msg = (
                        f"\u2705 Товарный знак **\u00ab{brand_name}\u00bb** не найден в реестре ТРОИС Республики Казахстан.\n\n"
                        f"Это означает, что для его ввоза таможенные органы РК не будут автоматически запрашивать разрешение "
                        f"у правообладателя, если только на границе не будут выявлены явные признаки контрафакта (подделки)."
                    )
                    return OrchestrateResponse(
                        intent=IntentType.question_about_law,
                        message=msg,
                        pipeline_results={"trois_record": None}
                    )
            finally:
                db.close()
    except Exception as e:
        logger.error(f"TROIS interceptor failed: {e}", exc_info=True)
        return None

# ════════════════════════════════════════════════════════════════════════
#  Workflow Function Nodes
# ════════════════════════════════════════════════════════════════════════

@node(rerun_on_resume=True)
async def coordinator_node(ctx, node_input):
    """
    First workflow node: classify intent, run smart interceptions,
    set ctx.route so the graph routes to the correct specialist node.
    """
    text = _extract_text_from_node_input(node_input)
    ctx.state["user_text"] = text
    # Preserve history seeded from session state (set by orchestrate endpoint)
    if "history" not in ctx.state or not ctx.state["history"]:
        ctx.state["history"] = []
    if not text:
        ctx.route = "unclear"
        return {"intent": "unclear", "message": "Пожалуйста, напишите ваш вопрос или загрузите файл."}

    text_lower = text.lower()

    # ── FAQ fastpath (bypasses LLM intent classification) ──────────
    from app.core.orchestrator.config_loader import ConfigLoader
    faq_answer = ConfigLoader().check_faq(text)
    if faq_answer:
        result = OrchestrateResponse(
            intent=IntentType.question_about_law,
            message=faq_answer,
            pipeline_results={
                "fastpath": True,
                "source": "faq.yaml",
                "reasoning": "Static keyword match",
            },
        )
        ctx.state["orchestrate_response"] = result
        ctx.route = "faq_response"
        return result.model_dump()

    # ── Smart interception: broker registry ────────────────────────
    if any(w in text_lower for w in ["брокер", "брокеры"]):
        result = await _handle_broker_interception(text_lower)
        if result is not None:
            ctx.state["orchestrate_response"] = result
            ctx.route = "interception_response"
            return result.model_dump()
        # fall through to normal classification on error

    # ── Smart interception: TROIS trademark registry ───────────────
    if any(w in text_lower for w in ["троис", "товарный знак", "товарные знаки", "торговая марка", "бренд"]):
        result = await _handle_trois_interception(text)
        if result is not None:
            ctx.state["orchestrate_response"] = result
            ctx.route = "interception_response"
            return result.model_dump()
        # fall through to normal classification on error

    # ── Normal intent classification ───────────────────────────────
    classification = await IntentClassifier.classify(text)
    ctx.state["intent"] = classification.intent.value
    ctx.state["confidence"] = classification.confidence
    ctx.state["reasoning"] = classification.reasoning

    ctx.route = classification.intent.value
    return classification.model_dump()

@node(rerun_on_resume=True)
async def greeting_node(ctx, node_input):
    """Handle greeting intent."""
    return {
        "intent": "greeting",
        "message": (
            "\U0001f44b Здравствуйте! Я — Кеден Көмекшісі (CustomAI Kazakhstan).\n\n"
            "Я могу помочь вам:\n"
            "\u2022 **Консультация по законодательству** — вопросы о ТК РК, Налоговом кодексе\n"
            "\u2022 **Классификация товаров** — подбор кода ТН ВЭД\n"
            "\u2022 **Расчёт таможенных платежей** — пошлины, НДС, акцизы, утильсбор\n\n"
            "Напишите ваш вопрос!"
        ),
    }

@node(rerun_on_resume=True)
async def document_upload_node(ctx, node_input):
    """Handle document upload intent."""
    return {
        "intent": "document_upload",
        "message": (
            "Для загрузки документа отправьте текст закона или нормативного акта, "
            "и я проиндексирую его в базе знаний. "
            "Поддерживаются тексты в формате: статьи, разделы, параграфы."
        ),
    }

@node(rerun_on_resume=True)
async def unclear_node(ctx, node_input):
    """Handle unclear / fallback intent."""
    return {
        "intent": "unclear",
        "message": (
            "Я не совсем понял ваш запрос. Пожалуйста, уточните:\n\n"
            "\u2022 **Вопрос о законодательстве** — \"Какая ставка НДС?\"\n"
            "\u2022 **Классификация товара** — \"Определи код для телефона\"\n"
            "\u2022 **Расчёт платежей** — \"Посчитай пошлину\"\n"
            "\u2022 **Загрузить закон** — \"Загрузи новый текст\""
        ),
    }

@node(rerun_on_resume=True)
async def legal_rag_node(ctx, node_input):
    """Handle question_about_law intent using LegalRAGService."""
    text = ctx.state.get("user_text", "")
    history_dicts: list[dict[str, str]] = []
    raw_history = ctx.state.get("history")
    if raw_history:
        history_dicts = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in raw_history]

    rag_result = await LegalRAGService.query_legal_base(text, history=history_dicts)

    return {
        "intent": "question_about_law",
        "message": rag_result.answer_synthesis,
        "pipeline_results": {"supporting_laws": [law.model_dump() for law in rag_result.supporting_laws]},
    }

@node(rerun_on_resume=True)
async def hs_classifier_node(ctx, node_input):
    """Handle product_description intent using HSCodeClassifier."""
    text = ctx.state.get("user_text", "")
    uploaded_bytes = ctx.state.get("uploaded_file_bytes")
    uploaded_mime = ctx.state.get("uploaded_file_mime", "image/jpeg")
    hs_result = await HSCodeClassifier.classify(
        description=text,
        image_bytes=uploaded_bytes,
        image_mime_type=uploaded_mime,
    )
    msg_lines = [f"**Товар:** {hs_result.product_description}"]
    if hs_result.qdrant_backed:
        msg_lines.append("_Результаты подтверждены поиском в базе кодов ТН ВЭД._")
    else:
        msg_lines.append("_Поиск в базе кодов недоступен, использованы знания модели._")
    msg_lines.append("\n**Кандидаты:**")
    for c in hs_result.candidates:
        recycle = "\u267b Утильсбор" if c.is_subject_to_recycling_fee else ""
        msg_lines.append(f"- {c.hs_code} ({c.product_name_ru}) \u2014 пошлина {c.duty_rate_percent}% {recycle}")
        msg_lines.append(f"  *{c.reasoning[:150]}*")

    result = {
        "intent": "product_description",
        "message": "\n".join(msg_lines),
        "pipeline_results": {"candidates": [c.model_dump() for c in hs_result.candidates]},
    }
    ctx.state["hs_classification_done"] = True
    ctx.state["hs_classification_result"] = result

    return result

@node(rerun_on_resume=True)
async def calculator_node(ctx, node_input):
    """Handle calculation_request intent using ProfileExtractor + CustomsCalculator."""
    text = ctx.state.get("user_text", "")
    raw_history = ctx.state.get("history", [])

    try:
        # Build chat message history for ProfileExtractor
        chat_history: list[ChatMessage] = []
        if raw_history:
            chat_history = [ChatMessage(role=m.get("role", "user"), content=m.get("content", "")) for m in raw_history]

        extraction = ProfileExtractor.extract(chat_history, text)
        profile = extraction.accumulated_profile
        # Smart Enhancement: Auto-lookup duty rate if HS Code is provided but duty rate is missing
        if profile.hs_code and profile.duty_rate_percent is None:
            try:
                from app.core.hs_classifier.classifier import HSCodeClassifier
                hs_result = await HSCodeClassifier.classify(description=profile.hs_code)
                if hs_result and hs_result.candidates:
                    best_match = hs_result.candidates[0]
                    profile.duty_rate_percent = best_match.duty_rate_percent
                    profile.is_subject_to_recycling_fee = best_match.is_subject_to_recycling_fee
                    logger.info(f"Auto-populated duty rate for HS Code {profile.hs_code} using {best_match.hs_code}: {best_match.duty_rate_percent}%")
            except Exception as hs_err:
                logger.warning(f"Failed to auto-lookup duty rate for HS Code {profile.hs_code}: {hs_err}")
        if (profile.invoice_price is not None and profile.invoice_price > 0.0
                and profile.currency is not None and profile.duty_rate_percent is not None):
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
                f"\U0001f4ca **Автоматический расчёт таможенных платежей (на основе накопленного контекста):**\n\n"
                f"\u2022 **Стоимость инвойса:** {profile.invoice_price:,.2f} {profile.currency}\n"
            )
            if profile.hs_code:
                msg += f"\u2022 **Код ТН ВЭД:** {profile.hs_code}\n"
            msg += (
                f"\u2022 **Ставка пошлины:** {profile.duty_rate_percent}%\n"
                f"\u2022 **Утильсбор:** {'Да' if is_recycling else 'Нет'}\n"
            )
            if profile.weight_kg:
                msg += f"\u2022 **Вес товара:** {profile.weight_kg} кг\n"
            if profile.transport_to_border:
                msg += f"\u2022 **Доставка до границы:** {profile.transport_to_border:,.2f} KZT\n"

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
            msg += f"\n\U0001f525 **Итого к уплате:** {res.total_payments_kzt:,.2f} KZT\n"

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

            return {
                "intent": "calculation_request",
                "message": msg,
                "pipeline_results": {
                    "calculation_request": calc_req.model_dump(),
                    "calculation_response": res.model_dump(),
                },
                "chain_warning": chain_warning_msg,
            }

        return {
            "intent": "calculation_request",
            "message": extraction.next_question,
            "pipeline_results": {
                "accumulated_profile": profile.model_dump(),
                "missing_fields": extraction.missing_fields,
            },
        }
    except Exception as exc:
        logger.error(f"Accumulator calculation handler failed: {exc}", exc_info=True)
        return {
            "intent": "calculation_request",
            "message": "Извините, произошла ошибка при обработке параметров расчета. Попробуйте ввести данные заново.",
        }

@node(rerun_on_resume=True)
async def conditional_route_node(ctx, node_input):
    """
    Decision node after HS classification:
    if a valid result exists AND the user also requested a calculation,
    chain to the calculator node.
    """
    hs_done = ctx.state.get("hs_classification_done", False)
    text = ctx.state.get("user_text", "")
    text_lower = text.lower()

    wants_calc = any(w in text_lower for w in ["пошлин", "растаможк", "ндс", "платеж", "калькуляци", "сколько", "пошлина"])

    if hs_done and wants_calc:
        ctx.route = "chain_to_calc"
        return {"chain": True, "message": "Chaining to calculator..."}

    # No chaining — the HS result (already stored) is the final output
    hs_result = ctx.state.get("hs_classification_result", {})
    if hs_result:
        return hs_result

    return {"intent": "product_description", "message": "Классификация выполнена."}

@node(rerun_on_resume=True)
async def interception_response_node(ctx, node_input):
    """Return a pre-built OrchestrateResponse from a smart interception."""
    result = ctx.state.get("orchestrate_response")
    if result is not None:
        # Convert Pydantic model to dict
        return result.model_dump()
    return {"intent": "unclear", "message": "Запрос обработан."}

@node(rerun_on_resume=True)
async def faq_response_node(ctx, node_input):
    """Return a pre-built FAQ OrchestrateResponse."""
    result = ctx.state.get("orchestrate_response")
    if result is not None:
        return result.model_dump()
    return {"intent": "question_about_law", "message": ""}

# ════════════════════════════════════════════════════════════════════════
#  Workflow Graph  (Section 4 of google_adk_orchestration_flow.md)
# ════════════════════════════════════════════════════════════════════════
#
#  State machine:
#    START -> coordinator_node
#    coordinator_node -(route: intent)-> specialist_node
#    specialist_node -> END (automatic)
#    hs_classifier_node -> conditional_route_node
#    conditional_route_node -(chain_to_calc)-> calculator_node
# ════════════════════════════════════════════════════════════════════════

_KEDEN_WORKFLOW_EDGES: list[Edge] = [
    # Entry
    Edge(from_node=START, to_node=coordinator_node),
    # Conditional intent-based routing from coordinator
    Edge(from_node=coordinator_node, to_node=greeting_node, route="greeting"),
    Edge(from_node=coordinator_node, to_node=document_upload_node, route="document_upload"),
    Edge(from_node=coordinator_node, to_node=unclear_node, route="unclear"),
    Edge(from_node=coordinator_node, to_node=hs_classifier_node, route="product_description"),
    Edge(from_node=coordinator_node, to_node=legal_rag_node, route="question_about_law"),
    Edge(from_node=coordinator_node, to_node=calculator_node, route="calculation_request"),
    # Smart interception routes
    Edge(from_node=coordinator_node, to_node=interception_response_node, route="interception_response"),
    # FAQ fastpath route
    Edge(from_node=coordinator_node, to_node=faq_response_node, route="faq_response"),
    # HS -> Conditional -> Calculator chain
    Edge(from_node=hs_classifier_node, to_node=conditional_route_node),
    Edge(from_node=conditional_route_node, to_node=calculator_node, route="chain_to_calc"),
]

KedenCustomsWorkflow: Workflow = Workflow(
    name="KedenCustomsWorkflow",
    edges=_KEDEN_WORKFLOW_EDGES,
    rerun_on_resume=True,
)

# Stateless in-memory session service -- each request manages its own
# session lifecycle to carry request-scoped state into ctx.state.
_APP_NAME = "keden_customs"
_USER_ID = "default_user"
_session_service: InMemorySessionService = InMemorySessionService()

_runner: Runner = Runner(
    node=KedenCustomsWorkflow,
    session_service=_session_service,
    app_name=_APP_NAME,
    auto_create_session=False,
)

# ════════════════════════════════════════════════════════════════════════
#  Orchestrate Endpoint
# ════════════════════════════════════════════════════════════════════════

@router.post("", response_model=OrchestrateResponse)
@observe(name="orchestrate")
async def orchestrate(
    text: str = Form(...),
    session_id: Optional[str] = Form(None),
    history: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    """
    Main orchestrator endpoint. Accepts a user message, runs it through
    the ADK 2.0 ``KedenCustomsWorkflow`` graph, and returns the
    ``OrchestrateResponse`` from the terminating workflow node.
    """
    if not text or not text.strip():
        raise HTTPException(
            status_code=400,
            detail="Пожалуйста, напишите ваш вопрос или загрузите файл.",
        )

    clean_text = text.strip()
    sess_id = session_id or "default"

    # Parse history
    parsed_history: List[ChatMessage] = []
    if history:
        try:
            data_list = json.loads(history)
            if isinstance(data_list, list):
                parsed_history = [ChatMessage(**m) for m in data_list]
        except Exception as e:
            logger.error(f"Failed to parse history: {e}")

    # Read uploaded file
    file_bytes: Optional[bytes] = None
    file_mime: Optional[str] = None
    file_name: Optional[str] = None
    if file is not None:
        file_bytes = await file.read()
        file_mime = file.content_type
        file_name = file.filename

    async def _run_workflow() -> Optional[dict[str, Any]]:
        """Create an ADK session seeded with request state, run the workflow,
        and return the terminal node's output."""
        # Wipe any prior session for this session_id so we start fresh
        try:
            await _session_service.delete_session(
                app_name=_APP_NAME,
                user_id=_USER_ID,
                session_id=sess_id,
            )
        except Exception:
            pass

        # Create a session whose initial state is picked up as ctx.state
        # by the workflow nodes (user_text + history).
        state_dict = {
            "user_text": clean_text,
            "history": [m.model_dump() for m in parsed_history] if parsed_history else [],
        }
        if file_bytes is not None:
            state_dict["uploaded_file_bytes"] = file_bytes
            state_dict["uploaded_file_mime"] = file_mime
            state_dict["uploaded_file_name"] = file_name

        await _session_service.create_session(
            app_name=_APP_NAME,
            user_id=_USER_ID,
            session_id=sess_id,
            state=state_dict,
        )
        final_output: Optional[dict[str, Any]] = None
        try:
            async for event in _runner.run_async(
                user_id=_USER_ID,
                session_id=sess_id,
                new_message=genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=clean_text)],
                ),
            ):
                if event.output is not None:
                    final_output = event.output
        except Exception as exc:
            logger.error(f"Workflow execution failed: {exc}", exc_info=True)
            final_output = None
        return final_output
    if settings.LANGFUSE_ENABLED and sess_id:
        with propagate_attributes(session_id=sess_id, tags=[settings.GEMINI_MODEL_ID]):
            return _workflow_output_to_response(await _run_workflow())
    return _workflow_output_to_response(await _run_workflow())

def _workflow_output_to_response(final_output: Optional[dict[str, Any]]) -> OrchestrateResponse:
    """Map the terminal workflow node's return value to an OrchestrateResponse."""
    if final_output and isinstance(final_output, dict):
        intent_str = final_output.get("intent", "unclear")
        try:
            intent = IntentType(intent_str)
        except ValueError:
            intent = IntentType.unclear

        message = final_output.get("message") or ""
        pipeline_results = final_output.get("pipeline_results")
        chain_warning = final_output.get("chain_warning")

        return OrchestrateResponse(
            intent=intent,
            message=message,
            pipeline_results=pipeline_results,
            chain_warning=chain_warning,
        )

    # Fallback: no output from workflow
    return OrchestrateResponse(
        intent=IntentType.unclear,
        message="Извините, при обработке вашего запроса произошла техническая ошибка. Попробуйте ещё раз.",
    )