"""Загрузка матрицы сценариев из seed-файла, собранного tools/extract_tz.py."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..engine.matcher import Method, Rule

SEED_FILE = Path(__file__).with_name("rules_seed.json")


@lru_cache
def load_seed() -> dict:
    return json.loads(SEED_FILE.read_text(encoding="utf-8"))


def seed_methods() -> list[Method]:
    return [
        Method(code=item["code"], title=item["title"], steps=item["steps"])
        for item in load_seed()["methods"]
    ]


def seed_rules() -> list[Rule]:
    return [
        Rule(
            code=item["code"],
            object_kind=item["object_kind"],
            state=item["state"],
            scenario_num=item["scenario_num"],
            conditions=item["conditions"],
            method_codes=item["methods"],
            source=item.get("source"),
        )
        for item in load_seed()["rules"]
    ]
