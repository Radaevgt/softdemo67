"""Прикладная логика поверх ORM: матрица правил, расчёт решения, дорожная карта."""
from __future__ import annotations

import hashlib
import itertools
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .engine import attributes
from .engine.matcher import Decision, Method, Rule, evaluate, has_exact_match
from .enums import (
    INPUT_OWNER_STATUSES,
    AssessmentStatus,
    ObjectKind,
    ObjectState,
    OwnerStatus,
)
from . import documents
from .models import (
    Assessment,
    AssessmentDocument,
    Method as MethodModel,
    RoadmapItem,
    ScenarioRule,
)
from .seed.loader import load_seed, seed_rules


def load_rules(db: Session) -> list[Rule]:
    rows = db.query(ScenarioRule).filter(ScenarioRule.is_active.is_(True)).all()
    return [
        Rule(
            code=row.code,
            object_kind=row.object_kind,
            state=row.state,
            scenario_num=row.scenario_num,
            conditions=row.conditions,
            method_codes=row.method_codes,
            source=row.source,
        )
        for row in rows
    ]


def load_methods(db: Session) -> dict[str, Method]:
    rows = db.query(MethodModel).filter(MethodModel.is_active.is_(True)).all()
    return {row.code: Method(code=row.code, title=row.title, steps=row.steps) for row in rows}


def decide(db: Session, object_kind: str, states: list[str], answers: dict) -> Decision:
    cleaned = attributes.prune(object_kind, answers)
    return evaluate(object_kind, states, cleaned, load_rules(db), load_methods(db))


def sync_seed(db: Session) -> dict:
    """Заливает матрицу из ТЗ, не затирая правила, добавленные методологом.

    Встроенные правила обновляются по коду, добавленные вручную не трогаются.
    """
    created = updated = 0

    for item in load_seed()["methods"]:
        row = db.get(MethodModel, item["code"])
        if row is None:
            db.add(
                MethodModel(
                    code=item["code"],
                    family=item["family"],
                    version=item["version"],
                    title=item["title"],
                    steps=item["steps"],
                )
            )
            created += 1
        else:
            row.title, row.steps = item["title"], item["steps"]

    for rule in seed_rules():
        row = db.query(ScenarioRule).filter(ScenarioRule.code == rule.code).one_or_none()
        if row is None:
            db.add(
                ScenarioRule(
                    code=rule.code,
                    object_kind=rule.object_kind,
                    state=rule.state,
                    scenario_num=rule.scenario_num,
                    conditions=rule.conditions,
                    method_codes=rule.method_codes,
                    source=rule.source,
                    is_builtin=True,
                )
            )
            created += 1
        elif row.is_builtin:
            row.conditions = rule.conditions
            row.method_codes = rule.method_codes
            row.source = rule.source
            updated += 1

    db.commit()
    return {"created": created, "updated": updated}


def combination_space(object_kind: str, state: str) -> list[dict]:
    """Все правдоподобные комбинации признаков для связки «вид × состояние».

    Используется в админке, чтобы показать методологу, какие ячейки матрицы
    не описаны в ТЗ, и дать добавить недостающее правило.
    """
    combos: list[dict] = []
    for rights_obj, rights_land, owner_status, taxpayer in itertools.product(
        (True, False), (True, False), INPUT_OWNER_STATUSES, (True, False)
    ):
        base = {
            "rights_obj": rights_obj,
            "rights_land": rights_land,
            "owner_status": owner_status,
            "taxpayer": taxpayer,
        }
        registered_values = (
            (True, False) if object_kind != ObjectKind.NONRESIDENTIAL else (None,)
        )
        heirs_values = (True, False) if owner_status != OwnerStatus.ALIVE else (None,)
        for registered in registered_values:
            for heirs in heirs_values:
                combo = dict(base)
                if registered is not None:
                    combo["registered_citizens"] = registered
                if heirs is not None:
                    combo["heirs"] = heirs
                combos.append(combo)
    return combos


def coverage(db: Session) -> list[dict]:
    rules = load_rules(db)
    report: list[dict] = []
    for object_kind in ObjectKind:
        for state in ObjectState:
            described = [r for r in rules if r.object_kind == object_kind and r.state == state]
            # Связка без единого правила не пропускается: именно она — самый
            # крупный пробел матрицы, и методолог должен её видеть.
            space = combination_space(object_kind, state)
            covered = sum(
                1 for combo in space if has_exact_match(object_kind, state, combo, described)
            )
            report.append(
                {
                    "object_kind": object_kind,
                    "state": state,
                    "described": len(described),
                    "combinations": len(space),
                    "gaps": len(space) - covered,
                }
            )
    return report


def build_roadmap(db: Session, assessment: Assessment, method_codes: list[str]) -> list[RoadmapItem]:
    """Разворачивает порядок действий выбранных способов в чек-лист поручений."""
    catalog = load_methods(db)
    unknown = [code for code in method_codes if code not in catalog]
    if unknown:
        raise ValueError(f"неизвестные способы: {', '.join(unknown)}")

    for item in list(assessment.roadmap_items):
        db.delete(item)
    assessment.roadmap_items.clear()

    items: list[RoadmapItem] = []
    order = 0
    for code in method_codes:
        for step in catalog[code].steps:
            items.append(
                RoadmapItem(
                    assessment=assessment,
                    method_code=code,
                    order_index=order,
                    kind=step.get("kind", "action"),
                    text=step["text"],
                )
            )
            order += 1
    db.add_all(items)
    return items


def store_documents(db: Session, assessment: Assessment, user) -> list[AssessmentDocument]:
    """Формирует протокол во всех доступных форматах и сохраняет его.

    Повторное формирование заменяет прежний файл: пока проверка не утверждена,
    актуален последний расчёт. После утверждения вызывающая сторона обязана
    запретить перегенерацию — утверждённый протокол неизменяем.
    """
    existing = {document.format: document for document in assessment.documents}
    stored: list[AssessmentDocument] = []

    for document_format in documents.available_formats():
        rendered = documents.render(assessment, document_format)
        digest = hashlib.sha256(rendered.content).hexdigest()

        document = existing.get(document_format)
        if document is None:
            document = AssessmentDocument(assessment=assessment, format=document_format)
            db.add(document)

        document.filename = rendered.filename
        document.content = rendered.content
        document.content_sha256 = digest
        document.size_bytes = len(rendered.content)
        document.generated_by_id = user.id
        document.generated_at = datetime.now(timezone.utc)
        stored.append(document)

    return stored


def approve(assessment: Assessment, user, hasher) -> None:
    """Фиксирует авторство решения. Поля УКЭП остаются пустыми до её подключения."""
    assessment.status = AssessmentStatus.APPROVED
    assessment.approved_by_id = user.id
    assessment.approved_at = datetime.now(timezone.utc)
    assessment.content_hash = hasher(
        {
            "case_id": str(assessment.case_id),
            "answers": assessment.answers,
            "decision": assessment.decision,
            "ruleset_version": assessment.ruleset_version,
            "approved_by": user.login,
        }
    )
