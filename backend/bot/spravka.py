"""Справка: сжатая выжимка в чат и полный документ файлом.

Оба вывода строятся из одного снимка решения, поэтому разойтись не могут.
В чат уходит именно выжимка: сообщение в MAX ограничено 4000 символами, а
порядок действий по одному способу бывает до 25 шагов.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app import documents
from app.documents.source import (
    PlainAssessment,
    PlainCase,
    PlainMunicipality,
    PlainPerson,
)
from . import texts
from .session import Session

TITLE = "СПРАВКА О СПОСОБЕ РАБОТЫ С НЕИСПОЛЬЗУЕМЫМ ОБЪЕКТОМ"
FILENAME_PREFIX = "Справка"
DASH = "—"


def plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение числительных: 1 шаг, 2 шага, 5 шагов."""
    tail_two, tail_one = count % 100, count % 10
    if 11 <= tail_two <= 14:
        return many
    if tail_one == 1:
        return one
    if 2 <= tail_one <= 4:
        return few
    return many


# Сколько шагов порядка действий показывать в чате: остальное уходит в файл.
STEPS_IN_CHAT = 4
CHAT_LIMIT = 3500


def build_assessment(session: Session, decision: dict) -> PlainAssessment:
    """Собирает снимок проверки для построителя документов.

    Полей ровно столько, сколько читает ``documents.builder.build``; ORM здесь
    не участвует — ради этого генератор и расцеплен с моделями.
    """
    now = datetime.now(timezone.utc)
    return PlainAssessment(
        id=uuid.uuid4(),
        case=PlainCase(
            address=session.address or DASH,
            object_kind=session.object_kind or "",
            states=list(session.states),
            municipality=PlainMunicipality(name=session.municipality or "не указано"),
            cadastral_number_oks=session.cadastre_oks,
            cadastral_number_land=session.cadastre_land,
        ),
        decision=decision,
        author=PlainPerson(full_name=session.user_name or "Пользователь бота"),
        created_at=session.started_at,
        updated_at=now,
    )


def render_file(assessment: PlainAssessment, document_format: str) -> documents.RenderedDocument:
    return documents.render(
        assessment, document_format, title=TITLE, filename_prefix=FILENAME_PREFIX
    )


def available_formats() -> tuple[str, ...]:
    return documents.available_formats()


def preferred_format() -> str:
    """PDF удобнее смотреть с телефона; docx — запасной, если нет шрифта."""
    formats = available_formats()
    return documents.PDF if documents.PDF in formats else documents.DOCX


# --- выжимка в чат ----------------------------------------------------------


def _outcome_lines(outcome: dict) -> list[str]:
    lines: list[str] = [f"▸ {outcome.get('state_label') or outcome.get('state')}"]

    if not outcome.get("exact"):
        lines.append("  Точный сценарий не определён.")
        for near in outcome.get("nearest", [])[:2]:
            lines.append(f"  Ближайший сценарий № {near['scenario_num']}:")
            for difference in near.get("differences", []):
                lines.append(
                    f"    · {difference['label']}: в сценарии «{difference['expected_label']}», "
                    f"по объекту «{difference['actual_label']}»"
                )
        return lines

    lines.append(f"  Сценарий № {outcome.get('scenario_num')}")
    for method in outcome.get("methods", []):
        lines.append(f"  Способ: {method['title']}")
        actions = [step for step in method.get("steps", []) if step.get("kind") != "header"]
        for number, step in enumerate(actions[:STEPS_IN_CHAT], start=1):
            lines.append(f"    {number}. {step['text']}")
        rest = len(actions) - STEPS_IN_CHAT
        if rest > 0:
            word = plural(rest, "шаг", "шага", "шагов")
            lines.append(f"    … ещё {rest} {word} — в справке")
    return lines


def chat_summary(session: Session, decision: dict) -> str:
    """Короткая справка для чата. На входе — снимок решения."""
    payload = decision
    lines: list[str] = [
        TITLE,
        "",
        f"Объект: {session.address or DASH}",
        f"Вид: {payload.get('object_kind_label')}",
    ]
    if session.cadastre_oks:
        lines.append(f"Кадастровый номер: {session.cadastre_oks}")

    lines.append("")
    if payload.get("needs_review"):
        lines.append(texts.NEEDS_REVIEW)
        lines.append("")

    for outcome in payload.get("outcomes", []):
        lines.extend(_outcome_lines(outcome))
        lines.append("")

    if len(payload.get("outcomes", [])) > 1:
        lines.append(
            "Состояний несколько, поэтому способов тоже несколько — они приведены "
            "в порядке приоритета: угроза жизни впереди оформления права."
        )
        lines.append("")

    lines.append(f"Версия набора правил: {payload.get('ruleset_version')}")

    text = "\n".join(lines).strip()
    if len(text) > CHAT_LIMIT:
        # Режем по границе строки, а не посреди слова.
        text = text[:CHAT_LIMIT].rsplit("\n", 1)[0] + "\n\n… продолжение — в справке."
    return text
