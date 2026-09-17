import os
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "change-me-in-production"
INSECURE_PASSWORD = "operator"

# Подсказка выводится в журнал платформы и часто оказывается единственным, что
# читает человек при упавшем развёртывании, — поэтому она про каждую переменную
# отдельно, а не общая.
REQUIRED_HINTS = {
    "APP_SECRET_KEY": (
        "ключ подписи токенов входа; сгенерировать: "
        'python -c "import secrets; print(secrets.token_urlsafe(48))"'
    ),
    "APP_BOOTSTRAP_OPERATOR_PASSWORD": (
        "пароль первой учётной записи оператора; не короче 8 символов, "
        "задаётся произвольно"
    ),
}

# Каталог со собранным фронтендом. Заполняется в образе; при локальной разработке
# фронтенд поднимает собственный сервер, и каталога здесь нет.
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def _normalize_database_url(url: str) -> str:
    """Приводит строку подключения к драйверу, который установлен в проекте.

    Railway, Heroku и подобные выдают URL вида ``postgresql://`` (а иногда и
    устаревший ``postgres://``), тогда как SQLAlchemy должен получить явный
    драйвер — иначе он попытается загрузить psycopg2, которого здесь нет.
    """
    for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://", "sqlite"):
        if url.startswith(prefix):
            return url
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    database_url: str = "postgresql+psycopg://portal:portal@localhost:5432/portal"
    secret_key: str = INSECURE_SECRET
    access_token_ttl_minutes: int = 12 * 60
    cors_origins: str = ""

    # Seeded on first start so the system is usable before an operator exists.
    bootstrap_operator_login: str = "operator"
    bootstrap_operator_password: str = INSECURE_PASSWORD

    # PostgreSQL schema is owned by Alembic; this is for local SQLite runs only.
    auto_create_schema: bool = False

    # Lowered only by the test suite; never reduce below 12 in a deployment.
    bcrypt_rounds: int = 12

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        # Платформы вроде Railway подставляют DATABASE_URL без префикса APP_.
        if "APP_DATABASE_URL" not in os.environ and os.environ.get("DATABASE_URL"):
            object.__setattr__(self, "database_url", os.environ["DATABASE_URL"])
        object.__setattr__(self, "database_url", _normalize_database_url(self.database_url))
        return self

    @model_validator(mode="after")
    def _refuse_insecure_deployment(self) -> "Settings":
        """Не даёт подняться с учебными секретами вне локальной разработки.

        Признак развёртывания — база не SQLite. Портал фиксирует авторство решений,
        поэтому ключ подписи токенов по умолчанию и пароль оператора «operator» —
        это не неудобство, а открытый доступ к чужим решениям.
        """
        if self.database_url.startswith("sqlite"):
            return self

        missing = []
        if self.secret_key == INSECURE_SECRET:
            missing.append("APP_SECRET_KEY")
        if self.bootstrap_operator_password == INSECURE_PASSWORD:
            missing.append("APP_BOOTSTRAP_OPERATOR_PASSWORD")

        if missing:
            raise ValueError(
                "Не заданы обязательные переменные окружения. "
                + " ".join(f"{name} — {REQUIRED_HINTS[name]}." for name in missing)
            )
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """Пусто, когда фронтенд отдаётся тем же приложением — CORS не нужен."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def serves_frontend(self) -> bool:
        return (STATIC_DIR / "index.html").exists()


@lru_cache
def get_settings() -> Settings:
    return Settings()
