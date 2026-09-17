"""Движок определения способа оформления (этап 4 ТЗ).

Матрица ТЗ описывает 61 сценарий, а комбинаций признаков около трёхсот, поэтому
точное совпадение — не единственный возможный исход. Когда правила нет, движок
показывает ближайшие сценарии с явным перечнем расходящихся признаков и помечает
результат как требующий решения методолога.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

from ..enums import LABELS, STATE_PRIORITY, ObjectState, OwnerStatus
from .attributes import ATTRIBUTES_BY_KEY, describe

NEAREST_LIMIT = 3


@dataclass(frozen=True)
class Rule:
    code: str
    object_kind: str
    state: str
    scenario_num: int
    conditions: dict
    method_codes: list[str]
    source: str | None = None


@dataclass(frozen=True)
class Method:
    code: str
    title: str
    steps: list[dict]


@dataclass
class Difference:
    key: str
    label: str
    expected: object
    expected_label: str
    actual: object
    actual_label: str


@dataclass
class NearMatch:
    rule_code: str
    scenario_num: int
    distance: int
    differences: list[Difference]
    methods: list[Method]
    source: str | None


@dataclass
class StateOutcome:
    """Результат по одному состоянию объекта."""

    state: str
    state_label: str
    exact: bool
    rule_code: str | None = None
    scenario_num: int | None = None
    methods: list[Method] = field(default_factory=list)
    source: str | None = None
    nearest: list[NearMatch] = field(default_factory=list)
    conflicting_rules: list[str] = field(default_factory=list)


@dataclass
class Decision:
    object_kind: str
    object_kind_label: str
    states: list[str]
    answers: dict
    answer_breakdown: list[dict]
    outcomes: list[StateOutcome]
    needs_review: bool
    ruleset_version: str

    def to_dict(self) -> dict:
        return asdict(self)


def owner_status_matches(expected: str, actual: str | None) -> bool:
    """ТЗ объединяет «мёртв/ликвидировано» для нежилых объектов в одно значение."""
    if expected == OwnerStatus.DEAD_OR_LIQUIDATED:
        return actual in (OwnerStatus.DEAD, OwnerStatus.LIQUIDATED)
    return expected == actual


def condition_matches(key: str, expected, actual) -> bool:
    if key == "owner_status":
        return owner_status_matches(expected, actual)
    return expected == actual


def _value_label(key: str, value) -> str:
    attr = ATTRIBUTES_BY_KEY.get(key)
    if value is None:
        return "не указано"
    if key == "owner_status":
        return LABELS["owner_status"].get(value, str(value))
    return attr.label_for(value) if attr else str(value)


def differences(rule: Rule, answers: dict) -> list[Difference]:
    """Признаки, по которым ответы расходятся с правилом."""
    result: list[Difference] = []
    for key, expected in rule.conditions.items():
        actual = answers.get(key)
        if condition_matches(key, expected, actual):
            continue
        attr = ATTRIBUTES_BY_KEY.get(key)
        result.append(
            Difference(
                key=key,
                label=attr.label if attr else key,
                expected=expected,
                expected_label=_value_label(key, expected),
                actual=actual,
                actual_label=_value_label(key, actual),
            )
        )
    return result


def has_exact_match(object_kind: str, state: str, answers: dict, rules: list[Rule]) -> bool:
    """Есть ли для набора ответов точное правило.

    Отдельно от :func:`evaluate`, потому что отчёт о покрытии перебирает сотни
    комбинаций и ему не нужны ни способы, ни отпечаток набора правил.
    """
    return any(
        rule.object_kind == object_kind and rule.state == state and not differences(rule, answers)
        for rule in rules
    )


def ruleset_version(rules: list[Rule]) -> str:
    """Отпечаток активного набора правил.

    Сохраняется вместе с решением, чтобы ранее утверждённый результат можно было
    объяснить даже после правок матрицы методологом.
    """
    payload = sorted(
        (rule.code, json.dumps(rule.conditions, sort_keys=True, ensure_ascii=False),
         ",".join(sorted(rule.method_codes)))
        for rule in rules
    )
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()[:16]


def _resolve(codes: list[str], catalog: dict[str, Method]) -> list[Method]:
    return [catalog[code] for code in codes if code in catalog]


def _sorted_states(states: list[str]) -> list[str]:
    return sorted(dict.fromkeys(states), key=lambda s: STATE_PRIORITY.get(ObjectState(s), 99))


def evaluate(
    object_kind: str,
    states: list[str],
    answers: dict,
    rules: list[Rule],
    methods: dict[str, Method],
) -> Decision:
    """Разрешает каждое состояние объекта отдельно и собирает общий результат.

    Состояния не конкурируют: объект, одновременно бесхозяйный и ФПО, порождает
    два исхода, упорядоченных по :data:`STATE_PRIORITY` — угроза жизни впереди.
    """
    outcomes: list[StateOutcome] = []

    for state in _sorted_states(states):
        candidates = [
            rule for rule in rules if rule.object_kind == object_kind and rule.state == state
        ]
        scored = [(differences(rule, answers), rule) for rule in candidates]

        # Правило методолога может быть менее специфичным, чем сценарий ТЗ, и
        # совпасть одновременно с ним. Побеждает более специфичное — остальные
        # показываются как пересечение, чтобы матрицу можно было починить.
        exact = sorted(
            (rule for diff, rule in scored if not diff),
            key=lambda rule: (-len(rule.conditions), rule.scenario_num),
        )

        outcome = StateOutcome(
            state=state,
            state_label=LABELS["state"].get(ObjectState(state), state),
            exact=bool(exact),
        )

        if exact:
            chosen = exact[0]
            outcome.rule_code = chosen.code
            outcome.scenario_num = chosen.scenario_num
            outcome.methods = _resolve(chosen.method_codes, methods)
            outcome.source = chosen.source
            outcome.conflicting_rules = [rule.code for rule in exact[1:]]
        else:
            scored.sort(key=lambda pair: (len(pair[0]), pair[1].scenario_num))
            outcome.nearest = [
                NearMatch(
                    rule_code=rule.code,
                    scenario_num=rule.scenario_num,
                    distance=len(diff),
                    differences=diff,
                    methods=_resolve(rule.method_codes, methods),
                    source=rule.source,
                )
                for diff, rule in scored[:NEAREST_LIMIT]
            ]

        outcomes.append(outcome)

    # Пустой список исходов — не «всё в порядке», а «ничего не определено»:
    # без состояния объекта сценарий не выводится и решение утверждать нельзя.
    needs_review = not outcomes or any(
        not outcome.exact or outcome.conflicting_rules for outcome in outcomes
    )

    return Decision(
        object_kind=object_kind,
        object_kind_label=LABELS["object_kind"].get(object_kind, object_kind),
        states=_sorted_states(states),
        answers=answers,
        answer_breakdown=describe(object_kind, answers),
        outcomes=outcomes,
        needs_review=needs_review,
        ruleset_version=ruleset_version(rules),
    )
