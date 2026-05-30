import logging
from typing import Any

from app.core.orchestrator.models import IntentType, OrchestrateResponse, ChatMessage
from app.core.orchestrator.intent_classifier import IntentClassifier
from app.core.orchestrator.smart_interception import (
    _extract_text_from_node_input,
    _handle_broker_interception,
    _handle_trois_interception,
)
from app.core.orchestrator.profile_extractor import ProfileExtractor
from app.core.wiring import hs_classifier, legal_rag_service
from app.core.calculation.engine import CustomsCalculator, CalculationRequest
from google.adk.workflow import node


logger = logging.getLogger(__name__)


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
        return {
            "intent": "unclear",
            "message": "Пожалуйста, напишите ваш вопрос или загрузите файл.",
        }

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
    if any(
        w in text_lower
        for w in ["троис", "товарный знак", "товарные знаки", "торговая марка", "бренд"]
    ):
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
            '\u2022 **Вопрос о законодательстве** — "Какая ставка НДС?"\n'
            '\u2022 **Классификация товара** — "Определи код для телефона"\n'
            '\u2022 **Расчёт платежей** — "Посчитай пошлину"\n'
            '\u2022 **Загрузить закон** — "Загрузи новый текст"'
        ),
    }


@node(rerun_on_resume=True)
async def legal_rag_node(ctx, node_input):
    """Handle question_about_law intent using LegalRAGService."""
    text = ctx.state.get("user_text", "")
    history_dicts: list[dict[str, str]] = []
    raw_history = ctx.state.get("history")
    if raw_history:
        history_dicts = [
            {"role": m.get("role", "user"), "content": m.get("content", "")}
            for m in raw_history
        ]

    rag_result = await legal_rag_service.query_legal_base(text, history=history_dicts)

    return {
        "intent": "question_about_law",
        "message": rag_result.answer_synthesis,
        "pipeline_results": {
            "supporting_laws": [law.model_dump() for law in rag_result.supporting_laws]
        },
    }


@node(rerun_on_resume=True)
async def hs_classifier_node(ctx, node_input):
    """Handle product_description intent using HSCodeClassifier + Classification Rules."""
    text = ctx.state.get("user_text", "")
    uploaded_bytes = ctx.state.get("uploaded_file_bytes")
    uploaded_mime = ctx.state.get("uploaded_file_mime", "image/jpeg")

    # ── Attribute extraction ────────────────────────────────────────────
    from app.core.classification.attribute_extractor import AttributeExtractor
    from app.core.orchestrator.adk_tools import apply_classification_rules

    attribute_extractor = AttributeExtractor()

    # Check if we're resuming after clarifying questions
    if "missing_attributes" in ctx.state and "user_answers" in ctx.state:
        # Merge user answers with existing attributes
        extracted_attributes = ctx.state.get("extracted_attributes", {})
        extracted_attributes.update(ctx.state["user_answers"])
        ctx.state.pop("missing_attributes", None)
        ctx.state.pop("user_answers", None)
    else:
        # First run: extract attributes from description and image
        extracted_attributes = await attribute_extractor.extract_attributes(
            description=text,
            image_bytes=uploaded_bytes,
        )

    # ── HS Classification ───────────────────────────────────────────────
    hs_result = await hs_classifier.classify(
        description=text,
        image_bytes=uploaded_bytes,
        image_mime_type=uploaded_mime,
    )

    # ── Apply classification rules ──────────────────────────────────────
    rules_result = await apply_classification_rules(
        ctx=ctx,
        candidates=[c.model_dump() for c in hs_result.candidates],
        attributes=extracted_attributes,
    )

    # Handle clarifying questions
    if rules_result.get("clarifying_questions"):
        ctx.state["missing_attributes"] = rules_result["clarifying_questions"]
        ctx.state["extracted_attributes"] = extracted_attributes
        return {
            "intent": "product_description",
            "message": "Для точной классификации уточните:",
            "clarifying_questions": rules_result["clarifying_questions"],
        }

    # Build a human-readable summary from the top candidate
    candidates = rules_result.get("candidates", [])
    if candidates:
        top = candidates[0]
        parts = [f"Рекомендуемый код ТН ВЭД: {top['hs_code']}"]
        if top.get("product_name_ru"):
            parts.append(f" ({top['product_name_ru']})")
        if top.get("duty_rate_percent") is not None:
            parts.append(f". Пошлина {top['duty_rate_percent']}%")
        if top.get("is_subject_to_recycling_fee"):
            parts.append(". Требуется уплатить утильсбор ♻")
        message = "".join(parts)
    else:
        message = ""

    result = {
        "intent": "product_description",
        "message": message,
        "pipeline_results": {
            "candidates": candidates
        },
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
            chat_history = [
                ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
                for m in raw_history
            ]

        extraction = ProfileExtractor.extract(chat_history, text)
        profile = extraction.accumulated_profile
        # Smart Enhancement: Auto-lookup duty rate if HS Code is provided but duty rate is missing
        if profile.hs_code and profile.duty_rate_percent is None:
            try:
                hs_result = await hs_classifier.classify(description=profile.hs_code)
                if hs_result and hs_result.candidates:
                    best_match = hs_result.candidates[0]
                    profile.duty_rate_percent = best_match.duty_rate_percent
                    profile.is_subject_to_recycling_fee = (
                        best_match.is_subject_to_recycling_fee
                    )
                    logger.info(
                        f"Auto-populated duty rate for HS Code {profile.hs_code} using {best_match.hs_code}: {best_match.duty_rate_percent}%"
                    )
            except Exception as hs_err:
                logger.warning(
                    f"Failed to auto-lookup duty rate for HS Code {profile.hs_code}: {hs_err}"
                )
        if (
            profile.invoice_price is not None
            and profile.invoice_price > 0.0
            and profile.currency is not None
            and profile.duty_rate_percent is not None
        ):
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
                f"- НДС на импорт (16%): {res.import_vat_kzt:,.2f} KZT\n"
            )
            if is_recycling:
                msg += f"- Утильсбор: {res.recycling_fee_kzt:,.2f} KZT\n"
            msg += (
                f"\n\U0001f525 **Итого к уплате:** {res.total_payments_kzt:,.2f} KZT\n"
            )

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
                chained_fields.append(
                    f"доставка до границы {profile.transport_to_border:,.2f} KZT"
                )

            chain_warning_msg = None
            if chained_fields:
                chain_warning_msg = "Накопленные параметры: " + ", ".join(
                    chained_fields
                )

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

    wants_calc = any(
        w in text_lower
        for w in [
            "пошлин",
            "растаможк",
            "ндс",
            "платеж",
            "калькуляци",
            "сколько",
            "пошлина",
        ]
    )

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
