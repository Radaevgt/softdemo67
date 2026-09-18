"""Клавиатуры и разбор нажатий.

Payload кнопки — ``<токен шага>|<действие>|<значение>``. Токен шага обязателен:
пользователь может прокрутить переписку вверх и нажать кнопку под старым
вопросом, и отличить это от осмысленного ответа больше нечем.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.engine.attributes import AttributeDef

from . import texts

SEPARATOR = "|"


class Action:
    START = "start"
    HELP = "help"
    SKIP = "skip"
    KIND = "kind"
    STATE = "state"
    STATES_DONE = "states_done"
    CONFIRM = "confirm"
    EDIT = "edit"
    ANSWER = "ans"
    BACK = "back"
    RESTART = "restart"
    RESTART_YES = "restart_yes"
    RESTART_NO = "restart_no"
    RESUME = "resume"
    DOCX = "docx"


@dataclass(frozen=True)
class Tap:
    token: str
    action: str
    value: str


def encode(token: str, action: str, value: str = "") -> str:
    return SEPARATOR.join((token, action, value))


def decode(payload: str | None) -> Tap | None:
    if not payload:
        return None
    parts = payload.split(SEPARATOR, 2)
    if len(parts) < 2:
        return None
    token, action = parts[0], parts[1]
    value = parts[2] if len(parts) > 2 else ""
    return Tap(token=token, action=action, value=value)


def button(text: str, payload: str) -> dict:
    return {"type": "callback", "text": text, "payload": payload}


# --- клавиатуры -------------------------------------------------------------


def greeting(token: str) -> list[list[dict]]:
    return [
        [button(texts.BTN_START, encode(token, Action.START))],
        [button(texts.BTN_HELP, encode(token, Action.HELP))],
    ]


def resume(token: str) -> list[list[dict]]:
    return [
        [button(texts.BTN_RESUME, encode(token, Action.RESUME))],
        [button(texts.BTN_RESTART, encode(token, Action.RESTART_YES))],
    ]


def navigation(token: str, *, with_back: bool = True) -> list[dict]:
    row = []
    if with_back:
        row.append(button(texts.BTN_BACK, encode(token, Action.BACK)))
    row.append(button(texts.BTN_RESTART, encode(token, Action.RESTART)))
    return row


def skippable(token: str, *, with_back: bool = True) -> list[list[dict]]:
    return [
        [button(texts.BTN_SKIP, encode(token, Action.SKIP))],
        navigation(token, with_back=with_back),
    ]


def text_step(token: str, *, with_back: bool = True) -> list[list[dict]]:
    return [navigation(token, with_back=with_back)]


def object_kinds(token: str) -> list[list[dict]]:
    rows = [
        [button(label, encode(token, Action.KIND, value))]
        for value, label in texts.OBJECT_KIND_BUTTONS.items()
    ]
    rows.append(navigation(token))
    return rows


def states(token: str, selected: list[str]) -> list[list[dict]]:
    """Переключатели: отметка показывает текущий выбор."""
    rows = []
    for value, label in texts.STATE_BUTTONS.items():
        mark = texts.CHECKED if value in selected else texts.UNCHECKED
        rows.append([button(f"{mark} {label}", encode(token, Action.STATE, value))])
    rows.append([button(texts.BTN_DONE, encode(token, Action.STATES_DONE))])
    rows.append(navigation(token))
    return rows


def confirmation(token: str) -> list[list[dict]]:
    return [
        [button(texts.BTN_CONFIRM, encode(token, Action.CONFIRM))],
        [button(texts.BTN_EDIT, encode(token, Action.EDIT))],
        navigation(token, with_back=False),
    ]


def question(token: str, attribute: AttributeDef) -> list[list[dict]]:
    """Кнопки строятся из описания признака, а не из зашитого списка."""
    rows = []
    for option in attribute.options:
        # Значение в payload — строка; логическое восстанавливается при разборе.
        raw = "true" if option.value is True else "false" if option.value is False else str(option.value)
        rows.append(
            [button(option.label, encode(token, Action.ANSWER, f"{attribute.key}:{raw}"))]
        )
    rows.append(navigation(token))
    return rows


def restart_confirmation(token: str) -> list[list[dict]]:
    return [
        [button(texts.BTN_RESTART_YES, encode(token, Action.RESTART_YES))],
        [button(texts.BTN_RESTART_NO, encode(token, Action.RESTART_NO))],
    ]


def result(token: str, *, with_docx: bool, with_edit: bool = False) -> list[list[dict]]:
    rows = []
    if with_docx:
        rows.append([button(texts.BTN_DOCX, encode(token, Action.DOCX))])
    if with_edit:
        # Сценарий не определён — самое полезное действие здесь поправить ответ.
        rows.append([button(texts.BTN_EDIT_ANSWERS, encode(token, Action.BACK))])
    rows.append([button(texts.BTN_NEW_CASE, encode(token, Action.RESTART_YES))])
    return rows


def parse_answer(value: str) -> tuple[str, bool | str] | None:
    """Разбирает ``<признак>:<значение>`` обратно в пару для движка."""
    key, _, raw = value.partition(":")
    if not key or not raw:
        return None
    if raw == "true":
        return key, True
    if raw == "false":
        return key, False
    return key, raw
