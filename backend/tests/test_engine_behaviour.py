"""Поведение движка за пределами матрицы ТЗ: пробелы, совмещённые состояния, приоритет."""
import pytest

from app.engine import attributes
from app.engine.matcher import evaluate
from app.enums import STATE_PRIORITY, ObjectKind, ObjectState, OwnerStatus
from app.seed.loader import seed_methods, seed_rules

RULES = seed_rules()
METHODS = {method.code: method for method in seed_methods()}

# ИЖС, бесхозяйное, но правообладатель жив — такой комбинации в ТЗ нет.
GAP_ANSWERS = {
    "rights_obj": True,
    "rights_land": True,
    "owner_status": OwnerStatus.ALIVE,
    "taxpayer": True,
    "registered_citizens": False,
}


def decide(object_kind, states, answers):
    cleaned = attributes.prune(object_kind, dict(answers))
    return evaluate(object_kind, list(states), cleaned, RULES, METHODS)


def test_unknown_combination_offers_nearest_scenarios():
    decision = decide(ObjectKind.IZHS, [ObjectState.OWNERLESS], GAP_ANSWERS)
    outcome = decision.outcomes[0]

    assert not outcome.exact
    assert outcome.rule_code is None
    assert decision.needs_review is True
    assert 1 <= len(outcome.nearest) <= 3

    # Ближайшие отсортированы по числу расхождений и каждое названо явно.
    distances = [near.distance for near in outcome.nearest]
    assert distances == sorted(distances)
    assert all(near.distance > 0 for near in outcome.nearest)
    for near in outcome.nearest:
        assert len(near.differences) == near.distance
        assert all(diff.label and diff.expected_label and diff.actual_label
                   for diff in near.differences)


def test_nearest_match_explains_which_attributes_diverge():
    outcome = decide(ObjectKind.IZHS, [ObjectState.OWNERLESS], GAP_ANSWERS).outcomes[0]
    closest = outcome.nearest[0]
    diverging = {diff.key for diff in closest.differences}

    # Сценарии ТЗ по бесхозяйному ИЖС требуют умершего правообладателя.
    assert "owner_status" in diverging
    assert closest.methods, "к ближайшему сценарию всё равно приложены способы"


def test_several_states_produce_several_outcomes_in_priority_order():
    """Объект бывает одновременно бесхозяйным и ФПО — оба исхода должны прийти."""
    answers = {
        "rights_obj": True,
        "rights_land": True,
        "owner_status": OwnerStatus.DEAD,
        "taxpayer": False,
        "registered_citizens": False,
        "heirs": False,
    }
    decision = decide(ObjectKind.IZHS, [ObjectState.OWNERLESS, ObjectState.FPO], answers)

    assert [o.state for o in decision.outcomes] == [ObjectState.FPO, ObjectState.OWNERLESS]
    assert all(outcome.exact for outcome in decision.outcomes)

    # Один и тот же набор признаков даёт разные способы в разных состояниях —
    # ровно та коллизия, ради которой состояние сделано обязательным входом.
    fpo, ownerless = decision.outcomes
    assert {m.code for m in fpo.methods} != {m.code for m in ownerless.methods}


def test_state_order_is_independent_of_input_order():
    answers = {
        "rights_obj": True,
        "rights_land": True,
        "owner_status": OwnerStatus.DEAD,
        "taxpayer": False,
        "registered_citizens": False,
        "heirs": False,
    }
    forward = decide(ObjectKind.IZHS, [ObjectState.OWNERLESS, ObjectState.FPO], answers)
    backward = decide(ObjectKind.IZHS, [ObjectState.FPO, ObjectState.OWNERLESS], answers)
    assert [o.state for o in forward.outcomes] == [o.state for o in backward.outcomes]


def test_duplicate_states_are_collapsed():
    decision = decide(
        ObjectKind.IZHS,
        [ObjectState.FPO, ObjectState.FPO],
        {
            "rights_obj": True,
            "rights_land": True,
            "owner_status": OwnerStatus.ALIVE,
            "taxpayer": True,
            "registered_citizens": False,
        },
    )
    assert len(decision.outcomes) == 1


def test_threat_to_life_outranks_paperwork():
    assert STATE_PRIORITY[ObjectState.CS_MODE] < STATE_PRIORITY[ObjectState.EMERGENCY]
    assert STATE_PRIORITY[ObjectState.EMERGENCY] < STATE_PRIORITY[ObjectState.FPO]
    assert STATE_PRIORITY[ObjectState.FPO] < STATE_PRIORITY[ObjectState.OWNERLESS]


def test_decision_is_serialisable_and_carries_its_evidence():
    decision = decide(
        ObjectKind.IZHS,
        [ObjectState.FPO],
        {
            "rights_obj": True,
            "rights_land": True,
            "owner_status": OwnerStatus.ALIVE,
            "taxpayer": True,
            "registered_citizens": False,
        },
    )
    payload = decision.to_dict()

    assert payload["outcomes"][0]["methods"][0]["steps"]
    assert payload["ruleset_version"]
    # Разбор ответов сохраняется вместе с решением: из чего именно оно выведено.
    assert {item["key"] for item in payload["answer_breakdown"]} == set(decision.answers)
    assert all(item["source_hint"] for item in payload["answer_breakdown"])


# --- применимость признаков -------------------------------------------------


def test_heirs_question_appears_only_after_owner_is_marked_not_alive():
    assert attributes.next_unanswered(ObjectKind.IZHS, {}).key == "rights_obj"

    partial = {"rights_obj": True, "rights_land": True, "owner_status": OwnerStatus.ALIVE,
               "taxpayer": True, "registered_citizens": False}
    assert attributes.next_unanswered(ObjectKind.IZHS, partial) is None

    partial["owner_status"] = OwnerStatus.DEAD
    assert attributes.next_unanswered(ObjectKind.IZHS, partial).key == "heirs"


def test_heirs_question_appears_when_owner_is_unknown():
    answers = {"rights_obj": False, "rights_land": False, "owner_status": OwnerStatus.UNKNOWN,
               "taxpayer": False, "registered_citizens": False}
    assert attributes.next_unanswered(ObjectKind.IZHS, answers).key == "heirs"


def test_registered_citizens_skipped_for_nonresidential():
    keys = [a.key for a in attributes.applicable_attributes(ObjectKind.NONRESIDENTIAL, {})]
    assert "registered_citizens" not in keys


def test_stale_answer_is_dropped_when_it_stops_applying():
    answers = {"rights_obj": True, "rights_land": True, "owner_status": OwnerStatus.DEAD,
               "taxpayer": False, "registered_citizens": False, "heirs": True}
    corrected = attributes.prune(ObjectKind.IZHS, {**answers, "owner_status": OwnerStatus.ALIVE})
    assert "heirs" not in corrected


def test_validate_reports_missing_and_invalid_answers():
    errors = attributes.validate(ObjectKind.IZHS, {"rights_obj": "да"})
    assert any("недопустимое значение" in error for error in errors)
    assert any("не заполнен" in error for error in errors)

    assert attributes.validate(ObjectKind.IZHS, {"bogus": True})[0].startswith("неизвестный признак")


@pytest.mark.parametrize("object_kind", list(ObjectKind))
def test_questionnaire_terminates_for_every_object_kind(object_kind):
    """Мастер обязан дойти до конца, какие бы допустимые ответы ни выбирали."""
    answers: dict = {}
    for _ in range(len(attributes.ATTRIBUTES) + 1):
        question = attributes.next_unanswered(object_kind, answers)
        if question is None:
            break
        answers[question.key] = question.options[0].value
    else:
        pytest.fail("опрос не завершился")

    assert attributes.validate(object_kind, answers) == []
