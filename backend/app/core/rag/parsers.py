from abc import ABC, abstractmethod
import logging
import re
import csv
import io
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class BaseDocumentParser(ABC):
    """Abstract base class for all legal document parsers."""

    @abstractmethod
    def parse(self, raw_text: str, doc_title: str) -> List[Dict[str, Any]]:
        """Parses raw text and returns a list of standardized IdeaBlocks."""
        pass


class CodeDocumentParser(BaseDocumentParser):
    """Parses codes like Customs and Tax Codes, splitting by 'Статья X' boundaries."""

    def parse(self, raw_text: str, doc_title: str) -> List[Dict[str, Any]]:
        if not raw_text or not raw_text.strip():
            return []

        blocks = []
        lines = raw_text.split("\n")
        current_article = "Общие положения"
        current_content = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Naive parse matching 'Статья '
            if line.startswith("Статья ") or "Статья " in line[:20]:
                if current_content:
                    quote = " ".join(current_content)
                    blocks.append(
                        {
                            "document_title": doc_title,
                            "article_number": current_article,
                            "content_quote": quote,
                            "tags": ["AUTO_PARSED", "REGULATION"],
                            "keywords": ", ".join(current_article.lower().split()),
                        }
                    )
                    current_content = []

                parts = line.split(".", 1)
                current_article = parts[0].strip()
                if len(parts) > 1:
                    current_content.append(parts[1].strip())
            else:
                current_content.append(line)

        # Append the last block if it exists
        if current_content:
            quote = " ".join(current_content)
            blocks.append(
                {
                    "document_title": doc_title,
                    "article_number": current_article,
                    "content_quote": quote,
                    "tags": ["AUTO_PARSED", "REGULATION"],
                    "keywords": ", ".join(current_article.lower().split()),
                }
            )

        return blocks


class DecisionDocumentParser(BaseDocumentParser):
    """Parses decisions (EEC/RK), splitting by 'Решение', 'Пункт', or numbered clauses."""

    def parse(self, raw_text: str, doc_title: str) -> List[Dict[str, Any]]:
        if not raw_text or not raw_text.strip():
            return []

        blocks = []
        lines = raw_text.split("\n")
        current_section = "Введение"
        current_content = []

        # Match boundary patterns at the start of lines
        boundary_re = re.compile(r"^(Решение|Пункт|\d+\.)", re.IGNORECASE)

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if boundary_re.match(line):
                if current_content:
                    quote = " ".join(current_content)
                    blocks.append(
                        {
                            "document_title": doc_title,
                            "article_number": current_section,
                            "content_quote": quote,
                            "tags": ["AUTO_PARSED", "DECISION"],
                            "keywords": ", ".join(current_section.lower().split()),
                        }
                    )
                    current_content = []

                match = boundary_re.match(line)
                prefix = match.group(1)

                if prefix.endswith(".") or re.match(r"^\d+\.", prefix):
                    parts = line.split(" ", 1)
                    current_section = parts[0].strip()
                    if len(parts) > 1:
                        current_content.append(parts[1].strip())
                else:
                    subparts = line.split(".", 1)
                    current_section = subparts[0].strip()
                    if len(subparts) > 1:
                        current_content.append(subparts[1].strip())
                    else:
                        words = line.split()
                        current_section = (
                            " ".join(words[:2]) if len(words) > 2 else line
                        )
                        current_content.append(line)
            else:
                current_content.append(line)

        if current_content:
            quote = " ".join(current_content)
            blocks.append(
                {
                    "document_title": doc_title,
                    "article_number": current_section,
                    "content_quote": quote,
                    "tags": ["AUTO_PARSED", "DECISION"],
                    "keywords": ", ".join(current_section.lower().split()),
                }
            )

        return blocks


class TariffTableParser(BaseDocumentParser):
    """Parses CSV/TSV tariff tables, extracting exact rows and attributes."""

    def parse(self, raw_text: str, doc_title: str) -> List[Dict[str, Any]]:
        if not raw_text or not raw_text.strip():
            return []

        blocks = []
        # Detect delimiter based on first line
        first_line = raw_text.split("\n")[0]
        delimiter = "\t" if "\t" in first_line else ","

        f = io.StringIO(raw_text.strip())
        reader = csv.DictReader(f, delimiter=delimiter)

        for idx, row in enumerate(reader):
            if not row:
                continue

            hs_code = row.get("hs_code") or row.get("code") or f"ROW_{idx + 1}"
            name = row.get("name") or row.get("description") or ""
            duty = row.get("duty") or row.get("rate") or ""

            # Key-value serialization for content quote
            row_items = [f"{k}: {v}" for k, v in row.items() if k and v]
            quote = ", ".join(row_items)

            blocks.append(
                {
                    "document_title": doc_title,
                    "article_number": f"HS {hs_code}",
                    "content_quote": quote,
                    "tags": ["AUTO_PARSED", "TARIFF"],
                    "keywords": f"{hs_code}, {name}".lower(),
                    "hs_code": hs_code,
                    "name": name,
                    "duty": duty,
                }
            )

        return blocks


class DocumentParserRegistry:
    """Registry to register and retrieve document parsers."""

    _parsers: Dict[str, BaseDocumentParser] = {}

    @classmethod
    def register(cls, doc_type: str, parser: BaseDocumentParser):
        """Registers a parser instance for a document type."""
        cls._parsers[doc_type] = parser

    @classmethod
    def get_parser(cls, doc_type: str) -> BaseDocumentParser:
        """Retrieves parser for doc_type, defaulting to CodeDocumentParser if unknown."""
        parser = cls._parsers.get(doc_type)
        if parser is None:
            logger.warning(
                "Unknown document type '%s'. Defaulting to CodeDocumentParser.",
                doc_type,
            )
            return cls._parsers.get("code") or CodeDocumentParser()
        return parser

    @classmethod
    def parse(
        cls, raw_text: str, doc_title: str, doc_type: str = "code"
    ) -> List[Dict[str, Any]]:
        """Utility method to directly parse using the registered parser."""
        try:
            parser = cls.get_parser(doc_type)
            return parser.parse(raw_text, doc_title)
        except Exception as e:
            logger.warning(
                "Error parsing document '%s' with parser '%s': %s",
                doc_title,
                doc_type,
                e,
            )
            return []


# Self-register default parsers
DocumentParserRegistry.register("code", CodeDocumentParser())
DocumentParserRegistry.register("decision", DecisionDocumentParser())
DocumentParserRegistry.register("tariff", TariffTableParser())
