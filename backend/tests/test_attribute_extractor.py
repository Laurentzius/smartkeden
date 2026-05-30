"""Unit tests for the Attribute Extractor.

Tests text-based extraction, vision-based extraction (mocked),
and attribute merging.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.core.classification.attribute_extractor import AttributeExtractor


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def extractor():
    """Create an AttributeExtractor without a vision client."""
    return AttributeExtractor(vision_client=None)


@pytest.fixture
def extractor_with_vision():
    """Create an AttributeExtractor with a mocked vision client."""
    mock_client = MagicMock()
    mock_client.generate_content = AsyncMock()
    return AttributeExtractor(vision_client=mock_client)


# ══════════════════════════════════════════════════════════════════════════
# Text Extraction
# ══════════════════════════════════════════════════════════════════════════

class TestExtractFromText:
    """Test text-based attribute extraction."""

    def test_extract_material_plastic(self, extractor):
        attrs = extractor._extract_from_text("пластиковая игрушка для детей")
        assert attrs.get("material_outer") == "пластик"

    def test_extract_material_wood(self, extractor):
        attrs = extractor._extract_from_text("деревянный конструктор")
        assert attrs.get("material_outer") == "дерево"

    def test_extract_material_metal(self, extractor):
        attrs = extractor._extract_from_text("металлическая машинка")
        assert attrs.get("material_outer") == "металл"

    def test_extract_material_textile(self, extractor):
        attrs = extractor._extract_from_text("текстильная кукла")
        assert attrs.get("material_outer") == "текстиль"

    def test_extract_material_leather(self, extractor):
        attrs = extractor._extract_from_text("кожаная сумка")
        assert attrs.get("material_outer") == "кожа"

    def test_extract_filling(self, extractor):
        attrs = extractor._extract_from_text("подушка с синтепоновым наполнителем")
        assert attrs.get("material_filling") == "синтепон"

    def test_extract_filling_down(self, extractor):
        attrs = extractor._extract_from_text("пуховая куртка")
        assert attrs.get("material_filling") == "пух"

    def test_extract_size_cm(self, extractor):
        attrs = extractor._extract_from_text("размер 30 см")
        assert attrs.get("size_cm") == 30.0

    def test_extract_size_mm(self, extractor):
        attrs = extractor._extract_from_text("диаметр 150 мм")
        assert attrs.get("size_cm") == 15.0

    def test_extract_size_m(self, extractor):
        attrs = extractor._extract_from_text("длина 2 м")
        assert attrs.get("size_cm") == 200.0

    def test_extract_weight_kg(self, extractor):
        attrs = extractor._extract_from_text("вес 2.5 кг")
        assert attrs.get("weight_kg") == 2.5

    def test_extract_weight_g(self, extractor):
        attrs = extractor._extract_from_text("вес 500 грамм")
        assert attrs.get("weight_kg") == 0.5

    def test_extract_electronics(self, extractor):
        attrs = extractor._extract_from_text("электронная игрушка на батарейках")
        assert attrs.get("has_electronics") is True

    def test_extract_sound_module(self, extractor):
        attrs = extractor._extract_from_text("музыкальная игрушка которая поет")
        assert attrs.get("has_sound_module") is True

    def test_extract_movement(self, extractor):
        attrs = extractor._extract_from_text("заводная механическая игрушка")
        assert attrs.get("has_movement") is True

    def test_extract_lighting(self, extractor):
        attrs = extractor._extract_from_text("игрушка со светодиодной подсветкой")
        assert attrs.get("has_lighting") is True

    def test_extract_target_audience_children(self, extractor):
        attrs = extractor._extract_from_text("детская игрушка для детей")
        assert attrs.get("target_audience") == "дети"

    def test_extract_target_audience_adult(self, extractor):
        attrs = extractor._extract_from_text("взрослая одежда")
        assert attrs.get("target_audience") == "взрослые"

    def test_extract_fur_percent(self, extractor):
        attrs = extractor._extract_from_text("шуба 80% натуральный мех")
        assert attrs.get("fur_coverage_percent") == 80.0

    def test_extract_textile_percent(self, extractor):
        attrs = extractor._extract_from_text("состав 70% хлопок")
        assert attrs.get("textile_percent") == 70.0

    def test_extract_country_china(self, extractor):
        attrs = extractor._extract_from_text("товар из китай")
        assert attrs.get("country_of_origin") == "Китай"

    def test_extract_country_kazakhstan(self, extractor):
        attrs = extractor._extract_from_text("казахстанский производитель")
        assert attrs.get("country_of_origin") == "Казахстан"

    def test_empty_description(self, extractor):
        attrs = extractor._extract_from_text("")
        assert attrs == {}

    def test_no_recognizable_attributes(self, extractor):
        attrs = extractor._extract_from_text("просто какой-то текст без ключевых слов")
        assert attrs == {}


# ══════════════════════════════════════════════════════════════════════════
# Vision Extraction (Mocked)
# ══════════════════════════════════════════════════════════════════════════

class TestExtractFromImage:
    """Test vision-based attribute extraction with mocked LLM."""

    @pytest.mark.asyncio
    async def test_extract_from_image_success(self, extractor_with_vision):
        extractor_with_vision.vision_client.generate_content.return_value = (
            '{"material_outer": "пластик", "size_cm": 30, "has_electronics": false}'
        )
        attrs = await extractor_with_vision._extract_from_image(b"fake_image_bytes")
        assert attrs.get("material_outer") == "пластик"
        assert attrs.get("size_cm") == 30
        assert attrs.get("has_electronics") is False

    @pytest.mark.asyncio
    async def test_extract_from_image_json_block(self, extractor_with_vision):
        extractor_with_vision.vision_client.generate_content.return_value = (
            '```json\n{"material_outer": "дерево", "size_cm": 50}\n```'
        )
        attrs = await extractor_with_vision._extract_from_image(b"fake_image_bytes")
        assert attrs.get("material_outer") == "дерево"
        assert attrs.get("size_cm") == 50

    @pytest.mark.asyncio
    async def test_extract_from_image_no_client(self, extractor):
        attrs = await extractor._extract_from_image(b"fake_image_bytes")
        assert attrs == {}

    @pytest.mark.asyncio
    async def test_extract_from_image_exception(self, extractor_with_vision):
        extractor_with_vision.vision_client.generate_content.side_effect = Exception("Vision API error")
        attrs = await extractor_with_vision._extract_from_image(b"fake_image_bytes")
        assert attrs == {}  # Graceful degradation

    @pytest.mark.asyncio
    async def test_extract_from_image_invalid_json(self, extractor_with_vision):
        extractor_with_vision.vision_client.generate_content.return_value = "not json at all"
        attrs = await extractor_with_vision._extract_from_image(b"fake_image_bytes")
        assert isinstance(attrs, dict)


# ══════════════════════════════════════════════════════════════════════════
# Merging Text + Vision
# ══════════════════════════════════════════════════════════════════════════

class TestMergeAttributes:
    """Test merging text and vision attributes (vision takes precedence)."""

    @pytest.mark.asyncio
    async def test_merge_vision_precedence(self, extractor_with_vision):
        extractor_with_vision.vision_client.generate_content.return_value = (
            '{"material_outer": "пластик", "size_cm": 25}'
        )
        attrs = await extractor_with_vision.extract_attributes(
            description="деревянная игрушка 30 см",
            image_bytes=b"fake",
        )
        # Vision takes precedence for overlapping fields
        assert attrs.get("material_outer") == "пластик"
        assert attrs.get("size_cm") == 25
    @pytest.mark.asyncio
    async def test_merge_vision_precedence(self, extractor_with_vision):
        extractor_with_vision.vision_client.generate_content.return_value = (
            '{"material_outer": "пластик", "size_cm": 25}'
        )
        attrs = await extractor_with_vision.extract_attributes(
            description="деревянный конструктор 30 см",
            image_bytes=b"fake",
        )
        # Vision takes precedence for overlapping fields
        assert attrs.get("material_outer") == "пластик"
        assert attrs.get("size_cm") == 25

    @pytest.mark.asyncio
    async def test_merge_text_fills_gaps(self, extractor_with_vision):
        extractor_with_vision.vision_client.generate_content.return_value = (
            '{"material_outer": "пластик"}'
        )
        attrs = await extractor_with_vision.extract_attributes(
            description="детская игрушка из китай",
            image_bytes=b"fake",
        )
        # Vision provides material, text provides country and audience
        assert attrs.get("material_outer") == "пластик"
        assert attrs.get("country_of_origin") == "Китай"
        assert attrs.get("target_audience") == "дети"
    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_text_only_no_image(self, extractor):
        attrs = await extractor.extract_attributes(
            description="пластиковая игрушка 20 см из китай",
        )
        assert attrs.get("material_outer") == "пластик"
        assert attrs.get("size_cm") == 20.0
        assert attrs.get("country_of_origin") == "Китай"

    @pytest.mark.asyncio
    async def test_image_only_no_text(self, extractor_with_vision):
        extractor_with_vision.vision_client.generate_content.return_value = (
            '{"material_outer": "металл", "has_electronics": true}'
        )
        attrs = await extractor_with_vision.extract_attributes(
            description="",
            image_bytes=b"fake",
        )
        assert attrs.get("material_outer") == "металл"
        assert attrs.get("has_electronics") is True

    @pytest.mark.asyncio
    async def test_empty_both(self, extractor):
        attrs = await extractor.extract_attributes(description="", image_bytes=None)
        assert attrs == {}


# ══════════════════════════════════════════════════════════════════════════
# JSON Parsing
# ══════════════════════════════════════════════════════════════════════════

class TestJsonParsing:
    """Test JSON response parsing."""

    def test_parse_json_direct(self):
        result = AttributeExtractor._parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_with_code_block(self):
        result = AttributeExtractor._parse_json_response('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_markdown_wrapped(self):
        result = AttributeExtractor._parse_json_response('Here is the result:\n```\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_invalid(self):
        result = AttributeExtractor._parse_json_response("not json")
        assert result == {}

    def test_parse_json_empty(self):
        result = AttributeExtractor._parse_json_response("")
        assert result == {}

    def test_parse_json_none(self):
        result = AttributeExtractor._parse_json_response(None)
        assert result == {}
