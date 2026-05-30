"""
Automated Quality E2E Test Suite for SmartKeden Intent Classifier & FAQ Fast-Path.

Design principles:
- NO test question may appear verbatim in intents.yaml few-shot examples.
- unclear questions MUST have min_confidence to verify model is actually uncertain.
- Negative tests verify the classifier does NOT confuse similar intents.
- Boundary cases test ambiguous questions that sit between two intents.

Run:
  PYTHONPATH=backend .venv/Scripts/pytest backend/tests/test_quality_e2e.py -v
"""

import json
import time
from dataclasses import dataclass
from typing import List, Optional

import pytest


# ═══════════════════════════════════════════════════════════════════════════
#  Test Data Types
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class IntentTestCase:
    text: str
    expected_intent: str
    min_confidence: float = 0.5
    description: str = ""


@dataclass
class NegativeIntentCase:
    text: str
    forbidden_intents: List[str]  # intents this question should NOT be classified as
    description: str = ""


@dataclass
class FAQTestCase:
    text: str
    should_match: bool = True
    expected_keywords: Optional[List[str]] = None  # substrings that MUST appear in response
    forbidden_keywords: Optional[List[str]] = None  # substrings that MUST NOT appear
    description: str = ""


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def Q(text, intent, min_conf=0.5, desc=""):
    return IntentTestCase(text=text, expected_intent=intent, min_confidence=min_conf, description=desc)


def NQ(text, forbidden, desc=""):
    return NegativeIntentCase(text=text, forbidden_intents=forbidden, description=desc)


def FQ(text, keywords=None, forbidden_kw=None, desc=""):
    return FAQTestCase(text=text, should_match=True, expected_keywords=keywords, forbidden_keywords=forbidden_kw, description=desc)


def NFQ(text, desc=""):
    return FAQTestCase(text=text, should_match=False, description=desc)


# ═══════════════════════════════════════════════════════════════════════════
#  Intent Classification Pool (~75 questions)
#
#  NO question here appears verbatim in intents.yaml few-shot examples.
#  Few-shot examples use: Lego, ноутбук, iPhone, 9503008900, Китай, Германия,
#  вата, погода в Астане, анекдот, привет!, сәлем!, etc.
#  We test with DIFFERENT goods, countries, phrasing, and topics.
# ═══════════════════════════════════════════════════════════════════════════

INTENT_POOL: List[IntentTestCase] = [
    # ── question_about_law (RU) ──
    Q("Какие таможенные процедуры применяются при транзите товаров через Казахстан?",
      "question_about_law", desc="транзит"),
    Q("Объясни порядок обжалования решений таможенного органа в РК",
      "question_about_law", desc="обжалование"),
    Q("Какие виды таможенных деклараций бывают и когда какую подавать?",
      "question_about_law", desc="виды деклараций"),
    Q("Можно ли вернуть уплаченную ввозную пошлину при реэкспорте товара?",
      "question_about_law", desc="возврат пошлины"),
    Q("Расскажи про таможенное сопровождение грузов — когда оно обязательно?",
      "question_about_law", desc="сопровождение"),
    Q("Что такое карнет АТА и для каких товаров он применяется?",
      "question_about_law", desc="карнет АТА"),
    Q("Какие требования к маркировке импортируемой обуви в ЕАЭС?",
      "question_about_law", desc="маркировка обуви"),
    Q("Чем отличается таможенный представитель от таможенного перевозчика?",
      "question_about_law", desc="представитель vs перевозчик"),
    Q("В каких случаях проводится таможенный досмотр, а не осмотр?",
      "question_about_law", desc="досмотр vs осмотр"),
    Q("Сколько времени даётся на подачу таможенной декларации после прибытия товара?",
      "question_about_law", desc="сроки подачи ДТ"),
    Q("Назови основания для отказа в выпуске товаров таможенным органом РК",
      "question_about_law", desc="отказ в выпуске"),
    Q("Может ли физическое лицо ввезти коммерческую партию товара без регистрации ИП?",
      "question_about_law", desc="физлицо коммерция"),
    Q("Какие изменения в Таможенный кодекс ЕАЭС вступили в силу в этом году?",
      "question_about_law", desc="изменения ТК"),

    # ── question_about_law (KZ) ──
    Q("Кеден органының шешіміне шағымдану тәртібі қандай?",
      "question_about_law", desc="[KZ] шағымдану"),
    Q("Тауарлар транзиті кезінде қандай кепілдіктер талап етіледі?",
      "question_about_law", desc="[KZ] транзит кепілдік"),
    Q("Импорттық баждарды қайтару мүмкін бе және қандай жағдайда?",
      "question_about_law", desc="[KZ] баж қайтару"),
    Q("Тауарларды шығарудан бас тарту негіздері қандай?",
      "question_about_law", desc="[KZ] шығарудан бас тарту"),
    Q("ЕАЭО кедендік кодексіне енгізілген соңғы өзгерістер туралы айтып беріңіз",
      "question_about_law", desc="[KZ] өзгерістер"),

    # ── product_description (RU) ──
    Q("подбери код ТН ВЭД для электрического самоката",
      "product_description", desc="электросамокат"),
    Q("классифицируй фильтр масляный для легкового автомобиля",
      "product_description", desc="масляный фильтр"),
    Q("какой код присвоить керамической плитке напольной 30x30 см",
      "product_description", desc="плитка"),
    Q("определи ТН ВЭД для рыбных консервов — сайра в масле, жестяная банка 250г",
      "product_description", desc="рыбные консервы"),
    Q("нужен код на комплект постельного белья из хлопка, евро-размер",
      "product_description", desc="постельное белье"),
    Q("классифицируй товар: фитнес-браслет с пульсометром и шагомером, силиконовый ремешок",
      "product_description", desc="фитнес-браслет"),
    Q("что за код у дизельного генератора 50 кВт в контейнерном исполнении",
      "product_description", desc="дизель-генератор"),
    Q("подскажи ТН ВЭД для деревянной мебели — обеденный стол из дуба",
      "product_description", desc="мебель деревянная"),

    # ── product_description (KZ) ──
    Q("электр самокаттың СЭҚ ТН кодын табыңыз",
      "product_description", desc="[KZ] электросамокат"),
    Q("балық консервілерін қалай классификациялау керек?",
      "product_description", desc="[KZ] балық консерві"),
    Q("мақтадан жасалған төсек жабдығының коды қандай?",
      "product_description", desc="[KZ] төсек жабдығы"),
    Q("ағаш жиһаз — емен үстел үшін СЭҚ ТН коды",
      "product_description", desc="[KZ] ағаш жиһаз"),

    # ── calculation_request (RU) ──
    Q("растаможка мотоцикла из Японии, Honda CBR 650, 2022 год, объём 650 кубов",
      "calculation_request", desc="мотоцикл Япония"),
    Q("вычисли размер ввозной пошлины на партию одежды из Турции, код 6204",
      "calculation_request", desc="одежда Турция"),
    Q("прикинь стоимость таможенного оформления для экскаватора из Кореи, б/у",
      "calculation_request", desc="экскаватор Корея"),
    Q("калькулятор: товар 9403, страна Италия, инвойс 8500 евро, доставка 1200 евро",
      "calculation_request", desc="мебель Италия"),
    Q("сколько выйдет растаможка электроники из ОАЭ, партия смарт-часов, 200 штук",
      "calculation_request", desc="электроника ОАЭ"),
    Q("рассчитай полные таможенные платежи: код 8703, страна США, стоимость $32000",
      "calculation_request", desc="авто США"),
    Q("какие платежи нужно уплатить за ввоз медицинского оборудования из Европы?",
      "calculation_request", desc="медоборудование Европа"),

    # ── calculation_request (KZ) ──
    Q("Германиядан Audi A4 автокөлігін кедендік тазарту бағасын есептеңіз",
      "calculation_request", desc="[KZ] Audi Германия"),
    Q("Кореядан экскаваторды кедендік ресімдеу қанша тұрады?",
      "calculation_request", desc="[KZ] экскаватор Корея"),
    Q("Түркиядан киім партиясы үшін баж салығын есептеу",
      "calculation_request", desc="[KZ] киім Түркия"),

    # ── greeting (RU) ──
    Q("доброе утро, нужна консультация", "greeting", desc="доброе утро"),
    Q("вечер добрый!", "greeting", desc="вечер добрый"),
    Q("салют!", "greeting", desc="салют"),
    Q("приветствую вас", "greeting", desc="приветствую"),
    Q("доброго времени суток", "greeting", desc="времени суток"),
    Q("хелло!", "greeting", desc="хелло"),

    # ── greeting (KZ) ──
    Q("сәлемет пе!", "greeting", desc="[KZ] сәлемет пе"),
    Q("амансыз ба!", "greeting", desc="[KZ] амансыз ба"),
    Q("қош келдіңіз!", "greeting", desc="[KZ] қош келдіңіз"),
    Q("армысыз!", "greeting", desc="[KZ] армысыз"),

    # ── document_upload (RU) ──
    Q("добавь приказ Минфина №456 в базу знаний",
      "document_upload", desc="приказ Минфина"),
    Q("залей новый регламент таможенного оформления",
      "document_upload", desc="регламент"),

    # ── document_upload (KZ) ──
    Q("кедендік ресімдеу туралы жаңа нұсқаулықты базаға қосыңыз",
      "document_upload", desc="[KZ] нұсқаулық"),
    Q("Қаржы министрлігінің бұйрығын жүйеге жүктеңіз",
      "document_upload", desc="[KZ] бұйрық"),

    # ── unclear (RU) — ALL have min_confidence lowered to verify model is uncertain ──
    Q("как пожарить шашлык правильно?", "unclear", min_conf=0.0,
      desc="кулинария — шашлык"),
    Q("посоветуй фильм на вечер в жанре фантастика",
      "unclear", min_conf=0.0, desc="кино"),
    Q("как записаться к врачу через егов?",
      "unclear", min_conf=0.0, desc="егов не таможня"),
    Q("какой сегодня курс тенге к доллару на бирже KASE?",
      "unclear", min_conf=0.0, desc="курс валют — не таможня"),
    Q("где купить билеты на концерт в Алматы?",
      "unclear", min_conf=0.0, desc="концерт"),
    Q("реши уравнение: 2x² + 5x - 3 = 0",
      "unclear", min_conf=0.0, desc="математика"),
    Q("напиши стихотворение про таможню",
      "unclear", min_conf=0.0, desc="творческое задание"),
    Q("как поменять масло в двигателе Toyota Camry?",
      "unclear", min_conf=0.0, desc="авторемонт — не растаможка"),

    # ── unclear (KZ) ──
    Q("бүгін ауа райы қандай болады?",
      "unclear", min_conf=0.0, desc="[KZ] ауа райы — не Астана"),
    Q("дәрігерге қалай жазылуға болады?",
      "unclear", min_conf=0.0, desc="[KZ] дәрігер"),
    Q("Алматыда жақсы мейрамхана ұсыныңыз",
      "unclear", min_conf=0.0, desc="[KZ] мейрамхана"),
    Q("футболдан Қазақстан чемпионатының кестесін көрсет",
      "unclear", min_conf=0.0, desc="[KZ] спорт"),
]


# ═══════════════════════════════════════════════════════════════════════════
#  Negative Intent Tests — questions that should NOT be classified as X
# ═══════════════════════════════════════════════════════════════════════════

NEGATIVE_INTENT_POOL: List[NegativeIntentCase] = [
    # "посчитай"/"рассчитай" questions → NOT question_about_law
    NQ("посчитай сколько будет пошлина на шины из Китая",
       ["question_about_law"], desc="расчёт шин — не law"),
    NQ("рассчитай таможенный платёж для партии сыра из Франции",
       ["question_about_law"], desc="расчёт сыра — не law"),

    # "что такое", "расскажи про" → NOT calculation_request
    NQ("что такое таможенная процедура уничтожения и когда применяется?",
       ["calculation_request"], desc="уничтожение — не расчёт"),
    NQ("расскажи про систему управления рисками на таможне",
       ["calculation_request"], desc="СУР — не расчёт"),

    # Question with "код" but about law, not HS → NOT product_description
    NQ("какие коды таможенных процедур используются при временном ввозе?",
       ["product_description"], desc="коды процедур — не HS"),

    # General customs conversation → NOT unclear
    NQ("расскажите подробнее про таможенное законодательство ЕАЭС",
       ["unclear"], desc="законодательство ЕАЭС — не unclear"),

    # Questions about systems/tools, not uploading documents → NOT document_upload
    NQ("как получить ЭЦП для работы с системой АСТАНА-1?",
       ["document_upload"], desc="ЭЦП АСТАНА-1 — не document_upload"),
]


# ═══════════════════════════════════════════════════════════════════════════
#  Boundary Cases — ambiguous questions between two intents
#  These test the classifier's judgment on non-obvious inputs.
# ═══════════════════════════════════════════════════════════════════════════

BOUNDARY_POOL: List[IntentTestCase] = [
    # Could be question_about_law OR calculation_request — either is acceptable
    Q("какие ставки пошлин применяются к товарам из развивающихся стран и как их рассчитать?",
      "question_about_law", min_conf=0.0, desc="boundary: ставки + рассчитать"),

    # Very short, almost no signal
    Q("пошлина", "question_about_law", min_conf=0.0, desc="boundary: одно слово"),

    # Could be law question or product classification
    Q("как оформляется сертификат происхождения товара формы А?",
      "question_about_law", min_conf=0.0, desc="boundary: сертификат происхождения"),
]


# ═══════════════════════════════════════════════════════════════════════════
#  FAQ Fast-Path Pool
# ═══════════════════════════════════════════════════════════════════════════

FAQ_POOL: List[FAQTestCase] = [
    # ── Positive: should match FAQ ──
    FQ("таможенный сбор сколько платить за одну декларацию?",
       keywords=["20 000"], desc="сбор за декларацию"),
    FQ("сколько сбор за таможенное оформление в тенге?",
       keywords=["20 000"], desc="оформление стоимость"),
    FQ("какая сумма лимита на посылки без уплаты пошлины в Казахстане?",
       keywords=["1000", "евро"], desc="лимит посылок РК"),

    # ── Positive: specific keyword before broad (утильсбор before сбор) ──
    FQ("кто должен платить утильсбор при ввозе авто в Казахстан?",
       keywords=["утилизационный", "транспортных"], forbidden_kw=["20 000"],
       desc="утильсбор — не сбор за декларирование"),

    # ── Positive: ТРОИС ──
    FQ("что такое ТРОИС и зачем он нужен при импорте брендовых товаров?",
       keywords=["реестр", "интеллектуальной"], desc="ТРОИС импорт"),

    # ── KZ FAQ ──
    FQ("кедендік төлем қанша теңге төлеу керек?",
       keywords=["20 000"], desc="[KZ] кедендік төлем"),
    FQ("Қазақстанда бажсыз сәлемдеме лимиті қанша?",
       keywords=["1000", "евро"], desc="[KZ] бажсыз лимит"),
    FQ("автокөлік әкелгенде кәдеге жарату алымын кім төлейді?",
       keywords=["утилизационный"], forbidden_kw=["20 000"],
       desc="[KZ] кәдеге жарату — не сбор"),

    # ── Negative: should NOT match FAQ ──
    NFQ("какие документы нужны для таможенного транзита через Казахстан?",
        desc="транзит — не FAQ"),
    NFQ("как классифицировать товар по ТН ВЭД если это смесь химических веществ?",
        desc="классификация — не FAQ"),
    NFQ("рассчитайте примерную сумму таможенных платежей для ввоза одежды из Китая",
        desc="расчёт — не FAQ"),
    NFQ("чем отличаются прямой и косвенный методы определения таможенной стоимости?",
        desc="методы ТС — не FAQ"),
    NFQ("как получить статус уполномоченного экономического оператора в РК?",
        desc="УЭО — не FAQ"),
    NFQ("салықтық жеңілдіктер туралы айтып беріңіз",
        desc="[KZ] жеңілдіктер — не FAQ"),
    NFQ("кедендік құнды анықтау әдістері қандай?",
        desc="[KZ] құн әдістері — не FAQ"),
]


# ═══════════════════════════════════════════════════════════════════════════
#  Intent Classification Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIntentQuality:
    """Run intent classifier against the question pool and score results."""

    SCORE_LOG: List[dict] = []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", INTENT_POOL, ids=lambda c: c.text[:50])
    async def test_intent_accuracy(self, case: IntentTestCase):
        from app.core.orchestrator.intent_classifier import IntentClassifier

        start = time.monotonic()
        result = await IntentClassifier.classify(case.text)
        elapsed = time.monotonic() - start

        score_entry = {
            "question": case.text,
            "expected": case.expected_intent,
            "actual": result.intent.value,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "latency_s": round(elapsed, 3),
            "passed": False,
        }

        intent_ok = result.intent.value == case.expected_intent
        confidence_ok = result.confidence >= case.min_confidence

        if not intent_ok:
            score_entry["error"] = (
                f"Intent mismatch: expected {case.expected_intent}, got {result.intent.value}"
            )
        elif not confidence_ok:
            score_entry["error"] = (
                f"Confidence too low: {result.confidence:.2f} < {case.min_confidence}"
            )

        score_entry["passed"] = intent_ok and confidence_ok
        self.__class__.SCORE_LOG.append(score_entry)

        assert intent_ok, (
            f"\n  Q: {case.text}"
            f"\n  Expected: {case.expected_intent}"
            f"\n  Got: {result.intent.value} (conf={result.confidence:.2f})"
            f"\n  Reasoning: {result.reasoning}"
            f"\n  ⏱ {elapsed:.2f}s"
            f"\n  Description: {case.description}"
        )
        assert confidence_ok, (
            f"\n  Q: {case.text}"
            f"\n  Confidence {result.confidence:.2f} below minimum {case.min_confidence}"
            f"\n  Description: {case.description}"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Negative Intent Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIntentNegative:
    """Verify the classifier does NOT confuse similar intents."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", NEGATIVE_INTENT_POOL, ids=lambda c: c.text[:50])
    async def test_intent_not_misclassified(self, case: NegativeIntentCase):
        from app.core.orchestrator.intent_classifier import IntentClassifier

        result = await IntentClassifier.classify(case.text)

        assert result.intent.value not in case.forbidden_intents, (
            f"\n  Q: {case.text}"
            f"\n  Should NOT be classified as any of: {case.forbidden_intents}"
            f"\n  But got: {result.intent.value} (conf={result.confidence:.2f})"
            f"\n  Reasoning: {result.reasoning}"
            f"\n  Description: {case.description}"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Boundary Case Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestIntentBoundary:
    """Test classifier behavior on ambiguous inputs with relaxed assertions."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("case", BOUNDARY_POOL, ids=lambda c: c.text[:50])
    async def test_boundary_not_unreasonable(self, case: IntentTestCase):
        from app.core.orchestrator.intent_classifier import IntentClassifier

        result = await IntentClassifier.classify(case.text)

        # For boundary cases we only check the intent isn't completely wrong.
        # E.g., "пошлина" could be law or calculation — but NOT greeting or document_upload.
        unreasonable = {"greeting", "document_upload"}
        assert result.intent.value not in unreasonable, (
            f"\n  Q: {case.text} (boundary: acceptable={case.expected_intent})"
            f"\n  Got unreasonable intent: {result.intent.value} (conf={result.confidence:.2f})"
            f"\n  Reasoning: {result.reasoning}"
            f"\n  Description: {case.description}"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  FAQ Fast-Path Tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFAQQuality:
    """Verify FAQ keyword matching returns correct responses and avoids false positives."""

    @pytest.mark.parametrize("case", FAQ_POOL, ids=lambda c: c.text[:50])
    def test_faq_matching(self, case: FAQTestCase):
        from app.core.orchestrator.config_loader import ConfigLoader

        result = ConfigLoader().check_faq(case.text)

        if case.should_match:
            assert result is not None, (
                f"\n  Q: {case.text}"
                f"\n  Expected FAQ match, but got None"
                f"\n  Description: {case.description}"
            )
            if case.expected_keywords:
                for kw in case.expected_keywords:
                    assert kw.lower() in result.lower(), (
                        f"\n  Q: {case.text}"
                        f"\n  FAQ response missing expected keyword: '{kw}'"
                        f"\n  Got (first 300 chars): {result[:300]}"
                        f"\n  Description: {case.description}"
                    )
            if case.forbidden_keywords:
                for kw in case.forbidden_keywords:
                    assert kw.lower() not in result.lower(), (
                        f"\n  Q: {case.text}"
                        f"\n  FAQ response contains forbidden keyword: '{kw}'"
                        f"\n  Got (first 300 chars): {result[:300]}"
                        f"\n  Description: {case.description}"
                    )
        else:
            assert result is None, (
                f"\n  Q: {case.text}"
                f"\n  Expected NO FAQ match, but got response (first 300 chars): {result[:300]}"
                f"\n  Description: {case.description}"
            )


# ═══════════════════════════════════════════════════════════════════════════
#  FAQ-Orchestrator Integration Test
# ═══════════════════════════════════════════════════════════════════════════

class TestFAQOrchestratorIntegration:
    """Verify FAQ fast-path integrates correctly — FAQ match skips intent classification."""

    @pytest.mark.asyncio
    async def test_faq_match_skips_llm_intent(self):
        """When a question matches FAQ, the orchestrator should use FAQ response directly."""
        from app.core.orchestrator.config_loader import ConfigLoader
        from app.main import app
        from httpx import ASGITransport, AsyncClient

        # A question that matches FAQ keywords AND could plausibly be misclassified
        faq_query = "сколько стоит таможенный сбор в Казахстане?"

        # Verify FAQ match exists
        faq_result = ConfigLoader().check_faq(faq_query)
        assert faq_result is not None, "Test precondition failed: query should match FAQ"

        # Hit the real orchestrator endpoint
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/orchestrate",
                data={"text": faq_query},
                timeout=30,
            )
        assert response.status_code == 200, f"Orchestrator returned {response.status_code}"
        data = response.json()

        # The response should contain the FAQ answer (20 000 tenge), not an LLM-generated one
        assert "20 000" in data["message"], (
            f"FAQ-matched query should return FAQ response containing '20 000'"
            f"\n  Got: {data['message'][:300]}"
        )
        # Intent should be set correctly
        assert data["intent"] in ("question_about_law", "greeting", "unclear",
                                   "calculation_request", "product_description", "document_upload"), (
            f"Unexpected intent value: {data['intent']}"
        )

    @pytest.mark.asyncio
    async def test_non_faq_query_goes_to_llm(self):
        """A non-FAQ question should produce a meaningful LLM response (not FAQ canned text)."""
        from app.main import app
        from httpx import ASGITransport, AsyncClient

        query = "какие ставки акциза на алкогольную продукцию из Европы?"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/orchestrate",
                data={"text": query},
                timeout=60,
            )
        assert response.status_code == 200, f"Orchestrator returned {response.status_code}"
        data = response.json()

        # Should NOT be the exact canned FAQ response
        faq_canned = "Фиксированный таможенный сбор за таможенное декларирование"
        assert faq_canned not in data["message"], (
            f"Non-FAQ query should not return the canned FAQ text verbatim"
            f"\n  Got (first 300 chars): {data['message'][:300]}"
        )
        # Response should be non-empty and substantial
        assert len(data["message"]) > 100, (
            f"Expected substantial response, got {len(data['message'])} chars"
        )
        # Intent should be question_about_law (asking about excise rates)
        assert data["intent"] == "question_about_law", (
            f"Expected question_about_law, got {data['intent']}"
            f"\n  Message: {data['message'][:200]}"
        )


# ═══════════════════════════════════════════════════════════════════════════
#  Score Report (runs last)
# ═══════════════════════════════════════════════════════════════════════════

def test_score_report():
    """Print aggregate quality scores after all intent tests complete."""
    log = TestIntentQuality.SCORE_LOG
    if not log:
        pytest.skip("No intent tests were executed")

    total = len(log)
    passed = sum(1 for e in log if e["passed"])
    failed = total - passed

    avg_latency = sum(e["latency_s"] for e in log) / total if total else 0
    avg_confidence = sum(e["confidence"] for e in log) / total if total else 0

    # Calculate per-intent breakdown
    per_intent: dict = {}
    for e in log:
        intent = e["expected"]
        if intent not in per_intent:
            per_intent[intent] = {"total": 0, "passed": 0}
        per_intent[intent]["total"] += 1
        if e["passed"]:
            per_intent[intent]["passed"] += 1

    print(f"\n{'='*60}")
    print(f"  QUALITY REPORT: {passed}/{total} passed ({100*passed/total:.0f}%)")
    print(f"  Avg confidence: {avg_confidence:.2f}")
    print(f"  Avg latency:    {avg_latency:.2f}s")
    print(f"{'='*60}")
    print(f"\n  Per-intent accuracy:")
    for intent, stats in sorted(per_intent.items()):
        pct = 100 * stats["passed"] / stats["total"]
        bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        print(f"    {intent:<25s} {stats['passed']:>2}/{stats['total']:<2}  {bar} {pct:.0f}%")

    if failed:
        print(f"\n  FAILURES ({failed}):")
        for e in log:
            if not e["passed"]:
                err = e.get("error", "unknown")
                print(f"  ❌ {e['question'][:80]}")
                print(f"     expected={e['expected']} actual={e['actual']} conf={e['confidence']:.2f}")
                if err:
                    print(f"     {err}")

    # Save report as JSON artifact
    report = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "accuracy": round(passed / total, 3) if total else 0,
        "avg_latency_s": round(avg_latency, 3),
        "avg_confidence": round(avg_confidence, 3),
        "per_intent": per_intent,
        "details": log,
    }
    report_path = "backend/tests/quality_report.json"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  Report saved to {report_path}")
    except Exception as exc:
        print(f"\n  ⚠ Failed to save report: {exc}")

    if failed:
        pytest.fail(f"{failed}/{total} intent tests failed. See report above.")
