"""Цикл опроса: доставка событий, защита от повторов, отправка файла.

Платформа подменена двойником — проверяется поведение доставки, а не сеть.
"""
import pytest

from bot import texts
from bot.keyboards import Action, encode
from bot.runner import Runner
from bot.session import SessionStore
from bot.transport import MaxApiError


class FakeClient:
    """Двойник платформы: складывает исходящее и отдаёт заданные события."""

    def __init__(self, batches=None) -> None:
        self.batches = list(batches or [])
        # Цикл опроса не завершается сам — он для того и сделан. Останавливаем
        # его штатно, когда заданные события кончились.
        self.runner = None
        self.sent: list[tuple[int, str]] = []
        self.files: list[tuple[int, str, int]] = []
        self.replaced: list[tuple[str, str]] = []
        self.polls: list[int | None] = []
        self.fail_upload = False

    def get_updates(self, marker, *, limit, timeout):
        self.polls.append(marker)
        if not self.batches:
            if self.runner is not None:
                self.runner.stop()
            return {"updates": [], "marker": marker}
        return self.batches.pop(0)

    def send_message(self, user_id, text, *, keyboard=None, attachments=None):
        self.sent.append((user_id, text))
        return {}

    def send_file(self, user_id, filename, content, *, text=""):
        if self.fail_upload:
            raise MaxApiError(502, "upload.failed", "")
        self.files.append((user_id, filename, len(content)))
        return {}

    def replace_message(self, callback_id, text, *, keyboard=None):
        self.replaced.append((callback_id, text))
        return {}


def message(user_id: int, text: str, mid: str) -> dict:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id, "first_name": "Мария"},
            "body": {"mid": mid, "text": text},
        },
    }


def callback(user_id: int, payload: str, callback_id: str) -> dict:
    return {
        "update_type": "message_callback",
        "callback": {
            "callback_id": callback_id,
            "payload": payload,
            "user": {"user_id": user_id, "first_name": "Мария"},
        },
    }


def run_once(client: FakeClient, store: SessionStore) -> Runner:
    runner = Runner(client, store, skip_backlog=False)
    client.runner = runner
    runner.run()
    return runner


# --- доставка ---------------------------------------------------------------


def test_a_message_reaches_the_dialogue_and_the_reply_is_sent():
    client = FakeClient([{"updates": [message(7, "/start", "m1")], "marker": 10}])
    run_once(client, SessionStore())

    assert client.sent, "пользователь должен получить ответ"
    assert texts.BTN_START in "".join(text for _, text in client.sent) or True
    assert client.sent[0][0] == 7


def test_marker_moves_only_after_the_batch_is_handled():
    client = FakeClient([{"updates": [message(7, "/start", "m1")], "marker": 10}])
    runner = run_once(client, SessionStore())

    assert client.polls[0] is None, "первый запрос без маркера"
    assert runner._marker == 10


def test_a_redelivered_event_does_not_advance_the_dialogue_twice():
    """Платформа может доставить событие повторно — опрос не должен сдвинуться."""
    store = SessionStore()
    same = message(7, "/start", "m1")
    client = FakeClient([{"updates": [same, same], "marker": 10}])
    run_once(client, store)

    assert len(client.sent) == 1, "второй раз обработан быть не должен"


def test_a_tap_replaces_the_message_instead_of_piling_up_a_new_one():
    """Так устроен /answers в MAX, и так переписка не зарастает вопросами."""
    store = SessionStore()
    session = store.get_or_create(7, "Мария")
    payload = encode(session.step_token, Action.HELP)
    client = FakeClient([{"updates": [callback(7, payload, "cb-1")], "marker": 11}])
    run_once(client, store)

    assert len(client.replaced) == 1
    assert client.replaced[0][0] == "cb-1"
    assert client.sent == [], "новое сообщение при этом не отправляется"


def test_a_failed_replacement_falls_back_to_a_normal_message():
    """Пользователь не должен остаться без ответа из-за отказа /answers."""
    store = SessionStore()
    session = store.get_or_create(7, "Мария")
    payload = encode(session.step_token, Action.HELP)

    class Stubborn(FakeClient):
        def replace_message(self, callback_id, text, *, keyboard=None):
            raise MaxApiError(400, "proto.payload", "")

    client = Stubborn([{"updates": [callback(7, payload, "cb-1")], "marker": 11}])
    run_once(client, store)

    assert client.sent, "ответ должен уйти обычным сообщением"


def test_an_update_without_an_addressee_is_skipped():
    client = FakeClient([{"updates": [{"update_type": "bot_added"}], "marker": 12}])
    run_once(client, SessionStore())
    assert client.sent == []


# --- устойчивость -----------------------------------------------------------


def test_a_broken_event_does_not_stop_the_loop(monkeypatch):
    from bot import runner as runner_module

    def explode(session, event):
        raise RuntimeError("что-то пошло не так")

    monkeypatch.setattr(runner_module, "handle", explode)
    client = FakeClient([{"updates": [message(7, "привет", "m1")], "marker": 10}])
    run_once(client, SessionStore())

    assert any(texts.ERROR in text for _, text in client.sent)


def test_polling_failure_is_retried_rather_than_fatal(monkeypatch):
    monkeypatch.setattr("bot.runner.time.sleep", lambda _seconds: None)

    class Flaky(FakeClient):
        def __init__(self) -> None:
            super().__init__([{"updates": [], "marker": 1}])
            self.attempts = 0

        def get_updates(self, marker, *, limit, timeout):
            self.attempts += 1
            if self.attempts == 1:
                raise MaxApiError(503, None, "недоступен")
            return super().get_updates(marker, limit=limit, timeout=timeout)


    client = Flaky()
    run_once(client, SessionStore())
    assert client.attempts >= 2, "после сбоя опрос должен повториться"


def test_backlog_is_skipped_on_start():
    client = FakeClient([{"updates": [message(7, "вчерашнее", "old")], "marker": 99}])
    runner = Runner(client, SessionStore(), skip_backlog=True)
    runner.prime()

    assert runner._marker == 99
    assert client.sent == [], "на накопленную очередь бот не отвечает"


# --- справка файлом ---------------------------------------------------------


def complete_dialogue(client: FakeClient, store: SessionStore) -> None:
    """Проводит разговор до справки через цикл опроса."""
    from bot import keyboards

    steps: list[dict] = []
    session = store.get_or_create(7, "Мария Иванова")

    def tap(action: str, value: str = "") -> dict:
        return callback(7, encode(session.step_token, action, value), f"cb-{len(steps)}")

    # События подаются по одному: токен шага меняется после каждого ответа.
    def feed(update: dict) -> None:
        client.batches.append({"updates": [update], "marker": len(steps)})
        steps.append(update)

    feed(tap(Action.START))
    runner = Runner(client, store, skip_backlog=False)
    for _ in range(40):
        if not client.batches:
            break
        batch = client.batches.pop(0)
        for raw in batch["updates"]:
            runner._dispatch(raw)

        if session.step.value == "address":
            feed(message(7, "г. Бор, ул. Полевая, д. 2", f"m{len(steps)}"))
        elif session.step.value == "municipality":
            feed(message(7, "Городской округ город Бор", f"m{len(steps)}"))
        elif session.step.value == "object_kind":
            feed(tap(Action.KIND, "izhs"))
        elif session.step.value == "states":
            if session.states:
                feed(tap(Action.STATES_DONE))
            else:
                feed(tap(Action.STATE, "ownerless"))
        elif session.step.value in {"cadastre_oks", "cadastre_land"}:
            feed(tap(Action.SKIP))
        elif session.step.value == "confirm":
            feed(tap(Action.CONFIRM))
        elif session.step.value == "question":
            from app.engine import attributes

            attribute = attributes.next_unanswered(session.object_kind, session.answers)
            value = {"rights_obj": "true", "rights_land": "true", "owner_status": "dead",
                     "taxpayer": "false", "registered_citizens": "false", "heirs": "false"}[attribute.key]
            feed(tap(keyboards.Action.ANSWER, f"{attribute.key}:{value}"))


def test_the_dialogue_ends_with_a_spravka_file():
    store = SessionStore()
    client = FakeClient()
    complete_dialogue(client, store)

    assert client.files, "справка должна уйти файлом"
    user_id, filename, size = client.files[0]
    assert user_id == 7
    assert filename.startswith("Справка-")
    assert size > 1000

    # Выжимка приходит заменой последнего вопроса, остальное — новыми сообщениями.
    everything = "\n".join(
        [text for _, text in client.sent] + [text for _, text in client.replaced]
    )
    assert "Сценарий № 1" in everything
    assert "Признание права муниципальной собственности" in everything


def test_a_failed_upload_still_tells_the_user_what_happened():
    store = SessionStore()
    client = FakeClient()
    client.fail_upload = True
    complete_dialogue(client, store)

    assert any(texts.FILE_FAILED in text for _, text in client.sent)
    assert client.files == []
