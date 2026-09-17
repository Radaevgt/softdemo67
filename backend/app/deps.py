"""Аутентификация, роли и разграничение доступа по муниципальным образованиям."""
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from .db import get_db
from .enums import Role
from .models import AuditLog, ObjectCase, User
from .security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

# Методолог и оператор работают со всеми МО; специалист и наблюдатель — только со своим.
CROSS_MUNICIPALITY_ROLES = {Role.OPERATOR, Role.METHODOLOGIST}


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")

    user = db.query(User).filter(User.login == payload["sub"]).one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Учётная запись недоступна")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
Db = Annotated[Session, Depends(get_db)]


def require_roles(*roles: Role):
    allowed = set(roles)

    def guard(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return guard


def can_read_case(user: User, case: ObjectCase) -> bool:
    if user.role in CROSS_MUNICIPALITY_ROLES:
        return True
    return user.municipality_id == case.municipality_id


def can_write_case(user: User, case: ObjectCase) -> bool:
    """Наблюдатель не редактирует; методолог правит матрицу, а не чужие дела."""
    if user.role == Role.OPERATOR:
        return True
    if user.role == Role.SPECIALIST:
        return user.municipality_id == case.municipality_id
    return False


def ensure_can_read(user: User, case: ObjectCase) -> ObjectCase:
    if not can_read_case(user, case):
        # Скрываем сам факт существования дела чужого МО.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Дело не найдено")
    return case


def ensure_can_write(user: User, case: ObjectCase) -> ObjectCase:
    ensure_can_read(user, case)
    if not can_write_case(user, case):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для изменения дела")
    return case


def audit(
    db: Session,
    user: User | None,
    action: str,
    entity_type: str | None = None,
    entity_id: object = None,
    payload: dict | None = None,
    request: Request | None = None,
) -> None:
    """Пишет действие в журнал. Коммит остаётся за вызывающей стороной."""
    if request is not None:
        payload = {**(payload or {}), "ip": request.client.host if request.client else None}
    db.add(
        AuditLog(
            actor_id=user.id if user else None,
            actor_login=user.login if user else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            payload=payload,
        )
    )
