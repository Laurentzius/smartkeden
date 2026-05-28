import json
import logging
import os
from typing import Type, TypeVar, Optional, List
from pydantic import BaseModel
from app.core.config import settings

logger = logging.getLogger(__name__)

import langfuse
if not hasattr(langfuse, "observe"):
    from langfuse.decorators import observe
    langfuse.observe = observe
if not hasattr(langfuse, "get_client"):
    from langfuse import Langfuse
    _client_instance = None
    def get_client_compat():
        global _client_instance
        if _client_instance is None:
            _client_instance = Langfuse()
        return _client_instance
    langfuse.get_client = get_client_compat

from langfuse import observe, get_client

def _extract_usage(response) -> Optional[dict]:
    if not response:
        return None
    usage = {}
    usage_metadata = getattr(response, "usage_metadata", None)
    if usage_metadata:
        usage["prompt_tokens"] = getattr(usage_metadata, "prompt_token_count", None)
        usage["completion_tokens"] = getattr(usage_metadata, "candidates_token_count", None)
    else:
        usage_metadata_alt = getattr(response, "usage", None) or getattr(response, "usage_info", None)
        if usage_metadata_alt:
            usage["prompt_tokens"] = getattr(usage_metadata_alt, "prompt_token_count", None) or getattr(usage_metadata_alt, "input_tokens", None)
            usage["completion_tokens"] = getattr(usage_metadata_alt, "candidates_token_count", None) or getattr(usage_metadata_alt, "output_tokens", None)
    filtered = {k: v for k, v in usage.items() if v is not None}
    return filtered if filtered else None

T = TypeVar("T", bound=BaseModel)


class GeminiVertexClient:
    """
    Wrapper client for calling Gemini models (via Gemini API or Vertex AI).

    Connection priority:
      1. GOOGLE_API_KEY → genai.Client(api_key=...) — Gemini API directly (no Vertex, no billing)
      2. ADC available  → genai.Client(vertexai=True, ...) — Vertex AI via Application Default Credentials
      3. ADC available  → legacy vertexai SDK fallback
      4. Nothing        → mock/dev mode (dummy responses)
    """
    _client = None          # genai.Client instance, "legacy", or "mock"
    _client_mode = None     # cls.MOCK / cls.API_KEY / cls.VERTEX_MODERN / cls.LEGACY

    # --- Client type constants ---
    MOCK = "mock"
    API_KEY = "api_key"       # genai.Client(api_key=...) → Gemini API
    VERTEX_MODERN = "vertex"  # genai.Client(vertexai=True) → Vertex AI
    LEGACY = "legacy"         # vertexai SDK → Vertex AI

    @classmethod
    def _initialize_client(cls):
        if cls._client is not None:
            return cls._client

        api_key = settings.GOOGLE_API_KEY or os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_CLOUD_API_KEY")
        project = settings.GOOGLE_CLOUD_PROJECT or os.getenv("GOOGLE_CLOUD_PROJECT")
        location = settings.GOOGLE_CLOUD_LOCATION or os.getenv("GOOGLE_CLOUD_LOCATION") or "global"

        # Determine if it's a Vertex AI key (starts with AQ. or explicitly set as global/vertex-based)
        is_vertex_key = False
        if api_key:
            if api_key.startswith("AQ.") or location not in (None, "", "global"):
                is_vertex_key = True

        # ------------------------------------------------------------------
        # Path 1: GOOGLE_API_KEY → Gemini API directly (no Vertex AI needed)
        # ------------------------------------------------------------------
        if api_key and not is_vertex_key:
            try:
                from google import genai
                cls._client = genai.Client(api_key=api_key)
                cls._client_mode = cls.API_KEY
                logger.info("Initialized Gemini API client via GOOGLE_API_KEY")
                return cls._client
            except Exception as e:
                logger.warning(f"Gemini API client init failed with GOOGLE_API_KEY: {e}")


        # ------------------------------------------------------------------
        # Path 1.5: Modern google-genai SDK with vertexai=True and Vertex API Key
        # ------------------------------------------------------------------
        if api_key and is_vertex_key:
            try:
                from google import genai
                cls._client = genai.Client(
                    vertexai=True,
                    api_key=api_key,
                )
                cls._client_mode = cls.VERTEX_MODERN
                logger.info("Initialized Vertex AI client via modern genai SDK with Vertex API Key")
                return cls._client
            except Exception as e:
                logger.warning(f"Modern genai SDK Vertex init with API key failed: {e}")
        # ------------------------------------------------------------------
        # Path 2: Modern google-genai SDK with vertexai=True (needs ADC)
        # ------------------------------------------------------------------
        # Since modern SDK does not allow project/location and api_key together,
        # we can only use it with ADC.
        has_adc = bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")) or os.path.exists(
            os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        )
        if has_adc and not api_key:  # Prefer legacy SDK if API key is explicitly provided
            try:
                from google import genai
                from google.auth import default as default_credentials

                creds, adc_project = default_credentials()
                target_project = project or adc_project

                cls._client = genai.Client(
                    vertexai=True,
                    project=target_project,
                    location=location,
                    credentials=creds,
                )
                cls._client_mode = cls.VERTEX_MODERN
                logger.info("Initialized Vertex AI client via ADC (modern genai SDK)")
                return cls._client
            except Exception as e:
                logger.warning(f"Modern genai SDK Vertex init failed: {e}")

        # ------------------------------------------------------------------
        # All paths failed → mock/dev mode
        # ------------------------------------------------------------------
        logger.warning("No Google Cloud credentials configured. Running in mock/dev mode.")
        cls._client = cls.MOCK
        cls._client_mode = cls.MOCK
        return cls._client

    @classmethod
    @observe(as_type="generation")
    def generate_structured_content(
        cls,
        prompt: str,
        response_schema: Type[T],
        image_bytes: Optional[bytes] = None,
        image_mime_type: Optional[str] = "image/jpeg",
    ) -> T:
        """
        Sends a text or multimodal prompt to Gemini and enforces a structured Pydantic response schema.
        """
        cls._initialize_client()
        mode = cls._client_mode

        if mode == cls.MOCK:
            logger.warning("Using mock response because Vertex AI client was not initialized")
            mock_res = cls._generate_mock_schema_response(response_schema)
            if settings.LANGFUSE_ENABLED:
                try:
                    get_client().update_current_generation(
                        name="generate_structured_content (MOCK)",
                        model=settings.GEMINI_MODEL_ID,
                        input={"prompt": prompt, "has_image": bool(image_bytes)},
                        output=str(mock_res),
                        usage_details={"prompt_tokens": 0, "completion_tokens": 0}
                    )
                except Exception as lf_err:
                    logger.warning(f"Failed to update Langfuse generation: {lf_err}")
            return mock_res

        try:
            from google.genai import types

            contents = []
            if image_bytes:
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type))
            contents.append(prompt)

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            )

            model_id = settings.GEMINI_MODEL_ID

            if mode in (cls.API_KEY, cls.VERTEX_MODERN):
                response = cls._client.models.generate_content(
                    model=model_id,
                    contents=contents,
                    config=config,
                )
                result = response_schema.model_validate_json(response.text)
                if settings.LANGFUSE_ENABLED:
                    try:
                        get_client().update_current_generation(
                            name="generate_structured_content",
                            model=model_id,
                            input={"prompt": prompt, "has_image": bool(image_bytes)},
                            output=response.text,
                            usage_details=_extract_usage(response)
                        )
                    except Exception as lf_err:
                        logger.warning(f"Failed to update Langfuse generation: {lf_err}")
                return result

            else:
                raise RuntimeError(f"Unknown client mode: {mode}")

        except Exception as e:
            logger.error(f"Error generating structured content from Gemini: {e}")
            raise
    @classmethod
    @observe(as_type="generation")
    def generate_chat_response(cls, system_instruction: str, message_history: List[dict]) -> str:
        """
        Standard free-text chat response for the customs assistant.
        """
        cls._initialize_client()
        mode = cls._client_mode

        if mode == cls.MOCK:
            mock_text = (
                "Это демонстрационный ответ. "
                "Пожалуйста, настройте учетные данные Google Cloud Vertex AI для реальных консультаций."
            )
            if settings.LANGFUSE_ENABLED:
                try:
                    get_client().update_current_generation(
                        name="generate_chat_response (MOCK)",
                        model=settings.GEMINI_MODEL_ID,
                        input={"system_instruction": system_instruction, "message_history": message_history},
                        output=mock_text,
                        usage_details={"prompt_tokens": 0, "completion_tokens": 0}
                    )
                except Exception as lf_err:
                    logger.warning(f"Failed to update Langfuse generation: {lf_err}")
            return mock_text

        try:
            from google.genai import types

            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
            )

            model_id = settings.GEMINI_MODEL_ID

            # Format contents
            contents = []
            for msg in message_history:
                role = "user" if msg["role"] == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])]))

            if mode in (cls.API_KEY, cls.VERTEX_MODERN):
                response = cls._client.models.generate_content(
                    model=model_id,
                    contents=contents,
                    config=config,
                )
                text_out = response.text
                if settings.LANGFUSE_ENABLED:
                    try:
                        get_client().update_current_generation(
                            name="generate_chat_response",
                            model=model_id,
                            input={"system_instruction": system_instruction, "message_history": message_history},
                            output=text_out,
                            usage_details=_extract_usage(response)
                        )
                    except Exception as lf_err:
                        logger.warning(f"Failed to update Langfuse generation: {lf_err}")
                return text_out


            else:
                raise RuntimeError(f"Unknown client mode: {mode}")

        except Exception as e:
            logger.error(f"Error generating chat response from Gemini: {e}")
            return f"Ошибка при подключении к Gemini: {str(e)}"
    # ------------------------------------------------------------------
    # Mock helpers
    # ------------------------------------------------------------------

    @classmethod
    def _generate_mock_schema_response(cls, schema: Type[T]) -> T:
        """Helper to create dummy data conforming to the pydantic schema for testing without API keys."""
        sample_data = {}
        for field_name, field in schema.model_fields.items():
            field_type = field.annotation
            if field_type == str:
                sample_data[field_name] = "Демонстрационная строка"
            elif field_type == float or field_type == Optional[float]:
                sample_data[field_name] = 0.9
            elif field_type == int or field_type == Optional[int]:
                sample_data[field_name] = 0
            elif field_type == bool:
                sample_data[field_name] = False
            elif getattr(field_type, "__origin__", None) == list:
                args = getattr(field_type, "__args__", [])
                if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
                    sample_data[field_name] = [cls._generate_mock_schema_response(args[0])]
                else:
                    sample_data[field_name] = []
            else:
                sample_data[field_name] = None
        return schema.model_validate(sample_data)

    @classmethod
    def _inline_refs(cls, schema, defs=None):
        if defs is None:
            defs = schema.get("$defs", {}) or schema.get("definitions", {})
        
        if isinstance(schema, dict):
            if "$ref" in schema:
                ref_path = schema["$ref"]
                def_name = ref_path.split("/")[-1]
                if def_name in defs:
                    return cls._inline_refs(defs[def_name], defs)
            
            new_schema = {}
            for k, v in schema.items():
                if k not in ("$defs", "definitions"):
                    new_schema[k] = cls._inline_refs(v, defs)
            return new_schema
        elif isinstance(schema, list):
            return [cls._inline_refs(item, defs) for item in schema]
        return schema

    @classmethod
    @observe(name="get_text_embedding")
    def get_text_embedding(
        cls,
        text: str,
        task_type: str = "RETRIEVAL_QUERY",
    ) -> List[float]:
        """
        Generate a dense embedding vector for the given text.

        Strategy (first success wins):
          1. Local Sentence‑Transformer model (ibm-granite/granite-embedding-97m-multilingual-r2)
          2. Gemini / Vertex AI embedding API (only when ``USE_GEMINI_EMBEDDING=True``)
          3. Mock zero vector (last resort)

        The local model is the default primary path.  The Gemini path exists as a
        configurable alternative and is **disabled** by default (see
        ``settings.USE_GEMINI_EMBEDDING``).
        """
        dim = settings.EMBEDDING_DIMENSION
        vector = None

        # Path 1: Local Sentence‑Transformer model (primary)
        try:
            from app.core.local_embeddings import LocalEmbeddingModel
            if LocalEmbeddingModel.is_available():
                vector = LocalEmbeddingModel.encode(text)
                logger.info("Using local Sentence‑Transformer embedding (dim=%d)", len(vector))
        except Exception as e:
            logger.warning(f"Local embedding model failed: {e}")

        # Path 2: Gemini / Vertex AI (only when explicitly enabled)
        if vector is None and settings.USE_GEMINI_EMBEDDING:
            cls._initialize_client()
            mode = cls._client_mode
            if mode in (cls.API_KEY, cls.VERTEX_MODERN):
                try:
                    from google.genai import types
                    model_id = settings.GEMINI_EMBEDDING_MODEL_ID
                    result = cls._client.models.embed_content(
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

        # Path 3: Mock zero vector (last resort)
        if vector is None:
            logger.warning("All embedding methods failed, returning mock %d-dim zero vector", dim)
            vector = [0.0] * dim

        if settings.LANGFUSE_ENABLED:
            try:
                get_client().update_current_span(
                    input={"text_length": len(text), "task_type": task_type},
                    output={"vector_length": len(vector)}
                )
            except Exception as lf_err:
                logger.warning(f"Failed to update Langfuse span: {lf_err}")

        return vector
