"""Проверка объекта: адаптивный опрос, расчёт способа, дорожная карта."""
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy.orm import joinedload

from ..deps import CurrentUser, Db, audit, ensure_can_read, ensure_can_write
from ..documents import MEDIA_TYPES
from ..engine import attributes
from ..enums import AssessmentStatus, CaseStatus, RoadmapItemStatus
from ..models import Assessment, AssessmentDocument, ObjectCase, RoadmapItem
from ..schemas import (
    AssessmentAnswers,
    AssessmentOut,
    AssessmentProgressOut,
    DocumentOut,
    PreviewRequest,
    QuestionOut,
    RoadmapBuildRequest,
    RoadmapItemOut,
    RoadmapItemUpdate,
)
from ..security import content_hash
from ..services import approve, build_roadmap, decide, store_documents

router = APIRouter(prefix="/api", tags=["Проверки"])


def _question(attr) -> QuestionOut:
    return QuestionOut(
        key=attr.key,
        label=attr.label,
        type=attr.type,
        source_hint=attr.source_hint,
        options=[{"value": option.value, "label": option.label} for option in attr.options],
    )


def _progress(case: ObjectCase, assessment: Assessment) -> AssessmentProgressOut:
    answers = assessment.answers or {}
    applicable = attributes.applicable_attributes(case.object_kind, answers)
    pending = [attr for attr in applicable if attr.key not in answers]
    return AssessmentProgressOut(
        assessment=AssessmentOut.model_validate(assessment),
        answered=attributes.describe(case.object_kind, answers),
        next_question=_question(pending[0]) if pending else None,
        remaining=len(pending),
        complete=not pending,
    )


def _load(db: Db, assessment_id: uuid.UUID) -> Assessment:
    assessment = db.get(
        Assessment,
        assessment_id,
        options=[joinedload(Assessment.case), joinedload(Assessment.author)],
    )
    if assessment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проверка не найдена")
    return assessment


def _editable(assessment: Assessment) -> Assessment:
    if assessment.status == AssessmentStatus.APPROVED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Проверка утверждена и не редактируется — создайте повторную проверку",
        )
    return assessment


@router.post("/cases/{case_id}/assessments", response_model=AssessmentOut, status_code=201)
def create_assessment(
    case_id: uuid.UUID, db: Db, user: CurrentUser, request: Request
) -> Assessment:
    case = db.get(ObjectCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дело не найдено")
    ensure_can_write(user, case)

    if not case.states:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "У объекта не указано состояние — без него сценарий не определяется",
        )

    # По делу одновременно ведётся не более одной неутверждённой проверки:
    # незавершённое заполнение продолжается, а не дублируется (ответ № 7 брифа).
    # Отбор именно по «не утверждена», а не по «черновик» — правка ответа
    # возвращает рассчитанную проверку в черновик, и двух одновременных
    # незавершённых проверок возникать не должно.
    unfinished = (
        db.query(Assessment)
        .filter(
            Assessment.case_id == case_id,
            Assessment.status != AssessmentStatus.APPROVED,
        )
        .order_by(Assessment.created_at.desc())
        .first()
    )
    if unfinished is not None:
        return unfinished

    assessment = Assessment(case_id=case_id, author_id=user.id, answers={})
    db.add(assessment)
    if case.status == CaseStatus.DRAFT:
        case.status = CaseStatus.IN_PROGRESS
    db.flush()
    audit(db, user, "assessment.create", "assessment", assessment.id, request=request)
    db.commit()
    db.refresh(assessment)
    return assessment


@router.get("/cases/{case_id}/assessments", response_model=list[AssessmentOut])
def list_assessments(case_id: uuid.UUID, db: Db, user: CurrentUser):
    case = db.get(ObjectCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дело не найдено")
    ensure_can_read(user, case)
    return (
        db.query(Assessment)
        .filter(Assessment.case_id == case_id)
        .order_by(Assessment.created_at.desc())
        .all()
    )


@router.get("/assessments/{assessment_id}", response_model=AssessmentProgressOut)
def get_assessment(assessment_id: uuid.UUID, db: Db, user: CurrentUser) -> AssessmentProgressOut:
    assessment = _load(db, assessment_id)
    ensure_can_read(user, assessment.case)
    return _progress(assessment.case, assessment)


@router.patch("/assessments/{assessment_id}/answers", response_model=AssessmentProgressOut)
def save_answers(
    assessment_id: uuid.UUID, payload: AssessmentAnswers, db: Db, user: CurrentUser
) -> AssessmentProgressOut:
    """Автосохранение мастера: ответы можно слать по одному.

    Ответы, переставшие быть применимыми после правки (например, наследники
    после смены статуса правообладателя на «жив»), удаляются автоматически.
    """
    assessment = _editable(_load(db, assessment_id))
    ensure_can_write(user, assessment.case)

    merged = {**(assessment.answers or {}), **payload.answers}
    unknown = [key for key in payload.answers if key not in attributes.ATTRIBUTES_BY_KEY]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Неизвестные признаки: {', '.join(unknown)}"
        )
    for key, value in payload.answers.items():
        if not attributes.ATTRIBUTES_BY_KEY[key].accepts(value):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Недопустимое значение признака «{key}»: {value!r}",
            )

    assessment.answers = attributes.prune(assessment.case.object_kind, merged)
    # Ответы изменились — ранее рассчитанное решение больше не действительно.
    # Статус тоже откатывается, иначе проверку можно было бы утвердить без решения.
    assessment.decision = None
    assessment.ruleset_version = None
    assessment.status = AssessmentStatus.DRAFT
    db.commit()
    db.refresh(assessment)
    return _progress(assessment.case, assessment)


@router.post("/assessments/{assessment_id}/decide", response_model=AssessmentOut)
def run_decision(
    assessment_id: uuid.UUID, db: Db, user: CurrentUser, request: Request
) -> Assessment:
    assessment = _editable(_load(db, assessment_id))
    ensure_can_write(user, assessment.case)
    case = assessment.case

    if not case.states:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "У объекта не указано состояние — без него сценарий не определяется",
        )

    errors = attributes.validate(case.object_kind, assessment.answers or {})
    if errors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "; ".join(errors))

    decision = decide(db, case.object_kind, case.states, assessment.answers)
    assessment.decision = decision.to_dict()
    assessment.ruleset_version = decision.ruleset_version
    assessment.status = AssessmentStatus.COMPLETED
    audit(
        db,
        user,
        "assessment.decide",
        "assessment",
        assessment.id,
        {"needs_review": decision.needs_review, "ruleset_version": decision.ruleset_version},
        request,
    )
    db.commit()
    db.refresh(assessment)
    return assessment


@router.post("/decisions/preview")
def preview(payload: PreviewRequest, db: Db, user: CurrentUser) -> dict:
    """Расчёт без сохранения — для проверки гипотез и отладки матрицы."""
    cleaned = attributes.prune(payload.object_kind, dict(payload.answers))
    errors = attributes.validate(payload.object_kind, cleaned)
    if errors:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "; ".join(errors))
    return decide(db, payload.object_kind, [s.value for s in payload.states], cleaned).to_dict()


@router.post("/assessments/{assessment_id}/approve", response_model=AssessmentOut)
def approve_assessment(
    assessment_id: uuid.UUID, db: Db, user: CurrentUser, request: Request
) -> Assessment:
    """Утверждение решения: фиксирует автора, время и отпечаток содержимого."""
    assessment = _load(db, assessment_id)
    ensure_can_write(user, assessment.case)

    decision = assessment.decision or {}
    if assessment.status != AssessmentStatus.COMPLETED or not decision.get("outcomes"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Сначала выполните расчёт решения")
    if decision.get("needs_review"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Точный сценарий не определён — решение утверждается только после "
            "рассмотрения методологом",
        )

    approve(assessment, user, content_hash)
    assessment.case.status = CaseStatus.DECIDED
    # Утверждение фиксирует и сам документ: дальше он уже не пересобирается.
    store_documents(db, assessment, user)
    audit(
        db,
        user,
        "assessment.approve",
        "assessment",
        assessment.id,
        {"content_hash": assessment.content_hash},
        request,
    )
    db.commit()
    db.refresh(assessment)
    return assessment


@router.post("/assessments/{assessment_id}/roadmap", response_model=list[RoadmapItemOut])
def create_roadmap(
    assessment_id: uuid.UUID,
    payload: RoadmapBuildRequest,
    db: Db,
    user: CurrentUser,
    request: Request,
):
    """Разворачивает порядок действий выбранных способов в чек-лист."""
    assessment = _load(db, assessment_id)
    ensure_can_write(user, assessment.case)
    if not assessment.decision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Решение ещё не рассчитано")

    offered = {
        method["code"]
        for outcome in assessment.decision["outcomes"]
        for method in outcome["methods"]
    }
    extra = set(payload.method_codes) - offered
    if extra:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Способы не относятся к рассчитанному решению: {', '.join(sorted(extra))}",
        )

    try:
        items = build_roadmap(db, assessment, payload.method_codes)
    except ValueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from error

    audit(
        db, user, "roadmap.build", "assessment", assessment.id, {"methods": payload.method_codes},
        request,
    )
    db.commit()
    for item in items:
        db.refresh(item)
    return items


@router.get("/assessments/{assessment_id}/roadmap", response_model=list[RoadmapItemOut])
def get_roadmap(assessment_id: uuid.UUID, db: Db, user: CurrentUser):
    assessment = _load(db, assessment_id)
    ensure_can_read(user, assessment.case)
    return assessment.roadmap_items


@router.patch("/roadmap-items/{item_id}", response_model=RoadmapItemOut)
def update_roadmap_item(
    item_id: uuid.UUID, payload: RoadmapItemUpdate, db: Db, user: CurrentUser
) -> RoadmapItem:
    item = db.get(RoadmapItem, item_id, options=[joinedload(RoadmapItem.assessment)])
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаг не найден")
    ensure_can_write(user, item.assessment.case)

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(item, field, value)
    if "status" in changes:
        # Снятая отметка снимает и дату, иначе шаг остаётся «выполнен» на вид.
        done = changes["status"] == RoadmapItemStatus.DONE
        item.completed_at = datetime.now(timezone.utc) if done else None
    db.commit()
    db.refresh(item)
    return item


# --- протокол проверки ------------------------------------------------------


def _document_or_404(assessment: Assessment, document_format: str) -> AssessmentDocument:
    for document in assessment.documents:
        if document.format == document_format:
            return document
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, "Протокол в этом формате не сформирован"
    )


@router.post("/assessments/{assessment_id}/documents", response_model=list[DocumentOut])
def generate_documents(
    assessment_id: uuid.UUID, db: Db, user: CurrentUser, request: Request
):
    """Формирует протокол проверки и сохраняет его в системе.

    Содержание берётся из снимка решения, поэтому протокол воспроизводим; хранится
    именно сформированный файл — он вкладывается в СЭДО и уходит в архив.
    """
    assessment = _load(db, assessment_id)
    ensure_can_write(user, assessment.case)

    if not assessment.decision:
        raise HTTPException(status.HTTP_409_CONFLICT, "Решение ещё не рассчитано")
    if assessment.status == AssessmentStatus.APPROVED and assessment.documents:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Протокол утверждённой проверки неизменяем — он сформирован при утверждении",
        )

    stored = store_documents(db, assessment, user)
    audit(
        db, user, "document.generate", "assessment", assessment.id,
        {"formats": [document.format for document in stored]}, request,
    )
    db.commit()
    for document in stored:
        db.refresh(document)
    return stored


@router.get("/assessments/{assessment_id}/documents", response_model=list[DocumentOut])
def list_documents(assessment_id: uuid.UUID, db: Db, user: CurrentUser):
    assessment = _load(db, assessment_id)
    ensure_can_read(user, assessment.case)
    return sorted(assessment.documents, key=lambda document: document.format)


@router.get("/assessments/{assessment_id}/documents/{document_format}")
def download_document(
    assessment_id: uuid.UUID, document_format: str, db: Db, user: CurrentUser
) -> Response:
    assessment = _load(db, assessment_id)
    ensure_can_read(user, assessment.case)
    document = _document_or_404(assessment, document_format)

    # Имя файла кириллическое: ASCII-вариант для старых клиентов, UTF-8 — для всех
    # остальных (RFC 6266).
    quoted = quote(document.filename)
    disposition = f"attachment; filename=\"protocol.{document.format}\"; filename*=UTF-8''{quoted}"

    return Response(
        content=document.content,
        media_type=MEDIA_TYPES.get(document.format, "application/octet-stream"),
        headers={
            "Content-Disposition": disposition,
            "X-Content-SHA256": document.content_sha256,
        },
    )
