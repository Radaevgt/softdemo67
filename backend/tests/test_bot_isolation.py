"""Бот не должен зависеть от базы данных.

Заказчик решил ничего не хранить, поэтому боту не нужны ни PostgreSQL, ни SQLite.
Но ``app/db.py`` создаёт движок SQLAlchemy прямо при импорте и требует строку
подключения — достаточно кому-нибудь добавить в ``bot`` импорт ``app.models``, и
бот перестанет запускаться без базы.

Проверка идёт **подпроцессом**: ``tests/conftest.py`` выставляет
``APP_DATABASE_URL`` при импорте, и в общем процессе тест прошёл бы ложно.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

# Всё, что бот импортирует на рабочем пути.
BOT_MODULES = [
    "bot.config",
    "bot.tls",
    "bot.transport",
    "bot.session",
    "bot.texts",
    "bot.keyboards",
    "bot.decide",
    "bot.flow",
    "bot.spravka",
    "bot.runner",
]


def run_without_database(code: str) -> subprocess.CompletedProcess:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"APP_DATABASE_URL", "DATABASE_URL", "APP_AUTO_CREATE_SCHEMA"}
    }
    # Токен нужен только bot.config, и он не должен тянуть за собой базу.
    environment["BOT_MAX_TOKEN"] = "isolation-test-token"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("module", BOT_MODULES)
def test_module_imports_without_a_database(module):
    result = run_without_database(f"import {module}")
    assert result.returncode == 0, f"{module} требует базу:\n{result.stderr[-1500:]}"


def test_the_whole_spravka_is_produced_without_a_database():
    """Не только импорт: справка должна реально собираться."""
    code = """
from bot.decide import decide
from bot.session import Session
from bot import spravka

session = Session(
    user_id=1,
    address="г. Бор, ул. Полевая, д. 2",
    object_kind="izhs",
    states=["ownerless"],
    answers={
        "rights_obj": True, "rights_land": True, "owner_status": "dead",
        "taxpayer": False, "registered_citizens": False, "heirs": False,
    },
)
session.decision = decide(session.object_kind, session.states, session.answers).to_dict()
assessment = spravka.build_assessment(session, session.decision)
rendered = spravka.render_file(assessment, "docx")
assert rendered.content, "документ пуст"
assert "Сценарий № 1" in spravka.chat_summary(session, session.decision)
print("ok")
"""
    result = run_without_database(code)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ok" in result.stdout


def test_the_bot_never_imports_the_orm():
    """Прямая проверка правила: движок — можно, модели и сессия БД — нет."""
    code = """
import sys
import bot.flow, bot.spravka, bot.runner

forbidden = [name for name in sys.modules if name in {"app.db", "app.models", "app.services"}]
assert not forbidden, f"бот затянул {forbidden}"
assert "app.engine.matcher" in sys.modules, "движок должен переиспользоваться, а не копироваться"
print("ok")
"""
    result = run_without_database(code)
    assert result.returncode == 0, result.stderr[-2000:]
    assert "ok" in result.stdout
