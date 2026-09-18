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
