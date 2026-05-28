"""
Seed the Qdrant knowledge base with:
1. Existing HS code directory entries (5 base entries via LegalRAGIndexer.seed_hs_code_directory)
2. 120+ additional ТН ВЭД ЕАЭС HS code entries from hs_code_data.HS_CODE_SEED_ENTRIES
3. 11+ key НК РК 2026 articles from hs_code_data.NK_RK_2026_ARTICLES

Usage:
    PYTHONPATH=backend .venv/Scripts/python backend/app/core/rag/seed_knowledge_base.py
"""
import logging
import time
import uuid
from typing import List, Dict, Any

from qdrant_client.models import PointStruct

from app.core.rag.indexer import LegalRAGIndexer
from app.core.vertex_client import GeminiVertexClient
from app.core.rag.hs_code_data import HS_CODE_SEED_ENTRIES, NK_RK_2026_ARTICLES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def seed_additional_hs_codes(entries: List[Dict[str, Any]]) -> int:
    """
    Index additional HS code entries into the hs_code_directory collection.
    Uses the same pattern as LegalRAGIndexer.seed_hs_code_directory().
    """
    client = LegalRAGIndexer.get_client()
    LegalRAGIndexer.setup_hs_code_collection()

    points: List[PointStruct] = []
    for entry in entries:
        hs = entry["hs_code"]
        text_to_embed = (
            f"HS Code: {hs}\n"
            f"Product: {entry['product_name_ru']}\n"
            f"Notes: {entry['reasoning_notes']}"
        )
        vector = GeminiVertexClient.get_text_embedding(
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

    logger.info(f"Upserting {len(points)} additional HS code points into Qdrant "
                f"collection: {LegalRAGIndexer.HS_CODE_COLLECTION_NAME}")
    if points:
        client.upsert(
            collection_name=LegalRAGIndexer.HS_CODE_COLLECTION_NAME,
            points=points,
        )
    return len(points)


def main():
    logger.info("=" * 60)
    logger.info("Starting Qdrant knowledge base seeding...")
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Seed the 5 base HS code entries
    # ------------------------------------------------------------------
    logger.info("[Step 1/3] Seeding 5 base HS code entries via LegalRAGIndexer.seed_hs_code_directory()...")
    try:
        base_count = LegalRAGIndexer.seed_hs_code_directory()
        logger.info(f"  -> Seeded {base_count} base HS code entries (or they already existed)")
    except Exception as e:
        logger.warning(f"  -> Base HS code seeding had an issue: {e}")

    # ------------------------------------------------------------------
    # Step 2: Seed 120+ additional ТН ВЭД ЕАЭС HS code entries
    # ------------------------------------------------------------------
    logger.info(f"[Step 2/3] Indexing {len(HS_CODE_SEED_ENTRIES)} additional ТН ВЭД ЕАЭС entries...")
    try:
        additional_count = seed_additional_hs_codes(HS_CODE_SEED_ENTRIES)
        logger.info(f"  -> Indexed {additional_count} additional HS code entries")
    except Exception as e:
        logger.error(f"  -> Failed to index additional HS codes: {e}")
        raise

    # ------------------------------------------------------------------
    # Step 3: Seed НК РК 2026 articles into legal regulations collection
    # ------------------------------------------------------------------
    logger.info(f"[Step 3/3] Indexing {len(NK_RK_2026_ARTICLES)} НК РК 2026 articles "
                f"via LegalRAGIndexer.index_blocks()...")
    try:
        legal_count = LegalRAGIndexer.index_blocks(NK_RK_2026_ARTICLES)
        logger.info(f"  -> Indexed {legal_count} legal articles")
    except Exception as e:
        logger.error(f"  -> Failed to index legal articles: {e}")
        raise

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    total_hs = len(HS_CODE_SEED_ENTRIES) + 5  # 5 base + additional
    logger.info("=" * 60)
    logger.info(f"Seeding complete! "
                f"~{total_hs} HS code entries + {len(NK_RK_2026_ARTICLES)} legal articles")
    logger.info(f"  - HS Code collection: {LegalRAGIndexer.HS_CODE_COLLECTION_NAME}")
    logger.info(f"  - Legal regulations collection: {LegalRAGIndexer.COLLECTION_NAME}")
    logger.info("=" * 60)


if __name__ == "__main__":
    t0 = time.time()
    main()
    elapsed = time.time() - t0
    logger.info(f"Total execution time: {elapsed:.2f}s")
