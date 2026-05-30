import logging

from app.core.orchestrator.models import IntentType, OrchestrateResponse, ChatMessage, IntentClassification
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


def _is_case_specific_customs_query(text_lower: str) -> bool:
    """Detect case-specific customs clearance queries that need agentic guidance.

    Returns True when the query mentions specific goods AND has
    import/clearance/payment/document/restriction context that goes
    beyond a plain legal FAQ question.
    """
    # ── Exclusion: pure HS classification queries ──────────────────────
    # If the query is clearly asking for HS code classification, let that
    # intent take priority even if goods and import context are present.
    pure_classification = any(
        w in text_lower for w in ["тн вэд", "hs ", "код тн", "классифицир", "определи код"]
    )
    if pure_classification:
        return False

    # Specific goods/product mentions
    goods_keywords = [
        "ноутбук", "телефон", "авто", "машин", "одежд", "обувь",
        "игрушк", "мебел", "техник", "запчаст", "продукт",
        "телевизор", "компьютер", "планшет", "велосипед",
        "косметик", "хими", "стройматериал", "инструмент",
        "оборудовани", "станок", "сыр", "ткань", "шин",
        "аккумулятор", "батарейк", "кабель", "провод",
        "игруше", "консерв", "молочн", "мяс", "рыб",
        "алкогол", "табак", "сигарет", "лекарств", "медицин",
        "цвет", "растени", "животн", "драгоцен", "ювелир",
        "оруж", "взрывчат", "нефтепродукт", "топлив",
    ]
    has_goods = any(w in text_lower for w in goods_keywords)

    # Customs clearance context beyond abstract rate questions
    clearance_context = [
        "растаможк", "растаможить", "оформить", "ввоз",
        "импорт", "доставк", "заказал", "купил", "привез",
        "отправить", "посылк", "груз", "контейнер",
        "деклараци", "декларирова",
    ]
    has_clearance = any(w in text_lower for w in clearance_context)

    # Document/restriction/calculation context
    doc_restriction_context = [
        "документ", "сертификат", "лицензи", "разрешени",
        "ограничени", "запрет", "квот",
    ]
    has_doc_restriction = any(w in text_lower for w in doc_restriction_context)

    # Currency/value mentions that indicate a real transaction
    currency_mentions = ["доллар", "евро", "юан", "рубл", "$", "€", "₽", "¥"]
    has_currency = any(w in text_lower for w in currency_mentions)

    # Must have goods AND at least one context signal
    if has_goods and (has_clearance or has_doc_restriction or has_currency):
        return True

    # Also detect critical goods categories in restriction context
    critical_goods = [
        "игрушк", "продукт", "медицин", "лекарств", "хими",
        "драгоцен", "ювелир", "оруж", "алкогол", "табак",
        "животн", "растен", "электроник",
    ]
    has_critical = any(w in text_lower for w in critical_goods)
    if has_critical and (has_clearance or has_doc_restriction):
        return True

    return False


 # ── Questionnaire marker used to detect pending questionnaire in history ──
_QUESTIONNAIRE_MARKER = "Для точной классификации уточните следующие данные:"

def _detect_pending_questionnaire(history: list) -> tuple:
    """Check if history indicates a pending classification questionnaire.

    Returns (is_pending: bool, original_product_text: str | None).
    """
    if not history:
        return False, None

    # A questionnaire is pending only when the latest assistant message is
    # the questionnaire. If a later assistant answer exists, the prior
    # questionnaire has already been resolved and must not hijack new intents.
    latest_assistant_idx = None
    for i in range(len(history) - 1, -1, -1):
        msg = history[i]
        role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
        if role == "assistant":
            latest_assistant_idx = i
            break

    if latest_assistant_idx is None:
        return False, None

    latest = history[latest_assistant_idx]
    content = (
        latest.get("content", "")
        if isinstance(latest, dict)
        else getattr(latest, "content", "")
    )
    if _QUESTIONNAIRE_MARKER not in content:
        return False, None

    # Found a pending questionnaire. Recover the most recent user message
    # before it as the original product description.
    for j in range(latest_assistant_idx - 1, -1, -1):
        prev = history[j]
        prev_role = (
            prev.get("role", "") if isinstance(prev, dict) else getattr(prev, "role", "")
        )
        prev_content = (
            prev.get("content", "")
            if isinstance(prev, dict)
            else getattr(prev, "content", "")
        )
        if prev_role == "user":
            return True, prev_content
    return True, None


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

    # ── Case-specific customs guidance detection (before FAQ) ───────
    # When the query mentions specific goods in an import/clearance context,
    # route to agentic customs guidance even if a broad FAQ keyword matches.
    if _is_case_specific_customs_query(text_lower):
        classification = IntentClassification(
            intent=IntentType.customs_guidance,
            confidence=0.85,
            reasoning="Case-specific customs clearance query detected",
        )
        ctx.state["intent"] = classification.intent.value
        ctx.state["confidence"] = classification.confidence
        ctx.state["reasoning"] = classification.reasoning
        ctx.route = "customs_guidance"
        return classification.model_dump()

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
    # ── Pending questionnaire continuation via history ──────────────
    # When the session is recreated per HTTP request, ADK state is lost.
    # Detect a pending questionnaire from chat history so continuation
    # messages (answers) still reach hs_classifier_node.
    is_pending_q, original_product_text = _detect_pending_questionnaire(
        ctx.state.get("history", [])
    )
    if is_pending_q:
        ctx.state["intent"] = "product_description"
        ctx.state["confidence"] = 0.9
        ctx.state["pending_classification"] = True
        if original_product_text:
            ctx.state["original_product_text"] = original_product_text
        ctx.route = "product_description"
        return {
            "intent": "product_description",
            "message": "",
        }

    # ── Normal intent classification ───────────────────────────────
    classification = await IntentClassifier.classify(text)
    ctx.state["intent"] = classification.intent.value
    ctx.state["confidence"] = classification.confidence
    ctx.state["reasoning"] = classification.reasoning

    ctx.route = classification.intent.value

    # Clear pending questionnaire when user switches away from classification
    if classification.intent != IntentType.product_description:
        ctx.state["pending_classification"] = None
        ctx.state["questionnaire_attributes"] = None
        ctx.state["missing_questionnaire_fields"] = None

    return classification.model_dump()


@node(rerun_on_resume=True)
async def greeting_node(ctx, node_input):
    """Handle greeting intent."""
    return {
        "intent": "greeting",
        "message": (
            "👋 Сәлеметсіз бе! / Здравствуйте!\n\n"
            "Мен — Кеден Көмекшісі (CustomAI Kazakhstan).\n\n"
            "Көмектесе аламын:\n"
            "• **Заңнама бойынша кеңес** — ЕАЭО ТК, ҚР Салық кодексі\n"
            "• **Тауарды жіктеу** — ТН ВЭД кодын таңдау\n"
            "• **Кедендік төлемдерді есептеу** — баж, ҚҚС, акциз, утильалым\n\n"
            "Я могу помочь:\n"
            "• **Консультация по законодательству** — ТК ЕАЭС, Налоговый кодекс РК\n"
            "• **Классификация товаров** — подбор кода ТН ВЭД\n"
            "• **Расчёт таможенных платежей** — пошлины, НДС, акцизы, утильсбор\n\n"
            "Сұрағыңызды жазыңыз / Напишите ваш вопрос."
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
    """Handle product_description intent using HSCodeClassifier + Classification Rules.

    Gate: requires mandatory pre-classification questionnaire fields before
    calling hs_classifier.classify().  Underspecified product descriptions
    receive a numbered questionnaire; answers are merged across turns.
    """
    text = ctx.state.get("user_text", "")
    uploaded_bytes = ctx.state.get("uploaded_file_bytes")
    uploaded_mime = ctx.state.get("uploaded_file_mime", "image/jpeg")

    # ── Attribute extraction ────────────────────────────────────────────
    from app.core.classification.attribute_extractor import AttributeExtractor
    from app.core.classification.questionnaire import (
        is_questionnaire_complete,
        missing_questionnaire_fields,
        build_questionnaire_message,
        parse_questionnaire_answer,
    )
    from app.core.orchestrator.adk_tools import apply_classification_rules

    attribute_extractor = AttributeExtractor()

    # ── Resume: existing RulesEngine clarifying-questions path ──────────
    if "missing_attributes" in ctx.state and ctx.state.get("missing_attributes") and "user_answers" in ctx.state and ctx.state.get("user_answers"):
        extracted_attributes = ctx.state.get("extracted_attributes", {})
        extracted_attributes.update(ctx.state["user_answers"])
        ctx.state["missing_attributes"] = None
        ctx.state["user_answers"] = None
    elif ctx.state.get("pending_classification"):
        # ── Resume: questionnaire continuation ──────────────────────────
        existing_attrs = ctx.state.get("questionnaire_attributes", {})

        # Cross-session recovery: when the session is recreated per HTTP
        # request, questionnaire_attributes is lost. Re-extract base attrs
        # from the original product text stored in ctx.state, then merge
        # the current answer text on top.
        if not existing_attrs:
            original_text = ctx.state.get("original_product_text", "")
            if original_text:
                existing_attrs = await attribute_extractor.extract_attributes(
                    description=original_text,
                )

        merged = parse_questionnaire_answer(text, existing_attrs)
        ctx.state["questionnaire_attributes"] = merged
        if is_questionnaire_complete(merged):
            # All required fields collected → proceed to classification
            ctx.state["pending_classification"] = False
            ctx.state["questionnaire_result"] = None
            extracted_attributes = merged
        else:
            # Still incomplete → ask remaining questions only
            missing = missing_questionnaire_fields(merged)
            ctx.state["missing_questionnaire_fields"] = missing
            result = {
                "intent": "product_description",
                "message": build_questionnaire_message(missing),
                "pipeline_results": {
                    "questionnaire": {
                        "missing_fields": missing,
                        "pending": True,
                    }
                },
            }
            ctx.state["questionnaire_result"] = result
            return result
    else:
        # ── First run: extract attributes from description and image ─────
        extracted_attributes = await attribute_extractor.extract_attributes(
            description=text,
            image_bytes=uploaded_bytes,
        )

        # ── Questionnaire gate ──────────────────────────────────────────
        if not is_questionnaire_complete(extracted_attributes):
            missing = missing_questionnaire_fields(extracted_attributes)
            ctx.state["questionnaire_attributes"] = extracted_attributes
            ctx.state["missing_questionnaire_fields"] = missing
            ctx.state["pending_classification"] = True
            # Save original product text for later enriched description
            if not ctx.state.get("original_product_text"):
                ctx.state["original_product_text"] = text
            result = {
                "intent": "product_description",
                "message": build_questionnaire_message(missing),
                "pipeline_results": {
                    "questionnaire": {
                        "missing_fields": missing,
                        "pending": True,
                    }
                },
            }
            ctx.state["questionnaire_result"] = result
            return result

    # ── Build enriched description ──────────────────────────────────────
    # Prefer original_product_text (e.g. "телефон") over the current
    # answer text so the HS classifier sees the actual product, not just
    # the questionnaire attributes.
    product_text = ctx.state.get("original_product_text", text)
    enriched_description = _build_enriched_description(product_text, extracted_attributes)

    # ── HS Classification ───────────────────────────────────────────────
    hs_result = await hs_classifier.classify(
        description=enriched_description,
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


def _build_enriched_description(
    original_text: str,
    attributes: dict,
) -> str:
    """Build an enriched classification query from original text + structured attrs.

    Appends key questionnaire fields as a structured suffix so the HS classifier
    receives both the original user description and the resolved attributes.
    """
    parts = [original_text.strip()] if original_text.strip() else []

    field_labels = {
        "is_kit": "Комплектность",
        "product_purpose": "Назначение",
        "material_composition": "Материал/состав",
        "technical_specs": "Тех. характеристики",
        "country_of_origin": "Страна происхождения",
        "customs_regime": "Таможенный режим",
        "jurisdiction": "Юрисдикция",
    }

    attr_parts: list[str] = []
    for field, label in field_labels.items():
        value = attributes.get(field)
        if value is not None and str(value).strip():
            attr_parts.append(f"{label}: {value}")

    if attr_parts:
        parts.append("Атрибуты товара: " + "; ".join(attr_parts))

    return " ".join(parts) if parts else original_text


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

    # If questionnaire is pending, return the questionnaire result
    qr = ctx.state.get("questionnaire_result")
    if qr:
        return qr

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
#  Agentic RAG Customs Guidance node + helpers
#  (Section 4–8 of agentic_rag_customs_clearance_flow.md)
# ════════════════════════════════════════════════════════════════════════

import re as _re

# ── Critical goods categories that escalate to CRITICAL risk ──────────
_CRITICAL_GOODS_PATTERNS: list[tuple[str, str]] = [
    ("игрушк|игруше|детск|ребен|ребён", "children_goods"),
    ("продукт|пищев|консерв|молочн|мяс|рыб|алкогол|табак|сигарет|напит", "food"),
    ("медицин|лекарств|фармацевти|медоборудован|хирурги", "medicine"),
    ("хими|химикат|реактив|удобрен|пестицид", "chemicals"),
    ("оруж|взрывчат|боеприпас|патрон", "weapons"),
    ("животн|звер|птиц|скот|рыб", "animals"),
    ("растени|цвет|семян|саженц|древесин|лесоматериал", "plants"),
    ("драгоцен|ювелир|золот|серебр|платин|бриллиант|алмаз", "precious_metals"),
    ("нефтепродукт|топлив|бензин|дизел|мазут|нефт", "petroleum"),
]


def _classify_risk(text_lower: str, hs_candidates: list[dict]) -> str:
    """Compute risk level from text keywords and HS candidates."""
    for pattern, category in _CRITICAL_GOODS_PATTERNS:
        if _re.search(pattern, text_lower):
            return "CRITICAL"
    # If HS candidates suggest high-risk chapters (e.g. 01-05 animals, 06-15 plants/food, 28-38 chemicals, 71 precious, 93 arms)
    high_risk_chapters = {"01", "02", "03", "04", "05", "06", "07", "08", "09", "10",
                          "11", "12", "13", "14", "15", "16", "17", "18", "19", "20",
                          "21", "22", "28", "29", "30", "31", "32", "33", "34", "35",
                          "36", "37", "38", "71", "93"}
    for c in hs_candidates:
        code = str(c.get("hs_code", ""))
        chapter = code[:2] if len(code) >= 2 else ""
        if chapter in high_risk_chapters:
            return "HIGH"
    return "LOW"


def _extract_customs_facts(text: str) -> dict:
    """Deterministic regex/simple-parsing extraction of shipment facts.

    Returns a flat dict of extracted facts with None for missing fields.
    """
    text_lower = text.lower()
    facts: dict = {
        "product_description": None,
        "hs_code": None,
        "customs_value": None,
        "currency": None,
        "country_of_origin": None,
        "country_of_export": None,
        "quantity": None,
        "weight_kg": None,
        "incoterms": None,
        "procedure_code": None,
    }

    # ── HS code: 4-10 digit numeric code ─────────────────────────────
    hs_match = _re.search(r"\b(\d{4,10})\b", text)
    if hs_match:
        code = hs_match.group(1)
        # Avoid catching years (2020-2030), prices, phone numbers
        if not (2020 <= int(code) <= 2030) and len(code) >= 6:
            facts["hs_code"] = code

    # ── Customs value: numbers with typical value indicators ─────────
    value_patterns = [
        r"(\d[\d\s]*)\s*(?:доллар|долл|usd|\$)",
        r"(\d[\d\s]*)\s*(?:евро|eur|€)",
        r"(\d[\d\s]*)\s*(?:юан|юан|cny|¥)",
        r"(\d[\d\s]*)\s*(?:рубл|rub|₽)",
        r"(\d[\d\s]*)\s*(?:тенге|kzt|₸)",
        r"(?:стоимость|цена|сумм|ценой|стоимост)\D+(\d[\d\s]*)",
        r"(?:на сумму|за)\s+(\d[\d\s]*)",
        r"(\d[\d\s]*)\s*(?:доллар|долл|usd|\$|евро|eur|€|юан|cny|¥|рубл|rub|₽|тенге|kzt|₸)",
    ]
    for pat in value_patterns:
        m = _re.search(pat, text_lower)
        if m:
            raw = m.group(1).replace(" ", "")
            try:
                facts["customs_value"] = float(raw)
            except ValueError:
                pass
            break

    # ── Currency ─────────────────────────────────────────────────────
    # ── Currency ─────────────────────────────────────────────────────
    currency_map = [
        (r"(?:доллар|долл|usd|\$)", "USD"),
        (r"(?:евро|eur|€)", "EUR"),
        (r"(?:юан|cny|¥)", "CNY"),
        (r"(?:рубл|rub|₽)", "RUB"),
        (r"(?:тенге|kzt|₸)", "KZT"),
    ]
    for pat, cur in currency_map:
        if _re.search(pat, text_lower):
            facts["currency"] = cur
            break
    # ── Country of origin/export ─────────────────────────────────────
    country_patterns = [
        (r"\b(?:из|с|от)\s+(кита[яй]|китай|китая|china)", "CN"),
        (r"\b(?:из|с|от)\s+(германи[иией]|германия|germany)", "DE"),
        (r"\b(?:из|с|от)\s+(турци[иией]|турция|turkey)", "TR"),
        (r"\b(?:из|с|от)\s+(оаэ|эмират|uae|dubai|дуба)", "AE"),
        (r"\b(?:из|с|от)\s+(росси[иией]|россия|russia|рф)", "RU"),
        (r"\b(?:из|с|от)\s+(сша|америк|usa|america)", "US"),
        (r"\b(?:из|с|от)\s+(япони[иией]|япония|japan)", "JP"),
        (r"\b(?:из|с|от)\s+(коре[иией]|корея|korea)", "KR"),
        (r"\b(?:из|с|от)\s+(польш[иие]|польша|poland)", "PL"),
        (r"\b(?:из|с|от)\s+(узбекистан|uzbekistan)", "UZ"),
        (r"\b(?:из|с|от)\s+(кыргызстан|киргиз|kyrgyzstan)", "KG"),
    ]
    for pat, code in country_patterns:
        if _re.search(pat, text_lower):
            facts["country_of_export"] = code
            break

    # ── Weight ───────────────────────────────────────────────────────
    wt_match = _re.search(r"(\d+(?:\.\d+)?)\s*(?:кг|kg|килограм)", text_lower)
    if wt_match:
        try:
            facts["weight_kg"] = float(wt_match.group(1))
        except ValueError:
            pass

    # ── Quantity ─────────────────────────────────────────────────────
    qty_match = _re.search(r"(\d+)\s*(?:шт|штук|единиц|ед\.?|item)", text_lower)
    if qty_match:
        try:
            facts["quantity"] = float(qty_match.group(1))
        except ValueError:
            pass

    # ── Incoterms ────────────────────────────────────────────────────
    incoterms_pat = r"\b(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP)\b"
    inc_match = _re.search(incoterms_pat, text.upper())
    if inc_match:
        facts["incoterms"] = inc_match.group(1)

    return facts


def _determine_requested_modes(text_lower: str) -> list:
    """Infer which guidance modes the user is requesting."""
    modes = []
    if any(w in text_lower for w in ["классифицир", "тн вэд", "hs ", "код т", "определи код"]):
        modes.append("classify_goods")
    if any(w in text_lower for w in ["пошлин", "растаможк", "ндс", "платеж",
                                       "калькуляци", "посчитай", "рассчитай",
                                       "сколько будет", "стоит", "стоимост"]):
        modes.append("calculate_payments")
    if any(w in text_lower for w in ["документ", "сертификат", "деклараци"]):
        modes.append("generate_document_checklist")
    if any(w in text_lower for w in ["ограничени", "запрет", "лицензи", "разрешени",
                                       "квот", "фитосанитар", "ветеринар", "сертификат"]):
        modes.append("check_restrictions")
    if any(w in text_lower for w in ["астана", "astana", "декларировани"]):
        modes.append("astana1_guidance")
    if not modes:
        modes.append("answer_from_law")
    return modes


def _identify_missing_fields(facts: dict, modes: list) -> list[str]:
    """Return list of missing critical field names needed by requested modes."""
    missing = []
    if "classify_goods" in modes:
        if not facts.get("product_description") and not facts.get("hs_code"):
            missing.append("product_description")
    if "calculate_payments" in modes:
        if facts.get("customs_value") is None:
            missing.append("customs_value")
        if not facts.get("currency"):
            missing.append("currency")
        if not facts.get("hs_code"):
            missing.append("hs_code_or_rate")
    if "check_restrictions" in modes:
        if not facts.get("hs_code") and not facts.get("product_description"):
            missing.append("hs_code_or_product_description")
    if "generate_document_checklist" in modes:
        if not facts.get("procedure_code") and not facts.get("country_of_export"):
            missing.append("procedure_or_country")
    return missing


def _assemble_guidance_payload(
    intent: str,
    text: str,
    facts: dict,
    modes: list,
    missing: list[str],
    hs_result: dict | None,
    calc_result: dict | None,
    rag_sources: list[dict] | None,
    risk_level: str,
) -> dict:
    """Build the customs_guidance JSON payload for pipeline_results."""
    from app.core.orchestrator.models import (
        GuidanceSource,
        GuidanceDocumentItem,
        GuidanceRestrictionItem,
        GuidancePaymentEstimate,
        CustomsGuidancePayload,
    )

    # Build sources
    sources: list[GuidanceSource] = []
    if rag_sources:
        for s in rag_sources:
            sources.append(GuidanceSource(
                source_type=s.get("source_type", "rag"),
                citation=s.get("citation", s.get("article_number", "")),
                snippet=s.get("snippet", s.get("content", "")),
            ))

    # Build payment estimate
    payment: GuidancePaymentEstimate | None = None
    assumptions: list[str] = []
    if calc_result:
        payment = GuidancePaymentEstimate(**calc_result)
    elif "calculate_payments" in modes and missing:
        pass  # Leave None, blocked by guardrail

    # Build HS candidates
    candidates: list[dict] = []
    if hs_result:
        for c in hs_result.get("candidates", []):
            candidates.append({
                "hs_code": c.get("hs_code", ""),
                "product_name_ru": c.get("product_name_ru", ""),
                "duty_rate_percent": c.get("duty_rate_percent"),
                "confidence": c.get("confidence_score"),
            })

    # Build document checklist (basic)
    docs: list[GuidanceDocumentItem] = []
    if "generate_document_checklist" in modes:
        docs.append(GuidanceDocumentItem(
            name="Таможенная декларация (ГТД)",
            required=True,
        ))
        docs.append(GuidanceDocumentItem(
            name="Инвойс (счет-фактура)",
            required=True,
        ))
        if facts.get("country_of_export"):
            docs.append(GuidanceDocumentItem(
                name="Сертификат происхождения",
                required=True,
                based_on=facts["country_of_export"],
            ))

    # Build restrictions
    restrictions: list[GuidanceRestrictionItem] = []
    if "check_restrictions" in modes:
        # Never state "no restriction" without sources
        # Only report restrictions when we can actually verify
        pass  # v1: restrictions require sources we may not have; mark as unverified

    needs_review = risk_level in ("CRITICAL", "HIGH") or bool(missing)
    confidence = "low" if missing else ("medium" if risk_level == "HIGH" else "high")

    critic_warnings: list[str] = []
    if risk_level == "CRITICAL":
        critic_warnings.append("Критическая категория товара: требуется обязательная проверка специалистом.")
    if "calculate_payments" in modes and not payment:
        critic_warnings.append("Расчет платежей невозможен: не хватает данных (стоимость, валюта, курс, ставка).")
    if "classify_goods" in modes and not candidates:
        critic_warnings.append("Классификация не выполнена: недостаточно атрибутов товара для точного определения кода ТН ВЭД.")
    if "check_restrictions" in modes and not restrictions:
        critic_warnings.append("Проверка ограничений не выполнена: отсутствуют верифицированные источники для заявляемой категории товара.")

    payload = CustomsGuidancePayload(
        answer_type="customs_import_guidance",
        confidence=confidence,
        risk_level=risk_level,
        needs_human_review=needs_review,
        missing_fields=missing,
        candidate_hs_codes=candidates,
        estimated_payments=payment,
        required_documents=docs,
        possible_restrictions=restrictions,
        assumptions=assumptions,
        sources=sources,
        critic_warnings=critic_warnings,
    )
    return payload.model_dump()


@node(rerun_on_resume=True)
async def customs_guidance_node(ctx, node_input):
    """Agentic RAG customs guidance: intake → guardrails → tools → critic → payload.

    Thin orchestrator over existing deterministic services. Never invents
    HS codes, rates, payment totals, or restriction clearance without sources.
    """
    text = ctx.state.get("user_text", "")
    if not text:
        return {
            "intent": "customs_guidance",
            "message": "Пожалуйста, опишите ваш запрос по таможенному оформлению.",
            "pipeline_results": {"customs_guidance": {"needs_human_review": False, "missing_fields": ["user_text"]}},
        }

    text_lower = text.lower()
    history = ctx.state.get("history", [])

    # ── Step 1: Intake — extract facts deterministically ─────────────
    facts = _extract_customs_facts(text)

    # Try to get product description from text when not explicit
    if not facts["product_description"]:
        # Use the full text as the product description for classification
        facts["product_description"] = text

    # ── Step 2: Mode selection ───────────────────────────────────────
    modes = _determine_requested_modes(text_lower)
    missing = _identify_missing_fields(facts, modes)

    # ── Step 3: Risk classification ──────────────────────────────────
    risk_level = _classify_risk(text_lower, [])

    # ── Step 4: Invoke deterministic services only where safe ────────
    hs_result: dict | None = None
    calc_result: dict | None = None
    rag_sources: list[dict] | None = None

    # HS classification: only when classify_goods mode + enough info
    if "classify_goods" in modes and not missing:
        try:
            hs_response = await hs_classifier.classify(description=text)
            if hs_response and hs_response.candidates:
                hs_result = {
                    "candidates": [
                        {
                            "hs_code": c.hs_code,
                            "product_name_ru": c.product_name_ru,
                            "duty_rate_percent": c.duty_rate_percent,
                            "confidence_score": c.confidence_score,
                            "is_subject_to_recycling_fee": c.is_subject_to_recycling_fee,
                        }
                        for c in hs_response.candidates
                    ]
                }
                # Re-compute risk with actual HS codes
                risk_level = _classify_risk(text_lower, hs_result["candidates"])
        except Exception as exc:
            logger.warning(f"HS classification in customs_guidance failed: {exc}")

    # Calculation: only when calculate_payments mode + all required fields and a sourced duty rate are present.
    if "calculate_payments" in modes and not any(
        field in missing for field in ("customs_value", "currency", "hs_code_or_rate")
    ):
        try:
            duty_rate: float | None = None
            if hs_result and hs_result.get("candidates"):
                top = hs_result["candidates"][0]
                if top.get("duty_rate_percent") is not None:
                    duty_rate = float(top["duty_rate_percent"])

            if duty_rate is None:
                missing.append("duty_rate")
            else:
                calc_req = CalculationRequest(
                    invoice_price=facts["customs_value"],
                    currency=facts["currency"],
                    duty_rate_percent=duty_rate,
                    transport_to_border=0.0,
                )
                res = CustomsCalculator.calculate(calc_req)
                calc_result = {
                    "customs_value_kzt": res.customs_value_kzt,
                    "customs_fee_kzt": res.customs_fee_kzt,
                    "customs_duty_kzt": res.customs_duty_kzt,
                    "vat_base_kzt": res.vat_base_kzt,
                    "import_vat_kzt": res.import_vat_kzt,
                    "recycling_fee_kzt": res.recycling_fee_kzt,
                    "total_payments_kzt": res.total_payments_kzt,
                    "formula": "customs_value_kzt * sourced_duty_rate% + customs_fee + (vat_base * VAT rate)",
                    "assumptions": [f"Ставка пошлины получена из кандидата классификации: {duty_rate}%"],
                }
        except Exception as exc:
            logger.warning(f"Calculation in customs_guidance failed: {exc}")
            missing.append("calculation_error")

    # RAG: query for legal/procedure context
    if modes:
        try:
            history_dicts = [
                {"role": m.get("role", "user"), "content": m.get("content", "")}
                for m in history
            ] if history else []
            rag_result = await legal_rag_service.query_legal_base(text, history=history_dicts)
            if rag_result and rag_result.supporting_laws:
                rag_sources = [
                    {
                        "source_type": "rag",
                        "citation": law.article_number or "",
                        "snippet": law.content or "",
                    }
                    for law in rag_result.supporting_laws
                ]
        except Exception as exc:
            logger.warning(f"RAG query in customs_guidance failed: {exc}")

    # ── Step 5: Assemble payload ─────────────────────────────────────
    guidance_payload = _assemble_guidance_payload(
        intent="customs_guidance",
        text=text,
        facts=facts,
        modes=modes,
        missing=missing,
        hs_result=hs_result,
        calc_result=calc_result,
        rag_sources=rag_sources,
        risk_level=risk_level,
    )

    # ── Step 6: Build human-readable response ────────────────────────
    message_parts: list[str] = []
    if guidance_payload.get("candidate_hs_codes"):
        top_code = guidance_payload["candidate_hs_codes"][0]
        message_parts.append(f"Предварительный код ТН ВЭД: {top_code['hs_code']} ({top_code.get('product_name_ru', '')})")
    if guidance_payload.get("estimated_payments"):
        ep = guidance_payload["estimated_payments"]
        message_parts.append(f"Расчёт платежей: итого ~{ep.get('total_payments_kzt', 0):,.0f} KZT")
    if guidance_payload.get("missing_fields"):
        message_parts.append(f"Необходимо уточнить: {', '.join(guidance_payload['missing_fields'])}")
    if guidance_payload.get("critic_warnings"):
        for w in guidance_payload["critic_warnings"][:3]:
            message_parts.append(f"Предупреждение: {w}")
    if guidance_payload.get("needs_human_review"):
        message_parts.append("Требуется проверка таможенным специалистом.")

    if not message_parts:
        message_parts.append("Запрос по таможенному оформлению обработан. Уточните детали для более точного ответа.")

    message = "\n\n".join(message_parts)

    try:
        from app.core.admin.audit_logger import AuditLogger

        AuditLogger.log(
            action="agentic_rag_guidance",
            entity_type="orchestrator",
            entity_id=ctx.state.get("session_id", ""),
            actor="system",
            changes={
                "user_query": text,
                "extracted_facts": facts,
                "guidance_modes": modes,
                "tools_called": {
                    "hs_classifier": hs_result is not None,
                    "calculator": calc_result is not None,
                    "legal_rag": rag_sources is not None,
                },
                "sources_count": len(rag_sources or []),
                "final_answer": message,
                "confidence": guidance_payload.get("confidence"),
                "risk_level": guidance_payload.get("risk_level"),
                "needs_human_review": guidance_payload.get("needs_human_review"),
            },
        )
    except Exception as exc:
        logger.warning(f"Agentic RAG audit logging failed: {exc}")

    return {
        "intent": "customs_guidance",
        "message": message,
        "pipeline_results": {
            "customs_guidance": guidance_payload,
        },
    }