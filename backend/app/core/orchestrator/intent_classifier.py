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

        # Document upload keywords — check BEFORE legal since "закон" is a legal keyword too
        if any(w in text_lower for w in ["загрузи", "документ", "текст закон"]):
            return IntentClassification(
                intent=IntentType.document_upload,
                confidence=0.8,
                reasoning="Document upload keywords detected",
            )

        # Legal question keywords — check BEFORE HS and calculation since overlaps exist
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
