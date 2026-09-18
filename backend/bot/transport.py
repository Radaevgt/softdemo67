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
    """Разбирает событие, не полагаясь на единственную форму ответа.

    Поля адресата и текста лежат на разной глубине у ``message_created`` и
    ``message_callback``, поэтому ищем по нескольким известным путям.
    """
    message = raw.get("message") or {}
    callback = raw.get("callback") or {}
    body = message.get("body") or {}
    recipient = message.get("recipient") or {}
    sender = _first(message, "sender") or callback.get("user") or raw.get("user") or {}

    user_id = _first(raw, "user_id") or sender.get("user_id") or recipient.get("user_id")

    name_parts = [sender.get("first_name"), sender.get("last_name")]
    user_name = " ".join(part for part in name_parts if part) or sender.get("name")

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

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_send
        if elapsed < MIN_SECONDS_BETWEEN_SENDS:
            time.sleep(MIN_SECONDS_BETWEEN_SENDS - elapsed)
        self._last_send = time.monotonic()

    # --- методы платформы ---------------------------------------------------

    def get_me(self) -> dict:
        return self._request("GET", "/me")

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
        payload: dict[str, Any] = {"text": text[:MAX_TEXT_LENGTH]}

        parts = list(attachments or [])
        if keyboard:
            parts.append({"type": "inline_keyboard", "payload": {"buttons": keyboard}})
        if parts:
            payload["attachments"] = parts

        self._throttle()
        return self._request("POST", "/messages", params={"user_id": user_id}, json=payload)

    def answer_callback(self, callback_id: str, notification: str | None = None) -> dict:
        """Снимает у нажатой кнопки состояние ожидания."""
        body = {"notification": notification} if notification else {}
        return self._request(
            "POST", "/answers", params={"callback_id": callback_id}, json=body
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
        token = self.upload_file(filename, content)
        return self.send_message(
            user_id, text, attachments=[{"type": "file", "payload": {"token": token}}]
        )
