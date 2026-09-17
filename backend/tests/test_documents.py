"""Протокол проверки: формирование, содержание, хранение и выгрузка."""
import zipfile
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.documents import fonts

ANSWERS = {
    "rights_obj": True,
    "rights_land": True,
    "owner_status": "dead",
    "taxpayer": False,
    "registered_citizens": False,
    "heirs": False,
}

ADDRESS = "г. Бор, ул. Полевая, д. 2"
CADASTRAL = "52:20:0100021:56"


@pytest.fixture
def specialist(login):
    return login("spec_a")


def make_case(client, headers, states=("ownerless", "fpo")):
    response = client.post(
        "/api/cases",
        headers=headers,
        json={
            "address": ADDRESS,
            "object_kind": "izhs",
            "states": list(states),
            "cadastral_number_oks": CADASTRAL,
            "cadastral_number_land": "52:20:0100021:9",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def decided_assessment(client, headers, case_id, answers=ANSWERS):
    assessment_id = client.post(f"/api/cases/{case_id}/assessments", headers=headers).json()["id"]
    for key, value in answers.items():
        client.patch(
            f"/api/assessments/{assessment_id}/answers",
            headers=headers,
            json={"answers": {key: value}},
        )
    assert client.post(f"/api/assessments/{assessment_id}/decide", headers=headers).status_code == 200
    return assessment_id


def docx_text(payload: bytes) -> str:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def pdf_text(payload: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(payload)).pages)


def download(client, headers, assessment_id, document_format):
    response = client.get(
        f"/api/assessments/{assessment_id}/documents/{document_format}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response


# --- формирование и хранение ------------------------------------------------


def test_document_is_generated_and_stored(client, specialist):
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)

    generated = client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist)
    assert generated.status_code == 200, generated.text

    stored = generated.json()
    assert {item["format"] for item in stored} == {"docx", "pdf"}
    for item in stored:
        assert item["size_bytes"] > 0
        assert len(item["content_sha256"]) == 64
        assert item["generated_by"]["login"] == "spec_a"
        assert item["filename"].startswith("Протокол-")

    listed = client.get(f"/api/assessments/{assessment_id}/documents", headers=specialist)
    assert [item["format"] for item in listed.json()] == ["docx", "pdf"]


def test_download_returns_the_stored_bytes(client, specialist):
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)
    stored = client.post(
        f"/api/assessments/{assessment_id}/documents", headers=specialist
    ).json()

    for item in stored:
        response = download(client, specialist, assessment_id, item["format"])
        assert len(response.content) == item["size_bytes"]
        assert response.headers["x-content-sha256"] == item["content_sha256"]
        # Кириллическое имя передаётся по RFC 6266, ASCII-вариант — для старых клиентов.
        assert "filename*=UTF-8''" in response.headers["content-disposition"]
        assert f'filename="protocol.{item["format"]}"' in response.headers["content-disposition"]

    assert download(client, specialist, assessment_id, "docx").headers["content-type"].startswith(
        "application/vnd.openxmlformats"
    )
    assert download(client, specialist, assessment_id, "pdf").headers["content-type"] == (
        "application/pdf"
    )


def test_regenerating_replaces_rather_than_duplicates(client, specialist):
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)

    first = client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist).json()
    again = client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist).json()

    assert len(client.get(f"/api/assessments/{assessment_id}/documents", headers=specialist).json()) == 2
    assert {item["id"] for item in first} == {item["id"] for item in again}


def test_document_cannot_be_generated_without_a_decision(client, specialist):
    case_id = make_case(client, specialist)
    assessment_id = client.post(
        f"/api/cases/{case_id}/assessments", headers=specialist
    ).json()["id"]

    response = client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist)
    assert response.status_code == 409
    assert "не рассчитано" in response.json()["detail"]


def test_missing_format_returns_404(client, specialist):
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)
    assert client.get(
        f"/api/assessments/{assessment_id}/documents/docx", headers=specialist
    ).status_code == 404


# --- содержание -------------------------------------------------------------


@pytest.mark.parametrize("document_format,extract", [("docx", docx_text), ("pdf", pdf_text)])
def test_document_carries_the_whole_assessment(client, specialist, document_format, extract):
    """Оба формата собираются из одной структуры и обязаны нести одно и то же."""
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)
    client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist)

    text = extract(download(client, specialist, assessment_id, document_format).content)

    # Карточка объекта.
    assert "ПРОТОКОЛ" in text
    assert "Полевая" in text
    assert CADASTRAL in text

    # Ответы на опрос вместе с источником сведений.
    assert "Статус правообладателя" in text
    assert "Справка о смерти" in text
    assert "Права на объект зарегистрированы" in text

    # Оба состояния и оба способа с порядком действий.
    assert "Демонтаж остаточных элементов" in text
    assert "Признание права муниципальной" in text
    assert "Выявление ОКС, обладающего признаками бесхозяйного имущества" in text

    # Сведения о проведении проверки.
    assert "Специалист А" in text
    assert "Версия набора правил" in text


def test_document_records_the_approval_and_its_fingerprint(client, specialist):
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)

    approved = client.post(f"/api/assessments/{assessment_id}/approve", headers=specialist)
    assert approved.status_code == 200, approved.text
    fingerprint = approved.json()["content_hash"]

    text = docx_text(download(client, specialist, assessment_id, "docx").content)
    assert fingerprint in text
    assert "Решение утвердил" in text
    # Пока УКЭП не подключена, документ обязан говорить об этом прямо.
    assert "электронная подпись не применялась" in text


def test_unresolved_scenario_is_marked_as_preliminary(client, specialist):
    """Бесхозяйное ИЖС с живым правообладателем в матрице ТЗ не описано."""
    case_id = make_case(client, specialist, states=("ownerless",))
    assessment_id = decided_assessment(
        client,
        specialist,
        case_id,
        {
            "rights_obj": True,
            "rights_land": True,
            "owner_status": "alive",
            "taxpayer": True,
            "registered_citizens": False,
        },
    )
    client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist)
    text = docx_text(download(client, specialist, assessment_id, "docx").content)

    assert "предварительный характер" in text
    assert "точный сценарий" in text.lower()
    # Ближайшие сценарии с расхождениями попадают в документ.
    assert "В сценарии" in text
    assert "решение не утверждено" in text


# --- утверждение и неизменяемость -------------------------------------------


def test_approval_generates_the_document_automatically(client, specialist):
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)

    assert client.get(f"/api/assessments/{assessment_id}/documents", headers=specialist).json() == []
    client.post(f"/api/assessments/{assessment_id}/approve", headers=specialist)

    documents = client.get(
        f"/api/assessments/{assessment_id}/documents", headers=specialist
    ).json()
    assert {item["format"] for item in documents} == {"docx", "pdf"}


def test_approved_document_cannot_be_regenerated(client, specialist):
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)
    client.post(f"/api/assessments/{assessment_id}/approve", headers=specialist)

    before = client.get(f"/api/assessments/{assessment_id}/documents", headers=specialist).json()
    blocked = client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist)
    assert blocked.status_code == 409
    assert "неизменяем" in blocked.json()["detail"]

    after = client.get(f"/api/assessments/{assessment_id}/documents", headers=specialist).json()
    assert [item["content_sha256"] for item in after] == [
        item["content_sha256"] for item in before
    ]


# --- доступ -----------------------------------------------------------------


def test_document_of_another_municipality_is_hidden(client, login, specialist):
    case_id = make_case(client, login("spec_b"))
    assessment_id = decided_assessment(client, login("spec_b"), case_id)
    client.post(f"/api/assessments/{assessment_id}/documents", headers=login("spec_b"))

    assert client.get(
        f"/api/assessments/{assessment_id}/documents", headers=specialist
    ).status_code == 404
    assert client.get(
        f"/api/assessments/{assessment_id}/documents/docx", headers=specialist
    ).status_code == 404


def test_viewer_downloads_but_does_not_generate(client, login, specialist):
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)
    client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist)

    viewer = login("view_a")
    assert client.get(
        f"/api/assessments/{assessment_id}/documents/docx", headers=viewer
    ).status_code == 200
    assert client.post(
        f"/api/assessments/{assessment_id}/documents", headers=viewer
    ).status_code == 403


def test_generation_is_recorded_in_the_audit_log(client, login, specialist):
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)
    client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist)

    entries = client.get("/api/admin/audit", headers=login("operator")).json()
    record = next(entry for entry in entries if entry["action"] == "document.generate")
    assert record["actor_login"] == "spec_a"
    assert sorted(record["payload"]["formats"]) == ["docx", "pdf"]


def test_pdf_font_is_available_in_this_environment():
    """Если шрифта с кириллицей нет, PDF не предлагается вовсе, а не выдаётся битым."""
    assert fonts.is_available(), "в окружении нет шрифта с кириллицей"


def test_stored_bytes_are_authoritative_because_pdf_is_not_byte_reproducible(client, specialist):
    """PDF вшивает дату создания, поэтому пересборка даёт другой отпечаток файла.

    Отсюда и решение хранить сам файл: восстановить его байты по снимку решения
    нельзя, а подписывать и вкладывать в СЭДО нужно конкретный экземпляр.
    """
    case_id = make_case(client, specialist)
    assessment_id = decided_assessment(client, specialist, case_id)

    first = client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist).json()
    second = client.post(f"/api/assessments/{assessment_id}/documents", headers=specialist).json()

    hashes = {item["format"]: (a["content_sha256"], b["content_sha256"])
              for item in first
              for a in [item]
              for b in second if b["format"] == item["format"]}

    assert hashes["docx"][0] == hashes["docx"][1], "docx собирается детерминированно"
    assert hashes["pdf"][0] != hashes["pdf"][1], "pdf несёт дату создания"

    # Выгрузка всегда отдаёт сохранённые байты, а не пересобранные.
    stored = {item["format"]: item for item in
              client.get(f"/api/assessments/{assessment_id}/documents", headers=specialist).json()}
    for document_format, item in stored.items():
        response = download(client, specialist, assessment_id, document_format)
        assert response.headers["x-content-sha256"] == item["content_sha256"]
