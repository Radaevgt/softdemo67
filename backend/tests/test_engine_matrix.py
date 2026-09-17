"""Сверка движка с матрицей ТЗ.

Каждый из 61 сценария документа прогоняется как отдельный тест: если правка
движка или seed изменит исход хотя бы одного сценария, тест назовёт конкретный
номер сценария и связку, в которой сломалось.
"""
import pytest

from app.engine import attributes
from app.engine.matcher import Rule, evaluate, owner_status_matches, ruleset_version
from app.enums import ObjectKind, ObjectState, OwnerStatus
from app.seed.loader import seed_methods, seed_rules

RULES = seed_rules()
METHODS = {method.code: method for method in seed_methods()}


def answers_for(rule: Rule) -> dict:
    """Ответы сотрудника, приводящие ровно к этому сценарию.

    ТЗ для нежилых объектов объединяет «мёртв/ликвидировано» в одно значение,
    а сотрудник выбирает конкретное — поэтому объединённое раскрывается в «умер».
    """
    answers = dict(rule.conditions)
    if answers.get("owner_status") == OwnerStatus.DEAD_OR_LIQUIDATED:
        answers["owner_status"] = OwnerStatus.DEAD
    return attributes.prune(rule.object_kind, answers)


def test_seed_is_complete():
    assert len(RULES) == 61, "в ТЗ описан 61 сценарий"
    assert len(METHODS) == 16
    assert all(rule.method_codes for rule in RULES)
    assert all(METHODS[code].steps for rule in RULES for code in rule.method_codes)


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule.code)
def test_every_tz_scenario_resolves_to_itself(rule: Rule):
    answers = answers_for(rule)

    assert attributes.validate(rule.object_kind, answers) == []

    decision = evaluate(rule.object_kind, [rule.state], answers, RULES, METHODS)
    outcome = decision.outcomes[0]

    assert outcome.exact, f"{rule.code} не находит точного совпадения"
    assert outcome.rule_code == rule.code
    assert outcome.conflicting_rules == []
    assert not decision.needs_review
    assert [method.code for method in outcome.methods] == rule.method_codes
    assert all(method.steps for method in outcome.methods)


def test_conditions_are_unique_within_a_branch():
    seen: dict[tuple, str] = {}
    for rule in RULES:
        key = (rule.object_kind, rule.state, tuple(sorted(rule.conditions.items())))
        assert key not in seen, f"{rule.code} дублирует {seen.get(key)}"
        seen[key] = rule.code


def test_heirs_asked_only_when_owner_is_not_alive():
    for rule in RULES:
        alive = rule.conditions["owner_status"] == OwnerStatus.ALIVE
        assert ("heirs" in rule.conditions) is not alive, rule.code


def test_registered_citizens_not_used_for_nonresidential():
    for rule in RULES:
        if rule.object_kind == ObjectKind.NONRESIDENTIAL:
            assert "registered_citizens" not in rule.conditions, rule.code


def test_merged_owner_status_matches_both_concrete_values():
    assert owner_status_matches(OwnerStatus.DEAD_OR_LIQUIDATED, OwnerStatus.DEAD)
    assert owner_status_matches(OwnerStatus.DEAD_OR_LIQUIDATED, OwnerStatus.LIQUIDATED)
    assert not owner_status_matches(OwnerStatus.DEAD_OR_LIQUIDATED, OwnerStatus.ALIVE)
    assert not owner_status_matches(OwnerStatus.DEAD, OwnerStatus.LIQUIDATED)


def test_liquidated_owner_resolves_for_nonresidential():
    """«Ликвидировано» должно попадать в сценарии, где ТЗ пишет «мёртв/ликвидировано»."""
    rule = next(
        r for r in RULES
        if r.code == "nonresidential.ownerless.1"
    )
    answers = attributes.prune(
        ObjectKind.NONRESIDENTIAL, {**rule.conditions, "owner_status": OwnerStatus.LIQUIDATED}
    )
    outcome = evaluate(
        ObjectKind.NONRESIDENTIAL, [ObjectState.OWNERLESS], answers, RULES, METHODS
    ).outcomes[0]
    assert outcome.exact and outcome.rule_code == rule.code


def test_ruleset_version_is_stable_and_order_independent():
    assert ruleset_version(RULES) == ruleset_version(list(reversed(RULES)))
    changed = [*RULES[:-1]]
    assert ruleset_version(changed) != ruleset_version(RULES)
