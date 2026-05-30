import logging
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class LocalEmbeddingModel:
    """
    Lazy-loaded sentence-transformers model for local embedding generation.

    Primary embedding provider for the customs assistant.
    Uses ``ibm-granite/granite-embedding-97m-multilingual-r2`` (384‑dim, 200+ languages,
    Apache 2.0, CPU‑friendly, ~390 MB).

    The model is loaded once on first ``encode()`` call and cached as a class-level
    singleton.  All subsequent calls are sub‑100 ms on a modern CPU.
    """

    _model = None
    _available: Optional[bool] = None

    # ------------------------------------------------------------------
    # Availability check (avoids import errors when package is missing)
    # ------------------------------------------------------------------
    @classmethod
    def is_available(cls) -> bool:
        if cls._available is None:
            try:
                from sentence_transformers import SentenceTransformer  # noqa: F401

                cls._available = True
            except ImportError:
                cls._available = False
        return cls._available

    # ------------------------------------------------------------------
    # Lazy singleton model loader
    # ------------------------------------------------------------------
    @classmethod
    def get_model(cls):
        if cls._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info(
                "Loading local embedding model: %s", settings.EMBEDDING_MODEL_NAME
            )
            cls._model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
            cls._model.max_seq_length = 512
        return cls._model

    # ------------------------------------------------------------------
    # Public encode API
    # ------------------------------------------------------------------
    @classmethod
    def encode(cls, text: str, task_type: Optional[str] = None) -> List[float]:
        """
        Encode a single text string into a dense embedding vector.

        Parameters
        ----------
        text:
            Input text to embed.
        task_type:
            Ignored for sentence‑transformers models (the same encoder is used for
            both retrieval queries and documents).  Kept in the signature for API
            compatibility with Gemini's ``get_text_embedding``.

        Returns
        -------
        A list of ``settings.EMBEDDING_DIMENSION`` floats.
        """
        if not cls.is_available():
            raise RuntimeError("sentence-transformers is not installed")

        model = cls.get_model()
        embedding = model.encode(text, normalize_embeddings=True)
        return embedding.tolist()
