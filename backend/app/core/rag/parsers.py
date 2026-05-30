from abc import ABC, abstractmethod
import logging
import re
import csv
import io
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class BaseDocumentParser(ABC):
    """Abstract base class for all legal document parsers."""

    @abstractmethod
    def parse(self, raw_text: str, doc_title: str) -> List[Dict[str, Any]]:
        """Parses raw text and returns a list of standardized KnowledgeChunks."""
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


class MarkdownBlockParser(BaseDocumentParser):
    """Parses MarkItDown-produced Markdown into KnowledgeChunk dicts by heading and article boundaries.

    Splits on Markdown ATX headings (#, ##, ###). When a heading or the first body line
    contains ``Статья N`` near its start, that is used as ``article_number``; otherwise the
    heading text itself becomes the article reference.
    """

    HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)(?:\s+#{1,3}\s*)?$")
    ARTICLE_RE = re.compile(r"Статья\s+(\d+)")

    def parse(self, raw_text: str, doc_title: str) -> List[Dict[str, Any]]:
        if not raw_text or not raw_text.strip():
            return []

        lines = raw_text.split("\n")
        blocks: List[Dict[str, Any]] = []
        current_heading: Optional[str] = None
        current_content: List[str] = []

        for line in lines:
            s = line.strip()
            if not s:
                continue

            hm = self.HEADING_RE.match(s)
            if hm:
                # Flush previous block if it has content
                if current_heading is not None and current_content:
                    blocks.append(
                        self._make_block(doc_title, current_heading, current_content)
                    )
                current_heading = hm.group(2).strip()
                current_content = []
                continue

            if current_heading is not None:
                current_content.append(s)

        # Flush final block
        if current_heading is not None and current_content:
            blocks.append(
                self._make_block(doc_title, current_heading, current_content)
            )

        return blocks

    def _make_block(
        self, doc_title: str, heading: str, content_lines: List[str]
    ) -> Dict[str, Any]:
        """Build a single KnowledgeChunk dict from a heading and its body lines."""
        content_text = " ".join(content_lines).strip()

        # Default article_number from heading text
        article_number = heading

        # Check heading for explicit "Статья N"
        art_match = self.ARTICLE_RE.search(heading)
        if art_match:
            article_number = art_match.group(0)
        elif content_lines:
            # Check first body line for "Статья N" near the start
            first = content_lines[0].strip()
            if "Статья " in first[:30]:
                art_match = self.ARTICLE_RE.search(first)
                if art_match:
                    article_number = art_match.group(0)

        return {
            "document_title": doc_title,
            "article_number": article_number,
            "content_quote": content_text,
            "tags": ["AUTO_PARSED", "MARKDOWN"],
            "keywords": ", ".join(article_number.lower().split()),
        }


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
DocumentParserRegistry.register("markdown", MarkdownBlockParser())
