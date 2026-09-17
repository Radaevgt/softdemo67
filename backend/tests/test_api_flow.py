"""Сквозной путь сотрудника: дело -> опрос -> решение -> дорожная карта -> утверждение."""
import pytest

from app.enums import OwnerStatus

FPO_ALIVE = {
    "rights_obj": True,
    "rights_land": True,
    "owner_status": OwnerStatus.ALIVE.value,
    "taxpayer": True,
    "registered_citizens": False,
}
OWNERLESS_DEAD = {
    "rights_obj": True,
    "rights_land": True,
    "owner_status": OwnerStatus.DEAD.value,
    "taxpayer": False,
    "registered_citizens": False,
    "heirs": False,
}


@pytest.fixture
def specialist(login):
    return login("spec_a")


def make_case(client, headers, states=("fpo",), object_kind="izhs"):
    response = client.post(
        "/api/cases",
        headers=headers,
        json={
            "address": "г. Нижний Новгород, ул. Ленина, д. 9",
            "object_kind": object_kind,
            "states": list(states),
            "cadastral_number_oks": "52:18:0000000:123",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def answer_all(client, headers, assessment_id, answers):
    progress = None
    for key, value in answers.items():
        response = client.patch(
            f"/api/assessments/{assessment_id}/answers",
            headers=headers,
            json={"answers": {key: value}},
        )
        assert response.status_code == 200, response.text
        progress = response.json()
    return progress


def test_full_path_from_case_to_approved_decision(client, specialist):
    case = make_case(client, specialist)

    created = client.post(f"/api/cases/{case['id']}/assessments", headers=specialist)
    assert created.status_code == 201
    assessment_id = created.json()["id"]

    progress = answer_all(client, specialist, assessment_id, FPO_ALIVE)
    assert progress["complete"] is True
    assert progress["next_question"] is None
    assert progress["remaining"] == 0

    decided = client.post(f"/api/assessments/{assessment_id}/decide", headers=specialist)
    assert decided.status_code == 200, decided.text
    decision = decided.json()["decision"]

    assert decision["needs_review"] is False
    outcome = decision["outcomes"][0]
    assert outcome["exact"] is True
    assert outcome["state"] == "fpo"
    assert outcome["methods"][0]["steps"]

    method_code = outcome["methods"][0]["code"]
    roadmap = client.post(
        f"/api/assessments/{assessment_id}/roadmap",
        headers=specialist,
        json={"method_codes": [method_code]},
    )
    assert roadmap.status_code == 200, roadmap.text
    items = roadmap.json()
    assert items and all(item["status"] == "pending" for item in items)
    assert [item["order_index"] for item in items] == list(range(len(items)))

    approved = client.post(f"/api/assessments/{assessment_id}/approve", headers=specialist)
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "approved"
    assert body["approved_by"]["login"] == "spec_a"
    assert len(body["content_hash"]) == 64
    # Подпись УКЭП ещё не подключена — поле остаётся пустым осознанно.
    assert body["signed_at"] is None

    assert client.get(f"/api/cases/{case['id']}", headers=specialist).json()["status"] == "decided"


def test_questionnaire_is_adaptive(client, specialist):
    case = make_case(client, specialist)
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]

    first = client.get(f"/api/assessments/{assessment_id}", headers=specialist).json()
    assert first["next_question"]["key"] == "rights_obj"
    assert first["next_question"]["source_hint"]

    answer_all(client, specialist, assessment_id, {
        "rights_obj": True, "rights_land": True, "owner_status": "alive", "taxpayer": True,
    })
    state = client.get(f"/api/assessments/{assessment_id}", headers=specialist).json()
    assert state["next_question"]["key"] == "registered_citizens"

    # Смена статуса на «умер» добавляет вопрос о наследниках.
    answer_all(client, specialist, assessment_id, {"owner_status": "dead"})
    state = client.get(f"/api/assessments/{assessment_id}", headers=specialist).json()
    assert state["next_question"]["key"] in {"registered_citizens", "heirs"}


def test_changing_an_answer_invalidates_the_previous_decision(client, specialist):
    case = make_case(client, specialist)
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]
    answer_all(client, specialist, assessment_id, FPO_ALIVE)
    client.post(f"/api/assessments/{assessment_id}/decide", headers=specialist)

    changed = client.patch(
        f"/api/assessments/{assessment_id}/answers",
        headers=specialist,
        json={"answers": {"taxpayer": False}},
    )
    assert changed.status_code == 200
    assert changed.json()["assessment"]["decision"] is None


def test_correcting_owner_status_drops_the_heirs_answer(client, specialist):
    case = make_case(client, specialist)
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]

    answer_all(client, specialist, assessment_id, OWNERLESS_DEAD)
    corrected = client.patch(
        f"/api/assessments/{assessment_id}/answers",
        headers=specialist,
        json={"answers": {"owner_status": "alive"}},
    )
    assert "heirs" not in corrected.json()["assessment"]["answers"]


def test_unresolved_combination_blocks_approval_and_offers_nearest(client, specialist):
    case = make_case(client, specialist, states=("ownerless",))
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]

    # Бесхозяйное ИЖС с живым правообладателем в матрице ТЗ не описано.
    answer_all(client, specialist, assessment_id, FPO_ALIVE)
    decision = client.post(
        f"/api/assessments/{assessment_id}/decide", headers=specialist
    ).json()["decision"]

    assert decision["needs_review"] is True
    outcome = decision["outcomes"][0]
    assert outcome["exact"] is False
    assert outcome["nearest"], "сотруднику показываются ближайшие сценарии"
    assert outcome["nearest"][0]["differences"]

    blocked = client.post(f"/api/assessments/{assessment_id}/approve", headers=specialist)
    assert blocked.status_code == 409
    assert "методолог" in blocked.json()["detail"]

    escalated = client.post(
        "/api/escalations",
        headers=specialist,
        json={"case_id": case["id"], "assessment_id": assessment_id,
              "comment": "Правообладатель жив, объект заброшен"},
    )
    assert escalated.status_code == 201
    assert escalated.json()["inputs"]["answers"]["owner_status"] == "alive"


def test_decide_refuses_incomplete_answers(client, specialist):
    case = make_case(client, specialist)
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]
    answer_all(client, specialist, assessment_id, {"rights_obj": True})

    response = client.post(f"/api/assessments/{assessment_id}/decide", headers=specialist)
    assert response.status_code == 400
    assert "не заполнен" in response.json()["detail"]


def test_answers_reject_wrong_types(client, specialist):
    case = make_case(client, specialist)
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]

    assert client.patch(
        f"/api/assessments/{assessment_id}/answers",
        headers=specialist, json={"answers": {"rights_obj": "да"}},
    ).status_code == 422
    assert client.patch(
        f"/api/assessments/{assessment_id}/answers",
        headers=specialist, json={"answers": {"owner_status": "zombie"}},
    ).status_code == 422
    assert client.patch(
        f"/api/assessments/{assessment_id}/answers",
        headers=specialist, json={"answers": {"nonexistent": True}},
    ).status_code == 422


def test_approved_assessment_is_immutable(client, specialist):
    case = make_case(client, specialist)
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]
    answer_all(client, specialist, assessment_id, FPO_ALIVE)
    client.post(f"/api/assessments/{assessment_id}/decide", headers=specialist)
    client.post(f"/api/assessments/{assessment_id}/approve", headers=specialist)

    blocked = client.patch(
        f"/api/assessments/{assessment_id}/answers",
        headers=specialist, json={"answers": {"taxpayer": False}},
    )
    assert blocked.status_code == 409


def test_repeat_check_keeps_the_previous_result(client, specialist):
    """Ответ № 7 брифа: при повторной проверке важно видеть предыдущий результат."""
    case = make_case(client, specialist)
    first_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]
    answer_all(client, specialist, first_id, FPO_ALIVE)
    client.post(f"/api/assessments/{first_id}/decide", headers=specialist)
    client.post(f"/api/assessments/{first_id}/approve", headers=specialist)

    second_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]
    assert second_id != first_id

    history = client.get(f"/api/cases/{case['id']}/assessments", headers=specialist).json()
    assert len(history) == 2
    approved = next(item for item in history if item["id"] == first_id)
    assert approved["decision"] is not None and approved["status"] == "approved"


def test_unfinished_draft_is_resumed_not_duplicated(client, specialist):
    """Ответ № 7 брифа: сохранять незавершённое заполнение и возвращаться к нему."""
    case = make_case(client, specialist)
    first = client.post(f"/api/cases/{case['id']}/assessments", headers=specialist).json()
    answer_all(client, specialist, first["id"], {"rights_obj": True})

    again = client.post(f"/api/cases/{case['id']}/assessments", headers=specialist).json()
    assert again["id"] == first["id"]
    assert again["answers"] == {"rights_obj": True}


def test_case_without_state_cannot_be_assessed(client, specialist):
    case = make_case(client, specialist, states=())
    response = client.post(f"/api/cases/{case['id']}/assessments", headers=specialist)
    assert response.status_code == 400
    assert "состояние" in response.json()["detail"]


def test_roadmap_rejects_methods_outside_the_decision(client, specialist):
    case = make_case(client, specialist)
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]
    answer_all(client, specialist, assessment_id, FPO_ALIVE)
    client.post(f"/api/assessments/{assessment_id}/decide", headers=specialist)

    response = client.post(
        f"/api/assessments/{assessment_id}/roadmap",
        headers=specialist,
        json={"method_codes": ["ESCHEAT.v1"]},
    )
    assert response.status_code == 400


def test_roadmap_item_can_be_assigned_and_completed(client, specialist):
    case = make_case(client, specialist)
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]
    answer_all(client, specialist, assessment_id, FPO_ALIVE)
    decision = client.post(
        f"/api/assessments/{assessment_id}/decide", headers=specialist
    ).json()["decision"]
    code = decision["outcomes"][0]["methods"][0]["code"]
    items = client.post(
        f"/api/assessments/{assessment_id}/roadmap",
        headers=specialist, json={"method_codes": [code]},
    ).json()

    action = next(item for item in items if item["kind"] == "action")
    updated = client.patch(
        f"/api/roadmap-items/{action['id']}",
        headers=specialist,
        json={"status": "done", "due_date": "2026-12-01", "note": "Акт составлен"},
    )
    assert updated.status_code == 200
    assert updated.json()["completed_at"] is not None


def test_several_states_yield_several_outcomes_over_api(client, specialist):
    case = make_case(client, specialist, states=("ownerless", "fpo"))
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]
    answer_all(client, specialist, assessment_id, OWNERLESS_DEAD)
    decision = client.post(
        f"/api/assessments/{assessment_id}/decide", headers=specialist
    ).json()["decision"]

    assert [outcome["state"] for outcome in decision["outcomes"]] == ["fpo", "ownerless"]


def test_preview_does_not_persist_anything(client, specialist):
    response = client.post(
        "/api/decisions/preview",
        headers=specialist,
        json={"object_kind": "izhs", "states": ["fpo"], "answers": FPO_ALIVE},
    )
    assert response.status_code == 200
    assert response.json()["outcomes"][0]["exact"] is True
    assert client.get("/api/cases", headers=specialist).json()["total"] == 0
