import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, JsonColumn
from .enums import (
    AssessmentStatus,
    CaseStatus,
    EscalationStatus,
    ObjectKind,
    RoadmapItemStatus,
    Role,
)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Municipality(Base):
    """Муниципальное образование — единица разграничения доступа."""

    __tablename__ = "municipality"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255), unique=True)
    code: Mapped[str | None] = mapped_column(String(32), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    users: Mapped[list["User"]] = relationship(back_populates="municipality")


class User(Base, TimestampMixin):
    """Учётная запись. Доступ выдаёт оператор системы (ответ № 2 брифа)."""

    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = _uuid_pk()
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default=Role.SPECIALIST)
    municipality_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("municipality.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    municipality: Mapped[Municipality | None] = relationship(back_populates="users")


class ObjectCase(Base, TimestampMixin):
    """Дело по объекту: сведения, собранные на этапах 1-3, введённые сотрудником."""

    __tablename__ = "object_case"

    id: Mapped[uuid.UUID] = _uuid_pk()
    municipality_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("municipality.id"), index=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))

    cadastral_number_oks: Mapped[str | None] = mapped_column(String(64), index=True)
    cadastral_number_land: Mapped[str | None] = mapped_column(String(64), index=True)
    address: Mapped[str] = mapped_column(Text)
    object_kind: Mapped[str] = mapped_column(String(32), default=ObjectKind.IZHS)

    # Several states can hold at once (ownerless + FPO is common), so this is a list.
    states: Mapped[list[str]] = mapped_column(JsonColumn, default=list)

    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=CaseStatus.DRAFT, index=True)

    # Filled once the ЦИУН integration is connected; unused in this stage.
    ciun_object_id: Mapped[str | None] = mapped_column(String(128), index=True)
    ciun_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    municipality: Mapped[Municipality] = relationship()
    created_by: Mapped[User] = relationship()
    assessments: Mapped[list["Assessment"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", order_by="Assessment.created_at"
    )


class Assessment(Base, TimestampMixin):
    """Одна проверка по делу.

    Ответы и рассчитанное решение сохраняются снимком: правила могут измениться,
    а ранее утверждённое решение обязано остаться воспроизводимым.
    """

    __tablename__ = "assessment"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("object_case.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    status: Mapped[str] = mapped_column(String(32), default=AssessmentStatus.DRAFT, index=True)

    answers: Mapped[dict] = mapped_column(JsonColumn, default=dict)
    decision: Mapped[dict | None] = mapped_column(JsonColumn)
    ruleset_version: Mapped[str | None] = mapped_column(String(64))

    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Authorship fixation. content_hash is filled on approval; the signature columns
    # stay empty until УКЭП is connected (see docs/signature.md).
    content_hash: Mapped[str | None] = mapped_column(String(64))
    signature_blob: Mapped[str | None] = mapped_column(Text)
    signature_cert_thumbprint: Mapped[str | None] = mapped_column(String(128))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    case: Mapped[ObjectCase] = relationship(back_populates="assessments")
    author: Mapped[User] = relationship(foreign_keys=[author_id])
    approved_by: Mapped[User | None] = relationship(foreign_keys=[approved_by_id])
    roadmap_items: Mapped[list["RoadmapItem"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="RoadmapItem.order_index",
    )
    documents: Mapped[list["AssessmentDocument"]] = relationship(
        back_populates="assessment", cascade="all, delete-orphan"
    )


class RoadmapItem(Base, TimestampMixin):
    """Шаг порядка действий, превращённый в рабочее поручение."""

    __tablename__ = "roadmap_item"

    id: Mapped[uuid.UUID] = _uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.id", ondelete="CASCADE"), index=True
    )
    method_code: Mapped[str] = mapped_column(String(64))
    order_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16), default="action")
    text: Mapped[str] = mapped_column(Text)

    status: Mapped[str] = mapped_column(String(32), default=RoadmapItemStatus.PENDING)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    due_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assessment: Mapped[Assessment] = relationship(back_populates="roadmap_items")
    assignee: Mapped[User | None] = relationship()


class AssessmentDocument(Base, TimestampMixin):
    """Протокол проверки, сохранённый как файл.

    Содержание берётся из снимка решения и потому воспроизводимо, а вот байты — нет:
    PDF вшивает дату создания, и повторная сборка даст другой ``content_sha256``.
    Поэтому хранится именно сформированный экземпляр: он уходит в СЭДО и архив, и
    он же будет подписан, когда подключат УКЭП. Срок хранения — постоянно
    (ответ № 6 брифа).
    """

    __tablename__ = "assessment_document"
    __table_args__ = (
        UniqueConstraint("assessment_id", "format", name="uq_assessment_document_format"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("assessment.id", ondelete="CASCADE"), index=True
    )
    format: Mapped[str] = mapped_column(String(8))
    filename: Mapped[str] = mapped_column(String(255))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    content_sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)

    generated_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    assessment: Mapped["Assessment"] = relationship(back_populates="documents")
    generated_by: Mapped[User] = relationship()


class Method(Base, TimestampMixin):
    """Справочник способов оформления и порядков действий (этап 4 ТЗ)."""

    __tablename__ = "method"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    family: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(Text)
    steps: Mapped[list[dict]] = mapped_column(JsonColumn, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ScenarioRule(Base, TimestampMixin):
    """Правило матрицы: набор признаков -> способы.

    Импортируется из ТЗ и дополняется методологом через админку, поэтому
    ``is_builtin`` отличает выгруженное из документа от добавленного вручную.
    """

    __tablename__ = "scenario_rule"
    __table_args__ = (UniqueConstraint("code", name="uq_scenario_rule_code"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(64), index=True)
    object_kind: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    scenario_num: Mapped[int] = mapped_column(Integer)

    conditions: Mapped[dict] = mapped_column(JsonColumn, default=dict)
    method_codes: Mapped[list[str]] = mapped_column(JsonColumn, default=list)

    source: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))

    created_by: Mapped[User | None] = relationship()


class Escalation(Base, TimestampMixin):
    """Обращение к методологу, когда точного сценария в матрице нет."""

    __tablename__ = "escalation"

    id: Mapped[uuid.UUID] = _uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("object_case.id", ondelete="CASCADE"))
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("assessment.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"))

    inputs: Mapped[dict] = mapped_column(JsonColumn, default=dict)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default=EscalationStatus.OPEN, index=True)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    case: Mapped[ObjectCase] = relationship()
    created_by: Mapped[User] = relationship(foreign_keys=[created_by_id])
    resolved_by: Mapped[User | None] = relationship(foreign_keys=[resolved_by_id])


class AuditLog(Base):
    """Журнал действий: кто выполнил проверку и сформировал решение."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"), index=True)
    actor_login: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)
    payload: Mapped[dict | None] = mapped_column(JsonColumn)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), index=True
    )
