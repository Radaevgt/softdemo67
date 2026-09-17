"""Реестр дел по объектам."""
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from ..deps import (
    CROSS_MUNICIPALITY_ROLES,
    CurrentUser,
    Db,
    audit,
    ensure_can_read,
    ensure_can_write,
)
from ..enums import CaseStatus, ObjectKind, ObjectState, Role
from ..models import ObjectCase
from ..schemas import CaseCreate, CaseListOut, CaseOut, CaseUpdate

router = APIRouter(prefix="/api/cases", tags=["Дела"])

WRITE_ROLES = {Role.SPECIALIST, Role.OPERATOR}


def _visible(db: Db, user):
    query = select(ObjectCase).options(
        joinedload(ObjectCase.municipality),
        joinedload(ObjectCase.created_by),
    )
    if user.role not in CROSS_MUNICIPALITY_ROLES:
        query = query.where(ObjectCase.municipality_id == user.municipality_id)
    return query


@router.get("", response_model=CaseListOut)
def list_cases(
    db: Db,
    user: CurrentUser,
    search: str | None = None,
    object_kind: ObjectKind | None = None,
    state: ObjectState | None = None,
    case_status: CaseStatus | None = None,
    municipality_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> CaseListOut:
    query = _visible(db, user)

    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                ObjectCase.address.ilike(pattern),
                ObjectCase.cadastral_number_oks.ilike(pattern),
                ObjectCase.cadastral_number_land.ilike(pattern),
            )
        )
    if object_kind:
        query = query.where(ObjectCase.object_kind == object_kind)
    if case_status:
        query = query.where(ObjectCase.status == case_status)
    if municipality_id and user.role in CROSS_MUNICIPALITY_ROLES:
        query = query.where(ObjectCase.municipality_id == municipality_id)

    query = query.order_by(ObjectCase.updated_at.desc())

    if state:
        # states хранится как JSON-массив; фильтрация по элементу переносима между
        # PostgreSQL и SQLite только на стороне приложения, поэтому страница
        # нарезается уже после отбора.
        rows = db.execute(query).unique().scalars().all()
        rows = [row for row in rows if state in row.states]
        return CaseListOut(items=rows[offset : offset + limit], total=len(rows))

    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    page = db.execute(query.limit(limit).offset(offset)).unique().scalars().all()
    return CaseListOut(items=page, total=total)


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(payload: CaseCreate, db: Db, user: CurrentUser, request: Request) -> ObjectCase:
    if user.role not in WRITE_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для создания дела")

    municipality_id = payload.municipality_id or user.municipality_id
    if municipality_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не указано муниципальное образование")
    if user.role == Role.SPECIALIST and municipality_id != user.municipality_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Дело можно завести только по своему МО")

    case = ObjectCase(
        municipality_id=municipality_id,
        created_by_id=user.id,
        address=payload.address,
        object_kind=payload.object_kind,
        states=[s.value for s in payload.states],
        cadastral_number_oks=payload.cadastral_number_oks,
        cadastral_number_land=payload.cadastral_number_land,
        notes=payload.notes,
        status=CaseStatus.DRAFT,
    )
    db.add(case)
    db.flush()
    audit(db, user, "case.create", "object_case", case.id, request=request)
    db.commit()
    db.refresh(case)
    return case


def _get_case(db: Db, case_id: uuid.UUID) -> ObjectCase:
    case = db.get(ObjectCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дело не найдено")
    return case


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: uuid.UUID, db: Db, user: CurrentUser) -> ObjectCase:
    return ensure_can_read(user, _get_case(db, case_id))


@router.patch("/{case_id}", response_model=CaseOut)
def update_case(
    case_id: uuid.UUID, payload: CaseUpdate, db: Db, user: CurrentUser, request: Request
) -> ObjectCase:
    case = ensure_can_write(user, _get_case(db, case_id))

    changes = payload.model_dump(exclude_unset=True)
    if "states" in changes and changes["states"] is not None:
        changes["states"] = [s.value if hasattr(s, "value") else s for s in changes["states"]]
    for field, value in changes.items():
        setattr(case, field, value)

    audit(db, user, "case.update", "object_case", case.id, {"fields": list(changes)}, request)
    db.commit()
    db.refresh(case)
    return case


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_case(case_id: uuid.UUID, db: Db, user: CurrentUser, request: Request) -> None:
    case = ensure_can_write(user, _get_case(db, case_id))
    if case.status != CaseStatus.DRAFT and user.role != Role.OPERATOR:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Удалить можно только черновик; дело в работе — архивируйте"
        )
    audit(db, user, "case.delete", "object_case", case.id, {"address": case.address}, request)
    db.delete(case)
    db.commit()
