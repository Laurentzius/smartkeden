"""Structured Attribute Extractor for product classification.

Extracts structured product attributes from text descriptions and images
using the Vision LLM (Gemini via Vertex AI).

Design decisions:
- Vision extraction: use structured prompt to force JSON output
- Text extraction: parse Russian-language description for key attributes
- Merge: vision attributes take precedence, text fills gaps
- Fallback: if vision unavailable, text-only extraction
"""

import json
import logging
from typing import Optional

from app.core.classification.rule_models import AttributeSchema

logger = logging.getLogger(__name__)


class AttributeExtractor:
    """Extract structured product attributes from text + optional image.

    Uses the Vision LLM client when an image is provided, and falls back
    to text parsing when no image or when vision is unavailable.
    """

    def __init__(self, vision_client=None):
        """Initialize with an optional vision client.

        Args:
            vision_client: Vertex AI / Gemini client for vision extraction.
        """
        self.vision_client = vision_client

    async def extract_attributes(
        self,
        description: str = "",
        image_bytes: Optional[bytes] = None,
    ) -> dict:
        """Extract structured product attributes.

        Args:
            description: Text description of the product (Russian/Kazakh).
            image_bytes: Optional image bytes for vision-based extraction.

        Returns:
            Dict with extracted attributes (only non-None values).
        """
        vision_attrs: dict = {}
        text_attrs: dict = {}

        if image_bytes:
            vision_attrs = await self._extract_from_image(image_bytes)

        if description:
            text_attrs = self._extract_from_text(description)

        # Merge: vision takes precedence over text
        merged = {**text_attrs, **vision_attrs}

        # Validate through schema
        try:
            schema = AttributeSchema(**merged)
            return schema.to_flat_dict()
        except Exception as e:
            logger.warning("Attribute validation failed, returning raw merged dict: %s", e)
            # Remove None values
            return {k: v for k, v in merged.items() if v is not None}

    async def _extract_from_image(self, image_bytes: bytes) -> dict:
        """Use Vision LLM to extract structured attributes from an image.

        Returns a dict with extracted attributes.
        """
        if not self.vision_client:
            logger.warning("No vision client configured, skipping image extraction")
            return {}

        try:
            prompt = _VISION_EXTRACTION_PROMPT
            response = await self.vision_client.generate_content(
                prompt=prompt,
                image_bytes=image_bytes,
                temperature=0.0,  # Deterministic extraction
            )

            # Parse JSON from response
            attrs = self._parse_json_response(response)
            return attrs
        except ImportError:
            logger.warning("Vertex AI client not available for vision extraction")
            return {}
        except Exception as e:
            logger.exception("Vision attribute extraction failed: %s", e)
            return {}

    def _extract_from_text(self, description: str) -> dict:
        """Extract attributes from text description using rule-based parsing.

        Handles common Russian/Kazakh patterns for material, size, weight,
        electronics presence, etc.
        """
        attrs: dict = {}
        text_lower = description.lower()

        # Material detection
        for material, keywords in _MATERIAL_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                attrs.setdefault("material_outer", material)
                break

        # Filling detection
        for filling, keywords in _FILLING_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                attrs["material_filling"] = filling
                break

        # Size extraction: look for number + unit (см, cm, мм, mm, м, m)
        import re
        size_match = re.search(r'(\d+[\.,]?\d*)\s*(см|cm|мм|mm|м|m)', text_lower)
        if size_match:
            try:
                size_val = float(size_match.group(1).replace(',', '.'))
                unit = size_match.group(2)
                if unit in ('мм', 'mm'):
                    size_val /= 10.0  # Convert mm to cm
                elif unit in ('м', 'm'):
                    size_val *= 100.0  # Convert m to cm
                attrs["size_cm"] = size_val
            except ValueError:
                pass

        # Weight extraction
        weight_match = re.search(r'(\d+[\.,]?\d*)\s*(кг|kg|г|g|грамм|грам)', text_lower)
        if weight_match:
            try:
                weight_val = float(weight_match.group(1).replace(',', '.'))
                unit = weight_match.group(2)
                if unit in ('г', 'g', 'грамм', 'грам'):
                    weight_val /= 1000.0  # Convert g to kg
                attrs["weight_kg"] = weight_val
            except ValueError:
                pass

        # Electronics detection
        electronics_kw = [
            'электрон', 'electron', 'батарейк', 'battery', 'аккумулятор',
            'светодиод', 'led', 'подсветк', 'моторчик', 'двигател',
            'звуковой модуль', 'sound module', 'музыкальн',
        ]
        if any(kw in text_lower for kw in electronics_kw):
            attrs["has_electronics"] = True

        # Sound module
        sound_kw = ['звук', 'sound', 'музык', 'music', 'поет', 'говорит', 'пищит']
        if any(kw in text_lower for kw in sound_kw):
            attrs["has_sound_module"] = True

        # Movement
        move_kw = ['двигается', 'движется', 'механическ', 'заводной', 'инерцион']
        if any(kw in text_lower for kw in move_kw):
            attrs["has_movement"] = True

        # Lighting
        light_kw = ['светится', 'светящ', 'подсветк', 'лампочк', 'светодиод', 'led']
        if any(kw in text_lower for kw in light_kw):
            attrs["has_lighting"] = True

        # Target audience
        if any(kw in text_lower for kw in ['детск', 'детям', 'ребен', 'игрушк', 'toy']):
            attrs["target_audience"] = "дети"
        elif any(kw in text_lower for kw in ['взросл', 'adult']):
            attrs["target_audience"] = "взрослые"

        # Fur coverage
        fur_match = re.search(r'(\d+)\s*%\s*(мех|натуральн|fur)', text_lower)
        if fur_match:
            try:
                attrs["fur_coverage_percent"] = float(fur_match.group(1))
            except ValueError:
                pass

        # Textile percent
        textile_match = re.search(r'(\d+)\s*%\s*(текстил|хлопок|cotton|ткань|textile)', text_lower)
        if textile_match:
            try:
                attrs["textile_percent"] = float(textile_match.group(1))
            except ValueError:
                pass

        # Country of origin
        for country, keywords in _COUNTRY_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                attrs["country_of_origin"] = country
                break

        return attrs

    @staticmethod
    def _parse_json_response(response) -> dict:
        """Parse JSON from LLM response text."""
        if not response:
            return {}
        text = response if isinstance(response, str) else str(response)

        # Try to find JSON block
        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract just the JSON object
            import re
            match = re.search(r'\{[^{}]*\}', text)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            logger.warning("Failed to parse JSON from vision response")
            return {}


# ── Keyword mappings for text extraction ──────────────────────────────────────

_MATERIAL_KEYWORDS: dict[str, list[str]] = {
    "пластик": ["пластик", "пластмасс", "plastic", "полимер", "полипропилен", "abs", "pvc"],
    "дерево": ["дерев", "wood", "деревян", "древесин", "фанера", "мдф"],
    "металл": ["металл", "metal", "сталь", "steel", "алюмин", "желез"],
    "текстиль": ["текстил", "textile", "ткань", "fabric", "хлопок", "cotton", "шерсть", "wool"],
    "резина": ["резин", "rubber", "каучук", "силикон", "silicone"],
    "кожа": ["кож", "leather", "замш"],
    "стекло": ["стекл", "glass", "стеклян"],
    "керамика": ["керамик", "ceramic", "фарфор", "porcelain"],
    "бумага": ["бумаг", "paper", "картон", "carton"],
    "мех": ["мех", "fur", "натуральный мех", "овчин"],
}

_FILLING_KEYWORDS: dict[str, list[str]] = {
    "синтепон": ["синтепон", "синтепух", "холлофайбер", "полиэстер"],
    "пух": ["пух", "перо", "down", "feather"],
    "поролон": ["поролон", "пенополиуретан", "foam"],
    "вата": ["вата", "cotton fill"],
    "песок": ["песок", "sand"],
}

_COUNTRY_KEYWORDS: dict[str, list[str]] = {
    "Китай": ["китай", "china", "made in china", "китайский"],
    "Казахстан": ["казахстан", "kazakhstan", "рк", "отечествен"],
    "Россия": ["росси", "russia", "российский"],
    "Турция": ["турци", "turkey", "турецкий"],
    "Германия": ["герман", "germany", "немецкий"],
    "Италия": ["итали", "italy", "итальянский"],
    "Узбекистан": ["узбекистан", "uzbekistan"],
    "Кыргызстан": ["кыргызстан", "kyrgyzstan", "киргиз"],
}


# ── Vision extraction prompt ──────────────────────────────────────────────────

_VISION_EXTRACTION_PROMPT = """Ты — эксперт таможенной классификации. Извлеки из изображения товара структурированные атрибуты.

Верни ТОЛЬКО JSON-объект (без markdown, без пояснений) со следующими полями (только те, которые можно определить по изображению):

{
  "material_outer": "основной материал (пластик, дерево, металл, текстиль, резина, кожа, ...)",
  "material_filling": "материал наполнителя если видно",
  "material_coating": "материал покрытия если есть",
  "size_cm": "примерный размер в сантиметрах (число)",
  "has_electronics": true/false,
  "has_sound_module": true/false,
  "has_movement": true/false,
  "has_lighting": true/false,
  "brand": "бренд если виден на упаковке",
  "country_of_origin": "страна происхождения если указана",
  "target_audience": "дети / взрослые / универсальное",
  "fur_coverage_percent": "процент натурального меха (0-100)",
  "textile_percent": "процент текстиля (0-100)",
  "metal_percent": "процент металла (0-100)"
}

Если атрибут невозможно определить по изображению — не включай его в JSON.
Отвечай только JSON-объектом, без текста до или после."""
