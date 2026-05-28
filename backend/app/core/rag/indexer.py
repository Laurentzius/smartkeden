import logging
import hashlib
import uuid
from collections import deque
from typing import List, Dict, Any, Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchText, MatchValue

from app.core.config import settings
from app.core.vertex_client import GeminiVertexClient
from app.core.local_embeddings import LocalEmbeddingModel
from app.core.rag.service import LegalChunk
from app.core.rag.seams import VectorStorage, EmbeddingModel, QdrantVectorStorageAdapter, LocalEmbeddingModelAdapter
logger = logging.getLogger(__name__)

# Sample/Seeding law data for Kazakhstan Customs & Tax Codes (IdeaBlocks style)
SEED_LAW_BLOCKS = [
    {
        "document_title": "Таможенный кодекс Республики Казахстан",
        "article_number": "Статья 104",
        "content_quote": "Таможенная стоимость товаров, ввозимых на таможенную территорию Союза, определяется, если товары пересекли таможенную границу Союза, и в отношении таких товаров принято решение о таможенном декларировании.",
        "tags": ["CUSTOMS_VALUE", "CUSTOMS_CODE", "REGULATION"],
        "keywords": "таможенная стоимость, ввоз товаров, декларирование, таможенная граница"
    },
    {
        "document_title": "Таможенный кодекс Республики Казахстан",
        "article_number": "Статья 75",
        "content_quote": "Таможенные сборы представляют собой обязательные платежи, взимаемые таможенными органами за совершение ими действий, связанных с выпуском товаров, таможенным сопровождением товаров, а также за совершение иных действий.",
        "tags": ["CUSTOMS_FEES", "CUSTOMS_CODE", "PAYMENTS"],
        "keywords": "таможенные сборы, обязательные платежи, выпуск товаров, таможенные органы"
    },
    {
        "document_title": "Кодекс Республики Казахстан О налогах и других обязательных платежах в бюджет (Налоговый кодекс)",
        "article_number": "Статья 422",
        "content_quote": "Ставка налога на добавленную стоимость составляет 12 процентов и применяется к размеру облагаемого оборота и облагаемого импорта, за исключением случаев, предусмотренных настоящим Кодексом.",
        "tags": ["TAX_CODE", "VAT", "IMPORT_VAT"],
        "keywords": "налог на добавленную стоимость, НДС 12%, облагаемый импорт, налоговая ставка"
    },
    {
        "document_title": "Кодекс Республики Казахстан О налогах и других обязательных платежах в бюджет (Налоговый кодекс)",
        "article_number": "Статья 462",
        "content_quote": "Плательщиками акцизов являются физические и юридические лица, которые производят подакцизные товары на территории Республики Казахстан и (или) импортируют подакцизные товары на территорию Республики Казахстан.",
        "tags": ["TAX_CODE", "EXCISE", "EXCISE_PLAYERS"],
        "keywords": "акцизы, подакцизные товары, импорт подакцизных товаров, плательщики акцизов"
    },
    {
        "document_title": "Экологический кодекс Республики Казахстан",
        "article_number": "Статья 386",
        "content_quote": "Производители и импортеры отдельных видов товаров (продукции), перечень которых утверждается уполномоченным органом в области охраны окружающей среды, обязаны обеспечивать сбор, транспортировку, подготовку к повторному использованию, сортировку, обработку, переработку, обезвреживание и (или) утилизацию отходов, образующихся после утраты потребительских свойств таких товаров (продукции), путем внесения утилизационного платежа.",
        "tags": ["ECO_CODE", "RECYCLING_FEE", "ENVIRONMENT"],
        "keywords": "утилизационный платеж, утильсбор, импортеры товаров, утилизация отходов"
    }
]

class LegalRAGIndexer:
    """
    Ingest, segment, and index RK laws and EAEU decisions into Qdrant vector database.
    Uses local Sentence‑Transformer model for 384‑dim multilingual embeddings.
    """

    COLLECTION_NAME = "legal_regulations_kz"
    VECTOR_DIMENSION = settings.EMBEDDING_DIMENSION
    HS_CODE_COLLECTION_NAME = "hs_code_directory"
    HS_CODE_VECTOR_DIMENSION = settings.EMBEDDING_DIMENSION
    _vector_storage: VectorStorage = QdrantVectorStorageAdapter()
    _embedding_model: EmbeddingModel = LocalEmbeddingModelAdapter()
    _fallback_client = None

    @classmethod
    def get_client(cls) -> QdrantClient:
        """Retrieves active QdrantClient instance from config settings."""
        from app.core.rag.seams import QdrantVectorStorageAdapter
        if isinstance(cls._vector_storage, QdrantVectorStorageAdapter):
            return cls._vector_storage._client
        return QdrantClient(":memory:")

    @classmethod
    def setup_collection(cls, force_recreate: bool = False) -> bool:
        """
        Creates/initializes the legal regulations collection in Qdrant.
        Vector dimension and distance metric are read from settings.
        """
        return cls._vector_storage.setup_collection(
            collection_name=cls.COLLECTION_NAME,
            vector_dimension=cls.VECTOR_DIMENSION,
            force_recreate=force_recreate
        )
    @classmethod
    def deduplicate_blocks_local(
        cls,
        blocks: List[Dict[str, Any]],
        similarity_threshold: float = 0.75,
        max_iterations: int = 4,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        In-process deduplication using Granite embeddings + rule-based merging.

        Replaces the Blockify Distill Docker service with a fully local,
        deterministic deduplication pipeline.

        Parameters
        ----------
        blocks:
            Parsed blocks in internal dict format (document_title, article_number,
            content_quote, tags, keywords).
        similarity_threshold:
            Cosine similarity threshold (0.0–1.0). Default 0.75.
        max_iterations:
            Max clustering/merge iterations. Default 4.

        Returns
        -------
        Deduplicated blocks in internal dict format, or ``None`` on error
        (caller falls back to original blocks).
        """
        # Phase 1: <2 blocks → return as-is
        if not blocks:
            return None
        if len(blocks) < 2:
            return list(blocks)

        if not LocalEmbeddingModel.is_available():
            logger.warning("Local embedding model not available, skipping dedup")
            return None

        working_blocks = [dict(b) for b in blocks]
        threshold = similarity_threshold

        for iteration in range(max_iterations):
            # Phase 3.1: Embed all blocks
            texts = [
                f"{b.get('article_number', '')} {b.get('content_quote', '')}"
                for b in working_blocks
            ]

            try:
                embeddings = np.array([
                    LocalEmbeddingModel.encode(t) for t in texts
                ])
            except Exception as exc:
                logger.warning("Embedding failed at iteration %d: %s", iteration, exc)
                return None

            # Cosine similarity matrix
            sim_matrix = cosine_similarity(embeddings)

            # Phase 3.2: BFS connected components
            n = len(working_blocks)
            visited = [False] * n
            clusters = []

            for i in range(n):
                if visited[i]:
                    continue
                cluster = []
                queue = deque([i])
                visited[i] = True
                while queue:
                    idx = queue.popleft()
                    cluster.append(idx)
                    for j in range(n):
                        if not visited[j] and sim_matrix[idx][j] >= threshold:
                            visited[j] = True
                            queue.append(j)
                clusters.append(cluster)

            # If all clusters are size 1, no more merges possible
            if all(len(c) == 1 for c in clusters):
                break

            # Phase 3.3: Merge each cluster
            merged_blocks = []
            merger_occurred = False

            for cluster in clusters:
                if len(cluster) == 1:
                    merged_blocks.append(working_blocks[cluster[0]])
                    continue

                merger_occurred = True
                cluster_blocks = [working_blocks[i] for i in cluster]

                # Check if all have same article_number
                first_art = cluster_blocks[0].get("article_number", "")
                all_same_article = all(
                    b.get("article_number", "") == first_art
                    for b in cluster_blocks
                )

                if all_same_article:
                    # Same article → dict.fromkeys preserves insertion order
                    merged_content = "\n".join(dict.fromkeys(
                        "\n".join(
                            b.get("content_quote", "") for b in cluster_blocks
                        ).splitlines()
                    ))
                else:
                    # Different article → concat with "(дубль из {art})" prefix
                    parts = []
                    for b in cluster_blocks:
                        art = b.get("article_number", "")
                        content = b.get("content_quote", "")
                        if art == first_art:
                            parts.append(content)
                        else:
                            parts.append(f"(дубль из {art})\n{content}")
                    merged_content = "\n---\n".join(parts)

                # Merge tags (ordered unique)
                merged_tags = list(dict.fromkeys(
                    sum([b.get("tags", []) for b in cluster_blocks], [])
                ))
                # Merge keywords (ordered unique)
                all_kw = ", ".join(
                    b.get("keywords", "") for b in cluster_blocks
                ).split(", ")
                merged_kw = ", ".join(
                    k for k in dict.fromkeys(all_kw) if k
                )

                merged_blocks.append({
                    "document_title": cluster_blocks[0].get(
                        "document_title", "Нормативный акт"
                    ),
                    "article_number": first_art,
                    "content_quote": merged_content.strip(),
                    "tags": merged_tags,
                    "keywords": merged_kw,
                })

            if not merger_occurred:
                break

            working_blocks = merged_blocks

            # Phase 3.6: Ramp up threshold after iteration 2
            if iteration >= 2:
                threshold = min(threshold + 0.01, 0.98)

        # Phase 4: Return deduplicated blocks with stats log
        starting_count = len(blocks)
        final_count = len(working_blocks)
        reduction_pct = ((starting_count - final_count) / starting_count) * 100

        logger.info(
            "Local dedup: %d → %d blocks (%.0f%% reduction)",
            starting_count, final_count, reduction_pct,
        )

        return working_blocks

    @classmethod
    def generate_point_id(cls, doc_title: str, article_number: str, content_quote: str) -> str:
        """
        Generates a deterministic UUIDv5 for a chunk based on its document title,
        article number, and content hash.
        """
        content_hash = hashlib.sha256(content_quote.encode("utf-8")).hexdigest()
        doc_key = f"{str(doc_title)}:{str(article_number)}"
        doc_key_ns = uuid.uuid5(uuid.NAMESPACE_DNS, doc_key)
        return str(uuid.uuid5(doc_key_ns, content_hash))
    @classmethod
    def parse_and_index_document(cls, raw_text: str, doc_title: str, doc_type: str = "code") -> int:
        """
        Parses a raw legal document into structured blocks and indexes into Qdrant.
        Returns the number of new/updated points indexed.
        """
        # Step 1: Parse locally into structured blocks
        blocks = cls.parse_legal_text_to_blocks(raw_text, doc_title, doc_type=doc_type)
        if not blocks:
            logger.warning("No blocks extracted from document: %s", doc_title)
            return 0
        # Step 2: Local deduplication via Granite embeddings
        deduped = cls.deduplicate_blocks_local(blocks)
        if deduped is not None:
            logger.info(
                "Local dedup: %d → %d blocks",
                len(blocks), len(deduped),
            )
            blocks = deduped
        else:
            logger.info("Local dedup skipped, using %d parsed blocks", len(blocks))
        # Step 3: Index into Qdrant using delta sync
        res = cls.update_document_index(blocks, doc_title)
        return res.get("added", 0)
    @classmethod
    def parse_legal_text_to_blocks(cls, raw_text: str, doc_title: str, doc_type: str = "code") -> List[Dict[str, Any]]:
        """Parses raw legal text into structured blocks (articles and sections), preserving article boundaries.
        Splits text by structural markers (e.g., 'Статья X') or paragraphs,
        producing clean, semantically dense IdeaBlock structures.
        """
        from app.core.rag.parsers import DocumentParserRegistry
        return DocumentParserRegistry.parse(raw_text, doc_title, doc_type=doc_type)
    @classmethod
    def index_blocks(cls, blocks: List[Dict[str, Any]]) -> int:
        """
        Ingests parsed blocks into Qdrant collection.
        Uses deterministic UUIDv5 point IDs from document_title + article_number + content_hash
        for idempotent upsert, and SHA256 content hash for dedup.
        """
        cls.setup_collection()
        points = []
        skipped = 0
        updated = 0
        for block in blocks:
            point_id = cls.generate_point_id(
                doc_title=block["document_title"],
                article_number=block["article_number"],
                content_quote=block["content_quote"]
            )
            content_hash = hashlib.sha256(block["content_quote"].encode("utf-8")).hexdigest()
            # Dedup check: query by point_id (deterministic UUIDv5)
            try:
                existing = cls._vector_storage.retrieve_points(
                    collection_name=cls.COLLECTION_NAME,
                    ids=[point_id]
                )
                if existing:
                    existing_hash = existing[0].payload.get("content_hash", "")
                    if existing_hash == content_hash:
                        skipped += 1
                        continue  # Exact match, skip
                    else:
                        updated += 1  # Content changed, will overwrite
            except Exception:
                pass  # If retrieve fails, proceed with upsert
            text_to_embed = f"Document: {block['document_title']}\nReference: {block['article_number']}\nContent: {block['content_quote']}"
            # Generate embedding vector via local Sentence‑Transformer model
            vector = cls._embedding_model.embed_text(
                text=text_to_embed,
                task_type="RETRIEVAL_DOCUMENT"
            )
            payload = {
                "document_title": block["document_title"],
                "article_number": block["article_number"],
                "content_quote": block["content_quote"],
                "content_hash": content_hash,
                "tags": block.get("tags", []),
                "keywords": block.get("keywords", "")
            }
            points.append(PointStruct(
                id=point_id,
                vector=vector,
                payload=payload
            ))
        logger.info(f"Upserting {len(points)} points into Qdrant collection: {cls.COLLECTION_NAME} "
                     f"(skipped {skipped} duplicates, updated {updated})")
        if points:
            cls._vector_storage.upsert_points(
                collection_name=cls.COLLECTION_NAME,
                points=points
            )
        return len(points)
    @classmethod
    def update_document_index(cls, blocks: List[Dict[str, Any]], doc_title: str) -> Dict[str, int]:
        """
        Syncs document blocks pointwise. Computes additions and deletions using
        Qdrant Scroll API.
        """
        cls.setup_collection()
        new_blocks_map = {}
        for block in blocks:
            pid = cls.generate_point_id(
                doc_title=block["document_title"],
                article_number=block["article_number"],
                content_quote=block["content_quote"]
            )
            new_blocks_map[pid] = block
        new_chunk_ids = set(new_blocks_map.keys())
        # Retrieve existing point IDs for this document from Qdrant
        old_chunk_ids = set()
        offset = None
        filter_cond = Filter(
            must=[
                FieldCondition(
                    key="document_title",
                    match=MatchValue(value=doc_title)
                )
            ]
        )
        try:
            while True:
                res_points, next_offset = cls._vector_storage.scroll_points(
                    collection_name=cls.COLLECTION_NAME,
                    filter_cond=filter_cond,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False
                )
                for pt in res_points:
                    old_chunk_ids.add(pt.id)
                if next_offset is None or not res_points:
                    break
                offset = next_offset
        except Exception as e:
            logger.warning(f"Failed to scroll points for document '{doc_title}', treating old as empty: {e}")
            pass
        to_delete = old_chunk_ids - new_chunk_ids
        to_add = new_chunk_ids - old_chunk_ids
        unchanged = old_chunk_ids & new_chunk_ids
        # Delete obsolete points
        if to_delete:
            cls._vector_storage.delete_points(cls.COLLECTION_NAME, list(to_delete))
        # Embed and upsert newly added/modified points
        points_to_upsert = []
        for pid in to_add:
            block = new_blocks_map[pid]
            content_hash = hashlib.sha256(block["content_quote"].encode("utf-8")).hexdigest()
            text_to_embed = f"Document: {block['document_title']}\nReference: {block['article_number']}\nContent: {block['content_quote']}"
            vector = cls._embedding_model.embed_text(
                text=text_to_embed,
                task_type="RETRIEVAL_DOCUMENT"
            )
            payload = {
                "document_title": block["document_title"],
                "article_number": block["article_number"],
                "content_quote": block["content_quote"],
                "content_hash": content_hash,
                "tags": block.get("tags", []),
                "keywords": block.get("keywords", "")
            }
            points_to_upsert.append(PointStruct(
                id=pid,
                vector=vector,
                payload=payload
            ))
        if points_to_upsert:
            cls._vector_storage.upsert_points(
                collection_name=cls.COLLECTION_NAME,
                points=points_to_upsert
            )
        logger.info(
            f"Pointwise sync for '{doc_title}' completed. "
            f"Added: {len(to_add)}, Deleted: {len(to_delete)}, Unchanged: {len(unchanged)}"
        )
        return {
            "added": len(to_add),
            "deleted": len(to_delete),
            "unchanged": len(unchanged)
        }
    @classmethod
    def seed_initial_legal_base(cls) -> int:
        """Seeds the standard reference RK codes and EAEU decisions on startup."""
        logger.info("Seeding initial legal base with standard Customs/Tax Code blocks")
        return cls.index_blocks(SEED_LAW_BLOCKS)

    @classmethod
    def setup_hs_code_collection(cls, force_recreate: bool = False) -> bool:
        """Creates/initializes the HS code directory collection in Qdrant."""
        return cls._vector_storage.setup_collection(
            collection_name=cls.HS_CODE_COLLECTION_NAME,
            vector_dimension=cls.HS_CODE_VECTOR_DIMENSION,
            force_recreate=force_recreate
        )

    @classmethod
    def seed_hs_code_directory(cls) -> int:
        """Seeds the hs_code_directory with sample ТН ВЭД ЕАЭС entries for MVP."""
        cls.setup_hs_code_collection()
        seed_entries = [
            {
                "hs_code": "9503008900",
                "product_name_ru": "Игрушки детские прочие",
                "product_name_en": "Other children's toys",
                "duty_rate_percent": 5.0,
                "excise_rate_percent": 0.0,
                "is_subject_to_recycling_fee": False,
                "section": "XX",
                "group": 95,
                "reasoning_notes": "Разные промышленные товары; игрушки, игры и спортивный инвентарь"
            },
            {
                "hs_code": "8471300000",
                "product_name_ru": "Портативные цифровые вычислительные машины",
                "product_name_en": "Portable digital computers",
                "duty_rate_percent": 0.0,
                "excise_rate_percent": 0.0,
                "is_subject_to_recycling_fee": True,
                "section": "XVI",
                "group": 84,
                "reasoning_notes": "Машины, оборудование и механизмы; электротехническое оборудование"
            },
            {
                "hs_code": "6204623900",
                "product_name_ru": "Брюки женские текстильные (хлопок)",
                "product_name_en": "Women's trousers cotton",
                "duty_rate_percent": 12.0,
                "excise_rate_percent": 0.0,
                "is_subject_to_recycling_fee": False,
                "section": "XI",
                "group": 62,
                "reasoning_notes": "Текстильные материалы и текстильные изделия; одежда и принадлежности"
            },
            {
                "hs_code": "8703231981",
                "product_name_ru": "Автомобили легковые с ДВС 1500-3000 см³",
                "product_name_en": "Passenger cars ICE 1500-3000cc",
                "duty_rate_percent": 15.0,
                "excise_rate_percent": 0.0,
                "is_subject_to_recycling_fee": True,
                "section": "XVII",
                "group": 87,
                "reasoning_notes": "Средства наземного транспорта; автомобили, тракторы"
            },
            {
                "hs_code": "4011100009",
                "product_name_ru": "Шины пневматические для легковых автомобилей",
                "product_name_en": "Passenger cars",
                "duty_rate_percent": 10.0,
                "excise_rate_percent": 0.0,
                "is_subject_to_recycling_fee": True,
                "section": "VII",
                "group": 40,
                "reasoning_notes": "Пластмассы и изделия из них; каучук и резиновые изделия"
            },
        ]

        points = []
        for entry in seed_entries:
            hs = entry["hs_code"]
            text_to_embed = f"HS Code: {hs}\nProduct: {entry['product_name_ru']}\nNotes: {entry['reasoning_notes']}"
            vector = cls._embedding_model.embed_text(
                text=text_to_embed,
                task_type="RETRIEVAL_DOCUMENT"
            )
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"hs_code/{hs}"))
            payload = {
                "hs_code": hs,
                "product_name_ru": entry["product_name_ru"],
                "product_name_en": entry["product_name_en"],
                "duty_rate_percent": entry["duty_rate_percent"],
                "excise_rate_percent": entry["excise_rate_percent"],
                "is_subject_to_recycling_fee": entry["is_subject_to_recycling_fee"],
                "section": entry["section"],
                "group": entry["group"],
                "reasoning_notes": entry["reasoning_notes"],
            }
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))

        logger.info(f"Upserting {len(points)} HS code points into Qdrant collection: {cls.HS_CODE_COLLECTION_NAME}")
        if points:
            cls._vector_storage.upsert_points(
                collection_name=cls.HS_CODE_COLLECTION_NAME,
                points=points
            )
        return len(points)