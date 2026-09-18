"""Цикл длинного опроса и исполнение ответов.

Вся логика разговора живёт в ``flow`` и ничего не знает про сеть. Здесь —
только доставка: получить события, отдать их разговору, отправить то, что он
вернул, и не упасть, что бы ни случилось.
"""
from __future__ import annotations

import logging
import random
import time
from collections import deque

from . import keyboards, spravka, texts
from .flow import Event, Outcome, handle
from .session import Session, SessionStore
from .transport import MaxApiError, MaxClient, Update, parse_update

logger = logging.getLogger(__name__)

BACKOFF_START = 1.0
BACKOFF_LIMIT = 30.0

# Сколько недавних событий помнить, чтобы не обработать повтор дважды.
SEEN_LIMIT = 500

HEARTBEAT_EVERY = 20


class Runner:
    def __init__(
        self,
        client: MaxClient,
        store: SessionStore,
        *,
        poll_limit: int = 100,
        poll_timeout: int = 90,
        skip_backlog: bool = True,
    ) -> None:
        self._client = client
        self._store = store
        self._limit = poll_limit
        self._timeout = poll_timeout
        self._skip_backlog = skip_backlog

        self._marker: int | None = None
        self._seen: deque[str] = deque(maxlen=SEEN_LIMIT)
        self._seen_set: set[str] = set()
        self._idle_polls = 0
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    # --- защита от повторов -------------------------------------------------

    def _already_seen(self, key: str | None) -> bool:
        if not key:
            return False
        if key in self._seen_set:
            return True
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(key)
        self._seen_set.add(key)
        return False

    # --- цикл ---------------------------------------------------------------

    def prime(self) -> None:
        """Пропускает накопленную очередь, чтобы не отвечать на вчерашнее."""
        if not self._skip_backlog:
            return
        batch = self._client.get_updates(None, limit=self._limit, timeout=0)
        self._marker = batch.get("marker")
        skipped = len(batch.get("updates", []))
        if skipped:
            logger.info("Пропущено накопленных событий: %s", skipped)

    def run(self) -> None:
        backoff = BACKOFF_START
        while not self._stopping:
            try:
                batch = self._client.get_updates(
                    self._marker, limit=self._limit, timeout=self._timeout
                )
            except MaxApiError as error:
                if not error.is_retryable:
                    logger.error("Опрос отклонён платформой: %s", error)
                backoff = self._sleep_backoff(backoff, error)
                continue
            except Exception as error:  # сеть, таймаут — цикл не должен умирать
                backoff = self._sleep_backoff(backoff, error)
                continue

            backoff = BACKOFF_START
            updates = batch.get("updates", [])
            if updates:
                self._idle_polls = 0
                for raw in updates:
                    self._dispatch(raw)
            else:
                self._heartbeat()

            # Маркер двигается только после обработки всей партии: повтор
            # безвреден благодаря защите выше, а потерянный ответ — нет.
            self._marker = batch.get("marker", self._marker)

    def _sleep_backoff(self, backoff: float, error: object) -> float:
        logger.warning("Опрос не удался (%s), пауза %.0f с", error, backoff)
        time.sleep(backoff + random.uniform(0, 0.5))
        return min(backoff * 2, BACKOFF_LIMIT)

    def _heartbeat(self) -> None:
        self._idle_polls += 1
        if self._idle_polls % HEARTBEAT_EVERY == 0:
            logger.info("Живы, диалогов в памяти: %s", len(self._store))

    # --- обработка ----------------------------------------------------------

    def _dispatch(self, raw: dict) -> None:
        update = parse_update(raw)
        if update.user_id is None:
            logger.debug("Событие без адресата: %s", update.update_type)
            return

        key = update.callback_id or update.message_id
        if self._already_seen(key):
            logger.info("Повтор события %s от %s — пропущен", key, update.user_id)
            return

        session = self._store.get_or_create(update.user_id, update.user_name)
        try:
            outcome = handle(session, self._to_event(update))
            session.touch()
            self._send(session, outcome, update)
        except Exception:
            logger.exception("Ошибка обработки события от %s", update.user_id)
            self._safely(lambda: self._client.send_message(update.user_id, texts.ERROR))

    @staticmethod
    def _to_event(update: Update) -> Event:
        return Event(
            text=update.text,
            tap=keyboards.decode(update.payload),
            callback_id=update.callback_id,
            is_start=update.update_type == "bot_started",
        )

    def _send(self, session: Session, outcome: Outcome, update: Update) -> None:
        """Отправляет ответы разговора.

        Первый ответ на нажатие кнопки заменяет сообщение с этой кнопкой, а не
        добавляет новое: так работает ``/answers`` в MAX, и так переписка не
        зарастает повторяющимися вопросами, а клавиатура мультивыбора
        перерисовывается на месте.
        """
        replaced = False
        for reply in outcome.replies:
            if reply.kind == "file":
                self._send_file(session, reply.document_format, reply.text)
                continue

            if update.callback_id and not replaced:
                replaced = True
                if self._replace(update.callback_id, reply):
                    continue
                # Замена не удалась — отправляем обычным сообщением, чтобы
                # пользователь не остался без ответа.

            self._safely(
                lambda r=reply: self._client.send_message(
                    session.user_id, r.text, keyboard=r.keyboard
                )
            )

    def _replace(self, callback_id: str, reply) -> bool:
        try:
            self._client.replace_message(callback_id, reply.text, keyboard=reply.keyboard)
            return True
        except Exception:
            logger.warning("Не удалось заменить сообщение, отправляем новым", exc_info=True)
            return False

    def _send_file(self, session: Session, document_format: str, caption: str) -> None:
        if not session.decision:
            return
        try:
            assessment = spravka.build_assessment(session, session.decision)
            rendered = spravka.render_file(assessment, document_format)
        except Exception:
            logger.exception("Не удалось собрать справку для %s", session.user_id)
            self._safely(lambda: self._client.send_message(session.user_id, texts.FILE_FAILED))
            return

        try:
            self._client.send_file(
                session.user_id, rendered.filename, rendered.content, text=caption
            )
        except Exception:
            logger.exception("Не удалось отправить файл %s", rendered.filename)
            self._safely(lambda: self._client.send_message(session.user_id, texts.FILE_FAILED))

    @staticmethod
    def _safely(action) -> None:
        """Сбой одного исходящего сообщения не должен ронять весь разговор."""
        try:
            action()
        except Exception:
            logger.exception("Не удалось отправить сообщение")
