"""Формирование протокола проверки в .docx и .pdf."""
from __future__ import annotations

from dataclasses import dataclass

from . import builder, docx_writer, fonts, pdf_writer
from .source import AssessmentLike

DOCX = "docx"
PDF = "pdf"

FORMATS = (DOCX, PDF)

MEDIA_TYPES = {
    DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    PDF: "application/pdf",
}


@dataclass(frozen=True)
class RenderedDocument:
    format: str
    filename: str
    content: bytes


def _filename(assessment: AssessmentLike, extension: str, prefix: str) -> str:
    number = str(assessment.id).split("-")[0].upper()
    return f"{prefix}-{number}.{extension}"


def render(
    assessment: AssessmentLike,
    document_format: str,
    *,
    title: str = builder.TITLE,
    filename_prefix: str = "Протокол",
) -> RenderedDocument:
    """Формирует протокол. Содержание берётся из снимка решения, не из текущих правил.

    ``title`` и ``filename_prefix`` позволяют выдать тот же документ как справку,
    не заводя второй построитель.
    """
    if document_format not in FORMATS:
        raise ValueError(f"неизвестный формат: {document_format}")

    layout = builder.build(assessment, title=title)
    writer = docx_writer if document_format == DOCX else pdf_writer
    return RenderedDocument(
        format=document_format,
        filename=_filename(assessment, document_format, filename_prefix),
        content=writer.render(layout),
    )


def available_formats() -> tuple[str, ...]:
    """PDF недоступен, если в системе нет шрифта с кириллицей."""
    return FORMATS if fonts.is_available() else (DOCX,)


__all__ = ["DOCX", "PDF", "FORMATS", "MEDIA_TYPES", "RenderedDocument", "render", "available_formats"]
