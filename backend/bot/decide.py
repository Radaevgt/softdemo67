"""Определение сценария без базы данных.

То же ядро, что в портале (``app/services.py``), но матрица берётся из seed, а не
из PostgreSQL. На свежем развёртывании они совпадают дословно; разойтись могут
только если методолог правит правила через админку портала. Такое расхождение не
останется незаметным: в справку пишется ``ruleset_version`` — отпечаток набора
правил, которым решение получено.
"""
from __future__ import annotations

from functools import lru_cache

from app.engine import attributes
from app.engine.matcher import Decision, Method, evaluate
from app.seed.loader import seed_methods, seed_rules


@lru_cache
def _methods_by_code() -> dict[str, Method]:
    # evaluate ждёт правила списком, а способы — словарём по коду.
    return {method.code: method for method in seed_methods()}


def decide(object_kind: str, states: list[str], answers: dict) -> Decision:
    cleaned = attributes.prune(object_kind, answers)
    return evaluate(object_kind, states, cleaned, seed_rules(), _methods_by_code())
