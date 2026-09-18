"""Сценарий разговора бота. Ни сети, ни базы — логика разговора чистая."""
import pytest

from bot import keyboards, texts
from bot.flow import Event, handle
from bot.keyboards import Action
from bot.session import Session, Step


class Dialog:
    """Прогоняет разговор и даёт смотреть на последний ответ."""

    def __init__(self, user_name: str = "Иванова Мария Петровна") -> None:
        self.session = Session(user_id=42, user_name=user_name)
        self.replies = []

    def send(self, text: str) -> "Dialog":
        self.replies = handle(self.session, Event(text=text)).replies
        return self

    def start(self) -> "Dialog":
        self.replies = handle(self.session, Event(is_start=True)).replies
        return self

    def tap(self, action: str, value: str = "", *, token: str | None = None) -> "Dialog":
        tap = keyboards.Tap(token=token or self.session.step_token, action=action, value=value)
        self.replies = handle(self.session, Event(tap=tap, callback_id="cb-1")).replies
        return self

    # --- разбор ответа ------------------------------------------------------

    @property
    def texts(self) -> list[str]:
        return [r.text for r in self.replies if r.kind == "text"]

    @property
    def last_text(self) -> str:
        return self.texts[-1] if self.texts else ""

    @property
    def buttons(self) -> list[str]:
        for reply in reversed(self.replies):
            if reply.kind == "text" and reply.keyboard:
                return [b["text"] for row in reply.keyboard for b in row]
        return []

    @property
    def notifications(self) -> list[str]:
        """В MAX нет всплывающих уведомлений — замечание идёт первой строкой."""
        return self.texts

    @property
    def files(self) -> list[str]:
        return [r.document_format for r in self.replies if r.kind == "file"]

    def answer_payloads(self) -> list[str]:
        for reply in reversed(self.replies):
            if reply.kind == "text" and reply.keyboard:
                return [
                    b["payload"] for row in reply.keyboard for b in row
                    if b["payload"].split("|")[1] == Action.ANSWER
                ]
        return []

    def answer(self, value: str) -> "Dialog":
        """Отвечает на текущий вопрос значением вида ``true`` / ``dead``."""
        payloads = self.answer_payloads()
        for payload in payloads:
            if payload.rsplit(":", 1)[1] == value:
                _, action, data = payload.split("|", 2)
                return self.tap(action, data)
        raise AssertionError(f"нет варианта {value!r} среди {payloads}")


def filled(kind: str = "izhs", states: tuple[str, ...] = ("ownerless",)) -> Dialog:
    """Доводит разговор до первого вопроса опроса."""
    dialog = Dialog().start().tap(Action.START)
    dialog.send("Иванова Мария Петровна")
    dialog.send("г. Бор, ул. Полевая, д. 2")
    dialog.send("Городской округ город Бор")
    dialog.tap(Action.KIND, kind)
    for state in states:
        dialog.tap(Action.STATE, state)
    dialog.tap(Action.STATES_DONE)
    dialog.send("52:20:0100021:56")
    dialog.tap(Action.SKIP)
    dialog.tap(Action.CONFIRM)
    return dialog


# --- начало -----------------------------------------------------------------


def test_greeting_offers_to_open_a_case():
    dialog = Dialog().start()
    assert texts.BTN_START in dialog.buttons
    assert "нигде не сохраняются" in dialog.last_text


def test_any_text_before_the_case_shows_the_greeting():
    dialog = Dialog().send("привет")
    assert texts.BTN_START in dialog.buttons


# --- сбор сведений ----------------------------------------------------------


def test_case_starts_by_asking_who_is_running_the_check():
    dialog = Dialog().start().tap(Action.START)
    assert dialog.session.step == Step.FULL_NAME
    assert "фамилия, имя и отчество" in dialog.last_text
    # На первом шаге возвращаться некуда.
    assert texts.BTN_BACK not in dialog.buttons


def test_the_full_name_is_remembered_and_the_address_comes_next():
    dialog = Dialog().start().tap(Action.START).send("Иванова Мария Петровна")
    assert dialog.session.full_name == "Иванова Мария Петровна"
    assert dialog.session.step == Step.ADDRESS


def test_states_are_multi_select_with_visible_marks():
    dialog = Dialog().start().tap(Action.START)
    dialog.send("Иванова М. П.").send("адрес").send("МО").tap(Action.KIND, "izhs")

    dialog.tap(Action.STATE, "ownerless")
    assert f"{texts.CHECKED} Бесхозяйное" in dialog.buttons

    dialog.tap(Action.STATE, "fpo")
    assert dialog.session.states == ["ownerless", "fpo"]

    # Повторное нажатие снимает отметку.
    dialog.tap(Action.STATE, "ownerless")
    assert dialog.session.states == ["fpo"]
    assert f"{texts.UNCHECKED} Бесхозяйное" in dialog.buttons


def test_done_without_a_state_does_not_advance():
    dialog = Dialog().start().tap(Action.START)
    dialog.send("Иванова М. П.").send("адрес").send("МО").tap(Action.KIND, "izhs")
    dialog.tap(Action.STATES_DONE)

    assert texts.NEED_ONE_STATE in dialog.last_text
    assert dialog.session.step == Step.STATES


def test_optional_fields_can_be_skipped():
    dialog = filled()
    assert dialog.session.cadastre_land is None
    assert dialog.session.cadastre_oks == "52:20:0100021:56"


def test_summary_lists_everything_before_the_questionnaire():
    dialog = Dialog().start().tap(Action.START)
    dialog.send("Иванова Мария Петровна").send("г. Бор, ул. Полевая, д. 2")
    dialog.send("Городской округ город Бор")
    dialog.tap(Action.KIND, "izhs").tap(Action.STATE, "ownerless").tap(Action.STATES_DONE)
    dialog.tap(Action.SKIP).tap(Action.SKIP)

    assert dialog.session.step == Step.CONFIRM
    assert "Иванова Мария Петровна" in dialog.last_text
    assert "г. Бор, ул. Полевая, д. 2" in dialog.last_text
    assert "ИЖС" in dialog.last_text
    assert "Бесхозяйное" in dialog.last_text


# --- опрос ------------------------------------------------------------------


def test_questions_carry_the_source_of_the_answer():
    dialog = filled()
    # Подсказка говорит, из какого документа читать ответ.
    assert "Откуда берутся сведения" in dialog.last_text
    assert "ЕГРН" in dialog.last_text


def test_counter_grows_when_death_adds_the_heirs_question():
    dialog = filled()
    assert "из 5" in dialog.last_text

    dialog.answer("true").answer("true").answer("dead")
    assert "из 6" in dialog.last_text


def test_nonresidential_is_never_asked_about_registered_citizens():
    dialog = filled(kind="nonresidential", states=("fpo",))
    dialog.answer("true").answer("true").answer("alive").answer("true")

    assert "registered_citizens" not in dialog.session.answers
    assert dialog.files, "опрос завершён, справка выдана"


def test_living_owner_is_never_asked_about_heirs():
    dialog = filled()
    dialog.answer("true").answer("true").answer("alive").answer("true").answer("false")

    assert "heirs" not in dialog.session.answers
    assert dialog.files


def test_changing_the_owner_back_to_alive_drops_the_heirs_answer():
    """Контракт prune: устаревший ответ не должен попасть в доказательную базу."""
    dialog = filled()
    dialog.answer("true").answer("true").answer("dead").answer("false").answer("false")
    dialog.answer("true")  # наследники есть
    assert dialog.session.answers["heirs"] is True

    # Возвращаемся и меняем статус правообладателя на «жив».
    dialog.tap(Action.BACK)  # снимает heirs
    dialog.tap(Action.BACK)  # снимает registered_citizens
    dialog.tap(Action.BACK)  # снимает taxpayer
    dialog.tap(Action.BACK)  # снимает owner_status
    dialog.answer("alive")

    assert "heirs" not in dialog.session.answers


def test_back_from_the_first_question_returns_to_the_input_steps():
    dialog = filled()
    dialog.tap(Action.BACK)
    assert dialog.session.step == Step.CONFIRM


def test_edit_returns_to_the_first_input_step():
    dialog = Dialog().start().tap(Action.START)
    dialog.send("Иванова М. П.").send("адрес").send("МО").tap(Action.KIND, "izhs")
    dialog.tap(Action.STATE, "ownerless").tap(Action.STATES_DONE)
    dialog.tap(Action.SKIP).tap(Action.SKIP).tap(Action.EDIT)

    assert dialog.session.step == Step.FULL_NAME


# --- сброс и устаревшие кнопки ----------------------------------------------


def test_restart_asks_for_confirmation_first():
    dialog = filled()
    dialog.tap(Action.RESTART)
    assert texts.BTN_RESTART_YES in dialog.buttons
    assert dialog.session.address is not None, "до подтверждения ничего не теряется"

    dialog.tap(Action.RESTART_YES)
    assert dialog.session.address is None
    assert dialog.session.step == Step.FULL_NAME


def test_declining_the_restart_returns_to_the_same_question():
    dialog = filled()
    before = dialog.session.answers.copy()
    dialog.tap(Action.RESTART).tap(Action.RESTART_NO)

    assert dialog.session.answers == before
    assert dialog.session.step == Step.QUESTION


def test_tapping_a_scrolled_up_button_does_not_move_the_questionnaire():
    """Пользователь прокрутил вверх и нажал кнопку под старым вопросом."""
    dialog = filled()
    stale = dialog.session.step_token
    dialog.answer("true")

    dialog.tap(Action.ANSWER, "rights_obj:false", token=stale)
    assert texts.BUTTON_EXPIRED in dialog.last_text
    assert dialog.session.answers == {"rights_obj": True}


def test_start_mid_case_offers_to_resume():
    dialog = filled()
    dialog.start()

    assert texts.BTN_RESUME in dialog.buttons
    assert "Полевая" in dialog.last_text
    assert dialog.session.answers == {}, "предложение продолжить ничего не стирает"


# --- результат --------------------------------------------------------------


def test_full_path_produces_a_spravka_with_the_scenario():
    dialog = filled()
    dialog.answer("true").answer("true").answer("dead")
    dialog.answer("false").answer("false").answer("false")

    summary = "\n".join(dialog.texts)
    assert "Сценарий № 1" in summary
    assert "Признание права муниципальной собственности" in summary
    assert dialog.files == ["pdf"] or dialog.files == ["docx"]
    assert dialog.session.step == Step.RESULT


def test_two_states_give_two_outcomes_in_priority_order():
    dialog = filled(states=("ownerless", "fpo"))
    dialog.answer("true").answer("true").answer("dead")
    dialog.answer("false").answer("false").answer("false")

    outcomes = [o["state"] for o in dialog.session.decision["outcomes"]]
    assert outcomes == ["fpo", "ownerless"], "угроза жизни впереди оформления права"
    assert "Демонтаж остаточных элементов" in "\n".join(dialog.texts)


def test_uncovered_combination_is_marked_preliminary_with_nearest_scenarios():
    """Бесхозяйное ИЖС с живым правообладателем в матрице ТЗ не описано."""
    dialog = filled()
    dialog.answer("true").answer("true").answer("alive").answer("true").answer("false")

    summary = "\n".join(dialog.texts)
    assert dialog.session.decision["needs_review"] is True
    assert "предварительный характер" in summary
    assert "Ближайший сценарий" in summary
    # Расхождение названо словами, а не кодом признака.
    assert "Статус правообладателя" in summary


def test_result_offers_the_second_format_and_a_new_case():
    dialog = filled()
    dialog.answer("true").answer("true").answer("dead")
    dialog.answer("false").answer("false").answer("false")

    assert texts.BTN_NEW_CASE in dialog.buttons


@pytest.mark.parametrize("kind", ["izhs", "mkd_apartment", "nonresidential"])
def test_questionnaire_terminates_for_every_object_kind(kind):
    dialog = filled(kind=kind, states=("ownerless",))
    for _ in range(len(dialog.answer_payloads()) + 8):
        payloads = dialog.answer_payloads()
        if not payloads:
            break
        _, action, data = payloads[0].split("|", 2)
        dialog.tap(action, data)
    else:
        pytest.fail("опрос не завершился")

    assert dialog.files, f"для {kind} справка не сформирована"


# --- инструкция -------------------------------------------------------------


def test_instruction_covers_the_whole_path():
    from bot.texts import help_text
    from bot.transport import MAX_TEXT_LENGTH

    text = help_text()

    assert len(text) <= MAX_TEXT_LENGTH, f"инструкция {len(text)} символов"
    for heading in ("КАК ПОЛЬЗОВАТЬСЯ", "ШАГ 1", "ШАГ 2", "ШАГ 3", "ЕСЛИ СЦЕНАРИЯ НЕТ", "КНОПКИ"):
        assert heading in text, f"нет раздела «{heading}»"

    # Что подготовить заранее и чем закончится.
    assert "акт обследования" in text
    assert "нигде не сохраняется" in text


def test_instruction_lists_every_question_with_its_source():
    """Перечень собирается из самого опроса — разойтись с вопросами он не может."""
    from app.engine.attributes import ATTRIBUTES
    from bot.texts import help_text

    text = help_text()
    for attribute in ATTRIBUTES:
        assert attribute.label in text, f"нет вопроса «{attribute.label}»"
        # Источник сведений — самое ценное в инструкции.
        assert attribute.source_hint[:24].lower() in text.lower()


def test_help_button_shows_the_instruction():
    dialog = Dialog().start().tap(Action.HELP)
    assert "КАК ПОЛЬЗОВАТЬСЯ" in dialog.last_text
    assert texts.BTN_START in dialog.buttons, "после инструкции можно сразу завести дело"
