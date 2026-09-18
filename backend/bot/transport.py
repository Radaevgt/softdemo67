"""Клиент MAX Bot API.

Здесь собрано всё, что отличает MAX от привычного Telegram-подобного API и что
дорого выясняется опытным путём:

* токен идёт заголовком ``Authorization`` **без** ``Bearer`` — с префиксом будет 401;
* личный диалог адресуется ``user_id``, а не ``chat_id``; ``chat_id`` в личке даёт
  ``404 chat.not.found``, а ``GET /chats`` личные диалоги вообще не возвращает;
* файл отправляется в три приёма: получить адрес загрузки, залить файл полем
  ``data``, приложить выданный токен к сообщению.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .tls import build_ssl_context

logger = logging.getLogger(__name__)

MAX_TEXT_LENGTH = 4000

# Платформа держит около 30 запросов в секунду и не более двух сообщений в
# секунду в один диалог. Держимся заметно ниже потолка.
MIN_SECONDS_BETWEEN_SENDS = 0.5

# Отказы с кодом 4xx, которые на самом деле временные — проверено на живом боте:
#
# * attachment.not.ready — платформа ещё обрабатывает только что залитый файл;
# * chat.denied — диалог не успел появиться сразу после открытия бота: первые
#   одна-две отправки отвергаются, следующая проходит.
TRANSIENT_CODES = frozenset({"attachment.not.ready", "chat.denied"})

# Пауза перед повтором. Последняя попытка — без паузы после неё.
RETRY_DELAYS = (0.7, 1.5, 3.0, 5.0)


class MaxApiError(RuntimeError):
    def __init__(self, status: int, code: str | None, body: str) -> None:
        self.status = status
        self.code = code
        self.body = body
        super().__init__(f"MAX API {status}: {code or body[:200]}")

    @property
    def is_retryable(self) -> bool:
        return self.status == 429 or self.status >= 500


@dataclass(frozen=True)
class Update:
    """Событие от платформы в разобранном виде."""

    update_type: str
    user_id: int | None
    text: str | None
    message_id: str | None
    callback_id: str | None
    payload: str | None
    user_name: str | None
    raw: dict


def _first(source: dict, *names: str) -> Any:
    for name in names:
        value = source.get(name)
        if value is not None:
            return value
    return None


def parse_update(raw: dict) -> Update:
    """Разбирает событие и, главное, находит собеседника.

    Тонкость, стоившая отладки: в событии о нажатии кнопки ``message`` — это
    сообщение, **на котором** была кнопка, то есть отправленное ботом. Брать
    собеседника оттуда нельзя: получится идентификатор самого бота, и попытка
    ответить упрётся в ``403 chat.denied``. Нажавшего кнопку хранит ``callback.user``.

    По той же причине не годится ``message.recipient``: в личном диалоге получатель
    входящего сообщения — бот.
    """
    message = raw.get("message") or {}
    callback = raw.get("callback") or {}
    body = message.get("body") or {}

    if callback:
        person = callback.get("user") or raw.get("user") or {}
    else:
        person = message.get("sender") or raw.get("user") or {}

    user_id = person.get("user_id") or _first(raw, "user_id")

    name_parts = [person.get("first_name"), person.get("last_name")]
    user_name = " ".join(part for part in name_parts if part) or person.get("name")

    return Update(
        update_type=raw.get("update_type", ""),
        user_id=int(user_id) if user_id is not None else None,
        text=body.get("text"),
        message_id=body.get("mid") or message.get("mid"),
        callback_id=callback.get("callback_id"),
        payload=callback.get("payload"),
        user_name=user_name or None,
        raw=raw,
    )


class MaxClient:
    """Синхронный клиент. Бот однопоточный, асинхронность ничего бы не дала."""

    def __init__(
        self,
        token: str,
        api_base: str,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._token = token
        self._last_send = 0.0
        self._timeout = timeout
        # Заполняется из /me. Нужен, чтобы поймать попытку написать самому себе:
        # платформа отвечает на это 403 chat.denied, и без явной проверки причина
        # выглядит как отказ доступа, а не как ошибка разбора события.
        self.bot_user_id: int | None = None
        # Отдельным полем, чтобы тесты не ждали по-настоящему.
        self._sleep = time.sleep
        # В тестах транспорт подменён, и настоящий контекст TLS не нужен —
        # собирать его там значило бы читать файл сертификата без надобности.
        self._verify = build_ssl_context() if transport is None else True
        self._transport = transport
        self._client = httpx.Client(
            base_url=api_base,
            headers={"Authorization": token},  # именно так: без "Bearer"
            timeout=timeout,
            transport=transport,
            verify=self._verify,
        )

    def __repr__(self) -> str:  # токен не должен попадать в журнал
        return f"<MaxClient {self._client.base_url}>"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MaxClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- низкий уровень -----------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            code = None
            try:
                code = response.json().get("code")
            except ValueError:
                pass
            raise MaxApiError(response.status_code, code, response.text)
        return response.json() if response.content else {}

    def _retrying(self, action: Any) -> dict:
        """Повторяет действие, если платформа отказала временно.

        Такие отказы приходят с кодом 400 и 403, поэтому обычная проверка
        «повторять только 429 и 5xx» их не ловит — различает именно код ошибки.
        """
        for delay in (*RETRY_DELAYS, None):
            try:
                return action()
            except MaxApiError as error:
                if delay is None or error.code not in TRANSIENT_CODES:
                    raise
                logger.info("Отказ %s, повтор через %.1f с", error.code, delay)
                self._sleep(delay)
        raise AssertionError("недостижимо")

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_send
        if elapsed < MIN_SECONDS_BETWEEN_SENDS:
            time.sleep(MIN_SECONDS_BETWEEN_SENDS - elapsed)
        self._last_send = time.monotonic()

    # --- методы платформы ---------------------------------------------------

    def get_me(self) -> dict:
        me = self._request("GET", "/me")
        if me.get("user_id") is not None:
            self.bot_user_id = int(me["user_id"])
        return me

    def get_updates(self, marker: int | None, *, limit: int, timeout: int) -> dict:
        params: dict[str, Any] = {"limit": limit, "timeout": timeout}
        if marker is not None:
            params["marker"] = marker
        return self._request("GET", "/updates", params=params)

    def send_message(
        self,
        user_id: int,
        text: str,
        *,
        keyboard: list[list[dict]] | None = None,
        attachments: list[dict] | None = None,
    ) -> dict:
        """Сообщение в личный диалог. Адресат — ``user_id``, не ``chat_id``."""
        if self.bot_user_id is not None and user_id == self.bot_user_id:
            raise ValueError(
                "Попытка отправить сообщение самому боту: событие разобрано неверно, "
                "собеседник потерян"
            )

        payload: dict[str, Any] = {"text": text[:MAX_TEXT_LENGTH]}

        parts = list(attachments or [])
        if keyboard:
            parts.append({"type": "inline_keyboard", "payload": {"buttons": keyboard}})
        if parts:
            payload["attachments"] = parts

        self._throttle()
        return self._retrying(
            lambda: self._request(
                "POST", "/messages", params={"user_id": user_id}, json=payload
            )
        )

    def replace_message(
        self,
        callback_id: str,
        text: str,
        *,
        keyboard: list[list[dict]] | None = None,
    ) -> dict:
        """Заменяет сообщение, на котором нажали кнопку.

        ``/answers`` требует ровно одно из двух полей — проверено вживую, платформа
        так и отвечает на пустое тело:
        ``400 proto.payload: Invalid request. `message` or `notification```.

        ``notification`` (всплывающая подсказка, как в Telegram) в документации не
        описан, но поддерживается. Здесь выбрана замена сообщения: она заодно
        перерисовывает клавиатуру мультивыбора и не засоряет переписку
        повторяющимися вопросами.
        """
        message: dict[str, Any] = {"text": text[:MAX_TEXT_LENGTH]}
        if keyboard:
            message["attachments"] = [
                {"type": "inline_keyboard", "payload": {"buttons": keyboard}}
            ]
        self._throttle()
        return self._request(
            "POST", "/answers", params={"callback_id": callback_id}, json={"message": message}
        )

    def upload_file(self, filename: str, content: bytes) -> str:
        """Загружает файл и возвращает токен вложения.

        Три приёма: адрес загрузки, сама загрузка полем ``data``, токен обратно.
        Токен может прийти как на первом шаге, так и на втором.
        """
        started = self._request("POST", "/uploads", params={"type": "file"})
        url = started.get("url")
        if not url:
            raise MaxApiError(502, "no.upload.url", str(started))

        # Отдельный клиент: адрес загрузки лежит на другом хосте (fu.oneme.ru),
        # заголовок авторизации туда слать незачем.
        with httpx.Client(
            timeout=self._timeout, verify=self._verify, transport=self._transport
        ) as uploader:
            response = uploader.post(url, files={"data": (filename, content)})
        if response.status_code >= 400:
            raise MaxApiError(response.status_code, "upload.failed", response.text)

        token = started.get("token")
        if response.content:
            try:
                token = response.json().get("token") or token
            except ValueError:
                pass
        if not token:
            raise MaxApiError(502, "no.upload.token", response.text[:200])
        return token

    def send_file(self, user_id: int, filename: str, content: bytes, *, text: str = "") -> dict:
        """Отправляет файл вложением.

        Между загрузкой и отправкой платформе нужно время на обработку: без
        паузы приходит ``400 attachment.not.ready``. Повтор берёт на себя
        :meth:`_retrying`.
        """
        token = self.upload_file(filename, content)
        return self.send_message(
            user_id, text, attachments=[{"type": "file", "payload": {"token": token}}]
        )
