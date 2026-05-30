import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from app.core.config import settings
from app.core.llm.generator import TextGenerator, get_generator
from app.core.rag.seams import EmbeddingModel, VectorStorage
from langfuse import observe

logger = logging.getLogger(__name__)

LEGAL_COLLECTION = "legal_regulations_kz"


class LegalChunk(BaseModel):
    document_title: str = Field(
        ..., description="E.g., Customs Code of RK, Tax Code of RK"
    )
    article_number: str = Field(..., description="E.g., Article 124, Section 2")
    content_quote: str = Field(
        ..., description="Exact textual or tabular quote from the law"
    )
    relevance_score: float = Field(..., description="Cosine similarity score")


class LegalRAGResponse(BaseModel):
    query: str = Field(...)
    answer_synthesis: str = Field(
        ..., description="Customs legal advice with exact references"
    )
    supporting_laws: List[LegalChunk] = Field(default=[])


class ChunkRelevance(BaseModel):
    chunk_index: int = Field(
        ..., description="0-based index of the chunk in the input list"
    )
    relevance_score: int = Field(..., description="Relevance score from 1 to 10")
    reasoning: str = Field(..., description="1-sentence explanation of relevance")


class ChunkFilterResponse(BaseModel):
    scores: List[ChunkRelevance] = Field(
        ..., description="Relevance scores for each input chunk"
    )


class GeminiChunkFilter:
    """Reranks and filters retrieved legal chunks using Gemini Structured Outputs."""

    @classmethod
    def filter_chunks(
        cls, query: str, chunks: List[LegalChunk], threshold: int = 5
    ) -> List[LegalChunk]:
        if not chunks:
            return []

        chunks_text_list = []
        for i, chunk in enumerate(chunks):
            chunks_text_list.append(
                f"--- Чанк #{i} ---\n"
                f"Источник: {chunk.document_title}, {chunk.article_number}\n"
                f"Текст: {chunk.content_quote}\n"
            )
        chunks_payload = "\n".join(chunks_text_list)

        prompt = f"""
Вы — эксперт по таможенному праву РК. Ваша задача — оценить степень релевантности предоставленных выдержек из законов (чанков) относительно запроса пользователя по шкале от 1 до 10.

Запрос пользователя:
"{query}"

Список выдержек для оценки:
{chunks_payload}

Правила оценки (relevance_score от 1 до 10):
- 10: Чанк содержит прямой, точный ответ на вопрос пользователя или непосредственно описывает запрошенную норму.
- 7-9: Чанк очень близок к теме запроса, содержит важный контекст или смежные правила, необходимые для ответа.
- 5-6: Чанк умеренно релевантен, касается общей темы, но не содержит специфических деталей запроса.
- 1-4: Чанк практически или полностью не имеет отношения к запросу пользователя (например, говорит о другой процедуре или товаре).

Пожалуйста, верните оценку для КАЖДОГО чанка строго по его 0-индексу (от 0 до {len(chunks) - 1}).
"""

        try:
            logger.info("Calling Gemini for chunk relevance filtering")
            response = get_generator().generate_structured(
                prompt=prompt,
                response_schema=ChunkFilterResponse,
            )

            score_map = {item.chunk_index: item for item in response.scores}

            filtered = []
            for i, chunk in enumerate(chunks):
                relevance_info = score_map.get(i)
                if relevance_info:
                    logger.info(
                        f"Chunk #{i} ({chunk.article_number}): Gemini score = "
                        f"{relevance_info.relevance_score}/10"
                    )
                    if relevance_info.relevance_score >= threshold:
                        filtered.append(chunk)
                else:
                    filtered.append(chunk)

            return filtered
        except Exception as e:
            logger.error(f"Failed to filter chunks using Gemini: {e}", exc_info=True)
            return chunks


SYSTEM_PROMPT = """Вы — Ведущий таможенный юрист Республики Казахстан (Кеден Заңгері) и признанный эксперт в области таможенного права Евразийского экономического союза (ЕАЭС). Ваша цель — предоставлять безупречные, юридически выверенные, профессиональные и практически применимые консультации по вопросам таможенного регулирования, декларирования, классификации товаров и исчисления таможенных платежей в Республике Казахстан.

### 1. ОБЛАСТЬ ЭКСПЕРТИЗЫ И ЗАКОНОДАТЕЛЬНАЯ БАЗА
Вы опираетесь исключительно на официальные и актуальные нормативные правовые акты:
- Таможенный кодекс Республики Казахстан (ТК РК).
- Таможенный кодекс Евразийского экономического союза (ТК ЕАЭС).
- Налоговый кодекс Республики Казахстан (НК РК) в части импортного НДС, акцизов и других налогов при импорте.
- Решения Коллегии и Совета Евразийской экономической комиссии (ЕЭК).
- Закон РК "О регулировании торговой деятельности" и иные профильные нормативные акты Казахстана.

### 2. ПРАВИЛА РАБОТЫ С КОНТЕКСТОМ (RAG) И ЦИТИРОВАНИЕМ
- К каждому текущему вопросу пользователя вам предоставляется выборка официальных статей или нормативных документов из базы знаний (раздел "Официальные источники из базы знаний").
- Вам также предоставляются актуальные ставки и сборы из Конфигурационного Сервиса (раздел "Актуальные ставки и сборы"). При ответах на вопросы о ставках налогов и сборов вы обязаны ссылаться именно на эти значения, а не на устаревшие данные из базы знаний.
- При составлении ответа вы обязаны ссылаться на конкретные статьи, пункты и подпункты документов из выборки (например: "в соответствии с подпунктом 1 пункта 2 статьи 104 Таможенного кодекса РК...").
- Цитируйте ключевые фразы законов дословно или максимально близко к тексту, выделяя их кавычками.
- Если предоставленной выборки документов недостаточно для исчерпывающего ответа, прямо укажите: "В предоставленной выдержке из нормативной базы отсутствует прямая норма по данному вопросу, однако на практике..." и предложите общий юридический алгоритм действий, основанный на базовых принципах ТК РК и ТК ЕАЭС. Не придумывайте статьи и номера законов, которых нет в контексте.

### 3. ПРАВИЛА КОРРЕКТНОГО ВЕДЕНИЯ ДИАЛОГА (MULTI-TURN CHAT)
- Вы ведете непрерывный и последовательный диалог. Помните всю историю переписки в текущей сессии.
- Если пользователь задает уточняющий вопрос (например: "А какая ставка пошлины для этого случая?" или "Какие документы потребуются?"), вы обязаны соотнести его с контекстом предыдущих сообщений (ранее названным товаром, кодом ТН ВЭД или описанной ситуацией). Не просите пользователя повторить описание товара или детали, если они уже были названы в диалоге.
- Обращайтесь к пользователю уважительно, на "Вы". Сохраняйте деловой, конструктивный и академический тон.

### 4. СТРУКТУРА ОТВЕТА
Ваш ответ должен быть четко структурирован для удобства чтения:
1. **Резюме (Прямой ответ)**: Краткое и емкое заключение по сути вопроса (1–3 предложения).
2. **Правовое обоснование**: Подробный разбор ситуации со ссылками на конкретные статьи и цитированием норм ТК РК/ЕАЭС/НК РК.
3. **Рекомендации / Следующие шаги**: Практические советы для декларанта или импортера (какие документы подготовить, какие риски минимизировать, какие государственные органы посетить).

### 5. ЯЗЫКОВЫЕ ПРАВИЛА
- Отвечайте на том языке, на котором обратился пользователь (русский или казахский).
- Терминология должна быть строго официальной. Используйте общепринятые юридические понятия таможенного дела: "таможенная стоимость", "корректировка таможенной стоимости", "выпуск товаров", "утильсбор", "декларант", "таможенный представитель".
"""


class LegalRAGService:
    """Layout-aware Legal RAG (EAEU Customs Code, Tax Code, Technical Regulations).

    Dependencies are injected through the constructor — callers provide the
    vector store, embedding model, and text generator they want to use.
    """

    def __init__(
        self,
        vector_storage: VectorStorage,
        embedding_model: EmbeddingModel,
        text_generator: TextGenerator,
    ) -> None:
        self._vector_storage = vector_storage
        self._embedding_model = embedding_model
        self._text_generator = text_generator

    def get_current_rates(self) -> dict[str, float]:
        """Return current customs rates for citation in RAG responses.

        Delegates to ConfigService.  Returns an empty dict on failure so
        the RAG response synthesis is never blocked.
        """
        try:
            from app.core.config_service import config_service

            return config_service.get_all_current()
        except Exception as exc:
            logger.error("Failed to fetch current rates from ConfigService: %s", exc)
            return {}

    @observe(name="LegalRAGService.query_legal_base")
    async def query_legal_base(
        self, query: str, history: Optional[List[dict]] = None
    ) -> LegalRAGResponse:
        """Embed query → vector search → chunk filter → synthesize answer."""
        logger.info(f"Querying customs legal base for: {query}")

        # Generate embedding vector via the injected seam
        query_vector = self._embedding_model.embed_text(
            text=query,
            task_type="RETRIEVAL_QUERY",
        )

        retrieved_chunks: List[LegalChunk] = []
        try:
            search_result = self._vector_storage.query_points(
                collection_name=LEGAL_COLLECTION,
                query_vector=query_vector,
                limit=6,
            ).points

            for hit in search_result:
                payload = hit.payload or {}
                retrieved_chunks.append(
                    LegalChunk(
                        document_title=payload.get(
                            "document_title", "Нормативный правовой акт"
                        ),
                        article_number=payload.get("article_number", "Статья"),
                        content_quote=payload.get("content_quote", ""),
                        relevance_score=hit.score,
                    )
                )

            # Apply post-retrieval relevance filter
            if retrieved_chunks:
                original_count = len(retrieved_chunks)
                retrieved_chunks = GeminiChunkFilter.filter_chunks(
                    query, retrieved_chunks, threshold=5
                )
                logger.info(
                    f"Post-retrieval filter: kept {len(retrieved_chunks)} / {original_count} chunks"
                )

                # Safeguard: if Gemini filtered out everything, keep the top-1 chunk
                if not retrieved_chunks and search_result:
                    payload = search_result[0].payload or {}
                    retrieved_chunks = [
                        LegalChunk(
                            document_title=payload.get(
                                "document_title", "Нормативный правовой акт"
                            ),
                            article_number=payload.get("article_number", "Статья"),
                            content_quote=payload.get("content_quote", ""),
                            relevance_score=search_result[0].score,
                        )
                    ]
        except Exception as e:
            logger.error(f"Vector search failed, falling back to basic mock: {e}")

        # Fallback if no chunks found
        if not retrieved_chunks:
            retrieved_chunks = [
                LegalChunk(
                    document_title="Таможенный кодекс Республики Казахстан",
                    article_number="Статья 104",
                    content_quote="Таможенная стоимость товаров, ввозимых на таможенную территорию Союза, определяется, если товары пересекли границу...",
                    relevance_score=0.5,
                )
            ]

        # Build synthesis prompt
        citations = "\n\n".join(
            [
                f'Source: {c.document_title}, {c.article_number}\nQuote: "{c.content_quote}"'
                for c in retrieved_chunks
            ]
        )

        # Prepare message history for chat
        gemini_history: list = []
        if history:
            for turn in history:
                gemini_history.append(
                    {"role": turn["role"], "content": turn["content"]}
                )

        # Fetch current rates from Config Service for accurate citations
        rates = self.get_current_rates()
        rates_text = ""
        if rates:
            rate_lines = []
            if "import_vat" in rates:
                rate_lines.append(
                    f"  - Импортный НДС: {rates['import_vat'] * 100:.0f}%"
                )
            if "customs_processing_fee" in rates:
                rate_lines.append(
                    f"  - Таможенный сбор: {rates['customs_processing_fee']:,.0f} KZT"
                )
            if "mci" in rates:
                rate_lines.append(f"  - МРП: {rates['mci']:,.0f} KZT")
            if rate_lines:
                rates_text = (
                    "\n\nАктуальные ставки и сборы (из Конфигурационного Сервиса):\n"
                    + "\n".join(rate_lines)
                )

        current_turn_content = (
            f"Вопрос пользователя: {query}\n\n"
            f"Официальные источники из базы знаний для справки:\n"
            f"{citations}"
            f"{rates_text}"
        )
        gemini_history.append({"role": "user", "content": current_turn_content})

        try:
            chat_response_text = self._text_generator.generate_chat(
                system_instruction=SYSTEM_PROMPT,
                message_history=gemini_history,
            )

            if settings.LANGFUSE_ENABLED:
                try:
                    from langfuse import get_client

                    get_client().update_current_span(
                        metadata={
                            "chunks_count": len(retrieved_chunks),
                            "source_citations": [
                                f"{c.document_title} - {c.article_number}"
                                for c in retrieved_chunks
                            ],
                        }
                    )
                except Exception as lf_err:
                    logger.warning(f"Failed to update RAG span: {lf_err}")

            return LegalRAGResponse(
                query=query,
                answer_synthesis=chat_response_text,
                supporting_laws=retrieved_chunks,
            )
        except Exception as e:
            logger.error(f"Legal RAG synthesis failed: {e}")
            return LegalRAGResponse(
                query=query,
                answer_synthesis=f"Ошибка синтеза нормативной базы: {str(e)}",
                supporting_laws=retrieved_chunks,
            )
