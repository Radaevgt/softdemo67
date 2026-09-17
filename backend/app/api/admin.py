"""Админка: учётные записи, муниципалитеты, матрица правил, покрытие, журнал."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..deps import CurrentUser, Db, audit, require_roles
from ..engine import attributes
from ..enums import ObjectKind, ObjectState, Role
from ..models import AuditLog, Municipality, ScenarioRule, User
from ..schemas import (
    AuditOut,
    CoverageCell,
    MunicipalityCreate,
    MunicipalityOut,
    RuleCreate,
    RuleOut,
    RuleUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)
from ..security import hash_password
from ..services import coverage, load_methods, sync_seed

router = APIRouter(prefix="/api/admin", tags=["Администрирование"])

OperatorOnly = Annotated[User, Depends(require_roles(Role.OPERATOR))]
RuleEditor = Annotated[User, Depends(require_roles(Role.OPERATOR, Role.METHODOLOGIST))]


# --- муниципальные образования ---------------------------------------------


@router.get("/municipalities", response_model=list[MunicipalityOut])
def list_municipalities(db: Db, _: CurrentUser):
    return db.query(Municipality).order_by(Municipality.name).all()


@router.post("/municipalities", response_model=MunicipalityOut, status_code=201)
def create_municipality(payload: MunicipalityCreate, db: Db, user: OperatorOnly, request: Request):
    if db.query(Municipality).filter(Municipality.name == payload.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Муниципальное образование уже заведено")
    municipality = Municipality(name=payload.name, code=payload.code)
    db.add(municipality)
    db.flush()
    audit(db, user, "municipality.create", "municipality", municipality.id, request=request)
    db.commit()
    db.refresh(municipality)
    return municipality


# --- учётные записи ---------------------------------------------------------


@router.get("/users", response_model=list[UserOut])
def list_users(db: Db, _: OperatorOnly):
    return db.query(User).order_by(User.full_name).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(payload: UserCreate, db: Db, user: OperatorOnly, request: Request) -> User:
    if db.query(User).filter(User.login == payload.login).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Логин уже занят")
    if payload.role in (Role.SPECIALIST, Role.VIEWER) and payload.municipality_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Для специалиста и наблюдателя обязательно муниципальное образование",
        )

    created = User(
        login=payload.login,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        position=payload.position,
        role=payload.role,
        municipality_id=payload.municipality_id,
    )
    db.add(created)
    db.flush()
    audit(db, user, "user.create", "app_user", created.id, {"role": payload.role}, request)
    db.commit()
    db.refresh(created)
    return created


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID, payload: UserUpdate, db: Db, user: OperatorOnly, request: Request
) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Учётная запись не найдена")

    changes = payload.model_dump(exclude_unset=True)
    password = changes.pop("password", None)
    if password:
        target.password_hash = hash_password(password)
    for field, value in changes.items():
        setattr(target, field, value)

    if target.role in (Role.SPECIALIST, Role.VIEWER) and target.municipality_id is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Для специалиста и наблюдателя обязательно муниципальное образование",
        )
    if target.id == user.id and changes.get("is_active") is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нельзя заблокировать самого себя")

    audit(
        db, user, "user.update", "app_user", target.id,
        {"fields": list(changes) + (["password"] if password else [])}, request,
    )
    db.commit()
    db.refresh(target)
    return target


# --- матрица правил ---------------------------------------------------------


@router.get("/rules", response_model=list[RuleOut])
def list_rules(
    db: Db,
    _: RuleEditor,
    object_kind: ObjectKind | None = None,
    state: ObjectState | None = None,
):
    query = db.query(ScenarioRule)
    if object_kind:
        query = query.filter(ScenarioRule.object_kind == object_kind)
    if state:
        query = query.filter(ScenarioRule.state == state)
    return query.order_by(
        ScenarioRule.object_kind, ScenarioRule.state, ScenarioRule.scenario_num
    ).all()


def _validate_conditions(object_kind: str, conditions: dict) -> None:
    errors = attributes.validate_rule_conditions(object_kind, conditions)
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "; ".join(errors))


@router.post("/rules", response_model=RuleOut, status_code=201)
def create_rule(payload: RuleCreate, db: Db, user: RuleEditor, request: Request) -> ScenarioRule:
    """Добавление правила методологом — закрытие пробела матрицы ТЗ."""
    _validate_conditions(payload.object_kind, dict(payload.conditions))

    catalog = load_methods(db)
    unknown = [code for code in payload.method_codes if code not in catalog]
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Неизвестные способы: {', '.join(unknown)}"
        )

    # Отключённые правила тоже участвуют: их коды заняты, а условия могут быть
    # включены обратно, поэтому дубликат по ним — тоже конфликт.
    siblings = (
        db.query(ScenarioRule)
        .filter(
            ScenarioRule.object_kind == payload.object_kind,
            ScenarioRule.state == payload.state,
        )
        .all()
    )
    for rule in siblings:
        if rule.conditions == dict(payload.conditions):
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Такие условия уже описаны правилом {rule.code}"
            )

    prefix = f"{payload.object_kind}.{payload.state}.custom."
    taken = {rule.code for rule in siblings}
    next_num = max((rule.scenario_num for rule in siblings), default=0) + 1
    while f"{prefix}{next_num}" in taken:
        next_num += 1

    created = ScenarioRule(
        code=f"{prefix}{next_num}",
        object_kind=payload.object_kind,
        state=payload.state,
        scenario_num=next_num,
        conditions=dict(payload.conditions),
        method_codes=payload.method_codes,
        source=payload.source or f"Добавлено методологом: {user.full_name}",
        is_builtin=False,
        created_by_id=user.id,
    )
    db.add(created)
    db.flush()
    audit(db, user, "rule.create", "scenario_rule", created.id, {"code": created.code}, request)
    db.commit()
    db.refresh(created)
    return created


@router.patch("/rules/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: uuid.UUID, payload: RuleUpdate, db: Db, user: RuleEditor, request: Request
) -> ScenarioRule:
    rule = db.get(ScenarioRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Правило не найдено")

    changes = payload.model_dump(exclude_unset=True)
    if rule.is_builtin and set(changes) - {"is_active"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Правило выгружено из ТЗ: его можно отключить, но не переписать — "
            "добавьте собственное правило",
        )
    if "conditions" in changes and changes["conditions"] is not None:
        _validate_conditions(rule.object_kind, dict(changes["conditions"]))

    for field, value in changes.items():
        setattr(rule, field, value)
    audit(db, user, "rule.update", "scenario_rule", rule.id, {"fields": list(changes)}, request)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("/rules/coverage", response_model=list[CoverageCell])
def rules_coverage(db: Db, _: RuleEditor):
    """Сколько комбинаций признаков в каждой связке остаётся без правила."""
    return coverage(db)


@router.post("/rules/resync")
def resync_rules(db: Db, user: OperatorOnly, request: Request) -> dict:
    """Перезаливка матрицы из ТЗ. Правила методолога не затрагиваются."""
    result = sync_seed(db)
    audit(db, user, "rule.resync", "scenario_rule", None, result, request)
    db.commit()
    return result


# --- журнал -----------------------------------------------------------------


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    db: Db,
    _: OperatorOnly,
    action: str | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    return query.order_by(AuditLog.created_at.desc()).limit(limit).all()
