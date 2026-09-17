"""Матрица в админке: правило методолога закрывает пробел ТЗ без релиза."""

# ИЖС, бесхозяйное, правообладатель жив — комбинация, которой в ТЗ нет.
GAP = {
    "rights_obj": True,
    "rights_land": True,
    "owner_status": "alive",
    "taxpayer": True,
    "registered_citizens": False,
}


def preview(client, headers, answers=None, states=("ownerless",)):
    return client.post(
        "/api/decisions/preview",
        headers=headers,
        json={"object_kind": "izhs", "states": list(states), "answers": answers or GAP},
    )


def test_seed_matches_the_tz(client, login):
    rules = client.get("/api/admin/rules", headers=login("method")).json()
    assert len(rules) == 61
    assert all(rule["is_builtin"] for rule in rules)

    methods = client.get("/api/catalog/methods", headers=login("spec_a")).json()
    assert len(methods) == 16
    assert all(method["steps"] for method in methods)


def test_coverage_report_shows_the_gaps(client, login):
    coverage = client.get("/api/admin/rules/coverage", headers=login("method")).json()

    # Все связки «вид × состояние», а не только те, где правила есть.
    assert len(coverage) == 3 * 4

    cells = {(cell["object_kind"], cell["state"]): cell for cell in coverage}
    assert cells[("izhs", "ownerless")]["described"] == 4
    assert cells[("mkd_apartment", "emergency")]["described"] == 15

    # Матрица ТЗ заведомо неполна — отчёт обязан это показывать, а не скрывать.
    assert all(cell["gaps"] > 0 for cell in coverage)


def test_coverage_report_does_not_hide_undescribed_branches(client, login):
    """Связки без единого правила — самые крупные пробелы матрицы.

    ТЗ описывает аварийность только для МКД, а ФПО — только для ИЖС и нежилого,
    поэтому три связки пусты. Отчёт обязан их показывать, иначе методолог видит
    частично закрытые ячейки и не видит полностью незакрытых.
    """
    coverage = client.get("/api/admin/rules/coverage", headers=login("method")).json()
    empty = {(cell["object_kind"], cell["state"]) for cell in coverage if cell["described"] == 0}

    assert empty == {
        ("izhs", "emergency"),
        ("mkd_apartment", "fpo"),
        ("nonresidential", "emergency"),
    }
    for cell in coverage:
        if cell["described"] == 0:
            assert cell["gaps"] == cell["combinations"]


def test_methodologist_closes_a_gap_and_it_works_immediately(client, login):
    methodologist = login("method")
    specialist = login("spec_a")

    before = preview(client, specialist).json()
    assert before["needs_review"] is True
    assert before["outcomes"][0]["exact"] is False

    created = client.post(
        "/api/admin/rules",
        headers=methodologist,
        json={
            "object_kind": "izhs",
            "state": "ownerless",
            "conditions": GAP,
            "method_codes": ["OWNERLESS_TITLE.v1"],
            "source": "Решение методического совета от 17.09.2026",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_builtin"] is False
    assert created.json()["code"].startswith("izhs.ownerless.custom.")

    after = preview(client, specialist).json()
    assert after["needs_review"] is False
    outcome = after["outcomes"][0]
    assert outcome["exact"] is True
    assert outcome["methods"][0]["code"] == "OWNERLESS_TITLE.v1"
    assert outcome["methods"][0]["steps"]
    # Версия набора правил изменилась — ранее принятые решения останутся объяснимы.
    assert after["ruleset_version"] != before["ruleset_version"]


def test_rule_with_duplicate_conditions_is_refused(client, login):
    methodologist = login("method")
    payload = {
        "object_kind": "izhs",
        "state": "ownerless",
        "conditions": GAP,
        "method_codes": ["OWNERLESS_TITLE.v1"],
    }
    assert client.post("/api/admin/rules", headers=methodologist, json=payload).status_code == 201
    repeated = client.post("/api/admin/rules", headers=methodologist, json=payload)
    assert repeated.status_code == 409


def test_rule_with_incomplete_conditions_is_refused(client, login):
    response = client.post(
        "/api/admin/rules",
        headers=login("method"),
        json={
            "object_kind": "izhs",
            "state": "ownerless",
            "conditions": {"rights_obj": True},
            "method_codes": ["OWNERLESS_TITLE.v1"],
        },
    )
    assert response.status_code == 422
    assert "не заполнен" in response.json()["detail"]


def test_rule_referencing_an_unknown_method_is_refused(client, login):
    response = client.post(
        "/api/admin/rules",
        headers=login("method"),
        json={
            "object_kind": "izhs",
            "state": "ownerless",
            "conditions": GAP,
            "method_codes": ["NO_SUCH_METHOD"],
        },
    )
    assert response.status_code == 422


def test_tz_rule_cannot_be_rewritten_but_can_be_disabled(client, login):
    methodologist = login("method")
    rules = client.get(
        "/api/admin/rules?object_kind=izhs&state=ownerless", headers=methodologist
    ).json()
    builtin = rules[0]

    rewrite = client.patch(
        f"/api/admin/rules/{builtin['id']}",
        headers=methodologist,
        json={"method_codes": ["ESCHEAT.v1"]},
    )
    assert rewrite.status_code == 409
    assert "ТЗ" in rewrite.json()["detail"]

    disabled = client.patch(
        f"/api/admin/rules/{builtin['id']}", headers=methodologist, json={"is_active": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False


def test_disabled_rule_stops_matching(client, login):
    methodologist = login("method")
    specialist = login("spec_a")
    answers = {
        "rights_obj": True, "rights_land": True, "owner_status": "dead",
        "taxpayer": False, "registered_citizens": False, "heirs": False,
    }

    assert preview(client, specialist, answers).json()["outcomes"][0]["exact"] is True

    matched = next(
        rule
        for rule in client.get(
            "/api/admin/rules?object_kind=izhs&state=ownerless", headers=methodologist
        ).json()
        if rule["code"] == "izhs.ownerless.1"
    )
    client.patch(
        f"/api/admin/rules/{matched['id']}", headers=methodologist, json={"is_active": False}
    )

    assert preview(client, specialist, answers).json()["outcomes"][0]["exact"] is False


def test_resync_restores_builtin_rules_without_touching_custom_ones(client, login):
    operator, methodologist = login("operator"), login("method")

    custom = client.post(
        "/api/admin/rules",
        headers=methodologist,
        json={
            "object_kind": "izhs", "state": "ownerless",
            "conditions": GAP, "method_codes": ["OWNERLESS_TITLE.v1"],
        },
    ).json()

    result = client.post("/api/admin/rules/resync", headers=operator)
    assert result.status_code == 200
    assert result.json()["updated"] == 61

    rules = client.get("/api/admin/rules", headers=methodologist).json()
    assert len(rules) == 62
    survivor = next(rule for rule in rules if rule["id"] == custom["id"])
    assert survivor["is_builtin"] is False


def test_only_operator_can_resync(client, login):
    assert client.post("/api/admin/rules/resync", headers=login("method")).status_code == 403


def test_dictionaries_expose_the_questionnaire(client, login):
    body = client.get("/api/catalog/dictionaries", headers=login("spec_a")).json()

    assert {item["value"] for item in body["object_kinds"]} == {
        "izhs", "mkd_apartment", "nonresidential"
    }
    assert {item["value"] for item in body["states"]} == {
        "ownerless", "fpo", "emergency", "cs_mode"
    }
    assert [attr["key"] for attr in body["attributes"]] == [
        "rights_obj", "rights_land", "owner_status", "taxpayer",
        "registered_citizens", "heirs",
    ]
    # Каждый признак подсказывает, из какого ответа органа он берётся.
    assert all(attr["source_hint"] for attr in body["attributes"])
