import re
import os
import logging
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ConfigLoader:
    """Loads and caches declarative YAML configurations for intents and FAQ fast-path."""

    _instance: Optional["ConfigLoader"] = None
    _cache: Dict[str, Any] = {}

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(ConfigLoader, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, config_dir: Optional[str] = None):
        if not hasattr(self, "config_dir"):
            if config_dir is None:
                # Default to subdirectory 'config' of orchestrator folder
                config_dir = Path(__file__).parent / "config"
            self.config_dir = Path(config_dir)

    def load_yaml(self, filename: str) -> Dict[str, Any]:
        """Loads a YAML file from the config directory with in-memory caching."""
        file_path = self.config_dir / filename
        cache_key = str(file_path.resolve())

        if cache_key in self._cache:
            return self._cache[cache_key]

        if not file_path.exists():
            logger.warning("Configuration file %s does not exist", file_path)
            return {}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
                self._cache[cache_key] = data
                return data
        except Exception as e:
            logger.error("Failed to load YAML configuration %s: %s", file_path, e)
            return {}

    def check_faq(self, query: str) -> Optional[str]:
        """
        Scans all FAQ entries for a keyword match against the cleaned query.
        Returns the pre-approved response if matched, otherwise None.
        """
        faq_data = self.load_yaml("faq.yaml")
        if not faq_data:
            return None

        # Clean query: lowercase and strip common punctuation
        clean_query = query.lower().strip()
        clean_query = re.sub(r"[^\w\s-]", "", clean_query)
        words = set(clean_query.split())

        for category, entries in faq_data.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if (
                    not isinstance(entry, dict)
                    or "keywords" not in entry
                    or "response" not in entry
                ):
                    continue
                keywords = entry["keywords"]
                response = entry["response"]

                # Check if any keyword matches the query.
                # We check either direct keyword substring or exact word match for robust matching.
                for kw in keywords:
                    kw_clean = kw.lower().strip()
                    # Word-boundary or substring match
                    if kw_clean in clean_query or kw_clean in words:
                        return response

        return None

    def get_intent_config(self) -> Dict[str, Any]:
        """Returns the intent classification parameters or hardcoded defaults."""
        data = self.load_yaml("intents.yaml")
        if not data:
            # Fallback defaults to match previous hardcoded list
            return {
                "system_prompt": "Classify the user's customs-related message into exactly one intent.",
                "examples": [
                    ["Какая ставка НДС на импорт в Казахстан?", "question_about_law"],
                    [
                        "Что говорит кодекс о таможенной стоимости?",
                        "question_about_law",
                    ],
                    ["классифицируй детскую игрушку Lego", "product_description"],
                    ["определи код ТН ВЭД для ноутбука", "product_description"],
                    [
                        "посчитай пошлину на товар 9503008900 из Китая",
                        "calculation_request",
                    ],
                    ["сколько будет растаможка iPhone 15 Pro", "calculation_request"],
                    ["загрузи новый закон о торговле", "document_upload"],
                    ["привет!", "greeting"],
                    ["здравствуйте", "greeting"],
                ],
            }
        return data
