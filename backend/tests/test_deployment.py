"""Поведение, от которого зависит развёртывание на платформе.

Ошибки в этой части не видны в разработке и проявляются только в продуктивной
среде, поэтому проверяются отдельно.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import INSECURE_PASSWORD, INSECURE_SECRET, Settings
from app.main import mount_frontend

SAFE = {"secret_key": "s" * 40, "bootstrap_operator_password": "Str0ng-Pass-1"}


def settings(monkeypatch, url: str, **overrides) -> Settings:
    # Переменные окружения могли остаться от conftest — иначе проверка
    # обязательных секретов не сработает.
    for name in ("APP_DATABASE_URL", "DATABASE_URL", "APP_SECRET_KEY",
                 "APP_BOOTSTRAP_OPERATOR_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    return Settings(database_url=url, _env_file=None, **overrides)


# --- строка подключения -----------------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        # Railway и Heroku выдают URL без драйвера, а старые плагины — postgres://.
        ("postgresql://u:p@db.railway.internal:5432/railway",
         "postgresql+psycopg://u:p@db.railway.internal:5432/railway"),
        ("postgres://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        # Уже указанный драйвер не трогаем.
        ("postgresql+psycopg://u:p@host:5432/db", "postgresql+psycopg://u:p@host:5432/db"),
        ("sqlite:///./dev.db", "sqlite:///./dev.db"),
    ],
)
def test_database_url_gets_an_explicit_driver(monkeypatch, given, expected):
    assert settings(monkeypatch, given, **SAFE).database_url == expected


def test_platform_database_url_is_picked_up_without_the_app_prefix(monkeypatch):
    for name in ("APP_DATABASE_URL", "APP_SECRET_KEY", "APP_BOOTSTRAP_OPERATOR_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host:5432/railway")
    monkeypatch.setenv("APP_SECRET_KEY", SAFE["secret_key"])
    monkeypatch.setenv("APP_BOOTSTRAP_OPERATOR_PASSWORD", SAFE["bootstrap_operator_password"])

    assert Settings(_env_file=None).database_url == "postgresql+psycopg://u:p@host:5432/railway"


def test_explicit_setting_wins_over_the_platform_variable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://platform/db")
    monkeypatch.setenv("APP_DATABASE_URL", "sqlite:///./chosen.db")
    assert Settings(_env_file=None).database_url == "sqlite:///./chosen.db"


# --- отказ подниматься с учебными секретами ---------------------------------


def test_deployment_refuses_to_start_with_the_default_secret(monkeypatch):
    with pytest.raises(ValueError) as error:
        settings(monkeypatch, "postgresql://u:p@host:5432/db")

    message = str(error.value)
    assert "APP_SECRET_KEY" in message
    assert "APP_BOOTSTRAP_OPERATOR_PASSWORD" in message
    # Подсказка своя у каждой переменной: ключ генерируется, пароль придумывается.
    assert "token_urlsafe" in message
    assert "не короче 8 символов" in message


def test_deployment_names_only_the_missing_variable(monkeypatch):
    """Именно этот случай встретился на платформе: ключ задан, пароль забыт."""
    with pytest.raises(ValueError) as error:
        settings(monkeypatch, "postgresql://u:p@host:5432/db", secret_key="s" * 40)

    message = str(error.value)
    assert "APP_BOOTSTRAP_OPERATOR_PASSWORD" in message
    assert "APP_SECRET_KEY" not in message
    # Совет генерировать ключ здесь неуместен — не хватает пароля.
    assert "token_urlsafe" not in message


def test_local_sqlite_run_needs_no_secrets(monkeypatch):
    local = settings(monkeypatch, "sqlite:///./dev.db")
    assert local.secret_key == INSECURE_SECRET
    assert local.bootstrap_operator_password == INSECURE_PASSWORD


def test_deployment_starts_once_secrets_are_set(monkeypatch):
    assert settings(monkeypatch, "postgresql://u:p@host:5432/db", **SAFE).secret_key == "s" * 40


# --- отдача фронтенда -------------------------------------------------------


@pytest.fixture
def spa(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><title>Портал</title>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.ico").write_bytes(b"icon")

    application = FastAPI()

    @application.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    mount_frontend(application, tmp_path)
    return TestClient(application)


def test_api_keeps_working_when_the_frontend_is_mounted(spa):
    assert spa.get("/api/health").json() == {"status": "ok"}


def test_unknown_api_path_stays_a_json_404(spa):
    """Иначе клиент получил бы HTML вместо описания ошибки и не смог его разобрать."""
    response = spa.get("/api/nothing-here")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("path", ["/", "/cases", "/cases/2f1c-4d", "/admin/rules"])
def test_browser_routes_return_the_application_shell(spa, path):
    response = spa.get(path)
    assert response.status_code == 200
    assert "Портал" in response.text


def test_real_files_are_served_as_themselves(spa):
    assert spa.get("/assets/app.js").status_code == 200
    assert spa.get("/favicon.ico").content == b"icon"


@pytest.mark.parametrize("path", ["/../config.py", "/..%2f..%2fsecret", "/assets/../../etc/passwd"])
def test_paths_cannot_escape_the_static_directory(spa, path):
    """Путь приходит из запроса, поэтому выход за каталог обязан упираться в оболочку."""
    response = spa.get(path)
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert "Портал" in response.text
