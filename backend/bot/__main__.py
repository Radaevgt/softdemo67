"""Запуск бота: ``python -m bot`` из каталога backend."""
from __future__ import annotations

import logging
import signal
import sys

from .config import get_settings
from .runner import Runner
from .session import SessionStore
from .transport import MaxApiError, MaxClient

logger = logging.getLogger("bot")


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    try:
        settings = get_settings()
    except Exception as error:
        # Настройки читаются до журнала, поэтому пишем прямо в поток ошибок.
        print(f"Бот не запущен: {error}", file=sys.stderr)
        return 2

    _setup_logging(settings.log_level)

    with MaxClient(settings.max_token, settings.api_base) as client:
        try:
            me = client.get_me()
        except MaxApiError as error:
            # Проверка токена сразу: иначе неверный токен выглядит как молчащий бот.
            logger.error("Токен не принят платформой: %s", error)
            return 2
        logger.info("Бот @%s (%s) запущен", me.get("username"), me.get("first_name"))

        store = SessionStore(ttl_minutes=settings.session_ttl_minutes)
        runner = Runner(
            client,
            store,
            poll_limit=settings.poll_limit,
            poll_timeout=settings.poll_timeout,
            skip_backlog=settings.skip_backlog,
        )

        def _stop(signum: int, _frame: object) -> None:
            logger.info("Получен сигнал %s, завершаем работу", signum)
            runner.stop()

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

        runner.prime()
        runner.run()

    logger.info("Остановлен")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
