"""Формато-независимое описание протокола проверки.

Содержание собирается один раз, а writers для .docx и .pdf только отрисовывают
готовую структуру. Иначе два формата разошлись бы по составу при первой же
правке, а протокол — доказательный документ: расхождение недопустимо.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Paragraph:
    text: str
    emphasis: str = "normal"  # normal | lead | note | warning


@dataclass
class Table:
    """Таблица «поле — значение» или произвольная с заголовком."""

    rows: list[list[str]]
    header: list[str] | None = None
    widths: list[float] | None = None


@dataclass
class Step:
    text: str
    kind: str = "action"  # action | header


@dataclass
class Steps:
    """Порядок действий: заголовки внутри не нумеруются."""

    items: list[Step]


Block = Paragraph | Table | Steps


@dataclass
class Section:
    title: str
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Document:
    title: str
    subtitle: str
    sections: list[Section] = field(default_factory=list)
    signature_lines: list[str] = field(default_factory=list)
