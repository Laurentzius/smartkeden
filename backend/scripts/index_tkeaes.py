"""Index TK EAEUS text + NK RK 2026 + seed law blocks into real Qdrant."""
import logging
import sys
sys.path.insert(0, 'backend')

from app.core.rag.indexer import LegalRAGIndexer, SEED_LAW_BLOCKS
from app.core.rag.hs_code_data import NK_RK_2026_ARTICLES
from qdrant_client import QdrantClient
from app.core.config import settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Verify real Qdrant
client = LegalRAGIndexer.get_client()
collections = client.get_collections()
logger.info("Connected to Qdrant, collections: %s", [c.name for c in collections.collections])

# Read TK EAEUS text
with open('backend/app/core/rag/data/tkeaes.txt', 'r', encoding='utf-8') as f:
    raw_text = f.read()
logger.info("TK EAEUS text: %d chars", len(raw_text))

# Parse into blocks
blocks = LegalRAGIndexer.parse_legal_text_to_blocks(raw_text, 'Таможенный кодекс Евразийского экономического союза')
logger.info("Parsed %d blocks", len(blocks))

# Recreate collection (force to clear old in-memory data)
LegalRAGIndexer.setup_collection(force_recreate=True)

# Index TK EAEUS
count = LegalRAGIndexer.index_blocks(blocks)
logger.info("Indexed %d TK EAEUS points", count)

# Index NK RK 2026
nk_count = LegalRAGIndexer.index_blocks(NK_RK_2026_ARTICLES)
logger.info("Indexed %d NK RK 2026 articles", nk_count)

# Index seed law blocks
seed_count = LegalRAGIndexer.index_blocks(SEED_LAW_BLOCKS)
logger.info("Indexed %d seed law blocks", seed_count)

# Verify
c2 = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
final = c2.get_collection('legal_regulations_kz')
logger.info("Final legal_regulations_kz: %d points", final.points_count)
