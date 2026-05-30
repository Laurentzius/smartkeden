"""
Shared wiring — creates singleton service instances with injected seams.

Import these in ``main.py``, ``router.py``, or any HTTP handler that needs
the real (production) adapters.  Tests inject their own instances directly.
"""

from app.core.rag.seams import QdrantVectorStorageAdapter, LocalEmbeddingModelAdapter
from app.core.llm.generator import get_generator
from app.core.rag.service import LegalRAGService
from app.core.hs_classifier.classifier import HSCodeClassifier

_vector_storage = QdrantVectorStorageAdapter()
_embedding_model = LocalEmbeddingModelAdapter()
_text_generator = get_generator()

hs_classifier = HSCodeClassifier(
    embedding_model=_embedding_model, vector_storage=_vector_storage
)
legal_rag_service = LegalRAGService(
    vector_storage=_vector_storage,
    embedding_model=_embedding_model,
    text_generator=_text_generator,
)

from app.core.classification.attribute_extractor import AttributeExtractor
from app.core.classification.rules_engine import RulesEngine

# Attribute extractor (reuses the same generator/Vision LLM)
_attribute_extractor = AttributeExtractor(vision_client=_text_generator)


def get_attribute_extractor() -> AttributeExtractor:
    """Get the singleton AttributeExtractor instance."""
    return _attribute_extractor


def get_rules_engine(db_session=None):
    """Create a RulesEngine instance bound to a DB session.

    RulesEngine is not a singleton — it needs a fresh DB session per request.
    """
    if db_session is None:
        from app.core.database import SessionLocal
        db_session = SessionLocal()
    return RulesEngine(db_session=db_session)
