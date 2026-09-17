"""Сборка протокола проверки из сохранённого снимка решения.

Источник — только ``assessment.answers`` и ``assessment.decision``: оба записаны
в момент расчёта и не меняются, поэтому протокол, сформированный сегодня и через
год, совпадёт дословно.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..enums import LABELS, ObjectKind, ObjectState
from ..models import Assessment
from .layout import Document, Paragraph, Section, Step, Steps, Table

TITLE = "ПРОТОКОЛ ОПРЕДЕЛЕНИЯ СПОСОБА РАБОТЫ С НЕИСПОЛЬЗУЕМЫМ ОБЪЕКТОМ"
DASH = "—"


def _moment(value: datetime | None) -> str:
    if value is None:
        return DASH
    local = value.astimezone(timezone.utc) if value.tzinfo else value
    return local.strftime("%d.%m.%Y %H:%M")


def _day(value: datetime | None) -> str:
    return DASH if value is None else value.strftime("%d.%m.%Y")


def _person(user) -> str:
    if user is None:
        return DASH
    return f"{user.full_name}, {user.position}" if user.position else user.full_name


def _states(case) -> str:
    if not case.states:
        return "не указано"
    return ", ".join(LABELS["state"].get(ObjectState(s), s) for s in case.states)


def _object_section(case) -> Section:
    return Section(
        "1. Сведения об объекте",
        [
            Table(
                widths=[0.36, 0.64],
                rows=[
                    ["Муниципальное образование", case.municipality.name],
                    ["Адрес объекта", case.address],
                    ["Вид объекта", LABELS["object_kind"].get(ObjectKind(case.object_kind), case.object_kind)],
                    ["Кадастровый номер ОКС", case.cadastral_number_oks or DASH],
                    ["Кадастровый номер земельного участка", case.cadastral_number_land or DASH],
                    ["Состояние объекта", _states(case)],
                    ["Примечание", case.notes or DASH],
                ],
            )
        ],
    )


def _answers_section(decision: dict) -> Section:
    breakdown = decision.get("answer_breakdown") or []
    if not breakdown:
        return Section("2. Установленные признаки", [Paragraph("Признаки не заполнены.")])

    return Section(
        "2. Установленные признаки",
        [
            Paragraph(
                "Признаки установлены по ответам уполномоченных органов, полученным на "
                "этапе сбора и анализа информации об объекте.",
                emphasis="note",
            ),
            Table(
                header=["Признак", "Значение", "Источник сведений"],
                widths=[0.34, 0.16, 0.50],
                rows=[
                    [item["label"], item["value_label"], item["source_hint"]]
                    for item in breakdown
                ],
            ),
        ],
    )


def _outcome_blocks(outcome: dict) -> list:
    blocks: list = []
    state = outcome.get("state_label") or outcome.get("state")

    if outcome.get("exact"):
        blocks.append(
            Table(
                widths=[0.36, 0.64],
                rows=[
                    ["Состояние объекта", state],
                    ["Сценарий", f"№ {outcome.get('scenario_num')}"],
                    ["Основание", outcome.get("source") or DASH],
                    [
                        "Способ",
                        "; ".join(method["title"] for method in outcome.get("methods", [])) or DASH,
                    ],
                ],
            )
        )
        if outcome.get("conflicting_rules"):
            blocks.append(
                Paragraph(
                    "Условиям отвечает несколько правил: "
                    + ", ".join(outcome["conflicting_rules"])
                    + ". Применено наиболее специфичное.",
                    emphasis="warning",
                )
            )
        return blocks

    blocks.append(
        Paragraph(
            f"Состояние «{state}»: точный сценарий в матрице не определён. "
            "Ниже приведены ближайшие описанные сценарии с указанием расхождений. "
            "Решение подлежит рассмотрению методологом.",
            emphasis="warning",
        )
    )
    for near in outcome.get("nearest", []):
        rows = [
            [
                difference["label"],
                difference["expected_label"],
                difference["actual_label"],
            ]
            for difference in near.get("differences", [])
        ]
        blocks.append(Paragraph(f"Сценарий № {near['scenario_num']}", emphasis="lead"))
        blocks.append(
            Table(
                header=["Признак", "В сценарии", "По объекту"],
                widths=[0.40, 0.30, 0.30],
                rows=rows,
            )
        )
        titles = "; ".join(method["title"] for method in near.get("methods", []))
        blocks.append(Paragraph(f"Способы по этому сценарию: {titles or DASH}"))
    return blocks


def _result_section(decision: dict) -> Section:
    outcomes = decision.get("outcomes") or []
    if not outcomes:
        return Section(
            "3. Результат определения",
            [Paragraph("Результат не определён: не указано состояние объекта.", emphasis="warning")],
        )

    blocks: list = []
    if len(outcomes) > 1:
        blocks.append(
            Paragraph(
                "Объект обладает несколькими признаками состояния. Способы приведены по "
                "каждому из них в порядке приоритета: угроза жизни и здоровью граждан "
                "опережает оформление права.",
                emphasis="note",
            )
        )
    for outcome in outcomes:
        blocks.extend(_outcome_blocks(outcome))
    return Section("3. Результат определения", blocks)


def _procedure_section(decision: dict) -> Section:
    blocks: list = []
    seen: set[str] = set()

    for outcome in decision.get("outcomes") or []:
        for method in outcome.get("methods", []):
            if method["code"] in seen:
                continue
            seen.add(method["code"])
            blocks.append(Paragraph(method["title"], emphasis="lead"))
            blocks.append(
                Steps([Step(step["text"], step.get("kind", "action")) for step in method["steps"]])
            )

    if not blocks:
        blocks.append(
            Paragraph(
                "Порядок действий не приводится: сценарий не определён.", emphasis="warning"
            )
        )
    return Section("4. Порядок действий", blocks)


def _provenance_section(assessment: Assessment, decision: dict) -> Section:
    rows = [
        ["Проверку выполнил", _person(assessment.author)],
        ["Дата начала проверки", _moment(assessment.created_at)],
        ["Дата расчёта решения", _moment(assessment.updated_at)],
        ["Решение утвердил", _person(assessment.approved_by)],
        ["Дата утверждения", _moment(assessment.approved_at)],
        ["Версия набора правил", decision.get("ruleset_version") or DASH],
        ["Отпечаток решения (SHA-256)", assessment.content_hash or "решение не утверждено"],
    ]
    blocks: list = [Table(widths=[0.36, 0.64], rows=rows)]

    if assessment.signed_at is None:
        blocks.append(
            Paragraph(
                "Усиленная квалифицированная электронная подпись не применялась. "
                "Авторство и целостность подтверждаются отпечатком решения и записями "
                "журнала действий системы.",
                emphasis="note",
            )
        )
    return Section("5. Сведения о проведении проверки", blocks)


def build(assessment: Assessment) -> Document:
    """Собирает протокол. Требует рассчитанного решения."""
    decision = assessment.decision
    if not decision:
        raise ValueError("Решение не рассчитано — протокол формировать не из чего")

    case = assessment.case
    number = str(assessment.id).split("-")[0].upper()
    document = Document(
        title=TITLE,
        subtitle=f"№ {number} от {_day(assessment.created_at)} · {case.municipality.name}",
        sections=[
            _object_section(case),
            _answers_section(decision),
            _result_section(decision),
            _procedure_section(decision),
            _provenance_section(assessment, decision),
        ],
        signature_lines=[
            f"Проверку выполнил: __________________ / {_person(assessment.author)}",
        ],
    )

    if decision.get("needs_review"):
        document.sections.insert(
            0,
            Section(
                "",
                [
                    Paragraph(
                        "Внимание: точный сценарий определён не по всем состояниям объекта. "
                        "Протокол носит предварительный характер и не является основанием "
                        "для принятия решения до рассмотрения методологом.",
                        emphasis="warning",
                    )
                ],
            ),
        )
    else:
        document.signature_lines.append(
            f"Решение утвердил: __________________ / {_person(assessment.approved_by)}"
        )

    return document
