"""
Backward-compatibility facade for the old ``GeminiVertexClient`` API.

New code should use:
- ``app.core.llm.generator.get_generator()`` for text / structured generation
- ``app.core.rag.seams.EmbeddingModel`` adapters for embeddings

This module will be removed once all callers migrate.
"""

import logging
from typing import List, Optional, Type, TypeVar

from pydantic import BaseModel

# One-time Langfuse compat shim (kept here for backward compat with importers).
from app.core.langfuse_setup import _ensure_langfuse_compat  # noqa: F401

from app.core.llm.generator import get_generator, set_generator
from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class GeminiVertexClient:
    """Thin backward-compat wrapper over the new TextGenerator + Embedding seams.

    Deprecated — migrate callers to the new modules directly.
    """

    @classmethod
    def generate_structured_content(
        cls,
        prompt: str,
        response_schema: Type[T],
        image_bytes: Optional[bytes] = None,
        image_mime_type: Optional[str] = "image/jpeg",
    ) -> T:
        return get_generator().generate_structured(
            prompt,
            response_schema,
            image_bytes=image_bytes,
            image_mime_type=image_mime_type,
        )

    @classmethod
    def generate_chat_response(
        cls,
        system_instruction: str,
        message_history: List[dict],
    ) -> str:
        return get_generator().generate_chat(system_instruction, message_history)

    @classmethod
    def get_text_embedding(
        cls,
        text: str,
        task_type: str = "RETRIEVAL_QUERY",
    ) -> List[float]:
        """Generate a dense embedding vector for *text*.

        Strategy (first success wins):
          1. Local Sentence-Transformer (primary)
          2. Gemini / Vertex AI embedding (only when USE_GEMINI_EMBEDDING=True)
          3. Mock zero vector (last resort)
        """
        import os as _os

        dim = settings.EMBEDDING_DIMENSION
        vector = None

        # Path 1: Local model (primary)
        try:
            from app.core.local_embeddings import LocalEmbeddingModel

            if LocalEmbeddingModel.is_available():
                vector = LocalEmbeddingModel.encode(text)
                logger.info(
                    "Using local Sentence-Transformer embedding (dim=%d)", len(vector)
                )
        except Exception as e:
            logger.warning(f"Local embedding model failed: {e}")

        # Path 2: Gemini / Vertex AI (only when explicitly enabled)
        if vector is None and settings.USE_GEMINI_EMBEDDING:
            gen = get_generator()
            gen._init_client()
            mode = gen._client_mode
            if mode in (gen.API_KEY, gen.VERTEX_MODERN):
                try:
                    from google.genai import types

                    model_id = settings.GEMINI_EMBEDDING_MODEL_ID
                    result = gen._client.models.embed_content(
                        model=model_id,
                        contents=[text],
                        config=types.EmbedContentConfig(
                            output_dimensionality=dim,
                            task_type=task_type,
                        ),
                    )
                    if result.embeddings:
                        vector = result.embeddings[0].values
                except Exception as e:
                    logger.warning(f"Gemini embedding failed: {e}")

        # Path 3: Mock zero vector
        if vector is None:
            logger.warning(
                "All embedding methods failed, returning mock %d-dim zero vector", dim
            )
            vector = [0.0] * dim

        if settings.LANGFUSE_ENABLED:
            from langfuse import get_client

            try:
                get_client().update_current_span(
                    input={"text_length": len(text), "task_type": task_type},
                    output={"vector_length": len(vector)},
                )
            except Exception as lf_err:
                logger.warning(f"Failed to update Langfuse span: {lf_err}")

        return vector
