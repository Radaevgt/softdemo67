"""Справочники: словари домена, состав опроса, каталог способов."""
from fastapi import APIRouter, HTTPException, status

from ..deps import CurrentUser, Db
from ..engine.attributes import ATTRIBUTES
from ..enums import LABELS, ObjectKind, ObjectState, OwnerStatus, Role
from ..models import Method as MethodModel
from ..schemas import MethodOut
from ..services import load_methods

router = APIRouter(prefix="/api/catalog", tags=["Справочники"])


def _options(enum_cls, label_key: str) -> list[dict]:
    return [
        {"value": member.value, "label": LABELS[label_key].get(member, member.value)}
        for member in enum_cls
    ]


@router.get("/dictionaries")
def dictionaries(_: CurrentUser) -> dict:
    return {
        "object_kinds": _options(ObjectKind, "object_kind"),
        "states": _options(ObjectState, "state"),
        "roles": _options(Role, "role"),
        # Подписи всех значений, встречающихся в правилах, а не только доступных
        # для ответа: в матрице ТЗ есть объединённый статус «умер/ликвидировано».
        "rule_value_labels": {
            "owner_status": {
                status.value: LABELS["owner_status"][status] for status in OwnerStatus
            }
        },
        "attributes": [
            {
                "key": attr.key,
                "label": attr.label,
                "type": attr.type,
                "source_hint": attr.source_hint,
                "options": [
                    {"value": option.value, "label": option.label} for option in attr.options
                ],
            }
            for attr in ATTRIBUTES
        ],
    }


@router.get("/methods", response_model=list[MethodOut])
def methods(db: Db, _: CurrentUser):
    return db.query(MethodModel).order_by(MethodModel.family, MethodModel.version).all()


@router.get("/methods/{code}")
def method(code: str, db: Db, _: CurrentUser) -> dict:
    found = load_methods(db).get(code)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Способ не найден")
    return {"code": found.code, "title": found.title, "steps": found.steps}
