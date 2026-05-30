import re
import logging
from typing import Any, Optional

from google.genai import types as genai_types
from app.core.orchestrator.models import IntentType, OrchestrateResponse


logger = logging.getLogger(__name__)


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
                    pipeline_results={"brokers": [b.license_number for b in brokers]},
                )
            else:
                city_str = f" в городе {detected_city}" if detected_city else ""
                return OrchestrateResponse(
                    intent=IntentType.question_about_law,
                    message=f"\u274c В реестре КГД РК не найдено лицензированных таможенных брокеров{city_str}.",
                    pipeline_results={"brokers": []},
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

        brand_match = re.search(
            r"['\"\u00ab\u201c]([^'\"\u00bb\u201d]+)['\"\u00bb\u201d]", text
        )
        brand_name = brand_match.group(1) if brand_match else None
        if not brand_name:
            words = text.split()
            for w in words:
                clean_w = w.strip("'\"\u00ab\u00bb\u201c\u201d.,!?")
                if clean_w.lower() not in [
                    "зарегистрирован",
                    "ли",
                    "товарный",
                    "знак",
                    "в",
                    "реестре",
                    "троис",
                    "республики",
                    "казахстан",
                    "бренд",
                    "торговая",
                    "марка",
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
                            valid_until=None,
                        ),
                        TROISRegistry(
                            trademark_name="Samsung",
                            right_holder="Samsung Electronics Co., Ltd. (Сувон, Корея)",
                            authorized_importers="ТОО 'Samsung Electronics Central Eurasia'",
                            unauthorized_importers_action="Приостановление выпуска товаров",
                            registry_number="002/TROIS-2024",
                            valid_until=None,
                        ),
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
                        pipeline_results={"trois_record": trademark.registry_number},
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
                        pipeline_results={"trois_record": None},
                    )
            finally:
                db.close()
    except Exception as e:
        logger.error(f"TROIS interceptor failed: {e}", exc_info=True)
        return None
