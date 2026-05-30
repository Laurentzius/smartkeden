import logging

from langfuse import observe
from app.core.config import settings
from app.core.llm.generator import get_generator
from app.core.orchestrator.models import IntentType, IntentClassification


logger = logging.getLogger(__name__)


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
        system_prompt = config.get(
            "system_prompt",
            "Classify the user's customs-related message into exactly one intent.",
        )

        examples_str = "\n".join(f'- "{q}" → {i}' for q, i in examples)

        prompt = (
            f"{system_prompt}\n\n"
            f"Examples:\n{examples_str}\n\n"
            f'User message: "{text}"\n\n'
            f"Respond with intent, confidence (0.0-1.0), and brief reasoning."
        )

        try:
            result: IntentClassification = get_generator().generate_structured(
                prompt=prompt,
                response_schema=IntentClassification,
            )
            # If Gemini returns unclear, try keyword fallback first
            if result.intent == IntentType.unclear:
                fallback = cls._fallback_classify(text)
                if fallback.intent != IntentType.unclear:
                    logger.info(
                        f"Gemini returned unclear, overridden by keyword fallback: {fallback.intent}"
                    )
                    result = fallback

            # If confidence is too low, downgrade to unclear
            if result.confidence < 0.7:
                result.intent = IntentType.unclear

            if settings.LANGFUSE_ENABLED:
                try:
                    from langfuse import get_client

                    get_client().update_current_span(
                        output={
                            "intent": result.intent.value,
                            "confidence": result.confidence,
                        }
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
        if any(
            w in text_lower
            for w in ["привет", "здравствуйте", "здрасте", "добр", "hi", "hello", "сәлем", "салам", "аман", "қош"]
        ):
            return IntentClassification(
                intent=IntentType.greeting,
                confidence=0.9,
                reasoning="Greeting keywords detected",
            )

        # Document upload keywords — only actual upload/ingest commands
        if any(w in text_lower for w in ["загрузи", "загрузить", "загрузк", "текст закон"]):
            return IntentClassification(
                intent=IntentType.document_upload,
                confidence=0.8,
                reasoning="Document upload keywords detected",
            )

        # ── Case-specific customs clearance guidance ──────────────────────
        # Detect when a user asks about specific goods in an import/clearance
        # context (vs. abstract legal rate/article questions).
        case_specific_goods = any(
            w in text_lower
            for w in [
                # product names that signal a real shipment
                "ноутбук", "телефон", "авто", "машин", "одежд", "обувь",
                "игрушк", "мебел", "техник", "запчаст", "продукт",
                "телевизор", "компьютер", "планшет", "велосипед",
                "косметик", "хими", "стройматериал", "инструмент",
                "оборудовани", "станок", "сыр", "ткань",
            ]
        )
        case_specific_context = any(
            w in text_lower
            for w in [
                "растаможк", "растаможить", "оформить", "ввоз",
                "импорт", "доставк", "заказал", "купил", "привез",
                "отправить", "посылк", "груз", "контейнер",
                "деклараци", "декларирова",
            ]
        )
        if case_specific_goods and case_specific_context:
            return IntentClassification(
                intent=IntentType.customs_guidance,
                confidence=0.82,
                reasoning="Case-specific customs clearance query detected (goods + import context)",
            )

        # Also detect case-specific queries with explicit values/currencies
        has_value_currency = any(
            w in text_lower for w in ["доллар", "евро", "юан", "рубл", "тенге", "$", "€", "₽", "¥"]
        )
        if has_value_currency and case_specific_context:
            return IntentClassification(
                intent=IntentType.customs_guidance,
                confidence=0.78,
                reasoning="Case-specific customs query with currency/value context",
            )

        # Restrictions/documents questions about specific goods categories
        goods_categories = any(
            w in text_lower
            for w in [
                "игрушк", "продукт", "медицин", "лекарств", "хими",
                "драгоцен", "ювелир", "оруж", "алкогол", "табак",
                "животн", "растен", "электроник",
            ]
        )
        restriction_context = any(
            w in text_lower
            for w in ["ограничени", "запрет", "лицензи", "разрешени", "сертификат",
                       "квот", "фитосанитар", "ветеринар"]
        )
        if goods_categories and restriction_context:
            return IntentClassification(
                intent=IntentType.customs_guidance,
                confidence=0.80,
                reasoning="Case-specific restriction/document query about goods category",
            )

        # Legal question keywords — check AFTER customs_guidance but BEFORE HS and calculation
        if any(w in text_lower for w in ["ставк", "закон", "кодекс", "статья", "норм", "процедур", "режим", "декларировани"]):
            return IntentClassification(
                intent=IntentType.question_about_law,
                confidence=0.75,
                reasoning="Legal question keywords detected",
            )

        # Calculation keywords
        if any(
            w in text_lower
            for w in ["пошлин", "растаможк", "ндс", "платеж", "калькуляци", "посчитай", "рассчитай"]
        ):
            return IntentClassification(
                intent=IntentType.calculation_request,
                confidence=0.8,
                reasoning="Calculation keywords detected",
            )

        # HS code classification keywords — "товар" deliberately excluded (too generic)
        if any(
            w in text_lower for w in ["тн вэд", "hs ", "код", "классифициру"]
        ):
            return IntentClassification(
                intent=IntentType.product_description,
                confidence=0.8,
                reasoning="HS code keywords detected",
            )
        return IntentClassification(
            intent=IntentType.unclear, confidence=0.5, reasoning="No matching keywords"
        )
