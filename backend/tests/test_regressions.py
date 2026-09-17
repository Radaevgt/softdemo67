"""Случаи, при которых решение могло быть утверждено без основания.

Каждый тест воспроизводит найденную при код-ревью ошибку.
"""

FPO_ALIVE = {
    "rights_obj": True,
    "rights_land": True,
    "owner_status": "alive",
    "taxpayer": True,
    "registered_citizens": False,
}

GAP_CONDITIONS = {
    "rights_obj": True,
    "rights_land": True,
    "owner_status": "alive",
    "taxpayer": True,
    "registered_citizens": True,
}


def make_case(client, headers, states=("fpo",)):
    response = client.post(
        "/api/cases",
        headers=headers,
        json={"address": "ул. Тестовая, д. 1", "object_kind": "izhs", "states": list(states)},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def prepared_assessment(client, headers, case_id, answers=FPO_ALIVE):
    assessment_id = client.post(f"/api/cases/{case_id}/assessments", headers=headers).json()["id"]
    for key, value in answers.items():
        response = client.patch(
            f"/api/assessments/{assessment_id}/answers",
            headers=headers,
            json={"answers": {key: value}},
        )
        assert response.status_code == 200, response.text
    return assessment_id


def test_editing_an_answer_returns_the_assessment_to_draft(client, login):
    """Правка ответа сбрасывала решение, но статус оставался «рассчитано»,
    из-за чего проверку можно было утвердить без решения вовсе."""
    headers = login("spec_a")
    case_id = make_case(client, headers)
    assessment_id = prepared_assessment(client, headers, case_id)

    assert client.post(f"/api/assessments/{assessment_id}/decide", headers=headers).status_code == 200

    edited = client.patch(
        f"/api/assessments/{assessment_id}/answers",
        headers=headers,
        json={"answers": {"rights_obj": False}},
    )
    assert edited.status_code == 200
    assert edited.json()["assessment"]["status"] == "draft"
    assert edited.json()["assessment"]["decision"] is None

    blocked = client.post(f"/api/assessments/{assessment_id}/approve", headers=headers)
    assert blocked.status_code == 409
    assert client.get(f"/api/assessments/{assessment_id}", headers=headers).json()[
        "assessment"
    ]["content_hash"] is None


def test_clearing_states_after_the_assessment_started_blocks_the_decision(client, login):
    """Состояние проверялось только при создании проверки, а стереть его можно
    было и позже — расчёт тогда давал пустое решение, которое проходило утверждение."""
    headers = login("spec_a")
    case_id = make_case(client, headers)
    assessment_id = prepared_assessment(client, headers, case_id)

    assert client.patch(f"/api/cases/{case_id}", headers=headers, json={"states": []}).status_code == 200

    decided = client.post(f"/api/assessments/{assessment_id}/decide", headers=headers)
    assert decided.status_code == 400
    assert "состояние" in decided.json()["detail"]

    blocked = client.post(f"/api/assessments/{assessment_id}/approve", headers=headers)
    assert blocked.status_code == 409


def test_decision_without_outcomes_is_flagged_for_review():
    """Защита на уровне движка: нет исходов — значит ничего не определено."""
    from app.engine.matcher import evaluate
    from app.seed.loader import seed_methods, seed_rules

    decision = evaluate("izhs", [], FPO_ALIVE, seed_rules(), {m.code: m for m in seed_methods()})
    assert decision.outcomes == []
    assert decision.needs_review is True


def test_rule_code_is_not_reused_after_a_custom_rule_is_disabled(client, login):
    """Номер для кода брался только среди активных правил, поэтому после
    отключения пользовательского правила следующее получало занятый код."""
    headers = login("method")

    first = client.post(
        "/api/admin/rules",
        headers=headers,
        json={
            "object_kind": "izhs",
            "state": "ownerless",
            "conditions": GAP_CONDITIONS,
            "method_codes": ["OWNERLESS_TITLE.v1"],
        },
    )
    assert first.status_code == 201, first.text

    disabled = client.patch(
        f"/api/admin/rules/{first.json()['id']}", headers=headers, json={"is_active": False}
    )
    assert disabled.status_code == 200

    second = client.post(
        "/api/admin/rules",
        headers=headers,
        json={
            "object_kind": "izhs",
            "state": "ownerless",
            "conditions": {**GAP_CONDITIONS, "registered_citizens": False},
            "method_codes": ["OWNERLESS_TITLE.v1"],
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["code"] != first.json()["code"]


def test_disabled_rule_still_blocks_duplicate_conditions(client, login):
    """Отключённое правило можно включить обратно — дубликат его условий
    создал бы пересечение, поэтому он отклоняется сразу."""
    headers = login("method")
    payload = {
        "object_kind": "izhs",
        "state": "ownerless",
        "conditions": GAP_CONDITIONS,
        "method_codes": ["OWNERLESS_TITLE.v1"],
    }

    created = client.post("/api/admin/rules", headers=headers, json=payload)
    assert created.status_code == 201
    client.patch(
        f"/api/admin/rules/{created.json()['id']}", headers=headers, json={"is_active": False}
    )

    duplicate = client.post("/api/admin/rules", headers=headers, json=payload)
    assert duplicate.status_code == 409


def test_second_assessment_is_not_created_while_one_is_unfinished(client, login):
    """Сброс проверки в черновик делал достижимым состояние с двумя черновиками,
    на котором выборка падала с ошибкой сервера."""
    headers = login("spec_a")
    case_id = make_case(client, headers)

    first = prepared_assessment(client, headers, case_id)
    assert client.post(f"/api/assessments/{first}/decide", headers=headers).status_code == 200

    # Проверка рассчитана — «Начать проверку» возвращает её же, а не заводит вторую.
    second = client.post(f"/api/cases/{case_id}/assessments", headers=headers).json()["id"]
    assert second == first

    client.patch(
        f"/api/assessments/{first}/answers", headers=headers, json={"answers": {"rights_obj": False}}
    )
    third = client.post(f"/api/cases/{case_id}/assessments", headers=headers)
    assert third.status_code == 201, third.text
    assert third.json()["id"] == first

    assert len(client.get(f"/api/cases/{case_id}/assessments", headers=headers).json()) == 1


def test_long_cyrillic_password_is_refused_not_crashed(client, login):
    """bcrypt молча обрезает пароль после 72 байт; 40 символов кириллицей — 80 байт.
    Раньше это доходило до хеширования и роняло запрос в ошибку сервера."""
    headers = login("operator")
    municipality = client.get("/api/admin/municipalities", headers=headers).json()[0]

    response = client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "login": "longpass",
            "password": "П" * 40,
            "full_name": "Длинный пароль",
            "role": "specialist",
            "municipality_id": municipality["id"],
        },
    )
    assert response.status_code == 422, response.text
    assert client.post(
        "/api/auth/login", data={"username": "longpass", "password": "П" * 40}
    ).status_code == 401


def test_viewer_cannot_create_an_escalation(client, login):
    """Наблюдатель по роли не пишет, а создание обращения копирует в него
    ответы и решение по делу."""
    case_id = make_case(client, login("spec_a"))
    response = client.post(
        "/api/escalations", headers=login("view_a"), json={"case_id": case_id}
    )
    assert response.status_code == 403


def test_unchecking_a_roadmap_step_clears_its_completion_date(client, login):
    """Дата выполнения оставалась заполненной, и снятый шаг продолжал
    отображаться выполненным."""
    headers = login("spec_a")
    case_id = make_case(client, headers)
    assessment_id = prepared_assessment(client, headers, case_id)
    decision = client.post(f"/api/assessments/{assessment_id}/decide", headers=headers).json()[
        "decision"
    ]
    items = client.post(
        f"/api/assessments/{assessment_id}/roadmap",
        headers=headers,
        json={"method_codes": [decision["outcomes"][0]["methods"][0]["code"]]},
    ).json()
    step = next(item for item in items if item["kind"] == "action")

    done = client.patch(f"/api/roadmap-items/{step['id']}", headers=headers, json={"status": "done"})
    assert done.json()["completed_at"] is not None

    undone = client.patch(
        f"/api/roadmap-items/{step['id']}", headers=headers, json={"status": "pending"}
    )
    assert undone.json()["status"] == "pending"
    assert undone.json()["completed_at"] is None


def test_methodologist_can_author_a_rule_with_the_merged_owner_status(client, login):
    """ТЗ использует «мёртв/ликвидировано» для нежилых объектов, а форма правил
    этот статус отвергала — методолог не мог выразить то, что написано в ТЗ."""
    headers = login("method")
    conditions = {
        "rights_obj": False,
        "rights_land": False,
        "owner_status": "dead_or_liquidated",
        "taxpayer": True,
        "heirs": False,
    }

    created = client.post(
        "/api/admin/rules",
        headers=headers,
        json={
            "object_kind": "nonresidential",
            "state": "fpo",
            "conditions": conditions,
            "method_codes": ["FPO_DEMOLITION.v2"],
        },
    )
    assert created.status_code == 201, created.text

    # Правило срабатывает на обоих конкретных статусах.
    for status_value in ("dead", "liquidated"):
        preview = client.post(
            "/api/decisions/preview",
            headers=headers,
            json={
                "object_kind": "nonresidential",
                "states": ["fpo"],
                "answers": {**conditions, "owner_status": status_value},
            },
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["outcomes"][0]["exact"] is True


def test_merged_owner_status_is_still_refused_as_an_answer(client, login):
    """Сотрудник выбирает конкретный статус — объединённый допустим только в правиле."""
    headers = login("spec_a")
    case_id = make_case(client, headers)
    assessment_id = client.post(
        f"/api/cases/{case_id}/assessments", headers=headers
    ).json()["id"]

    response = client.patch(
        f"/api/assessments/{assessment_id}/answers",
        headers=headers,
        json={"answers": {"owner_status": "dead_or_liquidated"}},
    )
    assert response.status_code == 422
