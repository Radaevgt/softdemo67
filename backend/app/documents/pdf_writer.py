"""Отрисовка протокола в PDF — неизменяемый файл для архива и подписи."""
from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph as PdfParagraph,
    SimpleDocTemplate,
    Spacer,
    Table as PdfTable,
    TableStyle,
)

from .fonts import ensure_registered
from .layout import Document, Paragraph, Steps, Table

MARGIN = 18 * mm
CONTENT_WIDTH = A4[0] - 2 * MARGIN

INK = colors.HexColor("#16202E")
SOFT = colors.HexColor("#4A5769")
LINE = colors.HexColor("#C3CBD8")
WARNING = colors.HexColor("#A32B2B")
HEADER_BG = colors.HexColor("#F4F6FA")


def _escape(text: str) -> str:
    """reportlab разбирает текст абзаца как мини-разметку."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _styles(regular: str, bold: str) -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "body", fontName=regular, fontSize=9.5, leading=13.5, textColor=INK, spaceAfter=4
    )
    return {
        "title": ParagraphStyle(
            "title", parent=base, fontName=bold, fontSize=13, leading=17,
            alignment=TA_CENTER, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base, fontSize=9, textColor=SOFT,
            alignment=TA_CENTER, spaceAfter=14,
        ),
        "section": ParagraphStyle(
            "section", parent=base, fontName=bold, fontSize=11.5, leading=15,
            spaceBefore=14, spaceAfter=6,
        ),
        # Ключи совпадают со значениями Paragraph.emphasis.
        "normal": base,
        "lead": ParagraphStyle("lead", parent=base, fontName=bold, spaceBefore=8),
        "note": ParagraphStyle("note", parent=base, fontSize=8.5, textColor=SOFT, leading=12),
        "warning": ParagraphStyle("warning", parent=base, fontName=bold, textColor=WARNING),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9, leading=12, spaceAfter=0),
        "cellBold": ParagraphStyle(
            "cellBold", parent=base, fontName=bold, fontSize=9, leading=12, spaceAfter=0
        ),
        "step": ParagraphStyle("step", parent=base, leftIndent=14, spaceAfter=3),
        "signature": ParagraphStyle("signature", parent=base, spaceBefore=16),
    }


def _table(block: Table, styles: dict) -> PdfTable:
    columns = len(block.header) if block.header else max(len(row) for row in block.rows)
    widths = block.widths or [1 / columns] * columns
    data: list[list] = []

    if block.header:
        data.append([PdfParagraph(_escape(title), styles["cellBold"]) for title in block.header])

    for row in block.rows:
        # Подпись поля выделяется только в таблице «поле — значение».
        first = styles["cellBold"] if not block.header else styles["cell"]
        data.append(
            [
                PdfParagraph(_escape(value), first if index == 0 else styles["cell"])
                for index, value in enumerate(row)
            ]
        )

    table = PdfTable(data, colWidths=[CONTENT_WIDTH * width for width in widths], repeatRows=1 if block.header else 0)
    commands = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if block.header:
        commands.append(("BACKGROUND", (0, 0), (-1, 0), HEADER_BG))
    table.setStyle(TableStyle(commands))
    return table


def render(source: Document) -> bytes:
    regular, bold = ensure_registered()
    styles = _styles(regular, bold)

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=source.title,
    )

    flow: list = [
        PdfParagraph(_escape(source.title), styles["title"]),
        PdfParagraph(_escape(source.subtitle), styles["subtitle"]),
    ]

    for section in source.sections:
        if section.title:
            flow.append(PdfParagraph(_escape(section.title), styles["section"]))

        for block in section.blocks:
            if isinstance(block, Paragraph):
                flow.append(PdfParagraph(_escape(block.text), styles[block.emphasis]))
            elif isinstance(block, Table):
                flow.append(Spacer(1, 4))
                flow.append(_table(block, styles))
                flow.append(Spacer(1, 6))
            elif isinstance(block, Steps):
                number = 0
                for step in block.items:
                    if step.kind == "header":
                        flow.append(PdfParagraph(_escape(step.text), styles["lead"]))
                        continue
                    number += 1
                    flow.append(
                        PdfParagraph(f"{number}. {_escape(step.text)}", styles["step"])
                    )

    if source.signature_lines:
        flow.append(Spacer(1, 10))
        for line in source.signature_lines:
            flow.append(PdfParagraph(_escape(line), styles["signature"]))

    document.build(flow)
    return buffer.getvalue()
