import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from .security import BCRYPT_MAX_BYTES
from .enums import (
    AssessmentStatus,
    CaseStatus,
    EscalationStatus,
    ObjectKind,
    ObjectState,
    RoadmapItemStatus,
    Role,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _fits_bcrypt(password: str) -> str:
    """bcrypt отбрасывает всё после 72 байт: кириллица упирается в предел вдвое
    раньше латиницы, поэтому ограничение считается в байтах, а не в символах."""
    if len(password.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"пароль длиннее {BCRYPT_MAX_BYTES} байт в кодировке UTF-8 "
            "(около 36 символов кириллицей)"
        )
    return password


Password = Annotated[str, Field(min_length=8, max_length=128), AfterValidator(_fits_bcrypt)]


# --- аутентификация ---------------------------------------------------------


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MunicipalityOut(ORMModel):
    id: uuid.UUID
    name: str
    code: str | None
    is_active: bool


class UserOut(ORMModel):
    id: uuid.UUID
    login: str
    full_name: str
    position: str | None
    role: Role
    is_active: bool
    municipality: MunicipalityOut | None = None


class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: Password
    full_name: str = Field(min_length=1, max_length=255)
    position: str | None = None
    role: Role = Role.SPECIALIST
    municipality_id: uuid.UUID | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    position: str | None = None
    role: Role | None = None
    municipality_id: uuid.UUID | None = None
    is_active: bool | None = None
    password: Password | None = None


class MunicipalityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    code: str | None = Field(default=None, max_length=32)


# --- дела -------------------------------------------------------------------


class CaseBase(BaseModel):
    address: str = Field(min_length=1)
    object_kind: ObjectKind
    states: list[ObjectState] = Field(default_factory=list)
    cadastral_number_oks: str | None = None
    cadastral_number_land: str | None = None
    notes: str | None = None


class CaseCreate(CaseBase):
    municipality_id: uuid.UUID | None = None


class CaseUpdate(BaseModel):
    address: str | None = None
    object_kind: ObjectKind | None = None
    states: list[ObjectState] | None = None
    cadastral_number_oks: str | None = None
    cadastral_number_land: str | None = None
    notes: str | None = None
    status: CaseStatus | None = None


class CaseOut(ORMModel):
    id: uuid.UUID
    address: str
    object_kind: ObjectKind
    states: list[str]
    cadastral_number_oks: str | None
    cadastral_number_land: str | None
    notes: str | None
    status: CaseStatus
    municipality: MunicipalityOut
    created_by: UserOut
    created_at: datetime
    updated_at: datetime


class CaseListOut(BaseModel):
    items: list[CaseOut]
    total: int


# --- проверки ---------------------------------------------------------------


class AssessmentAnswers(BaseModel):
    answers: dict[str, bool | str]


class QuestionOut(BaseModel):
    key: str
    label: str
    type: str
    source_hint: str
    options: list[dict]


class AssessmentOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID
    status: AssessmentStatus
    answers: dict
    decision: dict | None
    ruleset_version: str | None
    author: UserOut
    approved_by: UserOut | None
    approved_at: datetime | None
    content_hash: str | None
    signed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AssessmentProgressOut(BaseModel):
    """Состояние мастера опроса: что уже отвечено и какой вопрос следующий."""

    assessment: AssessmentOut
    answered: list[dict]
    next_question: QuestionOut | None
    remaining: int
    complete: bool


class PreviewRequest(BaseModel):
    object_kind: ObjectKind
    states: list[ObjectState]
    answers: dict[str, bool | str] = Field(default_factory=dict)


# --- дорожная карта ---------------------------------------------------------


class RoadmapBuildRequest(BaseModel):
    method_codes: list[str] = Field(min_length=1)


class RoadmapItemOut(ORMModel):
    id: uuid.UUID
    method_code: str
    order_index: int
    kind: str
    text: str
    status: RoadmapItemStatus
    due_date: date | None
    note: str | None
    completed_at: datetime | None
    assignee: UserOut | None


class RoadmapItemUpdate(BaseModel):
    status: RoadmapItemStatus | None = None
    assignee_id: uuid.UUID | None = None
    due_date: date | None = None
    note: str | None = None


class DocumentOut(ORMModel):
    """Метаданные сохранённого протокола. Содержимое отдаётся отдельной ссылкой."""

    id: uuid.UUID
    format: str
    filename: str
    content_sha256: str
    size_bytes: int
    generated_at: datetime
    generated_by: UserOut


# --- матрица правил ---------------------------------------------------------


class MethodOut(ORMModel):
    code: str
    family: str
    version: int
    title: str
    steps: list[dict]
    is_active: bool


class RuleOut(ORMModel):
    id: uuid.UUID
    code: str
    object_kind: ObjectKind
    state: ObjectState
    scenario_num: int
    conditions: dict
    method_codes: list[str]
    source: str | None
    is_active: bool
    is_builtin: bool


class RuleCreate(BaseModel):
    object_kind: ObjectKind
    state: ObjectState
    conditions: dict[str, bool | str]
    method_codes: list[str] = Field(min_length=1)
    source: str | None = None


class RuleUpdate(BaseModel):
    conditions: dict[str, bool | str] | None = None
    method_codes: list[str] | None = None
    source: str | None = None
    is_active: bool | None = None


class CoverageCell(BaseModel):
    object_kind: ObjectKind
    state: ObjectState
    described: int
    combinations: int
    gaps: int


# --- эскалации --------------------------------------------------------------


class EscalationCreate(BaseModel):
    case_id: uuid.UUID
    assessment_id: uuid.UUID | None = None
    comment: str | None = None


class EscalationResolve(BaseModel):
    status: EscalationStatus
    resolution: str


class EscalationOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID
    assessment_id: uuid.UUID | None
    inputs: dict
    comment: str | None
    status: EscalationStatus
    resolution: str | None
    created_by: UserOut
    resolved_by: UserOut | None
    resolved_at: datetime | None
    created_at: datetime


class AuditOut(ORMModel):
    id: uuid.UUID
    actor_login: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    payload: dict | None
    created_at: datetime
