import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from app.core.llm.generator import get_generator
from app.core.orchestrator.models import ChatMessage

logger = logging.getLogger(__name__)


class CustomsProfileAccumulator(BaseModel):
    invoice_price: Optional[float] = Field(
        None, description="Invoice price / value of goods (числовое значение стоимости)"
    )
    currency: Optional[str] = Field(
        None,
        description="Three-letter currency code in uppercase (e.g. USD, EUR, RUB, KZT)",
    )
    transport_to_border: Optional[float] = Field(
        None,
        description="Transport cost to the RK/EAEU border in KZT (стоимость доставки до границы)",
    )
    duty_rate_percent: Optional[float] = Field(
        None,
        description="Customs duty rate in percent (ставка пошлины, например 10.0 для 10%)",
    )
    weight_kg: Optional[float] = Field(
        None, description="Gross or net weight of goods in kilograms (вес товара в кг)"
    )
    hs_code: Optional[str] = Field(
        None, description="10-digit customs HS Code / ТН ВЭД (10 цифр)"
    )
    is_subject_to_recycling_fee: Optional[bool] = Field(
        None,
        description="Whether the product is subject to recycling fee / утильсбор (true/false)",
    )


class ProfileExtractionResult(BaseModel):
    accumulated_profile: CustomsProfileAccumulator = Field(
        ...,
        description="The currently accumulated parameters after analyzing the conversation",
    )
    missing_fields: List[str] = Field(
        ...,
        description="List of required parameters that are still missing (choose from: ['invoice_price', 'currency', 'duty_rate_percent'])",
    )
    next_question: str = Field(
        ...,
        description="A polite, helpful conversational response in Russian (RU) asking the user to provide the next missing field, or summarizing the status if all are present.",
    )


class ProfileExtractor:
    """
    Stateful parameters extractor for Customs Calculation.
    Uses Gemini Structured Outputs to accumulate params over multiple conversation turns.
    """

    @classmethod
    def extract(
        cls, history: Optional[List[ChatMessage]], current_text: str
    ) -> ProfileExtractionResult:
        """
        Processes the conversation history and the current user input to extract
        and update the accumulated customs profile parameters.
        """
        # Format the conversation transcript for the LLM
        transcript_lines = []
        if history:
            for msg in history:
                role_label = "Пользователь" if msg.role == "user" else "Ассистент"
                transcript_lines.append(f"{role_label}: {msg.content}")

        # Add the current text as the latest message if it's not already at the end of the history
        transcript_lines.append(f"Пользователь: {current_text}")
        transcript = "\n".join(transcript_lines)

        prompt = f"""
Вы — опытный таможенный декларант Казахстана. Ваша задача — проанализировать стенограмму диалога и извлечь параметры, необходимые для таможенного расчёта:
1. invoice_price (стоимость товара / цена по инвойсу) — должно быть положительным числом.
2. currency (трехбуквенный код валюты, например: USD, EUR, RUB, KZT) — всегда приводите к верхнему регистру.
3. transport_to_border (стоимость доставки до границы РК/ЕАЭС в тенге, по умолчанию None) — число.
4. duty_rate_percent (ставка таможенной пошлины в процентах, например: 5.0, 12.0) — число.
5. weight_kg (вес товара в килограммах) — число.
6. hs_code (10-значный код ТН ВЭД) — строка из 10 цифр.
7. is_subject_to_recycling_fee (подлежит ли утильсбору) — логическое значение (true/false).

КРИТИЧЕСКИЕ ПРАВИЛА:
1. Накапливайте параметры из всей истории диалога. Если параметр был назван ранее, сохраните его.
2. Если пользователь изменяет или корректирует ранее названный параметр (например, говорит: "Ой, цена не 5000, а 6000" или "сделай в евро, а не долларах"), ВСЕГДА обновляйте этот параметр до самого последнего озвученного значения.
3. Обязательными параметрами (required) считаются только:
   - 'invoice_price'
   - 'currency'
   - 'duty_rate_percent'
   Остальные параметры являются дополнительными. Если обязательные параметры отсутствуют, добавьте их названия в список `missing_fields`.
4. Сформируйте вежливый и профессиональный вопрос на русском языке (`next_question`):
   - Если отсутствует 'invoice_price', спросите о стоимости товара и валюте инвойса.
   - Если отсутствует 'currency', уточните, в какой валюте (USD, EUR, тенге) указана стоимость.
   - Если отсутствует 'duty_rate_percent', спросите ставку пошлины (или предложите помочь подобрать её, если у них есть описание товара / код ТН ВЭД).
   - Если все три обязательных параметра собраны, напишите, что вы готовы провести расчёт таможенных пошлин.

Стенограмма диалога:
\"\"\"
{transcript}
\"\"\"
        """

        try:
            logger.info(
                "Calling Gemini Vertex Client for structured profile extraction"
            )
            result = get_generator().generate_structured(
                prompt=prompt, response_schema=ProfileExtractionResult
            )
            return result
        except Exception as e:
            logger.error(f"Structured profile extraction failed: {e}", exc_info=True)
            # Safe crash-free fallback
            return cls._fallback_extraction(current_text, history)

    @classmethod
    def _fallback_extraction(
        cls, text: str, history: Optional[List[ChatMessage]]
    ) -> ProfileExtractionResult:
        """
        Regex-based fallback extraction if LLM fails or is unavailable.
        """
        import re

        profile = CustomsProfileAccumulator()

        # Simple extraction from history and text
        all_messages = []
        if history:
            all_messages.extend([m.content for m in history])
        all_messages.append(text)

        # Reverse messages so we process the most recent ones first
        for msg_content in reversed(all_messages):
            # 1. Price & Currency (exclude 10-digit codes)
            if profile.invoice_price is None:
                price_matches = re.finditer(
                    r"(?:[\$\s]*)(\d+(?:\.\d+)?)(?:\s*)(USD|\$|EUR|€|RUB|руб|KZT|тг|тенге)?",
                    msg_content,
                    re.IGNORECASE,
                )
                for pm in price_matches:
                    val_str = pm.group(1)
                    if len(val_str) == 10:
                        continue

                    profile.invoice_price = float(val_str)
                    curr_symbol = pm.group(2)
                    if curr_symbol:
                        curr_symbol = curr_symbol.lower()
                        if curr_symbol in ("$", "usd"):
                            profile.currency = "USD"
                        elif curr_symbol in ("€", "eur"):
                            profile.currency = "EUR"
                        elif curr_symbol in ("руб", "rub"):
                            profile.currency = "RUB"
                        elif curr_symbol in ("тг", "тнг", "тенге", "kzt"):
                            profile.currency = "KZT"
                    else:
                        profile.currency = "USD"
                    break

            # 2. HS Code
            if profile.hs_code is None:
                hs_match = re.search(r"\b(\d{10})\b", msg_content)
                if hs_match:
                    profile.hs_code = hs_match.group(1)

            # 3. Duty Rate
            if profile.duty_rate_percent is None:
                rate_match = re.search(
                    r"пошлин[аы]\s*(\d+(?:\.\d+)?)%", msg_content, re.IGNORECASE
                )
                if rate_match:
                    profile.duty_rate_percent = float(rate_match.group(1))

            # 4. Recycling
            if profile.is_subject_to_recycling_fee is None:
                if "утильсбор" in msg_content.lower() or "♻" in msg_content:
                    profile.is_subject_to_recycling_fee = True

        # Check what is missing
        missing = []
        if profile.invoice_price is None:
            missing.append("invoice_price")
        if profile.currency is None:
            missing.append("currency")
        if profile.duty_rate_percent is None:
            missing.append("duty_rate_percent")

        # Determine next question
        if "invoice_price" in missing:
            q = "Пожалуйста, укажите стоимость вашего товара и валюту инвойса (например, 5000 USD)."
        elif "currency" in missing:
            q = "Уточните, пожалуйста, валюту инвойса (например, USD, EUR или KZT)."
        elif "duty_rate_percent" in missing:
            q = "Какая ставка таможенной пошлины (%) применяется к вашему товару?"
        else:
            q = "Все обязательные параметры собраны. Выполняю расчёт."

        return ProfileExtractionResult(
            accumulated_profile=profile, missing_fields=missing, next_question=q
        )
