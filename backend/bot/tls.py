"""Проверка сертификата MAX.

Цепочка `*.max.ru` идёт от корня удостоверяющего центра Минцифры, которого нет в
наборе certifi. На Windows запрос проходит — корень лежит в хранилище системы, —
а в контейнере `python:3.12-slim` падает на проверке. Поэтому корень приложен к
репозиторию и добавляется к обычному набору.

Отключать проверку нельзя: в каждом запросе уходит токен бота, и без проверки его
получит любой посредник.
"""
from __future__ import annotations

import ssl
from pathlib import Path

import certifi

ROOT_CA = Path(__file__).with_name("certs") / "russian_trusted_root_ca.pem"


def build_ssl_context() -> ssl.SSLContext:
    """Обычный набор доверенных корней плюс корень Минцифры."""
    if not ROOT_CA.is_file():
        raise FileNotFoundError(
            f"Не найден корневой сертификат {ROOT_CA}. Без него запросы к MAX "
            "не пройдут проверку сертификата в контейнере."
        )

    context = ssl.create_default_context(cafile=certifi.where())
    context.load_verify_locations(cafile=str(ROOT_CA))
    return context
