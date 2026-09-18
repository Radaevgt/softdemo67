"""Клиент MAX.

Проверяются не выдумки, а особенности платформы, каждая из которых стоила
времени: заголовок без ``Bearer``, адресация личного диалога по ``user_id``,
трёхшаговая загрузка файла полем ``data``.
"""
import httpx
import pytest

from bot.transport import MaxApiError, MaxClient, parse_update

TOKEN = "test-token-value"
BASE = "https://platform-api2.max.ru"


def client_with(handler) -> MaxClient:
    return MaxClient(TOKEN, BASE, transport=httpx.MockTransport(handler))


# --- авторизация и адресация ------------------------------------------------


def test_token_goes_without_the_bearer_prefix():
    """С префиксом «Bearer» платформа отвечает 401, хотя токен верный."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"user_id": 1})

    client_with(handler).get_me()
    assert seen["auth"] == TOKEN
    assert not seen["auth"].lower().startswith("bearer")


def test_private_dialog_is_addressed_by_user_id_not_chat_id():
    """chat_id в личном диалоге даёт 404 chat.not.found."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={})

    client_with(handler).send_message(234747847, "привет")
    assert seen["params"] == {"user_id": "234747847"}
    assert "chat_id" not in seen["params"]


def test_repr_does_not_leak_the_token():
    client = client_with(lambda request: httpx.Response(200, json={}))
    assert TOKEN not in repr(client)


# --- события ----------------------------------------------------------------


def test_marker_is_passed_back_and_omitted_when_unknown():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"updates": [], "marker": 777})

    client = client_with(handler)
    client.get_updates(None, limit=100, timeout=90)
    client.get_updates(777, limit=100, timeout=90)

    assert "marker" not in seen[0], "первый запрос идёт без маркера"
    assert seen[1]["marker"] == "777"
    assert seen[0]["limit"] == "100" and seen[0]["timeout"] == "90"


def test_message_update_is_parsed_into_addressee_and_text():
    update = parse_update(
        {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 5, "first_name": "Мария", "last_name": "Иванова"},
                "body": {"mid": "mid-1", "text": "г. Бор, ул. Полевая, д. 2"},
            },
        }
    )
    assert update.user_id == 5
    assert update.text == "г. Бор, ул. Полевая, д. 2"
    assert update.message_id == "mid-1"
    assert update.user_name == "Мария Иванова"


def test_callback_update_carries_payload_and_callback_id():
    update = parse_update(
        {
            "update_type": "message_callback",
            "callback": {
                "callback_id": "cb-9",
                "payload": "tok|ans|rights_obj:true",
                "user": {"user_id": 7, "first_name": "Сергей"},
            },
        }
    )
    assert update.user_id == 7
    assert update.callback_id == "cb-9"
    assert update.payload == "tok|ans|rights_obj:true"


def test_update_without_addressee_is_parsed_without_crashing():
    update = parse_update({"update_type": "bot_added"})
    assert update.user_id is None


# --- ошибки -----------------------------------------------------------------


def test_error_carries_the_platform_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "chat.not.found"})

    with pytest.raises(MaxApiError) as error:
        client_with(handler).send_message(1, "текст")

    assert error.value.status == 404
    assert error.value.code == "chat.not.found"
    assert error.value.is_retryable is False


@pytest.mark.parametrize("status,retryable", [(429, True), (500, True), (503, True), (400, False), (401, False)])
def test_only_transient_failures_are_worth_retrying(status, retryable):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={})

    with pytest.raises(MaxApiError) as error:
        client_with(handler).get_me()
    assert error.value.is_retryable is retryable


# --- отправка ---------------------------------------------------------------


def test_keyboard_is_sent_as_an_inline_keyboard_attachment():
    import json

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client_with(handler).send_message(
        1, "вопрос", keyboard=[[{"type": "callback", "text": "Да", "payload": "t|ans|x:true"}]]
    )

    attachment = seen["body"]["attachments"][0]
    assert attachment["type"] == "inline_keyboard"
    assert attachment["payload"]["buttons"][0][0]["text"] == "Да"


def test_long_text_is_trimmed_to_the_platform_limit():
    import json

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client_with(handler).send_message(1, "я" * 5000)
    assert len(seen["body"]["text"]) == 4000


def test_file_upload_takes_three_steps_with_the_data_field():
    """Адрес загрузки → сам файл полем data → токен во вложении сообщения."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/uploads":
            assert dict(request.url.params)["type"] == "file"
            return httpx.Response(200, json={"url": "https://fu.oneme.ru/upload.do?x=1"})
        if request.url.path == "/upload.do":
            body = request.content.decode("utf-8", "ignore")
            assert 'name="data"' in body, "поле формы называется data"
            assert "Справка-AB.pdf" in body
            return httpx.Response(200, json={"token": "upload-token"})
        import json

        assert json.loads(request.content)["attachments"][0] == {
            "type": "file",
            "payload": {"token": "upload-token"},
        }
        return httpx.Response(200, json={})

    client_with(handler).send_file(1, "Справка-AB.pdf", b"%PDF-1.4 ...", text="держите")

    assert calls == [
        ("POST", "/uploads"),
        ("POST", "/upload.do"),
        ("POST", "/messages"),
    ]


def test_upload_without_a_url_is_reported_rather_than_crashing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    with pytest.raises(MaxApiError) as error:
        client_with(handler).upload_file("a.pdf", b"x")
    assert error.value.code == "no.upload.url"


# --- ошибки, найденные при живом запуске ------------------------------------


def test_button_tap_identifies_the_person_not_the_bot():
    """В событии о нажатии ``message`` — сообщение, отправленное ботом.

    Брать собеседника из ``message.sender`` нельзя: получится идентификатор
    самого бота, и ответ упрётся в 403 chat.denied. Именно это и случилось.
    """
    update = parse_update(
        {
            "update_type": "message_callback",
            "callback": {
                "callback_id": "cb-1",
                "payload": "tok|ans|rights_obj:true",
                "user": {"user_id": 7256433, "first_name": "Мария"},
            },
            "message": {
                # Сообщение с кнопкой отправлено ботом.
                "sender": {"user_id": 234747847, "first_name": "Бот", "is_bot": True},
                "recipient": {"user_id": 7256433},
                "body": {"mid": "mid-1", "text": "Вопрос 1 из 5"},
            },
        }
    )
    assert update.user_id == 7256433, "собеседник — тот, кто нажал кнопку"
    assert update.user_name == "Мария"


def test_incoming_message_identifies_the_sender_not_the_recipient():
    """В личном диалоге получатель входящего сообщения — сам бот."""
    update = parse_update(
        {
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": 7256433, "first_name": "Мария"},
                "recipient": {"user_id": 234747847},
                "body": {"mid": "mid-2", "text": "г. Бор"},
            },
        }
    )
    assert update.user_id == 7256433


def test_sending_to_the_bot_itself_is_refused_outright():
    """Платформа отвечает на это 403 chat.denied — причина неочевидна из ответа."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"user_id": 234747847, "username": "bot"})

    client = client_with(handler)
    client.get_me()

    with pytest.raises(ValueError, match="самому боту"):
        client.send_message(234747847, "сам себе")


def test_answering_a_tap_replaces_the_message_rather_than_notifying():
    """В MAX /answers принимает message; пустое тело даёт 400 proto.payload."""
    import json

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={})

    client_with(handler).replace_message(
        "cb-1", "Вопрос 2 из 5", keyboard=[[{"type": "callback", "text": "Да", "payload": "p"}]]
    )

    assert seen["params"] == {"callback_id": "cb-1"}
    assert seen["body"]["message"]["text"] == "Вопрос 2 из 5"
    assert seen["body"]["message"]["attachments"][0]["type"] == "inline_keyboard"
    assert seen["body"] != {}, "пустое тело платформа отвергает"


# --- временные отказы с кодом 4xx -------------------------------------------


def transient_then_ok(code: str, failures: int):
    """Обработчик, который отказывает заданное число раз, потом отвечает успехом."""
    state = {"left": failures}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/uploads":
            return httpx.Response(200, json={"url": "https://fu.oneme.ru/api/upload.do", "token": "t"})
        if request.url.path == "/api/upload.do":
            return httpx.Response(200, json={"token": "t"})
        if state["left"] > 0:
            state["left"] -= 1
            return httpx.Response(400, json={"code": code})
        return httpx.Response(200, json={"ok": True})

    return handler, state


def no_wait(client: MaxClient) -> list[float]:
    """Убирает настоящие паузы и записывает, сколько бот собирался ждать."""
    waited: list[float] = []
    client._sleep = waited.append
    return waited


def test_a_file_is_resent_until_the_platform_finishes_processing_it():
    """Сразу после загрузки платформа отвечает 400 attachment.not.ready."""
    handler, state = transient_then_ok("attachment.not.ready", failures=2)
    client = client_with(handler)
    waited = no_wait(client)

    result = client.send_file(1, "Справка-AB.pdf", b"%PDF-1.4", text="держите")

    assert result == {"ok": True}
    assert state["left"] == 0
    assert len(waited) == 2, "две неудачи — две паузы"
    assert waited == sorted(waited), "паузы нарастают"


def test_the_first_message_is_retried_while_the_dialog_is_not_ready_yet():
    """Сразу после открытия бота первые отправки отвергаются 403 chat.denied."""
    handler, _ = transient_then_ok("chat.denied", failures=2)
    client = client_with(handler)
    no_wait(client)

    assert client.send_message(1, "Здравствуйте") == {"ok": True}


def test_a_permanent_refusal_is_not_retried():
    """Повторять «нет такого чата» бессмысленно — это не временный отказ."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(404, json={"code": "chat.not.found"})

    client = client_with(handler)
    no_wait(client)

    with pytest.raises(MaxApiError):
        client.send_message(1, "текст")
    assert calls["count"] == 1


def test_a_stubbornly_unready_attachment_eventually_gives_up():
    """Бесконечно ждать нельзя: пользователю надо сказать, что файл не дошёл."""
    handler, _ = transient_then_ok("attachment.not.ready", failures=99)
    client = client_with(handler)
    waited = no_wait(client)

    with pytest.raises(MaxApiError) as error:
        client.send_file(1, "a.pdf", b"x")

    assert error.value.code == "attachment.not.ready"
    assert len(waited) == 4, "попытки не бесконечны"
