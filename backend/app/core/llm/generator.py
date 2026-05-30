"""
Text generation seam with a Gemini/Vertex AI adapter.

All LLM text-generation callers depend on ``TextGenerator``, never on the
concrete adapter.  This makes tests injectable and keeps observability
(Langfuse) in one place.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Type, TypeVar

from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# ── Observability ──────────────────────────────────────────────────────────
# Import after the compat shim has run.
from langfuse import observe, get_client  # noqa: E402


def _extract_usage(response) -> Optional[dict]:
    """Pull token counts from a genai response object (best-effort)."""
    if not response:
        return None
    usage: dict = {}
    usage_metadata = getattr(response, "usage_metadata", None)
    if usage_metadata:
        usage["prompt_tokens"] = getattr(usage_metadata, "prompt_token_count", None)
        usage["completion_tokens"] = getattr(
            usage_metadata, "candidates_token_count", None
        )
    else:
        alt = getattr(response, "usage", None) or getattr(response, "usage_info", None)
        if alt:
            usage["prompt_tokens"] = getattr(
                alt, "prompt_token_count", None
            ) or getattr(alt, "input_tokens", None)
            usage["completion_tokens"] = getattr(
                alt, "candidates_token_count", None
            ) or getattr(alt, "output_tokens", None)
    return {k: v for k, v in usage.items() if v is not None} or None


# ── Abstract seam ──────────────────────────────────────────────────────────


class TextGenerator(ABC):
    """Abstract seam for LLM-powered text / structured-output generation."""

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        *,
        image_bytes: Optional[bytes] = None,
        image_mime_type: Optional[str] = "image/jpeg",
    ) -> T: ...

    @abstractmethod
    def generate_chat(
        self,
        system_instruction: str,
        message_history: List[dict],
    ) -> str: ...


# ── Gemini / Vertex AI adapter ─────────────────────────────────────────────


class GeminiTextGenerator(TextGenerator):
    """Concrete adapter that calls Gemini via the google-genai SDK.

    Supports API-key mode, Vertex AI with ADC, and a transparent mock/dev
    fallback when no credentials are available.
    """

    MOCK = "mock"
    API_KEY = "api_key"
    VERTEX_MODERN = "vertex"

    def __init__(self) -> None:
        self._client: object = None
        self._client_mode: Optional[str] = None
        self._initialized = False

    # -- client init --------------------------------------------------------

    def _init_client(self) -> None:
        if self._initialized:
            return

        import os as _os

        api_key = (
            settings.GOOGLE_API_KEY
            or _os.getenv("GOOGLE_API_KEY")
            or _os.getenv("GOOGLE_CLOUD_API_KEY")
        )
        project = settings.GOOGLE_CLOUD_PROJECT or _os.getenv("GOOGLE_CLOUD_PROJECT")
        location = (
            settings.GOOGLE_CLOUD_LOCATION
            or _os.getenv("GOOGLE_CLOUD_LOCATION")
            or "global"
        )

        is_vertex_key = bool(
            api_key
            and (api_key.startswith("AQ.") or location not in (None, "", "global"))
        )

        # Path 1: GOOGLE_API_KEY → Gemini API
        if api_key and not is_vertex_key:
            try:
                from google import genai

                self._client = genai.Client(api_key=api_key)
                self._client_mode = self.API_KEY
                logger.info("Initialized Gemini API client via GOOGLE_API_KEY")
                self._initialized = True
                return
            except Exception as e:
                logger.warning(f"Gemini API client init failed: {e}")

        # Path 2: Vertex AI with API key
        if api_key and is_vertex_key:
            try:
                from google import genai

                self._client = genai.Client(vertexai=True, api_key=api_key)
                self._client_mode = self.VERTEX_MODERN
                logger.info("Initialized Vertex AI client via API key")
                self._initialized = True
                return
            except Exception as e:
                logger.warning(f"Vertex AI init with API key failed: {e}")

        # Path 3: ADC (Application Default Credentials)
        has_adc = bool(
            _os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        ) or _os.path.exists(
            _os.path.expanduser("~/.config/gcloud/application_default_credentials.json")
        )
        if has_adc and not api_key:
            try:
                from google import genai
                from google.auth import default as default_credentials

                creds, adc_project = default_credentials()
                target_project = project or adc_project
                self._client = genai.Client(
                    vertexai=True,
                    project=target_project,
                    location=location,
                    credentials=creds,
                )
                self._client_mode = self.VERTEX_MODERN
                logger.info("Initialized Vertex AI client via ADC")
                self._initialized = True
                return
            except Exception as e:
                logger.warning(f"Vertex AI init via ADC failed: {e}")

        # Fallback: mock
        logger.warning("No Google credentials — running in mock/dev mode.")
        self._client = self.MOCK
        self._client_mode = self.MOCK
        self._initialized = True

    # -- generate_structured ------------------------------------------------

    @observe(as_type="generation")
    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        *,
        image_bytes: Optional[bytes] = None,
        image_mime_type: Optional[str] = "image/jpeg",
    ) -> T:
        self._init_client()

        if self._client_mode == self.MOCK:
            logger.warning("Using mock structured response")
            mock_res = _generate_mock_schema_response(response_schema)
            self._record_langfuse(
                "generate_structured_content (MOCK)",
                settings.GEMINI_MODEL_ID,
                {"prompt": prompt, "has_image": bool(image_bytes)},
                str(mock_res),
            )
            return mock_res

        try:
            from google.genai import types

            contents: list = []
            if image_bytes:
                contents.append(
                    types.Part.from_bytes(data=image_bytes, mime_type=image_mime_type)
                )
            contents.append(prompt)

            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=response_schema,
            )
            model_id = settings.GEMINI_MODEL_ID
            response = self._client.models.generate_content(  # type: ignore[union-attr]
                model=model_id,
                contents=contents,
                config=config,
            )
            result = response_schema.model_validate_json(response.text)
            self._record_langfuse(
                "generate_structured_content",
                model_id,
                {"prompt": prompt, "has_image": bool(image_bytes)},
                response.text,
                response,
            )
            return result
        except Exception:
            logger.error(
                "Error generating structured content from Gemini", exc_info=True
            )
            raise

    # -- generate_chat ------------------------------------------------------

    @observe(as_type="generation")
    def generate_chat(
        self,
        system_instruction: str,
        message_history: List[dict],
    ) -> str:
        self._init_client()

        if self._client_mode == self.MOCK:
            mock_text = (
                "Это демонстрационный ответ. "
                "Пожалуйста, настройте учетные данные Google Cloud Vertex AI для реальных консультаций."
            )
            self._record_langfuse(
                "generate_chat_response (MOCK)",
                settings.GEMINI_MODEL_ID,
                {"system_instruction": system_instruction},
                mock_text,
            )
            return mock_text

        try:
            from google.genai import types

            config = types.GenerateContentConfig(system_instruction=system_instruction)
            model_id = settings.GEMINI_MODEL_ID

            contents: list = []
            for msg in message_history:
                role = "user" if msg["role"] == "user" else "model"
                contents.append(
                    types.Content(
                        role=role, parts=[types.Part.from_text(text=msg["content"])]
                    )
                )

            response = self._client.models.generate_content(  # type: ignore[union-attr]
                model=model_id,
                contents=contents,
                config=config,
            )
            text_out = response.text
            self._record_langfuse(
                "generate_chat_response",
                model_id,
                {"system_instruction": system_instruction},
                text_out,
                response,
            )
            return text_out
        except Exception as e:
            logger.error(f"Error generating chat response from Gemini: {e}")
            return f"Ошибка при подключении к Gemini: {str(e)}"

    # -- Langfuse helper ----------------------------------------------------

    def _record_langfuse(
        self,
        name: str,
        model: str,
        input_data: dict,
        output: str,
        response: object = None,
    ) -> None:
        if not settings.LANGFUSE_ENABLED:
            return
        try:
            get_client().update_current_generation(
                name=name,
                model=model,
                input=input_data,
                output=output,
                usage_details=_extract_usage(response)
                if response
                else {"prompt_tokens": 0, "completion_tokens": 0},
            )
        except Exception as lf_err:
            logger.warning(f"Failed to update Langfuse generation: {lf_err}")


# ── Mock helpers (moved from GeminiVertexClient) ───────────────────────────


def _generate_mock_schema_response(schema: Type[T]) -> T:
    """Create dummy data conforming to *schema* for testing without API keys."""
    sample_data: dict = {}
    schema_clean = _inline_refs(schema)
    props = getattr(schema_clean, "model_fields", None) or {}
    for field_name, field_info in props.items():
        annotation = field_info.annotation
        if annotation is float:
            sample_data[field_name] = 0.0
        elif annotation is int:
            sample_data[field_name] = 0
        elif annotation is bool:
            sample_data[field_name] = False
        elif annotation is str:
            sample_data[field_name] = "mock"
        elif hasattr(annotation, "model_fields"):
            sample_data[field_name] = _generate_mock_schema_response(annotation)
        elif hasattr(annotation, "__origin__") and annotation.__origin__ is list:
            inner = annotation.__args__[0] if annotation.__args__ else str
            if hasattr(inner, "model_fields"):
                sample_data[field_name] = [_generate_mock_schema_response(inner)]
            else:
                sample_data[field_name] = []
        else:
            sample_data[field_name] = None
    return schema.model_validate(sample_data)


def _inline_refs(schema, defs=None):
    """Resolve JSON Schema ``$defs`` / ``$ref`` to produce flat field metadata."""
    if defs is None:
        raw = getattr(schema, "model_json_schema", lambda: {})()
        defs = raw.get("$defs", {})
    if hasattr(schema, "model_fields"):
        return schema
    try:
        ref = schema.get("$ref", "")
        if ref.startswith("#/$defs/"):
            key = ref.split("/")[-1]
            return defs.get(key, schema)
    except AttributeError:
        pass
    return schema


# ── Module-level singleton ─────────────────────────────────────────────────

_generator: Optional[TextGenerator] = None


def get_generator() -> TextGenerator:
    """Return the module-level TextGenerator singleton."""
    global _generator
    if _generator is None:
        _generator = GeminiTextGenerator()
    return _generator


def set_generator(g: TextGenerator) -> None:
    """Inject a TextGenerator (for testing)."""
    global _generator
    _generator = g
