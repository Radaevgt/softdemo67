"""Настройки бота.

Отдельно от ``app/config.py``: боту не нужны ни база, ни секреты портала, и
связывать их значило бы требовать PostgreSQL там, где он не используется.
"""
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Старые platform-api.max.ru и botapi.max.ru ещё отвечают, но объявлены устаревшими.
DEFAULT_API_BASE = "https://platform-api2.max.ru"


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="BOT_", extra="ignore")

    max_token: str = ""
    api_base: str = DEFAULT_API_BASE

    # Пределы платформы: timeout не больше 90, limit не больше 1000.
    poll_timeout: int = 90
    poll_limit: int = 100

    # При первом старте накопленная очередь пропускается, иначе демонстрацию
    # завалит вчерашними сообщениями.
    skip_backlog: bool = True

    # Сколько держать брошенный диалог, прежде чем забыть его.
    session_ttl_minutes: int = 60

    log_level: str = "INFO"

    @model_validator(mode="after")
    def _require_token(self) -> "BotSettings":
        if not self.max_token:
            raise ValueError(
                "Не задан токен бота. Переменная BOT_MAX_TOKEN — токен, выданный "
                "@MasterBot в мессенджере MAX."
            )
        return self


@lru_cache
def get_settings() -> BotSettings:
    return BotSettings()
