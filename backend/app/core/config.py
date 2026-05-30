import os
import sys
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "CustomAI Kazakhstan"
    API_VERSION: str = "1.0.0"

    # Vertex AI / GCP Configuration
    GOOGLE_CLOUD_PROJECT: str = os.getenv(
        "GOOGLE_CLOUD_PROJECT", "project-432947fc-1170-4cc3-9fc"
    )
    GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
    GOOGLE_API_KEY: Optional[str] = os.getenv("GOOGLE_API_KEY") or os.getenv(
        "GOOGLE_CLOUD_API_KEY"
    )
    GEMINI_MODEL_ID: str = os.getenv("GEMINI_MODEL_ID", "gemini-3.1-flash-lite")
    # Gemini Embedding (disabled by default — use local model instead)
    GEMINI_EMBEDDING_MODEL_ID: str = os.getenv(
        "GEMINI_EMBEDDING_MODEL_ID", "gemini-embedding-2"
    )
    USE_GEMINI_EMBEDDING: bool = os.getenv("USE_GEMINI_EMBEDDING", "False").lower() in (
        "true",
        "1",
        "yes",
    )
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "384"))
    # Local Sentence‑Transformer model (primary embedding provider)
    EMBEDDING_MODEL_NAME: str = os.getenv(
        "EMBEDDING_MODEL_NAME", "ibm-granite/granite-embedding-97m-multilingual-r2"
    )
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_API_KEY: Optional[str] = os.getenv("QDRANT_API_KEY", None)

    # Relational Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./customs_ai.db")

    # Langfuse Configuration
    LANGFUSE_PUBLIC_KEY: Optional[str] = os.getenv("LANGFUSE_PUBLIC_KEY", None)
    LANGFUSE_SECRET_KEY: Optional[str] = os.getenv("LANGFUSE_SECRET_KEY", None)
    LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    LANGFUSE_ENABLED: bool = os.getenv("LANGFUSE_ENABLED", "True").lower() in (
        "true",
        "1",
        "yes",
    )
    # Admin API
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "admin-secret-change-me")
    # Configuration Service
    CONFIG_DB_PATH: str = os.getenv("CONFIG_DB_PATH", "data/config.json")
    # Classification Rules Engine
    RULES_CACHE_TTL: int = 300  # 5 minutes

    model_config = SettingsConfigDict(
        case_sensitive=True, env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── Document Parsing / Upload ─────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "10"))
    TEMP_UPLOAD_DIR: str = os.getenv("TEMP_UPLOAD_DIR", "/tmp/smartkeden_uploads")
    OCR_PRIMARY: str = os.getenv("OCR_PRIMARY", "gemini")  # gemini | tesseract


settings = Settings()

# Disable Langfuse if running under pytest
if "pytest" in sys.modules:
    settings.LANGFUSE_ENABLED = False

# Synchronize environment variables for Langfuse SDK if set and enabled
if settings.LANGFUSE_ENABLED:
    if settings.LANGFUSE_PUBLIC_KEY:
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
    if settings.LANGFUSE_SECRET_KEY:
        os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
    if settings.LANGFUSE_HOST:
        os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_HOST
    if settings.LANGFUSE_HOST:
        os.environ["LANGFUSE_BASE_URL"] = settings.LANGFUSE_HOST
else:
    # Explicitly clear keys if disabled to prevent any network tracking
    os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
    os.environ.pop("LANGFUSE_SECRET_KEY", None)
