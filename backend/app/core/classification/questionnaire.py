"""Pre-HS classification questionnaire — pure functions, no LLM calls.

Gates HS vector search until required customs-critical attributes are gathered.
"""

from __future__ import annotations


# ── Required fields (order matters for rendering) ─────────────────────────────

QUESTIONNAIRE_REQUIRED_FIELDS: list[str] = [
    "is_kit",
    "product_purpose",
    "material_composition",
    "technical_specs",
    "country_of_origin",
    "customs_regime",
    "jurisdiction",
]

# ── Russian-language question text ────────────────────────────────────────────

_QUESTIONNAIRE_FIELD_QUESTIONS: dict[str, str] = {
    "is_kit": (
        "1. Товар поставляется отдельно или в составе комплекта/набора? "
        "(отдельно / в составе комплекта)"
    ),
    "product_purpose": (
        "2. Основное назначение товара (для чего используется)?"
    ),
    "material_composition": (
        "3. Материал / состав товара?"
    ),
    "technical_specs": (
        "4. Технические характеристики (мощность, напряжение, производительность, "
        "габариты и т.д.)?"
    ),
    "country_of_origin": (
        "5. Страна происхождения товара?"
    ),
    "customs_regime": (
        "6. Таможенный режим (импорт / экспорт / транзит)?"
    ),
    "jurisdiction": (
        "7. Юрисдикция (ЕАЭС / ЕС / США / другая)?"
    ),
}


def is_questionnaire_complete(attrs: dict) -> bool:
    """Return True when every required questionnaire field has a non-None value."""
    return all(attrs.get(f) is not None for f in QUESTIONNAIRE_REQUIRED_FIELDS)


def missing_questionnaire_fields(attrs: dict) -> list[str]:
    """Return the list of required fields still absent from *attrs*."""
    return [f for f in QUESTIONNAIRE_REQUIRED_FIELDS if attrs.get(f) is None]


def question_for_field(field: str) -> str:
    """Return the Russian-language question for a single attribute field."""
    return _QUESTIONNAIRE_FIELD_QUESTIONS.get(
        field, f"Уточните: {field.replace('_', ' ')}?"
    )


def build_questionnaire_message(missing: list[str]) -> str:
    """Build a concise numbered questionnaire message for the user."""
    header = "Для точной классификации уточните следующие данные:\n"
    questions = "\n".join(question_for_field(f) for f in missing)
    return header + questions


# ── Conservative answer parser ────────────────────────────────────────────────

# Keyword maps for each questionnaire field (lowercase).  Order within each list
# reflects priority: earlier matches win.
_IS_KIT_POS = {"отдельно", "отдельный", "separate", "один", "single", "не комплект"}
_IS_KIT_NEG = {"комплект", "набор", "kit", "set", "в составе", "в комплекте"}

_PURPOSE_AFTER: list[str] = [
    "для", "предназначен", "назначение", "используется", "применяется",
    "цель", "purpose", "used for", "use case",
]

_MATERIAL_KEYWORDS: dict[str, str] = {
    "пластик": "пластик", "plastic": "пластик", "полипропилен": "полипропилен",
    "дерево": "дерево", "wood": "дерево",
    "металл": "металл", "metal": "металл", "сталь": "сталь", "steel": "сталь",
    "алюмин": "алюминий",
    "текстил": "текстиль", "textile": "текстиль", "ткань": "ткань", "хлопок": "хлопок",
    "резин": "резина", "rubber": "резина", "силикон": "силикон",
    "стекл": "стекло", "glass": "стекло",
    "кож": "кожа", "leather": "кожа",
    "керам": "керамика", "ceramic": "керамика",
}

_SPECS_PATTERNS: list[str] = [
    r'(\d+[\.,]?\d*\s*(в|В|v|V)\b)',         # 220V, 220В
    r'(\d+[\.,]?\d*\s*(вт|Вт|w|W|ватт|квт|кВт|kw|kW))',   # power
    r'(\d+[\.,]?\d*\s*(а|А|a|A)\b)',          # current
    r'(\d+[\.,]?\d*\s*(гц|Гц|hz|Hz|герц))',   # frequency
    r'(\d+[\.,]?\d*\s*(л/ч|л/мин|m³/h|л\\с))', # throughput
]

_REGIME_IMPORT: set[str] = {"импорт", "import", "ввоз", "ввозим"}
_REGIME_EXPORT: set[str] = {"экспорт", "export", "вывоз", "вывозим"}
_REGIME_TRANSIT: set[str] = {"транзит", "transit"}

_JURISDICTION_EAEU: set[str] = {"еаэс", "eaeu", "евразэс", "таможенный союз", "тс"}
_JURISDICTION_EU: set[str] = {"ес", "eu", "евросоюз", "европейский союз"}
_JURISDICTION_US: set[str] = {"сша", "us", "usa", "америк"}


def parse_questionnaire_answer(
    user_text: str,
    existing_attrs: dict,
) -> dict:
    """Merge free-form user answer into existing questionnaire attributes.

    Strategy: for each required field still missing, try conservative keyword
    extraction from *user_text*.  Only assign a value when a single clear match
    is found; otherwise leave the field missing so the follow-up question stays
    in the prompt.

    Returns *existing_attrs* mutably updated (caller owns the dict).
    """
    if not user_text:
        return existing_attrs

    text_lower = user_text.lower()

    missing = missing_questionnaire_fields(existing_attrs)

    # ── is_kit ───────────────────────────────────────────────────────────
    if "is_kit" in missing:
        has_pos = any(kw in text_lower for kw in _IS_KIT_POS)
        has_neg = any(kw in text_lower for kw in _IS_KIT_NEG)
        if has_pos and not has_neg:
            existing_attrs["is_kit"] = "separate"
        elif has_neg and not has_pos:
            existing_attrs["is_kit"] = "kit"

    # ── product_purpose ──────────────────────────────────────────────────
    if "product_purpose" in missing:
        for marker in _PURPOSE_AFTER:
            idx = text_lower.find(marker)
            if idx != -1:
                candidate = user_text[idx + len(marker):].strip(" ,.-:;")
                # Take first sentence or up to ~120 chars
                candidate = candidate.split(".")[0].strip()
                if 3 <= len(candidate) <= 200:
                    existing_attrs["product_purpose"] = candidate
                    break

    # ── material_composition ─────────────────────────────────────────────
    if "material_composition" in missing:
        found: list[str] = []
        for key, name in _MATERIAL_KEYWORDS.items():
            if key in text_lower:
                if name not in found:
                    found.append(name)
        if found:
            existing_attrs["material_composition"] = ", ".join(found)

    # ── technical_specs ──────────────────────────────────────────────────
    if "technical_specs" in missing:
        import re as _re
        hits: list[str] = []
        for pat in _SPECS_PATTERNS:
            for m in _re.finditer(pat, text_lower):
                val = m.group(0).strip()
                if val not in hits:
                    hits.append(val)
        if hits:
            existing_attrs["technical_specs"] = "; ".join(hits)
        # Also capture "220В 1.5кВт"-style freeform if no hits yet
        if not hits:
            gen_spec = _re.findall(
                r'[\d]+[\s]*[а-яА-Яa-zA-Z/]+',
                user_text
            )
            if gen_spec:
                existing_attrs["technical_specs"] = "; ".join(g.strip() for g in gen_spec[:8])

    # ── customs_regime ───────────────────────────────────────────────────
    if "customs_regime" in missing:
        if any(kw in text_lower for kw in _REGIME_IMPORT):
            existing_attrs["customs_regime"] = "import"
        elif any(kw in text_lower for kw in _REGIME_EXPORT):
            existing_attrs["customs_regime"] = "export"
        elif any(kw in text_lower for kw in _REGIME_TRANSIT):
            existing_attrs["customs_regime"] = "transit"

    # ── jurisdiction ─────────────────────────────────────────────────────
    if "jurisdiction" in missing:
        if any(kw in text_lower for kw in _JURISDICTION_EAEU):
            existing_attrs["jurisdiction"] = "EAEU"
        elif any(kw in text_lower for kw in _JURISDICTION_EU):
            existing_attrs["jurisdiction"] = "EU"
        elif any(kw in text_lower for kw in _JURISDICTION_US):
            existing_attrs["jurisdiction"] = "US"

    # country_of_origin: the existing country extraction in AttributeExtractor
    # already handles this; but the questionnaire may still need it filled by
    # answer if extractor didn't catch it.  Do a lightweight country re-check.
    if "country_of_origin" in missing:
        for kw, name in _QUESTIONNAIRE_COUNTRY_HINTS.items():
            if kw in text_lower:
                existing_attrs["country_of_origin"] = name
                break

    return existing_attrs


_QUESTIONNAIRE_COUNTRY_HINTS: dict[str, str] = {
    "китай": "Китай", "china": "Китай",
    "казахстан": "Казахстан", "kazakhstan": "Казахстан",
    "росси": "Россия", "russia": "Россия",
    "турци": "Турция", "turkey": "Турция",
    "герман": "Германия", "germany": "Германия",
    "итали": "Италия", "italy": "Италия",
    "узбекистан": "Узбекистан", "uzbekistan": "Узбекистан",
    "кыргызстан": "Кыргызстан", "kyrgyzstan": "Кыргызстан",
    "сша": "США", "usa": "США", "us": "США",
    "европ": "ЕС",
    "франци": "Франция", "france": "Франция",
    "япони": "Япония", "japan": "Япония",
    "коре": "Корея", "korea": "Корея",
    "польш": "Польша", "poland": "Польша",
    "инди": "Индия", "india": "Индия",
}
