# -*- coding: utf-8 -*-
"""Rebuilds the decision-rule seed from the customer's source TZ (.docx).

The TZ describes stage 4 as prose: each scenario is a list of attributes, and the
"Способ ..." blocks that follow bind one or more procedures to a range of scenarios.
This tool reconstructs that binding, validates it, and writes app/seed/rules_seed.json.

The generated seed is committed so the application does not depend on the .docx at
runtime, but it must stay reproducible: rerun this tool whenever the TZ changes.

Usage:
    python tools/extract_tz.py "path/to/ТЗ.docx"
"""
from __future__ import annotations

import html
import json
import re
import sys
import zipfile
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[1] / "app" / "seed" / "rules_seed.json"

OBJECT_KINDS = {
    "ижс": "izhs",
    "квартира в мкд": "mkd_apartment",
    "нежилое": "nonresidential",
}
STATE_KEYS = {
    "Бесхозяйное": "ownerless",
    "ФПО": "fpo",
    "Аварийное": "emergency",
    "Режим ЧС или ПГ": "cs_mode",
}
OWNER_STATUS = {
    "жив": "alive",
    "мёртв": "dead",
    "нет": "unknown",
    "мёртв/ликвидировано": "dead_or_liquidated",
    "мёрт/ликвидировано": "dead_or_liquidated",  # typo in the source TZ
}
YES_NO = {"да": True, "нет": False}

ATTRIBUTES = {
    "Вид объекта": "object_kind",
    "Права на объект": "rights_obj",
    "Права на земельный участок": "rights_land",
    "Статус правообладателя": "owner_status",
    "Налогоплательщик": "taxpayer",
    "Прописанные граждане": "registered_citizens",
    "Наследники": "heirs",
}
ATTRIBUTES.update(STATE_KEYS)

# Readable codes instead of hashes, keyed by the procedure title as written in the TZ.
METHOD_CODES = {
    "признание права муниципальной собственности на бесхозяйное имущество": "OWNERLESS_TITLE",
    "оформление права муниципальной собственности на выморочное имущество": "ESCHEAT",
    "оформление права муниципальной собственности на выморочное имущество "
    "(если собственник физическое лицо)": "ESCHEAT_INDIVIDUAL",
    "включение окс и земельного участка в реестр муниципального имущества": "MUNICIPAL_REGISTRY",
    "реквизиция": "REQUISITION",
    "демонтаж остаточных элементов фпо": "FPO_DEMOLITION",
}
# The TZ title for this one is a long sentence with a typo ("подлещажим").
MKD_EMERGENCY_PREFIX = "признание мкд аварийным"
MKD_EMERGENCY = (
    "MKD_EMERGENCY_SEIZURE",
    "Признание МКД аварийным и подлежащим сносу или реконструкции с последующим "
    "изъятием земельного участка и жилых помещений для муниципальных нужд",
)

DASHES = "-–—"


def read_docx(path: Path) -> list[str]:
    """Returns the document's paragraphs as plain text lines."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", "ignore")
    xml = xml.replace("</w:p>", "\n</w:p>")
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    text = html.unescape(re.sub(r"<[^>]+>", "", xml))
    return [normalize(line) for line in text.split("\n")]


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).replace(" ", " ").strip()


def is_boundary(line: str) -> bool:
    return (
        bool(re.match(r"^Сценари[ий]\s*№", line))
        or line.startswith("В отношении")
        or line.startswith("Способ")
    )


def title_case(title: str) -> str:
    """The TZ writes some procedure titles in lower case mid-sentence."""
    return title[:1].upper() + title[1:] if title else title


def parse(lines: list[str]) -> tuple[list[dict], list[dict]]:
    """Splits the document into scenario definitions and method blocks."""
    scenarios: list[dict] = []
    blocks: list[dict] = []
    group: str | None = None
    current: dict | None = None
    index = 0

    while index < len(lines):
        line = lines[index]

        if line.startswith("В отношении"):
            group = line
            if current:
                scenarios.append(current)
                current = None

        header = re.match(r"^Сценари[ий]\s*№?\s*(\d+)", line)
        if header:
            if current:
                scenarios.append(current)
            current = {"num": int(header.group(1)), "group": group, "line": index + 1, "attrs": {}}
            index += 1
            continue

        if current is not None:
            pair = re.match(r"^(.+?)\s*[" + DASHES + r"]\s*(.+)$", line)
            if pair:
                key = ATTRIBUTES.get(normalize(pair.group(1)).rstrip(DASHES + " "))
                if key:
                    current["attrs"][key] = normalize(pair.group(2)).lower().rstrip(". ")
                    index += 1
                    continue
            if is_boundary(line):
                scenarios.append(current)
                current = None

        if line.startswith("Способ") and not re.match(r"^Способ\s*№\s*\d+\.", line):
            blocks.append(parse_method_block(lines, index, group, scenarios))
            index = blocks[-1].pop("_next")
            continue

        index += 1

    if current:
        scenarios.append(current)
    return scenarios, blocks


def parse_method_block(lines: list[str], index: int, group: str | None, scenarios: list[dict]) -> dict:
    """Reads a 'Способ(ы) для сценариев ...' header and the procedures beneath it."""
    line = lines[index]
    numbers = [int(x) for x in re.findall(r"№\s*(\d+)", line)]
    if "по" in line and "с №" in line and len(numbers) >= 2:
        scenario_ids = list(range(numbers[0], numbers[-1] + 1))
    elif numbers:
        scenario_ids = numbers
    else:
        # A bare "Способы:" applies to the scenario immediately above it.
        scenario_ids = [scenarios[-1]["num"]] if scenarios else []

    methods: list[dict] = []
    inline = line.split(":", 1)[1].strip().rstrip(".") if ":" in line else ""
    if inline:
        methods.append({"title": inline, "steps": []})

    cursor = index + 1
    while cursor < len(lines):
        entry = lines[cursor]
        if re.match(r"^Сценари[ий]\s*№", entry) or entry.startswith("В отношении"):
            break
        numbered = re.match(r"^Способ\s*№\s*\d+\.\s*(.+)$", entry)
        if numbered:
            methods.append({"title": numbered.group(1).strip().rstrip("."), "steps": []})
        elif entry.startswith("Способ"):
            break
        elif entry.startswith("Порядок действий") or not entry:
            pass
        elif methods:
            text = entry.lstrip(DASHES + " ").strip()
            # A non-bulleted line ending in ':' is a sub-heading inside the procedure
            # ("При согласии собственника ...:"), not an action to be checked off.
            is_bullet = entry[:1] in DASHES
            kind = "header" if text.endswith(":") and not is_bullet else "action"
            methods[-1]["steps"].append({"kind": kind, "text": text})
        cursor += 1

    return {"group": group, "scenario_ids": scenario_ids, "methods": methods, "_next": cursor}


def state_of(attrs: dict) -> str | None:
    for key in STATE_KEYS.values():
        if key in attrs:
            return key
    return None


def method_identity(title: str) -> tuple[str, str]:
    """Maps a TZ procedure title to a stable code and a cleaned-up display title."""
    key = title.lower().strip()
    if key.startswith(MKD_EMERGENCY_PREFIX):
        return MKD_EMERGENCY
    for known, code in METHOD_CODES.items():
        if key == known:
            return code, title_case(title)
    raise ValueError(f"неизвестный способ в ТЗ: {title!r}")


def build(scenarios: list[dict], blocks: list[dict]) -> tuple[list[dict], list[dict]]:
    # Each prose heading in the TZ covers exactly one (object kind, state) pair.
    groups: dict[str, tuple[str, str]] = {}
    for scenario in scenarios:
        groups.setdefault(
            scenario["group"],
            (OBJECT_KINDS[scenario["attrs"]["object_kind"]], state_of(scenario["attrs"])),
        )

    # One title can carry different step lists across branches (e.g. the land-plot
    # formation step is only present when the plot has no registered rights), so each
    # distinct (title, steps) pair becomes its own catalog entry with a version suffix.
    variants: dict[tuple, str] = {}
    catalog: list[dict] = []

    def register(method: dict) -> str:
        code, display = method_identity(method["title"])
        signature = (code, tuple((s["kind"], s["text"]) for s in method["steps"]))
        if signature not in variants:
            version = sum(1 for existing in variants if existing[0] == code) + 1
            variants[signature] = f"{code}.v{version}"
            catalog.append(
                {
                    "code": variants[signature],
                    "family": code,
                    "version": version,
                    "title": display,
                    "steps": method["steps"],
                }
            )
        return variants[signature]

    bindings: dict[tuple, list[str]] = {}
    for block in blocks:
        kind, state = groups[block["group"]]
        codes = [register(method) for method in block["methods"]]
        for scenario_id in block["scenario_ids"]:
            bindings[(kind, state, scenario_id)] = codes

    rules = []
    for scenario in scenarios:
        attrs = scenario["attrs"]
        kind, state = OBJECT_KINDS[attrs["object_kind"]], state_of(attrs)
        conditions = {
            "rights_obj": YES_NO[attrs["rights_obj"]],
            "rights_land": YES_NO[attrs["rights_land"]],
            "owner_status": OWNER_STATUS[attrs["owner_status"]],
            "taxpayer": YES_NO[attrs["taxpayer"]],
        }
        if "registered_citizens" in attrs:
            conditions["registered_citizens"] = YES_NO[attrs["registered_citizens"]]
        if "heirs" in attrs:
            conditions["heirs"] = YES_NO[attrs["heirs"]]
        rules.append(
            {
                "code": f"{kind}.{state}.{scenario['num']}",
                "object_kind": kind,
                "state": state,
                "scenario_num": scenario["num"],
                "conditions": conditions,
                "methods": bindings.get((kind, state, scenario["num"]), []),
                "source": f"{scenario['group']} Сценарий № {scenario['num']}",
            }
        )
    return rules, catalog


def validate(rules: list[dict], methods: list[dict]) -> list[str]:
    errors: list[str] = []
    codes = {method["code"] for method in methods}

    for rule in rules:
        if not rule["methods"]:
            errors.append(f"{rule['code']}: не привязан ни один способ")
        for code in rule["methods"]:
            if code not in codes:
                errors.append(f"{rule['code']}: ссылка на несуществующий способ {code}")
        if rule["conditions"]["owner_status"] in ("dead", "dead_or_liquidated"):
            if "heirs" not in rule["conditions"]:
                errors.append(f"{rule['code']}: правообладатель мёртв, но признак «наследники» не задан")
        if rule["object_kind"] == "nonresidential" and "registered_citizens" in rule["conditions"]:
            errors.append(f"{rule['code']}: признак «прописанные граждане» у нежилого объекта")

    seen: dict[tuple, str] = {}
    for rule in rules:
        key = (rule["object_kind"], rule["state"], tuple(sorted(rule["conditions"].items())))
        if key in seen:
            errors.append(f"конфликт условий: {rule['code']} и {seen[key]}")
        seen[key] = rule["code"]

    for method in methods:
        if not method["steps"]:
            errors.append(f"способ {method['code']} «{method['title']}»: пустой порядок действий")
    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    source = Path(sys.argv[1])
    scenarios, blocks = parse(read_docx(source))
    rules, methods = build(scenarios, blocks)
    errors = validate(rules, methods)

    for error in errors:
        print(f"ОШИБКА: {error}", file=sys.stderr)
    if errors:
        return 1

    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEED_PATH.write_text(
        json.dumps(
            {"source_document": source.name, "methods": methods, "rules": rules},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"{len(rules)} правил, {len(methods)} способов -> {SEED_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
