"""Логика разговора.

Чистая: ни сети, ни часов, ни диска. ``handle`` получает событие и возвращает
список ответов, которые исполняет цикл опроса. Благодаря этому весь сценарий
проверяется тестами без обращения к платформе.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.engine import attributes
from app.enums import LABELS, ObjectKind, ObjectState

from . import keyboards, spravka, texts
from .decide import decide
from .keyboards import Action
from .session import INPUT_STEPS, Session, Step

DASH = "—"


@dataclass
class Reply:
    """Одно исходящее действие."""

    kind: str  # text | file
    text: str = ""
    keyboard: list[list[dict]] | None = None
    document_format: str | None = None


@dataclass
class Event:
    """Входящее событие в том виде, в каком его понимает разговор."""

    text: str | None = None
    tap: keyboards.Tap | None = None
    callback_id: str | None = None
    is_start: bool = False


@dataclass
class Outcome:
    replies: list[Reply] = field(default_factory=list)
    _pending_note: str | None = None

    def say(self, text: str, keyboard: list[list[dict]] | None = None) -> "Outcome":
        if self._pending_note:
            text = f"{self._pending_note}\n\n{text}"
            self._pending_note = None
        self.replies.append(Reply(kind="text", text=text, keyboard=keyboard))
        return self

    def note(self, notification: str) -> "Outcome":
        """Замечание к следующему сообщению.

        В MAX нет всплывающего уведомления по нажатию кнопки, как в Telegram,
        поэтому замечание становится первой строкой ответа.
        """
        self._pending_note = notification
        return self

    def file(self, document_format: str, text: str = "") -> "Outcome":
        self.replies.append(Reply(kind="file", document_format=document_format, text=text))
        return self


# --- вопросы шага ввода -----------------------------------------------------


def _ask(session: Session, out: Outcome) -> Outcome:
    """Задаёт вопрос текущего шага, обновив токен шага."""
    token = session.rotate_token()
    first_step = session.step == INPUT_STEPS[0]

    if session.step == Step.ADDRESS:
        return out.say(texts.ASK_ADDRESS, keyboards.text_step(token, with_back=not first_step))
    if session.step == Step.MUNICIPALITY:
        return out.say(texts.ASK_MUNICIPALITY, keyboards.skippable(token))
    if session.step == Step.OBJECT_KIND:
        return out.say(texts.ASK_OBJECT_KIND, keyboards.object_kinds(token))
    if session.step == Step.STATES:
        return out.say(texts.ASK_STATES, keyboards.states(token, session.states))
    if session.step == Step.CADASTRE_OKS:
        return out.say(texts.ASK_CADASTRE_OKS, keyboards.skippable(token))
    if session.step == Step.CADASTRE_LAND:
        return out.say(texts.ASK_CADASTRE_LAND, keyboards.skippable(token))
    if session.step == Step.CONFIRM:
        return out.say(_summary(session), keyboards.confirmation(token))
    if session.step == Step.QUESTION:
        return _ask_question(session, out)
    return out


def _summary(session: Session) -> str:
    kind = LABELS["object_kind"].get(ObjectKind(session.object_kind), session.object_kind)
    states = ", ".join(
        LABELS["state"].get(ObjectState(state), state) for state in session.states
    )
    lines = [
        texts.CONFIRM_TITLE,
        "",
        f"Адрес: {session.address or DASH}",
        f"Муниципальное образование: {session.municipality or DASH}",
        f"Вид объекта: {kind}",
        f"Состояние: {states or DASH}",
        f"Кадастровый номер ОКС: {session.cadastre_oks or DASH}",
        f"Кадастровый номер ЗУ: {session.cadastre_land or DASH}",
    ]
    return "\n".join(lines)


def _ask_question(session: Session, out: Outcome) -> Outcome:
    attribute = attributes.next_unanswered(session.object_kind, session.answers)
    if attribute is None:
        return _finish(session, out)

    applicable = attributes.applicable_attributes(session.object_kind, session.answers)
    token = session.rotate_token()
    counter = texts.QUESTION_COUNTER.format(
        current=len(session.answers) + 1, total=len(applicable)
    )
    body = "\n\n".join(
        [counter, attribute.label, texts.QUESTION_SOURCE.format(hint=attribute.source_hint)]
    )
    return out.say(body, keyboards.question(token, attribute))


def _finish(session: Session, out: Outcome) -> Outcome:
    errors = attributes.validate(session.object_kind, session.answers)
    if errors:
        session.step = Step.QUESTION
        return _ask_question(session, out)

    decision = decide(session.object_kind, session.states, session.answers)
    session.decision = decision.to_dict()
    session.step = Step.RESULT
    token = session.rotate_token()

    out.say(spravka.chat_summary(session, session.decision))
    out.file(spravka.preferred_format(), texts.SPRAVKA_FILE_CAPTION)

    formats = spravka.available_formats()
    with_docx = spravka.preferred_format() != "docx" and "docx" in formats
    return out.say(
        texts.SPRAVKA_READY,
        keyboards.result(token, with_docx=with_docx, with_edit=decision.needs_review),
    )


# --- переходы ---------------------------------------------------------------


def _advance(session: Session, out: Outcome) -> Outcome:
    """Переводит на следующий шаг ввода, затем в опрос."""
    index = INPUT_STEPS.index(session.step)
    if index + 1 < len(INPUT_STEPS):
        session.step = INPUT_STEPS[index + 1]
    else:
        session.step = Step.QUESTION
    session.touch()
    return _ask(session, out)


def _go_back(session: Session, out: Outcome) -> Outcome:
    """Снимает последний ответ и возвращает на его шаг.

    В опросе порядок признаков фиксирован, а ``prune`` за один проход улаживает
    применимость, поэтому особых случаев не требуется.
    """
    if session.step == Step.IDLE:
        token = session.rotate_token()
        return out.say(texts.GREETING, keyboards.greeting(token))

    # С экрана результата «Назад» возвращает к последнему вопросу, чтобы можно
    # было поправить ответ, не начиная дело заново.
    if session.step == Step.RESULT:
        session.step = Step.QUESTION
        session.decision = None

    if session.step == Step.QUESTION and session.answers:
        answered = [
            attribute.key
            for attribute in attributes.ATTRIBUTES
            if attribute.key in session.answers
        ]
        session.answers.pop(answered[-1], None)
        session.answers = attributes.prune(session.object_kind, session.answers)
        return _ask_question(session, out)

    if session.step == Step.QUESTION:
        session.step = INPUT_STEPS[-1]
        return _ask(session, out)

    index = INPUT_STEPS.index(session.step)
    if index == 0:
        return _ask(session, out)
    session.step = INPUT_STEPS[index - 1]
    return _ask(session, out)


def _start_case(session: Session, out: Outcome) -> Outcome:
    session.reset()
    session.step = Step.ADDRESS
    return _ask(session, out)


def _set_answer(session: Session, key: str, value: bool | str, out: Outcome) -> Outcome:
    session.answers[key] = value
    # prune вызывается после каждой записи, а не только перед расчётом: иначе
    # ответ про наследников переживёт смену статуса на «жив» и попадёт в справку.
    session.answers = attributes.prune(session.object_kind, session.answers)
    session.touch()
    return _ask_question(session, out)


# --- вход -------------------------------------------------------------------


def handle(session: Session, event: Event) -> Outcome:
    out = Outcome()

    if event.tap is not None:
        return _handle_tap(session, event, out)
    return _handle_text(session, event, out)


def _handle_text(session: Session, event: Event, out: Outcome) -> Outcome:
    text = (event.text or "").strip()

    if event.is_start or text.lower() in {"/start", "начать", "старт"}:
        token = session.rotate_token()
        if session.step not in (Step.IDLE, Step.RESULT) and session.address:
            return out.say(
                texts.RESUME.format(address=session.address), keyboards.resume(token)
            )
        session.reset()
        return out.say(texts.GREETING, keyboards.greeting(token))

    if session.step in (Step.IDLE, Step.RESULT):
        token = session.rotate_token()
        return out.say(texts.GREETING, keyboards.greeting(token))

    if not text:
        return out.say(texts.NEED_TEXT)

    if session.step == Step.ADDRESS:
        session.address = text
        return _advance(session, out)
    if session.step == Step.MUNICIPALITY:
        session.municipality = text
        return _advance(session, out)
    if session.step == Step.CADASTRE_OKS:
        session.cadastre_oks = text
        return _advance(session, out)
    if session.step == Step.CADASTRE_LAND:
        session.cadastre_land = text
        return _advance(session, out)

    # На шагах с кнопками текст не ожидается — повторяем вопрос.
    return _ask(session, out)


def _handle_tap(session: Session, event: Event, out: Outcome) -> Outcome:
    tap = event.tap
    assert tap is not None

    # Кнопка из прокрученного вверх старого сообщения приходит со старым токеном.
    # Приветствие и подтверждение сброса — исключение: они живут вне шага.
    token_free = {Action.START, Action.HELP, Action.RESUME, Action.RESTART_YES, Action.RESTART_NO}
    if tap.action not in token_free and tap.token != session.step_token:
        out.note(texts.BUTTON_EXPIRED)
        return _ask(session, out)

    if tap.action == Action.HELP:
        token = session.rotate_token()
        return out.say(texts.HELP, keyboards.greeting(token))

    if tap.action in (Action.START, Action.RESTART_YES):
        return _start_case(session, out)

    if tap.action == Action.RESUME:
        return _ask(session, out)

    if tap.action == Action.RESTART:
        token = session.rotate_token()
        return out.say(texts.RESTART_CONFIRM, keyboards.restart_confirmation(token))

    if tap.action == Action.RESTART_NO:
        return _ask(session, out)

    if tap.action == Action.BACK:
        return _go_back(session, out)

    if tap.action == Action.SKIP:
        return _advance(session, out)

    if tap.action == Action.KIND:
        session.object_kind = tap.value
        return _advance(session, out)

    if tap.action == Action.STATE:
        if tap.value in session.states:
            session.states.remove(tap.value)
        else:
            session.states.append(tap.value)
        session.touch()
        return _ask(session, out)

    if tap.action == Action.STATES_DONE:
        if not session.states:
            out.note(texts.NEED_ONE_STATE)
            return _ask(session, out)
        return _advance(session, out)

    if tap.action == Action.EDIT:
        session.step = INPUT_STEPS[0]
        return _ask(session, out)

    if tap.action == Action.CONFIRM:
        session.step = Step.QUESTION
        return _ask_question(session, out)

    if tap.action == Action.ANSWER:
        parsed = keyboards.parse_answer(tap.value)
        if parsed is None:
            return _ask(session, out)
        key, value = parsed
        return _set_answer(session, key, value, out)

    if tap.action == Action.DOCX:
        return out.file("docx", texts.SPRAVKA_FILE_CAPTION)

    return out.say(texts.UNKNOWN_COMMAND)
