"""Контракт источника данных для протокола.

Построитель протокола читает у проверки полтора десятка простых полей и ничего
больше — ни запросов, ни ленивых коллекций. Раньше это знание было неявным: в
аннотациях стояла ORM-модель, и модуль нельзя было импортировать без базы, хотя
база ему не нужна.

Здесь контракт записан явно. ORM-``Assessment`` удовлетворяет ему структурно и
менять его не пришлось; бот заполняет ``PlainAssessment`` вручную и получает тот
же протокол тем же кодом.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class PersonLike(Protocol):
    full_name: str
    position: str | None


@runtime_checkable
class MunicipalityLike(Protocol):
    name: str


@runtime_checkable
class CaseLike(Protocol):
    address: str
    object_kind: str
    states: list[str]
    cadastral_number_oks: str | None
    cadastral_number_land: str | None
    notes: str | None
    municipality: MunicipalityLike


@runtime_checkable
class AssessmentLike(Protocol):
    """Снимок проверки, из которого собирается протокол."""

    id: object
    decision: dict | None
    case: CaseLike
    author: PersonLike | None
    approved_by: PersonLike | None
    created_at: datetime | None
    updated_at: datetime | None
    approved_at: datetime | None
    content_hash: str | None
    signed_at: datetime | None


# --- реализация для потребителей без базы -----------------------------------


@dataclass
class PlainPerson:
    full_name: str
    position: str | None = None


@dataclass
class PlainMunicipality:
    name: str


@dataclass
class PlainCase:
    address: str
    object_kind: str
    states: list[str] = field(default_factory=list)
    municipality: PlainMunicipality = field(
        default_factory=lambda: PlainMunicipality(name="не указано")
    )
    cadastral_number_oks: str | None = None
    cadastral_number_land: str | None = None
    notes: str | None = None


@dataclass
class PlainAssessment:
    """Проверка, не связанная с базой: бот собирает её из ответов в диалоге."""

    id: object
    case: PlainCase
    decision: dict | None = None
    author: PlainPerson | None = None
    approved_by: PlainPerson | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    approved_at: datetime | None = None
    content_hash: str | None = None
    signed_at: datetime | None = None
