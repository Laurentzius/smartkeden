import datetime
import logging
import hashlib
import uuid
from collections import deque
from typing import List, Dict, Any, Optional

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from qdrant_client.models import (
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

from app.core.config import settings
from app.core.local_embeddings import LocalEmbeddingModel
from app.core.rag.seams import (
    VectorStorage,
    EmbeddingModel,
    QdrantVectorStorageAdapter,
    LocalEmbeddingModelAdapter,
)
from app.core.rag.seed_loader import load_seed_law_blocks, load_seed_hs_codes


logger = logging.getLogger(__name__)


# Sample/Seeding law data loaded from JSON — kept as module-level for backward compat
SEED_LAW_BLOCKS = load_seed_law_blocks()


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

    # NOTE: get_client() was removed — callers must use the VectorStorage seam.
    # The indexer remains the sole owner of _vector_storage for seeding/indexing ops.

    @classmethod
    def setup_collection(cls, force_recreate: bool = False) -> bool:
        """
        Creates/initializes the legal regulations collection in Qdrant.
        Vector dimension and distance metric are read from settings.
        """
        return cls._vector_storage.setup_collection(
            collection_name=cls.COLLECTION_NAME,
            vector_dimension=cls.VECTOR_DIMENSION,
            force_recreate=force_recreate,
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
        Fully local deterministic deduplication pipeline using cosine similarity
        and rule-based merging — no external service required.
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
                embeddings = np.array([LocalEmbeddingModel.encode(t) for t in texts])
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
                    b.get("article_number", "") == first_art for b in cluster_blocks
                )

                if all_same_article:
                    # Same article → dict.fromkeys preserves insertion order
                    merged_content = "\n".join(
                        dict.fromkeys(
                            "\n".join(
                                b.get("content_quote", "") for b in cluster_blocks
                            ).splitlines()
                        )
                    )
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
                merged_tags = list(
                    dict.fromkeys(sum([b.get("tags", []) for b in cluster_blocks], []))
                )
                # Merge keywords (ordered unique)
                all_kw = ", ".join(b.get("keywords", "") for b in cluster_blocks).split(
                    ", "
                )
                merged_kw = ", ".join(k for k in dict.fromkeys(all_kw) if k)

                merged_blocks.append(
                    {
                        "document_title": cluster_blocks[0].get(
                            "document_title", "Нормативный акт"
                        ),
                        "article_number": first_art,
                        "content_quote": merged_content.strip(),
                        "tags": merged_tags,
                        "keywords": merged_kw,
                    }
                )

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
            starting_count,
            final_count,
            reduction_pct,
        )

        return working_blocks

    @classmethod
    def generate_point_id(
        cls, doc_title: str, article_number: str, content_quote: str
    ) -> str:
        """
        Generates a deterministic UUIDv5 for a chunk based on its document title,
        article number, and content hash.
        """
        content_hash = hashlib.sha256(content_quote.encode("utf-8")).hexdigest()
        doc_key = f"{str(doc_title)}:{str(article_number)}"
        doc_key_ns = uuid.uuid5(uuid.NAMESPACE_DNS, doc_key)
        return str(uuid.uuid5(doc_key_ns, content_hash))

    @classmethod
    def parse_and_index_document(
        cls, raw_text: str, doc_title: str, doc_type: str = "code"
    ) -> int:
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
                len(blocks),
                len(deduped),
            )
            blocks = deduped
        else:
            logger.info("Local dedup skipped, using %d parsed blocks", len(blocks))
        # Step 3: Index into Qdrant using delta sync
        res = cls.update_document_index(blocks, doc_title)
        return res.get("added", 0)

    @classmethod
    def parse_legal_text_to_blocks(
        cls, raw_text: str, doc_title: str, doc_type: str = "code"
    ) -> List[Dict[str, Any]]:
        """Parses raw legal text into structured blocks (articles and sections), preserving article boundaries.
        Splits text by structural markers (e.g., 'Статья X') or paragraphs,
        producing clean, semantically dense KnowledgeChunk structures.
        """
        from app.core.rag.parsers import DocumentParserRegistry

        return DocumentParserRegistry.parse(raw_text, doc_title, doc_type=doc_type)

    @classmethod
    def _normalize_source_metadata(
        cls, markdown_text: str, source_metadata: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Normalize and enrich source metadata with conservative defaults and computed fields.

        Must produce: source_filename, source_type, source_hash, converter, ocr_applied, ingested_at.
        """
        meta = dict(source_metadata) if source_metadata else {}

        # Conservative defaults for required provenance fields
        meta.setdefault("source_filename", "unknown")
        meta.setdefault("converter", "unknown")
        meta.setdefault("source_type", "markdown")
        meta.setdefault("ocr_applied", False)

        # Compute source_hash from markdown if not explicitly provided
        if not meta.get("source_hash"):
            meta["source_hash"] = hashlib.sha256(
                markdown_text.encode("utf-8")
            ).hexdigest()

        # Timestamp the ingestion
        if not meta.get("ingested_at"):
            meta["ingested_at"] = (
                datetime.datetime.now(datetime.timezone.utc).isoformat()
            )

        return meta

    @classmethod
    def parse_and_index_markdown(
        cls,
        markdown_text: str,
        doc_title: str,
        source_metadata: Dict[str, Any],
    ) -> Dict[str, int]:
        """Parse MarkItDown-produced Markdown into legal RAG chunks with source provenance.

        Validates inputs, enriches source metadata, parses via ``doc_type="markdown"``,
        deduplicates, and syncs into Qdrant via pointwise delta. Returns the same
        ``{added, deleted, unchanged}`` count dict from ``update_document_index``,
        or zero counts when no chunks are extracted.
        """
        # Validate
        if not markdown_text or not markdown_text.strip():
            logger.warning(
                "Empty markdown text rejected for doc_title='%s'", doc_title
            )
            return {"added": 0, "deleted": 0, "unchanged": 0}
        if not doc_title or not doc_title.strip():
            logger.warning("Missing doc_title rejected for markdown ingestion")
            return {"added": 0, "deleted": 0, "unchanged": 0}

        # Normalize and enrich source metadata
        enriched_meta = cls._normalize_source_metadata(markdown_text, source_metadata)

        # Parse
        from app.core.rag.parsers import DocumentParserRegistry

        blocks = DocumentParserRegistry.parse(
            markdown_text, doc_title, doc_type="markdown"
        )
        if not blocks:
            logger.warning(
                "No chunks extracted from markdown for '%s'", doc_title
            )
            return {"added": 0, "deleted": 0, "unchanged": 0}

        # Enrich each block with source provenance so it survives indexing
        for block in blocks:
            block.update(enriched_meta)

        # Deduplicate
        deduped = cls.deduplicate_blocks_local(blocks)
        if deduped is not None:
            logger.info(
                "Local dedup: %d → %d blocks", len(blocks), len(deduped)
            )
            blocks = deduped
        else:
            logger.info("Local dedup skipped, using %d parsed blocks", len(blocks))

        # Pointwise delta sync
        return cls.update_document_index(blocks, doc_title)


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
                content_quote=block["content_quote"],
            )
            content_hash = hashlib.sha256(
                block["content_quote"].encode("utf-8")
            ).hexdigest()
            # Dedup check: query by point_id (deterministic UUIDv5)
            try:
                existing = cls._vector_storage.retrieve_points(
                    collection_name=cls.COLLECTION_NAME, ids=[point_id]
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
                text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
            )
            payload = {
                "document_title": block["document_title"],
                "article_number": block["article_number"],
                "content_quote": block["content_quote"],
                "content_hash": content_hash,
                "tags": block.get("tags", []),
                "keywords": block.get("keywords", ""),
            }
            # Carry unknown/extra block fields (e.g. source provenance) into payload
            for key, value in block.items():
                if key not in payload and not key.startswith("_"):
                    payload[key] = value
            points.append(PointStruct(id=point_id, vector=vector, payload=payload))
        logger.info(
            f"Upserting {len(points)} points into Qdrant collection: {cls.COLLECTION_NAME} "
            f"(skipped {skipped} duplicates, updated {updated})"
        )
        if points:
            cls._vector_storage.upsert_points(
                collection_name=cls.COLLECTION_NAME, points=points
            )
        return len(points)

    @classmethod
    def update_document_index(
        cls, blocks: List[Dict[str, Any]], doc_title: str
    ) -> Dict[str, int]:
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
                content_quote=block["content_quote"],
            )
            new_blocks_map[pid] = block
        new_chunk_ids = set(new_blocks_map.keys())
        # Retrieve existing point IDs for this document from Qdrant
        old_chunk_ids = set()
        offset = None
        filter_cond = Filter(
            must=[
                FieldCondition(key="document_title", match=MatchValue(value=doc_title))
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
                    with_vectors=False,
                )
                for pt in res_points:
                    old_chunk_ids.add(pt.id)
                if next_offset is None or not res_points:
                    break
                offset = next_offset
        except Exception as e:
            logger.warning(
                f"Failed to scroll points for document '{doc_title}', treating old as empty: {e}"
            )
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
            content_hash = hashlib.sha256(
                block["content_quote"].encode("utf-8")
            ).hexdigest()
            text_to_embed = f"Document: {block['document_title']}\nReference: {block['article_number']}\nContent: {block['content_quote']}"
            vector = cls._embedding_model.embed_text(
                text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
            )
            payload = {
                "document_title": block["document_title"],
                "article_number": block["article_number"],
                "content_quote": block["content_quote"],
                "content_hash": content_hash,
                "tags": block.get("tags", []),
                "keywords": block.get("keywords", ""),
            }
            # Carry unknown/extra block fields (e.g. source provenance) into payload
            for key, value in block.items():
                if key not in payload and not key.startswith("_"):
                    payload[key] = value
            points_to_upsert.append(PointStruct(id=pid, vector=vector, payload=payload))
        if points_to_upsert:
            cls._vector_storage.upsert_points(
                collection_name=cls.COLLECTION_NAME, points=points_to_upsert
            )
        logger.info(
            f"Pointwise sync for '{doc_title}' completed. "
            f"Added: {len(to_add)}, Deleted: {len(to_delete)}, Unchanged: {len(unchanged)}"
        )
        return {
            "added": len(to_add),
            "deleted": len(to_delete),
            "unchanged": len(unchanged),
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
            force_recreate=force_recreate,
        )

    @classmethod
    def seed_hs_code_directory(cls) -> int:
        """Seeds the hs_code_directory with sample ТН ВЭД ЕАЭС entries for MVP."""
        cls.setup_hs_code_collection()
        seed_entries = load_seed_hs_codes()

        points = []
        for entry in seed_entries:
            hs = entry["hs_code"]
            text_to_embed = f"HS Code: {hs}\nProduct: {entry['product_name_ru']}\nNotes: {entry['reasoning_notes']}"
            vector = cls._embedding_model.embed_text(
                text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
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

        logger.info(
            f"Upserting {len(points)} HS code points into Qdrant collection: {cls.HS_CODE_COLLECTION_NAME}"
        )
        if points:
            cls._vector_storage.upsert_points(
                collection_name=cls.HS_CODE_COLLECTION_NAME, points=points
            )
        return len(points)

    # ── Admin CRUD: Law Documents ──────────────────────────────────────────

    @classmethod
    def _law_id_from_data(cls, data: dict) -> str:
        """Generate a deterministic point ID for a law document."""
        return cls.generate_point_id(
            doc_title=data.get("title", data.get("document_title", "")),
            article_number=data.get("article", data.get("article_number", "")),
            content_quote=data.get("content", data.get("content_quote", "")),
        )

    @classmethod
    def create_law_point(cls, data: dict) -> str:
        """Create a single law document point. Returns the point ID."""
        cls.setup_collection()
        point_id = cls._law_id_from_data(data)
        content = data.get("content", data.get("content_quote", ""))
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        text_to_embed = (
            f"Document: {data.get('title', data.get('document_title', ''))}\\n"
            f"Reference: {data.get('article', data.get('article_number', ''))}\\n"
            f"Content: {content}"
        )
        vector = cls._embedding_model.embed_text(
            text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
        )
        payload = {
            "document_title": data.get("title", data.get("document_title", "")),
            "article_number": data.get("article", data.get("article_number", "")),
            "content_quote": content,
            "content_hash": content_hash,
            "tags": data.get("tags", []),
            "keywords": data.get("keywords", ""),
        }
        effective_date = data.get("effective_date")
        if effective_date is not None:
            payload["effective_date"] = str(effective_date)
        cls._vector_storage.upsert_points(
            collection_name=cls.COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )
        return point_id

    @classmethod
    def update_law_point(cls, point_id: str, data: dict) -> bool:
        """Update an existing law document point. Re-embeds if content changed."""
        existing = cls._vector_storage.retrieve_points(
            collection_name=cls.COLLECTION_NAME, ids=[point_id]
        )
        if not existing:
            raise ValueError(f"Law document not found: {point_id}")
        existing_payload = existing[0].payload or {}

        # Merge: new values override existing
        merged = dict(existing_payload)
        field_map = {
            "title": "document_title",
            "article": "article_number",
            "content": "content_quote",
            "keywords": "keywords",
        }
        for api_field, db_field in field_map.items():
            if api_field in data and data[api_field] is not None:
                merged[db_field] = data[api_field]
        if "tags" in data and data["tags"] is not None:
            merged["tags"] = data["tags"]
        if "effective_date" in data and data["effective_date"] is not None:
            merged["effective_date"] = str(data["effective_date"])

        content = merged.get("content_quote", "")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        merged["content_hash"] = content_hash

        text_to_embed = (
            f"Document: {merged.get('document_title', '')}\\n"
            f"Reference: {merged.get('article_number', '')}\\n"
            f"Content: {content}"
        )
        vector = cls._embedding_model.embed_text(
            text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
        )
        cls._vector_storage.upsert_points(
            collection_name=cls.COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload=merged)],
        )
        return True

    @classmethod
    def delete_law_point(cls, point_id: str) -> bool:
        """Delete a single law document point."""
        cls._vector_storage.delete_points(
            collection_name=cls.COLLECTION_NAME, ids=[point_id]
        )
        return True

    @classmethod
    def get_law_point(cls, point_id: str) -> Optional[dict]:
        """Retrieve a single law document point by ID."""
        points = cls._vector_storage.retrieve_points(
            collection_name=cls.COLLECTION_NAME, ids=[point_id]
        )
        if not points:
            return None
        pt = points[0]
        payload = dict(pt.payload or {}) if pt.payload else {}
        payload["id"] = pt.id
        return payload

    @classmethod
    def list_law_points(cls, page: int = 1, size: int = 20) -> tuple:
        """List law document points with pagination. Returns (items, total)."""
        cls.setup_collection()
        all_items = []
        offset = None
        while True:
            pts, next_offset = cls._vector_storage.scroll_points(
                collection_name=cls.COLLECTION_NAME,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for pt in pts:
                payload = dict(pt.payload or {}) if pt.payload else {}
                payload["id"] = pt.id
                all_items.append(payload)
            if next_offset is None or not pts:
                break
            offset = next_offset

        total = len(all_items)
        # Sort by document_title, article_number for stable pagination
        all_items.sort(
            key=lambda x: (x.get("document_title", ""), x.get("article_number", ""))
        )
        start = (page - 1) * size
        return all_items[start : start + size], total

    # ── Admin CRUD: HS Codes ───────────────────────────────────────────────

    @classmethod
    def _hs_id_from_code(cls, hs_code: str) -> str:
        """Generate a deterministic point ID for an HS code."""
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"hs_code/{hs_code}"))

    @classmethod
    def create_hs_code_point(cls, data: dict) -> str:
        """Create a single HS code point. Returns the point ID."""
        cls.setup_hs_code_collection()
        hs_code = data["hs_code"]
        point_id = cls._hs_id_from_code(hs_code)
        product_name = data.get("product_name_ru", "")
        text_to_embed = f"HS Code: {hs_code}\\nProduct: {product_name}"
        if data.get("keywords"):
            text_to_embed += f"\\nKeywords: {data['keywords']}"
        vector = cls._embedding_model.embed_text(
            text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
        )
        payload = {
            "hs_code": hs_code,
            "product_name_ru": product_name,
            "product_name_en": data.get("product_name_en", ""),
            "duty_rate_percent": float(data.get("duty_rate", 0)),
            "excise_rate_percent": float(data.get("excise_rate", 0)),
            "is_subject_to_recycling_fee": bool(data.get("recycling_fee", False)),
            "section": data.get("section", ""),
            "group": data.get("group", ""),
            "keywords": data.get("keywords", ""),
        }
        cls._vector_storage.upsert_points(
            collection_name=cls.HS_CODE_COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )
        return point_id

    @classmethod
    def update_hs_code_point(cls, point_id: str, data: dict) -> bool:
        """Update an existing HS code point. Re-embeds if name changed."""
        existing = cls._vector_storage.retrieve_points(
            collection_name=cls.HS_CODE_COLLECTION_NAME, ids=[point_id]
        )
        if not existing:
            raise ValueError(f"HS code not found: {point_id}")
        existing_payload = (
            dict(existing[0].payload or {}) if existing[0].payload else {}
        )

        merged = dict(existing_payload)
        field_map = {
            "product_name_ru": "product_name_ru",
            "product_name_en": "product_name_en",
            "section": "section",
            "group": "group",
            "keywords": "keywords",
        }
        for api_field, db_field in field_map.items():
            if api_field in data and data[api_field] is not None:
                merged[db_field] = data[api_field]
        if "duty_rate" in data and data["duty_rate"] is not None:
            merged["duty_rate_percent"] = float(data["duty_rate"])
        if "excise_rate" in data and data["excise_rate"] is not None:
            merged["excise_rate_percent"] = float(data["excise_rate"])
        if "recycling_fee" in data and data["recycling_fee"] is not None:
            merged["is_subject_to_recycling_fee"] = bool(data["recycling_fee"])

        hs_code = merged.get("hs_code", "")
        product_name = merged.get("product_name_ru", "")
        text_to_embed = f"HS Code: {hs_code}\\nProduct: {product_name}"
        if merged.get("keywords"):
            text_to_embed += f"\\nKeywords: {merged['keywords']}"
        vector = cls._embedding_model.embed_text(
            text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
        )
        cls._vector_storage.upsert_points(
            collection_name=cls.HS_CODE_COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload=merged)],
        )
        return True

    @classmethod
    def delete_hs_code_point(cls, point_id: str) -> bool:
        """Delete a single HS code point."""
        cls._vector_storage.delete_points(
            collection_name=cls.HS_CODE_COLLECTION_NAME, ids=[point_id]
        )
        return True

    @classmethod
    def get_hs_code_point(cls, point_id: str) -> Optional[dict]:
        """Retrieve a single HS code point by ID."""
        points = cls._vector_storage.retrieve_points(
            collection_name=cls.HS_CODE_COLLECTION_NAME, ids=[point_id]
        )
        if not points:
            return None
        pt = points[0]
        payload = dict(pt.payload or {}) if pt.payload else {}
        payload["id"] = pt.id
        return payload

    @classmethod
    def list_hs_code_points(
        cls, page: int = 1, size: int = 20, search: str = ""
    ) -> tuple:
        """List HS code points with optional search and pagination. Returns (items, total)."""
        cls.setup_hs_code_collection()
        all_items = []
        offset = None
        while True:
            pts, next_offset = cls._vector_storage.scroll_points(
                collection_name=cls.HS_CODE_COLLECTION_NAME,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for pt in pts:
                payload = dict(pt.payload or {}) if pt.payload else {}
                payload["id"] = pt.id
                if search:
                    haystack = " ".join(
                        str(v) for v in payload.values() if isinstance(v, str)
                    ).lower()
                    if search.lower() not in haystack:
                        continue
                all_items.append(payload)
            if next_offset is None or not pts:
                break
            offset = next_offset

        total = len(all_items)
        all_items.sort(key=lambda x: x.get("hs_code", ""))
        start = (page - 1) * size
        return all_items[start : start + size], total

    # ── Content Deduplication ───────────────────────────────────────────────

    @classmethod
    def check_content_similarity(
        cls, collection_name: str, text: str, threshold: float = 0.95
    ) -> Optional[str]:
        """Check if text is too similar to existing content in a collection.

        Returns the existing point ID if cosine similarity > threshold, else None.
        """
        from app.core.local_embeddings import LocalEmbeddingModel

        if not LocalEmbeddingModel.is_available():
            return None  # Can't check, allow creation

        try:
            query_vector = LocalEmbeddingModel.encode(text)
        except Exception:
            return None

        result = cls._vector_storage.query_points(
            collection_name=collection_name,
            query_vector=query_vector,
            limit=3,
        )
        if result is None or not hasattr(result, "points") or not result.points:
            return None

        for pt in result.points:
            if pt.score and pt.score >= threshold:
                return pt.id

        return None

    # ── Reindex ─────────────────────────────────────────────────────────────

    @classmethod
    def reindex_collection(cls, collection_name: str, timeout: int = 3600) -> dict:
        """Reindex a collection using temp-collection atomic-swap strategy.

        1. Create ``{name}_temp`` collection.
        2. Load seed data and embed all points into temp.
        3. Scroll all from temp and upsert into main (overwriting).
        4. Delete temp collection.

        The original collection remains queryable throughout reindexing;
        only the final upsert batch is destructive (last-write-wins).
        """

        main_name = collection_name
        temp_name = f"{collection_name}_temp"
        dim = (
            cls.VECTOR_DIMENSION
            if collection_name == cls.COLLECTION_NAME
            else cls.HS_CODE_VECTOR_DIMENSION
        )

        # 1. Setup temp collection (force recreate)
        cls._vector_storage.setup_collection(temp_name, dim, force_recreate=True)

        try:
            # 2. Load and embed seed data into temp
            if collection_name == cls.COLLECTION_NAME:
                blocks = load_seed_law_blocks()
                _index_blocks_into(
                    cls, blocks, collection_name=temp_name, dim=dim, is_law=True
                )
            elif collection_name == cls.HS_CODE_COLLECTION_NAME:
                entries = load_seed_hs_codes()
                _index_hs_into(cls, entries, collection_name=temp_name, dim=dim)
            else:
                raise ValueError(f"Unknown collection: {collection_name}")

            # 3. Scroll all from temp and upsert into main (atomic-ish batch)
            all_temp_points = []
            offset = None
            while True:
                pts, next_offset = cls._vector_storage.scroll_points(
                    collection_name=temp_name,
                    limit=100,
                    offset=offset,
                    with_payload=True,
                    with_vectors=True,
                )
                for pt in pts:
                    all_temp_points.append(
                        PointStruct(
                            id=pt.id,
                            vector=pt.vector if pt.vector else [],
                            payload=pt.payload,
                        )
                    )
                if next_offset is None or not pts:
                    break
                offset = next_offset

            if all_temp_points:
                # Ensure main collection exists
                cls._vector_storage.setup_collection(
                    main_name, dim, force_recreate=False
                )
                # Batch upsert from temp into main
                cls._vector_storage.upsert_points(
                    collection_name=main_name, points=all_temp_points
                )

            # 4. Delete temp
            cls._vector_storage.delete_collection(temp_name)

            return {
                "status": "completed",
                "points_indexed": len(all_temp_points),
            }
        except Exception:
            # Rollback: delete temp, keep main intact
            cls._vector_storage.delete_collection(temp_name)
            raise


def _index_blocks_into(indexer_cls, blocks, collection_name, dim, is_law=True):
    """Helper: embed and index law blocks into a specific collection."""
    points = []
    for block in blocks:
        point_id = indexer_cls.generate_point_id(
            doc_title=block["document_title"],
            article_number=block["article_number"],
            content_quote=block["content_quote"],
        )
        text_to_embed = (
            f"Document: {block['document_title']}\\n"
            f"Reference: {block['article_number']}\\n"
            f"Content: {block['content_quote']}"
        )
        vector = indexer_cls._embedding_model.embed_text(
            text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
        )
        payload = {
            "document_title": block["document_title"],
            "article_number": block["article_number"],
            "content_quote": block["content_quote"],
            "content_hash": hashlib.sha256(
                block["content_quote"].encode("utf-8")
            ).hexdigest(),
            "tags": block.get("tags", []),
            "keywords": block.get("keywords", ""),
        }
        points.append(PointStruct(id=point_id, vector=vector, payload=payload))
    if points:
        indexer_cls._vector_storage.upsert_points(
            collection_name=collection_name, points=points
        )


def _index_hs_into(indexer_cls, entries, collection_name, dim):
    """Helper: embed and index HS code entries into a specific collection."""
    points = []
    for entry in entries:
        hs = entry["hs_code"]
        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"hs_code/{hs}"))
        text_to_embed = (
            f"HS Code: {hs}\\n"
            f"Product: {entry.get('product_name_ru', '')}\\n"
            f"Notes: {entry.get('reasoning_notes', '')}"
        )
        vector = indexer_cls._embedding_model.embed_text(
            text=text_to_embed, task_type="RETRIEVAL_DOCUMENT"
        )
        payload = {
            "hs_code": hs,
            "product_name_ru": entry.get("product_name_ru", ""),
            "product_name_en": entry.get("product_name_en", ""),
            "duty_rate_percent": entry.get("duty_rate_percent", 0),
            "excise_rate_percent": entry.get("excise_rate_percent", 0),
            "is_subject_to_recycling_fee": entry.get(
                "is_subject_to_recycling_fee", False
            ),
            "section": entry.get("section", ""),
            "group": entry.get("group", ""),
            "reasoning_notes": entry.get("reasoning_notes", ""),
            "keywords": entry.get("keywords", ""),
        }
        points.append(PointStruct(id=point_id, vector=vector, payload=payload))
    if points:
        indexer_cls._vector_storage.upsert_points(
            collection_name=collection_name, points=points
        )
