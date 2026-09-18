"""Справка бота: выжимка в чат и файл, собранные из одного снимка решения."""
import zipfile
from io import BytesIO

import pytest
from pypdf import PdfReader

from bot import spravka
from bot.decide import decide
from bot.session import Session
from bot.transport import MAX_TEXT_LENGTH
from app.seed.loader import seed_rules

ANSWERS = {
    "rights_obj": True,
    "rights_land": True,
    "owner_status": "dead",
    "taxpayer": False,
    "registered_citizens": False,
    "heirs": False,
}


def session_for(states=("ownerless",), kind="izhs") -> Session:
    return Session(
        user_id=1,
        full_name="Иванова Мария Петровна",
        address="г. Бор, ул. Полевая, д. 2",
        municipality="Городской округ город Бор",
        object_kind=kind,
        states=list(states),
        cadastre_oks="52:20:0100021:56",
        answers=dict(ANSWERS),
    )


def decided(session: Session) -> dict:
    decision = decide(session.object_kind, session.states, session.answers)
    session.decision = decision.to_dict()
    return session.decision


def docx_text(payload: bytes) -> str:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


# --- определение без базы ---------------------------------------------------


def test_decide_matches_the_tz_matrix_without_a_database():
    session = session_for()
    decision = decided(session)

    assert decision["needs_review"] is False
    assert decision["outcomes"][0]["scenario_num"] == 1
    assert decision["ruleset_version"]


def test_two_states_resolve_in_priority_order():
    session = session_for(states=("ownerless", "fpo"))
    decision = decided(session)
    assert [o["state"] for o in decision["outcomes"]] == ["fpo", "ownerless"]


# --- файл -------------------------------------------------------------------


def test_file_carries_the_object_answers_and_procedure():
    session = session_for()
    decision = decided(session)
    assessment = spravka.build_assessment(session, decision)
    rendered = spravka.render_file(assessment, "docx")

    text = docx_text(rendered.content)
    assert "СПРАВКА" in text
    assert "Полевая" in text
    assert "52:20:0100021:56" in text
    assert "Городской округ город Бор" in text
    # Источник сведений по каждому признаку — это доказательная часть.
    assert "Справка о смерти" in text
    assert "Признание права муниципальной собственности" in text
    assert "Иванова Мария Петровна" in text


def test_file_is_named_as_a_spravka_not_a_protocol():
    session = session_for()
    assessment = spravka.build_assessment(session, decided(session))
    rendered = spravka.render_file(assessment, "docx")
    assert rendered.filename.startswith("Справка-")


def test_pdf_renders_cyrillic():
    if "pdf" not in spravka.available_formats():
        pytest.skip("в окружении нет шрифта с кириллицей")

    session = session_for()
    assessment = spravka.build_assessment(session, decided(session))
    rendered = spravka.render_file(assessment, "pdf")

    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(rendered.content)).pages)
    assert "СПРАВКА" in text
    assert "Полевая" in text


def test_missing_municipality_does_not_break_the_file():
    session = session_for()
    session.municipality = None
    assessment = spravka.build_assessment(session, decided(session))
    assert spravka.render_file(assessment, "docx").content


# --- выжимка в чат ----------------------------------------------------------


def test_chat_summary_names_the_scenario_and_the_method():
    session = session_for()
    summary = spravka.chat_summary(session, decided(session))

    assert "Сценарий № 1" in summary
    assert "Признание права муниципальной собственности" in summary
    assert "в справке" in summary, "полный порядок действий остаётся в файле"


def test_chat_summary_declines_the_word_step_correctly():
    assert spravka.plural(1, "шаг", "шага", "шагов") == "шаг"
    assert spravka.plural(2, "шаг", "шага", "шагов") == "шага"
    assert spravka.plural(5, "шаг", "шага", "шагов") == "шагов"
    assert spravka.plural(11, "шаг", "шага", "шагов") == "шагов"
    assert spravka.plural(21, "шаг", "шага", "шагов") == "шаг"


def test_chat_summary_spells_out_the_divergence_when_no_scenario_matches():
    session = session_for()
    session.answers = {
        "rights_obj": True,
        "rights_land": True,
        "owner_status": "alive",
        "taxpayer": True,
        "registered_citizens": False,
    }
    summary = spravka.chat_summary(session, decided(session))

    assert "Точный сценарий не определён" in summary
    assert "Ближайший сценарий" in summary
    assert "Статус правообладателя" in summary


@pytest.mark.parametrize("rule", seed_rules(), ids=lambda rule: rule.code)
def test_chat_summary_fits_the_platform_limit_for_every_tz_scenario(rule):
    """Сообщение в MAX — не длиннее 4000 символов, а шагов бывает до 25."""
    answers = dict(rule.conditions)
    if answers.get("owner_status") == "dead_or_liquidated":
        answers["owner_status"] = "dead"

    session = Session(
        user_id=1,
        address="г. Бор, ул. Очень Длинного Наименования, д. 128, корп. 3",
        object_kind=rule.object_kind,
        states=[rule.state],
        cadastre_oks="52:20:0100021:56",
        answers=answers,
    )
    summary = spravka.chat_summary(session, decided(session))
    assert len(summary) <= MAX_TEXT_LENGTH, f"{rule.code}: выжимка {len(summary)} символов"


# --- кто проводил проверку --------------------------------------------------


def test_the_file_names_the_person_who_ran_the_check():
    """В справку идёт ФИО, введённое в диалоге, а не имя из мессенджера."""
    session = session_for()
    session.full_name = "Иванова Мария Петровна"
    session.user_name = "gorky tech"

    assessment = spravka.build_assessment(session, decided(session))
    text = docx_text(spravka.render_file(assessment, "docx").content)

    assert "Иванова Мария Петровна" in text
    assert "gorky tech" not in text, "имя из мессенджера в документ не попадает"


def test_the_messenger_name_is_only_a_last_resort():
    session = session_for()
    session.full_name = None
    session.user_name = "gorky tech"

    assessment = spravka.build_assessment(session, decided(session))
    assert assessment.author.full_name == "gorky tech"


def test_the_chat_summary_does_not_show_the_ruleset_version():
    """Отпечаток набора правил нужен в документе, а в чате это шум."""
    session = session_for()
    decision = decided(session)
    summary = spravka.chat_summary(session, decision)

    assert "Версия набора правил" not in summary
    assert decision["ruleset_version"] not in summary

    # В файле он остаётся: там это часть сведений о проведении проверки.
    text = docx_text(spravka.render_file(spravka.build_assessment(session, decision), "docx").content)
    assert "Версия набора правил" in text
