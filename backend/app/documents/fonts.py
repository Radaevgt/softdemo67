"""Поиск кириллического шрифта для PDF.

Встроенные шрифты reportlab кириллицу не содержат, поэтому нужен TrueType.
Шрифт не кладётся в репозиторий: в контейнер ставится пакет fonts-dejavu-core,
на рабочих местах разработчика берётся системный Arial.
"""
from __future__ import annotations

import logging
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

REGULAR = "PortalSans"
BOLD = "PortalSans-Bold"

# Пары «обычное — полужирное». Первый найденный вариант побеждает.
CANDIDATES: tuple[tuple[str, str], ...] = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
)


class FontUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Не найден шрифт с поддержкой кириллицы для формирования PDF. "
            "Установите пакет fonts-dejavu-core."
        )


_registered = False


def ensure_registered() -> tuple[str, str]:
    """Регистрирует шрифт в reportlab и возвращает имена начертаний."""
    global _registered
    if _registered:
        return REGULAR, BOLD

    for regular, bold in CANDIDATES:
        if not Path(regular).exists():
            continue
        pdfmetrics.registerFont(TTFont(REGULAR, regular))
        # Полужирное начертание не обязательно: если его нет, используется обычное.
        bold_path = bold if Path(bold).exists() else regular
        pdfmetrics.registerFont(TTFont(BOLD, bold_path))
        pdfmetrics.registerFontFamily(REGULAR, normal=REGULAR, bold=BOLD)
        _registered = True
        logger.info("PDF-шрифт: %s", regular)
        return REGULAR, BOLD

    raise FontUnavailableError


def is_available() -> bool:
    return _registered or any(Path(regular).exists() for regular, _ in CANDIDATES)
