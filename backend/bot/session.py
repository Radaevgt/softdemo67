"""Состояние разговора.

По решению заказчика бот ничего не хранит: сессии живут в памяти процесса и
исчезают при перезапуске. Брошенные диалоги вычищаются по времени бездействия,
иначе память течёт на каждом, кто открыл бота и ушёл.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum


class Step(StrEnum):
    IDLE = "idle"
    FULL_NAME = "full_name"
    ADDRESS = "address"
    MUNICIPALITY = "municipality"
    OBJECT_KIND = "object_kind"
    STATES = "states"
    CADASTRE_OKS = "cadastre_oks"
    CADASTRE_LAND = "cadastre_land"
    CONFIRM = "confirm"
    QUESTION = "question"
    RESULT = "result"


# Шаги ввода сведений в порядке прохождения — по нему работает кнопка «Назад».
INPUT_STEPS: tuple[Step, ...] = (
    Step.FULL_NAME,
    Step.ADDRESS,
    Step.MUNICIPALITY,
    Step.OBJECT_KIND,
    Step.STATES,
    Step.CADASTRE_OKS,
    Step.CADASTRE_LAND,
    Step.CONFIRM,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Session:
    user_id: int
    step: Step = Step.IDLE
    # Отображаемое имя из мессенджера: годится для журнала, но не для справки —
    # там нужны фамилия, имя и отчество, которые спрашиваются отдельно.
    user_name: str | None = None
    full_name: str | None = None

    address: str | None = None
    municipality: str | None = None
    object_kind: str | None = None
    states: list[str] = field(default_factory=list)
    cadastre_oks: str | None = None
    cadastre_land: str | None = None

    answers: dict = field(default_factory=dict)
    decision: dict | None = None

    started_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    # Новый на каждый заданный вопрос. Нажатие кнопки из прокрученного вверх
    # старого сообщения придёт со старым токеном — так это и ловится.
    step_token: str = field(default_factory=lambda: secrets.token_urlsafe(6))

    def touch(self) -> None:
        self.updated_at = _now()

    def rotate_token(self) -> str:
        self.step_token = secrets.token_urlsafe(6)
        return self.step_token

    def reset(self) -> None:
        """Сбрасывает дело, сохраняя того, с кем идёт разговор."""
        self.step = Step.IDLE
        self.full_name = None
        self.address = None
        self.municipality = None
        self.object_kind = None
        self.states = []
        self.cadastre_oks = None
        self.cadastre_land = None
        self.answers = {}
        self.decision = None
        self.started_at = _now()
        self.rotate_token()
        self.touch()


class SessionStore:
    """Сессии в памяти процесса с вычисткой по бездействию."""

    def __init__(self, ttl_minutes: int = 60) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._sessions: dict[int, Session] = {}

    def get(self, user_id: int) -> Session | None:
        self.purge()
        return self._sessions.get(user_id)

    def get_or_create(self, user_id: int, user_name: str | None = None) -> Session:
        session = self.get(user_id)
        if session is None:
            session = Session(user_id=user_id, user_name=user_name)
            self._sessions[user_id] = session
        elif user_name and not session.user_name:
            session.user_name = user_name
        return session

    def drop(self, user_id: int) -> None:
        self._sessions.pop(user_id, None)

    def purge(self) -> None:
        deadline = _now() - self._ttl
        stale = [uid for uid, s in self._sessions.items() if s.updated_at < deadline]
        for user_id in stale:
            del self._sessions[user_id]

    def __len__(self) -> int:
        return len(self._sessions)
