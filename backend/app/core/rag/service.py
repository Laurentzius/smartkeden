import logging
from typing import List, Optional
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from app.core.config import settings
from app.core.vertex_client import GeminiVertexClient
from langfuse import observe
logger = logging.getLogger(__name__)

class LegalChunk(BaseModel):
    document_title: str = Field(..., description="E.g., Customs Code of RK, Tax Code of RK")
    article_number: str = Field(..., description="E.g., Article 124, Section 2")
    content_quote: str = Field(..., description="Exact textual or tabular quote from the law")
    relevance_score: float = Field(..., description="Cosine similarity score")

class LegalRAGResponse(BaseModel):
    query: str = Field(...)
    answer_synthesis: str = Field(..., description="Customs legal advice with exact references")
    supporting_laws: List[LegalChunk] = Field(default=[])


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
    """
    Layout-aware Legal RAG (EAEU Customs Code, Tax Code, Technical Regulations).
    Uses Qdrant + Blockify structural chunking.
    """
    _qdrant_client: Optional[QdrantClient] = None

    @classmethod
    @observe(name="LegalRAGService.query_legal_base")
    async def query_legal_base(cls, query: str, history: Optional[List[dict]] = None) -> LegalRAGResponse:
        """
        1. Embed the query.
        2. Perform vector search in Qdrant for matching articles/tables.
        3. Synthesize expert legal answer with citations using Gemini Flash.
        """
        logger.info(f"Querying customs legal base for: {query}")
        from app.core.rag.indexer import LegalRAGIndexer
        storage = LegalRAGIndexer._vector_storage
        embedder = LegalRAGIndexer._embedding_model

        # Generate embedding vector via the embedding model seam
        query_vector = embedder.embed_text(
            text=query,
            task_type="RETRIEVAL_QUERY"
        )
        
        retrieved_chunks = []
        try:
            search_result = storage.query_points(
                collection_name="legal_regulations_kz",
                query_vector=query_vector,
                limit=3
            ).points
            
            for hit in search_result:
                payload = hit.payload or {}
                retrieved_chunks.append(
                    LegalChunk(
                        document_title=payload.get("document_title", "Нормативный правовой акт"),
                        article_number=payload.get("article_number", "Статья"),
                        content_quote=payload.get("content_quote", ""),
                        relevance_score=hit.score
                    )
                )
        except Exception as e:
            logger.error(f"Vector search failed, falling back to basic mock: {e}")
            
        # Fallback if no chunks found
        if not retrieved_chunks:
            retrieved_chunks = [
                LegalChunk(
                    document_title="Таможенный кодекс Республики Казахстан",
                    article_number="Статья 104",
                    content_quote="Таможенная стоимость товаров, ввозимых на таможенную территорию Союза, определяется, если товары пересекли границу...",
                    relevance_score=0.5
                )
            ]
        
        # Build synthesis prompt
        citations = "\n\n".join([
            f"Source: {c.document_title}, {c.article_number}\nQuote: \"{c.content_quote}\"" 
            for c in retrieved_chunks
        ])
        

        # Prepare message history for GeminiVertexClient.generate_chat_response
        gemini_history = []
        if history:
            for turn in history:
                gemini_history.append({"role": turn["role"], "content": turn["content"]})

        # Format current turn: append the retrieved citations as reference sources for the latest user message
        current_turn_content = (
            f"Вопрос пользователя: {query}\n\n"
            f"Официальные источники из базы знаний для справки:\n"
            f"{citations}"
        )

        # Append the decorated current turn to the chat history
        gemini_history.append({"role": "user", "content": current_turn_content})

        try:
            # Use Gemini native chat response supporting history + system instruction
            chat_response_text = GeminiVertexClient.generate_chat_response(
                system_instruction=SYSTEM_PROMPT,
                message_history=gemini_history
            )

            if settings.LANGFUSE_ENABLED:
                try:
                    from langfuse import get_client
                    get_client().update_current_span(
                        metadata={"chunks_count": len(retrieved_chunks), "source_citations": [f"{c.document_title} - {c.article_number}" for c in retrieved_chunks]}
                    )
                except Exception as lf_err:
                    logger.warning(f"Failed to update RAG span: {lf_err}")

            return LegalRAGResponse(
                query=query,
                answer_synthesis=chat_response_text,
                supporting_laws=retrieved_chunks
            )
        except Exception as e:
            logger.error(f"Legal RAG synthesis failed: {e}")
            return LegalRAGResponse(
                query=query,
                answer_synthesis=f"Ошибка синтеза нормативной базы: {str(e)}",
                supporting_laws=retrieved_chunks
            )
