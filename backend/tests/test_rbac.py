"""Разграничение доступа: роли и изоляция муниципальных образований."""
import pytest

FPO_ALIVE = {
    "rights_obj": True,
    "rights_land": True,
    "owner_status": "alive",
    "taxpayer": True,
    "registered_citizens": False,
}


def make_case(client, headers, **overrides):
    payload = {
        "address": "ул. Тестовая, д. 1",
        "object_kind": "izhs",
        "states": ["fpo"],
        **overrides,
    }
    return client.post("/api/cases", headers=headers, json=payload)


# --- аутентификация ---------------------------------------------------------


def test_anonymous_access_is_refused(client):
    for method, path in [
        ("get", "/api/cases"),
        ("get", "/api/auth/me"),
        ("get", "/api/catalog/dictionaries"),
        ("get", "/api/admin/users"),
    ]:
        assert getattr(client, method)(path).status_code == 401, path


def test_wrong_password_is_indistinguishable_from_unknown_login(client):
    unknown = client.post("/api/auth/login", data={"username": "nobody", "password": "x" * 12})
    wrong = client.post("/api/auth/login", data={"username": "spec_a", "password": "x" * 12})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_blocked_account_cannot_log_in(client, login, db):
    from app.models import User

    operator = login("operator")
    target = db.query(User).filter(User.login == "spec_b").one()
    response = client.patch(
        f"/api/admin/users/{target.id}", headers=operator, json={"is_active": False}
    )
    assert response.status_code == 200

    denied = client.post(
        "/api/auth/login", data={"username": "spec_b", "password": "test-password-1"}
    )
    assert denied.status_code == 403


def test_tampered_token_is_rejected(client, login):
    headers = login("spec_a")
    broken = {"Authorization": headers["Authorization"][:-3] + "abc"}
    assert client.get("/api/auth/me", headers=broken).status_code == 401


# --- изоляция муниципальных образований -------------------------------------


def test_specialist_cannot_see_another_municipality(client, login):
    other = make_case(client, login("spec_b")).json()

    mine = login("spec_a")
    assert client.get("/api/cases", headers=mine).json()["total"] == 0
    # Чужое дело маскируется под отсутствующее, а не под запрещённое.
    assert client.get(f"/api/cases/{other['id']}", headers=mine).status_code == 404


def test_specialist_cannot_modify_another_municipality(client, login):
    other = make_case(client, login("spec_b")).json()
    mine = login("spec_a")

    assert client.patch(
        f"/api/cases/{other['id']}", headers=mine, json={"address": "подмена"}
    ).status_code == 404
    assert client.delete(f"/api/cases/{other['id']}", headers=mine).status_code == 404
    assert client.post(
        f"/api/cases/{other['id']}/assessments", headers=mine
    ).status_code == 404


def test_specialist_cannot_create_a_case_for_another_municipality(client, login, municipalities):
    _, second = municipalities
    response = make_case(client, login("spec_a"), municipality_id=str(second.id))
    assert response.status_code == 403


def test_methodologist_reads_every_municipality_but_does_not_edit(client, login):
    case = make_case(client, login("spec_a")).json()
    methodologist = login("method")

    assert client.get(f"/api/cases/{case['id']}", headers=methodologist).status_code == 200
    assert client.patch(
        f"/api/cases/{case['id']}", headers=methodologist, json={"address": "правка"}
    ).status_code == 403
    assert make_case(client, methodologist).status_code == 403


def test_viewer_is_read_only(client, login):
    case = make_case(client, login("spec_a")).json()
    viewer = login("view_a")

    assert client.get(f"/api/cases/{case['id']}", headers=viewer).status_code == 200
    assert make_case(client, viewer).status_code == 403
    assert client.patch(
        f"/api/cases/{case['id']}", headers=viewer, json={"notes": "правка"}
    ).status_code == 403
    assert client.post(f"/api/cases/{case['id']}/assessments", headers=viewer).status_code == 403


def test_assessment_of_another_municipality_is_hidden(client, login):
    foreign = make_case(client, login("spec_b")).json()
    foreign_assessment = client.post(
        f"/api/cases/{foreign['id']}/assessments", headers=login("spec_b")
    ).json()

    mine = login("spec_a")
    assert client.get(
        f"/api/assessments/{foreign_assessment['id']}", headers=mine
    ).status_code == 404
    assert client.patch(
        f"/api/assessments/{foreign_assessment['id']}/answers",
        headers=mine, json={"answers": {"rights_obj": True}},
    ).status_code == 404


# --- админка ----------------------------------------------------------------


@pytest.mark.parametrize("who", ["spec_a", "view_a", "method"])
def test_only_operator_manages_accounts(client, login, who):
    assert client.get("/api/admin/users", headers=login(who)).status_code == 403


def test_operator_manages_accounts(client, login, municipalities):
    first, _ = municipalities
    response = client.post(
        "/api/admin/users",
        headers=login("operator"),
        json={
            "login": "new_spec",
            "password": "strong-password-1",
            "full_name": "Новый специалист",
            "role": "specialist",
            "municipality_id": str(first.id),
        },
    )
    assert response.status_code == 201
    assert client.post(
        "/api/auth/login", data={"username": "new_spec", "password": "strong-password-1"}
    ).status_code == 200


def test_specialist_account_requires_a_municipality(client, login):
    response = client.post(
        "/api/admin/users",
        headers=login("operator"),
        json={"login": "orphan", "password": "strong-password-1",
              "full_name": "Без МО", "role": "specialist"},
    )
    assert response.status_code == 400


def test_operator_cannot_lock_themselves_out(client, login, db):
    from app.models import User

    operator = db.query(User).filter(User.login == "operator").one()
    response = client.patch(
        f"/api/admin/users/{operator.id}", headers=login("operator"), json={"is_active": False}
    )
    assert response.status_code == 400


@pytest.mark.parametrize("who", ["spec_a", "view_a"])
def test_rule_matrix_is_closed_to_ordinary_users(client, login, who):
    headers = login(who)
    assert client.get("/api/admin/rules", headers=headers).status_code == 403
    assert client.post(
        "/api/admin/rules",
        headers=headers,
        json={"object_kind": "izhs", "state": "ownerless",
              "conditions": {}, "method_codes": ["ESCHEAT.v1"]},
    ).status_code == 403


def test_escalations_are_visible_to_their_author_and_to_the_methodologist(client, login):
    author = login("spec_a")
    case = make_case(client, author).json()
    created = client.post(
        "/api/escalations", headers=author, json={"case_id": case["id"], "comment": "вопрос"}
    )
    assert created.status_code == 201

    assert len(client.get("/api/escalations", headers=author).json()) == 1
    assert len(client.get("/api/escalations", headers=login("method")).json()) == 1
    # Специалист другого МО не видит чужих обращений.
    assert client.get("/api/escalations", headers=login("spec_b")).json() == []


def test_only_methodologist_resolves_escalations(client, login):
    author = login("spec_a")
    case = make_case(client, author).json()
    escalation = client.post(
        "/api/escalations", headers=author, json={"case_id": case["id"]}
    ).json()

    assert client.post(
        f"/api/escalations/{escalation['id']}/resolve",
        headers=author, json={"status": "resolved", "resolution": "сам себе"},
    ).status_code == 403

    resolved = client.post(
        f"/api/escalations/{escalation['id']}/resolve",
        headers=login("method"),
        json={"status": "resolved", "resolution": "Добавлено правило"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["resolved_by"]["login"] == "method"

    # Повторное рассмотрение закрытого обращения запрещено.
    assert client.post(
        f"/api/escalations/{escalation['id']}/resolve",
        headers=login("method"), json={"status": "rejected", "resolution": "ещё раз"},
    ).status_code == 409


# --- журнал -----------------------------------------------------------------


def test_audit_records_who_approved_the_decision(client, login):
    specialist = login("spec_a")
    case = make_case(client, specialist).json()
    assessment_id = client.post(
        f"/api/cases/{case['id']}/assessments", headers=specialist
    ).json()["id"]
    for key, value in FPO_ALIVE.items():
        client.patch(
            f"/api/assessments/{assessment_id}/answers",
            headers=specialist, json={"answers": {key: value}},
        )
    client.post(f"/api/assessments/{assessment_id}/decide", headers=specialist)
    client.post(f"/api/assessments/{assessment_id}/approve", headers=specialist)

    entries = client.get("/api/admin/audit", headers=login("operator")).json()
    actions = {entry["action"] for entry in entries}
    assert {"login.success", "case.create", "assessment.decide", "assessment.approve"} <= actions

    approval = next(entry for entry in entries if entry["action"] == "assessment.approve")
    assert approval["actor_login"] == "spec_a"
    assert approval["payload"]["content_hash"]


def test_failed_login_is_recorded(client, login):
    client.post("/api/auth/login", data={"username": "spec_a", "password": "wrong-password"})
    entries = client.get("/api/admin/audit", headers=login("operator")).json()
    assert any(entry["action"] == "login.failed" for entry in entries)
