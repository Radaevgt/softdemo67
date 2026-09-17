# -*- coding: utf-8 -*-
"""Демонстрационные данные: муниципалитет, сотрудники и несколько дел.

Запускается против работающего сервера. Только для показа и ручной проверки —
в рабочий контур не заливать.
"""
import io
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8000"
DEMO_PASSWORD = "Portal2026!"
out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def call(path, data=None, token=None, form=False):
    headers, body = {}, None
    if form:
        body, headers["Content-Type"] = data.encode(), "application/x-www-form-urlencoded"
    elif data is not None:
        body, headers["Content-Type"] = json.dumps(data).encode(), "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        BASE + path, data=body, headers=headers, method="POST" if body else "GET"
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read() or "null")
    except urllib.error.HTTPError as error:
        print(f"  {path}: HTTP {error.code} {error.read().decode('utf-8')[:120]}", file=out)
        return None


def main():
    operator = call("/api/auth/login", "username=operator&password=operator", form=True)
    if not operator:
        print("Не удалось войти оператором — запустите сервер и проверьте пароль.", file=out)
        return 1
    token = operator["access_token"]

    municipality = call(
        "/api/admin/municipalities",
        {"name": "Городской округ город Бор", "code": "22740000"},
        token,
    )
    print(f"МО: {municipality['name']}", file=out)

    staff = [
        ("ivanova", "Иванова Мария Петровна", "specialist",
         "Главный специалист отдела имущественных отношений"),
        ("petrov", "Петров Сергей Николаевич", "specialist", "Ведущий специалист"),
        ("smirnova", "Смирнова Ольга Ивановна", "methodologist",
         "Начальник отдела Минимущества Нижегородской области"),
    ]
    for login, full_name, role, position in staff:
        payload = {"login": login, "password": DEMO_PASSWORD, "full_name": full_name,
                   "role": role, "position": position}
        if role == "specialist":
            payload["municipality_id"] = municipality["id"]
        call("/api/admin/users", payload, token)
        print(f"  {full_name} — {login} / {role}", file=out)

    specialist = call(
        "/api/auth/login", f"username=ivanova&password={DEMO_PASSWORD}", form=True
    )["access_token"]

    cases = [
        ("г. Бор, ул. Луначарского, д. 9", "izhs", ["ownerless"],
         "52:20:0100015:41", "52:20:0100015:7"),
        ("г. Бор, ул. Заводская, д. 14, кв. 3", "mkd_apartment", ["emergency"],
         "52:20:0100032:118", None),
        ("г. Бор, ул. Полевая, д. 2", "izhs", ["ownerless", "fpo"],
         "52:20:0100021:56", "52:20:0100021:9"),
        ("пос. Октябрьский, ул. Мира, стр. 5", "nonresidential", ["fpo"],
         "52:20:0300004:12", None),
    ]
    for address, kind, states, oks, land in cases:
        payload = {"address": address, "object_kind": kind, "states": states,
                   "cadastral_number_oks": oks}
        if land:
            payload["cadastral_number_land"] = land
        call("/api/cases", payload, specialist)
        print(f"  дело: {address}", file=out)

    print(f"\nПароль демонстрационных учётных записей: {DEMO_PASSWORD}", file=out)
    out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
