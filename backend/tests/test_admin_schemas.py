"""Tests for admin Pydantic schemas (app.core.admin.schemas)."""

from datetime import date
from pydantic import ValidationError
import pytest

from app.core.admin.schemas import (
    AuditLogEntry,
    ErrorResponse,
    HsCodeCreate,
    HsCodeResponse,
    HsCodeUpdate,
    LawDocumentCreate,
    LawDocumentResponse,
    LawDocumentUpdate,
    PaginatedResponse,
    ReindexRequest,
    ReindexStatus,
)


class TestLawDocumentCreate:
    def test_valid(self):
        data = LawDocumentCreate(
            title="Таможенный кодекс РК",
            article="Статья 124",
            content="Полный текст статьи...",
            keywords="таможня, кодекс",
            effective_date=date(2024, 1, 1),
        )
        assert data.title == "Таможенный кодекс РК"
        assert data.article == "Статья 124"
        assert data.content == "Полный текст статьи..."
        assert data.keywords == "таможня, кодекс"
        assert data.effective_date == date(2024, 1, 1)

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            LawDocumentCreate()

    def test_default_keywords(self):
        data = LawDocumentCreate(title="Закон", article="1", content="Содержание")
        assert data.keywords == ""
        assert data.effective_date is None


class TestLawDocumentUpdate:
    def test_partial_title_only(self):
        data = LawDocumentUpdate(title="Новый заголовок")
        assert data.title == "Новый заголовок"
        assert data.article is None
        assert data.content is None
        assert data.keywords is None
        assert data.effective_date is None

    def test_partial_content_only(self):
        data = LawDocumentUpdate(content="Обновлённое содержание")
        assert data.content == "Обновлённое содержание"
        assert data.title is None

    def test_empty_is_valid(self):
        """All fields are optional."""
        data = LawDocumentUpdate()
        assert data.title is None
        assert data.article is None
        assert data.content is None
        assert data.keywords is None
        assert data.effective_date is None


class TestLawDocumentResponse:
    def test_default_status(self):
        data = LawDocumentResponse(
            id="123",
            document_title="T",
            article_number="A",
            content_quote="C",
            keywords="k",
        )
        assert data.status == "indexed"
        assert data.tags == []
        assert data.effective_date is None


class TestHsCodeCreate:
    def test_valid(self):
        data = HsCodeCreate(
            hs_code="0101.21.0000",
            product_name_ru="Лошади",
            duty_rate=5.0,
            excise_rate=2.5,
            recycling_fee=True,
            keywords="лошади, животные",
        )
        assert data.hs_code == "0101.21.0000"
        assert data.product_name_ru == "Лошади"
        assert data.duty_rate == 5.0
        assert data.excise_rate == 2.5
        assert data.recycling_fee is True
        assert data.keywords == "лошади, животные"

    def test_invalid_duty_rate(self):
        with pytest.raises(ValidationError):
            HsCodeCreate(
                hs_code="0101.21.0000",
                product_name_ru="Лошади",
                duty_rate=-1.0,
            )

    def test_invalid_excise_rate(self):
        with pytest.raises(ValidationError):
            HsCodeCreate(
                hs_code="0101.21.0000",
                product_name_ru="Лошади",
                duty_rate=5.0,
                excise_rate=-0.5,
            )

    def test_defaults(self):
        data = HsCodeCreate(
            hs_code="0101.21.0000",
            product_name_ru="Лошади",
            duty_rate=5.0,
        )
        assert data.excise_rate == 0.0
        assert data.recycling_fee is False
        assert data.keywords == ""


class TestHsCodeUpdate:
    def test_partial_product_name_only(self):
        data = HsCodeUpdate(product_name_ru="Обновлённое название")
        assert data.product_name_ru == "Обновлённое название"
        assert data.duty_rate is None
        assert data.excise_rate is None
        assert data.recycling_fee is None
        assert data.keywords is None

    def test_partial_duty_rate_only(self):
        data = HsCodeUpdate(duty_rate=10.0)
        assert data.duty_rate == 10.0
        assert data.product_name_ru is None

    def test_empty_is_valid(self):
        data = HsCodeUpdate()
        assert data.product_name_ru is None
        assert data.duty_rate is None

    def test_invalid_duty_rate_negative(self):
        with pytest.raises(ValidationError):
            HsCodeUpdate(duty_rate=-5.0)


class TestHsCodeResponse:
    def test_default_status(self):
        data = HsCodeResponse(
            id="abc",
            hs_code="0101.21.0000",
            product_name_ru="Лошади",
            duty_rate_percent=5.0,
        )
        assert data.status == "indexed"
        assert data.product_name_en == ""
        assert data.excise_rate_percent == 0.0
        assert data.is_subject_to_recycling_fee is False


class TestReindexRequest:
    def test_valid_laws(self):
        data = ReindexRequest(collection="laws")
        assert data.collection == "laws"

    def test_valid_hs_codes(self):
        data = ReindexRequest(collection="hs_codes")
        assert data.collection == "hs_codes"

    def test_valid_all(self):
        data = ReindexRequest(collection="all")
        assert data.collection == "all"

    def test_invalid_collection_unknown(self):
        """Schema does not validate the collection value — the router does."""
        data = ReindexRequest(collection="unknown")
        assert data.collection == "unknown"

    def test_missing_collection(self):
        with pytest.raises(ValidationError):
            ReindexRequest()


class TestReindexStatus:
    def test_default_message_and_progress(self):
        data = ReindexStatus(job_id="job-1", status="running")
        assert data.job_id == "job-1"
        assert data.status == "running"
        assert data.progress == "0%"
        assert data.message == ""

    def test_valid(self):
        data = ReindexStatus(
            job_id="job-1",
            status="started",
            progress="50%",
            message="Reindexing laws",
        )
        assert data.job_id == "job-1"
        assert data.status == "started"
        assert data.progress == "50%"


class TestPaginatedResponse:
    def test_structure(self):
        items = [{"id": 1}, {"id": 2}]
        data = PaginatedResponse(items=items, total=2, page=1, size=10)
        assert data.items == items
        assert data.total == 2
        assert data.page == 1
        assert data.size == 10

    def test_empty_items(self):
        data = PaginatedResponse(items=[], total=0, page=1, size=10)
        assert data.items == []
        assert data.total == 0

    def test_missing_required(self):
        with pytest.raises(ValidationError):
            PaginatedResponse()


class TestAuditLogEntry:
    def test_structure(self):
        ts = "2024-06-15T10:30:00"
        data = AuditLogEntry(
            timestamp=ts,
            actor="admin@example.com",
            action="create",
            entity_type="law",
            entity_id="doc-123",
            changes={"title": "New title"},
            old_values={"title": "Old title"},
            new_values={"title": "New title"},
        )
        assert data.timestamp == ts
        assert data.actor == "admin@example.com"
        assert data.action == "create"
        assert data.entity_type == "law"
        assert data.entity_id == "doc-123"
        assert data.changes == {"title": "New title"}
        assert data.old_values == {"title": "Old title"}
        assert data.new_values == {"title": "New title"}

    def test_default_actor_and_empty_changes(self):
        data = AuditLogEntry(
            timestamp="2024-06-15T10:30:00",
            action="delete",
            entity_type="hs_code",
        )
        assert data.actor == "admin"
        assert data.changes == {}
        assert data.old_values is None
        assert data.new_values is None
        assert data.entity_id == ""

    def test_missing_timestamp(self):
        with pytest.raises(ValidationError):
            AuditLogEntry(action="delete", entity_type="hs_code")

    def test_missing_action(self):
        with pytest.raises(ValidationError):
            AuditLogEntry(timestamp="2024-06-15T10:30:00", entity_type="hs_code")


class TestErrorResponse:
    def test_valid(self):
        data = ErrorResponse(detail="Not found", error_code="NOT_FOUND")
        assert data.detail == "Not found"
        assert data.error_code == "NOT_FOUND"

    def test_error_code_optional(self):
        data = ErrorResponse(detail="Server error")
        assert data.detail == "Server error"
        assert data.error_code is None

    def test_missing_detail(self):
        with pytest.raises(ValidationError):
            ErrorResponse()
