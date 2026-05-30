"""Reindex the entire Qdrant knowledge base from scratch.

Combines TK EAEUS text, NK RK 2026 articles (original + extra),
reference data, HS codes (original + extra), and seed law blocks
into a single run.

Usage:
    PYTHONPATH=backend .venv/Scripts/python backend/scripts/reindex_all.py [--skip-tkeaes]
"""

import logging
import sys
import argparse
import time

sys.path.insert(0, "backend")

from app.core.rag.indexer import LegalRAGIndexer, SEED_LAW_BLOCKS
from app.core.rag.hs_code_data import HS_CODE_SEED_ENTRIES, NK_RK_2026_ARTICLES
from app.core.rag.seed_knowledge_base import seed_additional_hs_codes
from app.core.rag.hs_extra_data import HS_CODE_EXTRA_ENTRIES
from app.core.rag.nk_extra_articles import NK_EXTRA_ARTICLES
from app.core.rag.reference_data import REFERENCE_ENTRIES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def rebuild_legal_collection(skip_tkeaes: bool = False):
    """Recreate and repopulate legal_regulations_kz."""
    logger.info("=" * 60)
    logger.info("Rebuilding legal_regulations_kz collection")
    logger.info("=" * 60)

    # Recreate collection
    LegalRAGIndexer.setup_collection(force_recreate=True)

    total = 0

    # 1. TK EAEUS text blocks
    if not skip_tkeaes:
        logger.info("\n[1/5] Indexing TK EAEUS text blocks...")
        try:
            with open(
                "backend/app/core/rag/data/tkeaes.txt", "r", encoding="utf-8"
            ) as f:
                raw_text = f.read()
            blocks = LegalRAGIndexer.parse_legal_text_to_blocks(
                raw_text, "Таможенный кодекс Евразийского экономического союза"
            )
            count = LegalRAGIndexer.index_blocks(blocks)
            logger.info(f"  -> Indexed {count} TK EAEUS blocks")
            total += count
        except Exception as e:
            logger.error(f"  -> Failed to index TK EAEUS: {e}")
            raise
    else:
        logger.info("\n[1/5] Skipping TK EAEUS (--skip-tkeaes)")

    # 2. NK RK 2026 original articles
    logger.info(
        f"\n[2/5] Indexing {len(NK_RK_2026_ARTICLES)} original НК РК 2026 articles..."
    )
    try:
        count = LegalRAGIndexer.index_blocks(NK_RK_2026_ARTICLES)
        logger.info(f"  -> Indexed {count} original NK RK articles")
        total += count
    except Exception as e:
        logger.error(f"  -> Failed: {e}")
        raise

    # 3. NK RK 2026 extra articles
    logger.info(
        f"\n[3/5] Indexing {len(NK_EXTRA_ARTICLES)} extra НК РК 2026 articles..."
    )
    try:
        count = LegalRAGIndexer.index_blocks(NK_EXTRA_ARTICLES)
        logger.info(f"  -> Indexed {count} extra NK RK articles")
        total += count
    except Exception as e:
        logger.error(f"  -> Failed: {e}")
        raise

    # 4. Reference data
    logger.info(f"\n[4/5] Indexing {len(REFERENCE_ENTRIES)} reference data entries...")
    try:
        count = LegalRAGIndexer.index_blocks(REFERENCE_ENTRIES)
        logger.info(f"  -> Indexed {count} reference entries")
        total += count
    except Exception as e:
        logger.error(f"  -> Failed: {e}")
        raise

    # 5. Seed law blocks
    logger.info(f"\n[5/5] Indexing {len(SEED_LAW_BLOCKS)} seed law blocks...")
    try:
        count = LegalRAGIndexer.index_blocks(SEED_LAW_BLOCKS)
        logger.info(f"  -> Indexed {count} seed law blocks")
        total += count
    except Exception as e:
        logger.error(f"  -> Failed: {e}")
        raise

    logger.info(f"\n>>> Legal collection total: {total} points")
    return total


def rebuild_hs_collection():
    """Recreate and repopulate hs_code_directory."""
    logger.info("=" * 60)
    logger.info("Rebuilding hs_code_directory collection")
    logger.info("=" * 60)

    LegalRAGIndexer.setup_hs_code_collection(force_recreate=True)

    total = 0

    # 1. Base 5 HS codes (via existing method)
    logger.info(f"\n[1/3] Seeding 5 base HS code entries...")
    try:
        count = LegalRAGIndexer.seed_hs_code_directory()
        logger.info(f"  -> Indexed {count} base HS codes")
        total += count
    except Exception as e:
        logger.error(f"  -> Failed: {e}")
        raise

    # 2. Original 138 HS codes from hs_code_data.py
    logger.info(f"\n[2/3] Indexing {len(HS_CODE_SEED_ENTRIES)} original HS codes...")
    try:
        count = seed_additional_hs_codes(HS_CODE_SEED_ENTRIES)
        logger.info(f"  -> Indexed {count} original HS codes")
        total += count
    except Exception as e:
        logger.error(f"  -> Failed: {e}")
        raise

    # 3. Extra 207 HS codes from hs_extra_data.py
    logger.info(f"\n[3/3] Indexing {len(HS_CODE_EXTRA_ENTRIES)} extra HS codes...")
    try:
        count = seed_additional_hs_codes(HS_CODE_EXTRA_ENTRIES)
        logger.info(f"  -> Indexed {count} extra HS codes")
        total += count
    except Exception as e:
        logger.error(f"  -> Failed: {e}")
        raise

    logger.info(f"\n>>> HS code collection total: {total} points")
    return total


def main():
    parser = argparse.ArgumentParser(
        description="Reindex all knowledge base data into Qdrant"
    )
    parser.add_argument(
        "--skip-tkeaes",
        action="store_true",
        help="Skip TK EAEUS text re-indexing (use if already indexed)",
    )
    args = parser.parse_args()

    t0 = time.time()
    logger.info("🚀 Starting full knowledge base reindex")
    logger.info(f"  Qdrant: localhost:6333")
    logger.info(f"  Embedding: Granite 384-dim (local)")
    logger.info(f"  Skip TK EAEUS: {args.skip_tkeaes}")
    logger.info("")

    # Legal collection
    legal_count = rebuild_legal_collection(skip_tkeaes=args.skip_tkeaes)

    # HS code collection
    hs_count = rebuild_hs_collection()

    # Summary
    elapsed = time.time() - t0
    logger.info("\n" + "=" * 60)
    logger.info("REINDEX COMPLETE")
    logger.info(f"  legal_regulations_kz: {legal_count} points")
    logger.info(f"  hs_code_directory: {hs_count} points")
    logger.info(f"  Total: {legal_count + hs_count} points")
    logger.info(f"  Time: {elapsed:.1f}s")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
