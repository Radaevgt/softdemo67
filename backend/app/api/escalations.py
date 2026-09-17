"""Эскалация методологу, когда точного сценария в матрице нет."""
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..deps import (
    CROSS_MUNICIPALITY_ROLES,
    CurrentUser,
    Db,
    audit,
    can_write_case,
    ensure_can_read,
    require_roles,
)
from ..enums import EscalationStatus, Role
from ..models import Assessment, Escalation, ObjectCase, User
from ..schemas import EscalationCreate, EscalationOut, EscalationResolve

router = APIRouter(prefix="/api/escalations", tags=["Эскалации"])

Methodologist = Annotated[User, Depends(require_roles(Role.OPERATOR, Role.METHODOLOGIST))]


@router.post("", response_model=EscalationOut, status_code=201)
def create_escalation(
    payload: EscalationCreate, db: Db, user: CurrentUser, request: Request
) -> Escalation:
    case = db.get(ObjectCase, payload.case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дело не найдено")
    ensure_can_read(user, case)
    if not can_write_case(user, case):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Недостаточно прав для создания обращения"
        )

    inputs = {"object_kind": case.object_kind, "states": case.states, "answers": {}}
    if payload.assessment_id:
        assessment = db.get(Assessment, payload.assessment_id)
        if assessment is None or assessment.case_id != case.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Проверка не найдена")
        inputs["answers"] = assessment.answers
        inputs["decision"] = assessment.decision

    escalation = Escalation(
        case_id=case.id,
        assessment_id=payload.assessment_id,
        created_by_id=user.id,
        inputs=inputs,
        comment=payload.comment,
    )
    db.add(escalation)
    db.flush()
    audit(db, user, "escalation.create", "escalation", escalation.id, request=request)
    db.commit()
    db.refresh(escalation)
    return escalation


@router.get("", response_model=list[EscalationOut])
def list_escalations(
    db: Db,
    user: CurrentUser,
    escalation_status: EscalationStatus | None = None,
):
    query = db.query(Escalation)
    if user.role not in CROSS_MUNICIPALITY_ROLES:
        # Специалист видит только собственные обращения.
        query = query.filter(Escalation.created_by_id == user.id)
    if escalation_status:
        query = query.filter(Escalation.status == escalation_status)
    return query.order_by(Escalation.created_at.desc()).all()


@router.post("/{escalation_id}/resolve", response_model=EscalationOut)
def resolve_escalation(
    escalation_id: uuid.UUID,
    payload: EscalationResolve,
    db: Db,
    user: Methodologist,
    request: Request,
) -> Escalation:
    escalation = db.get(Escalation, escalation_id)
    if escalation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Обращение не найдено")
    if escalation.status != EscalationStatus.OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, "Обращение уже рассмотрено")
    if payload.status == EscalationStatus.OPEN:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Укажите итог рассмотрения")

    escalation.status = payload.status
    escalation.resolution = payload.resolution
    escalation.resolved_by_id = user.id
    escalation.resolved_at = datetime.now(timezone.utc)
    audit(
        db, user, "escalation.resolve", "escalation", escalation.id,
        {"status": payload.status}, request,
    )
    db.commit()
    db.refresh(escalation)
    return escalation
