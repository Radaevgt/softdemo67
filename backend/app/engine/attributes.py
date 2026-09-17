"""Признаки объекта, из которых складывается сценарий этапа 4.

Каждый признак — результат запроса в уполномоченный орган (этап 3 ТЗ). На этом
этапе сотрудник вводит уже полученные ответы, поэтому здесь описан только их
состав, применимость и подсказка, из какого ответа берётся значение.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..enums import INPUT_OWNER_STATUSES, LABELS, ObjectKind, OwnerStatus

BOOLEAN_LABELS = {True: "Да", False: "Нет"}


@dataclass(frozen=True)
class Option:
    value: str | bool
    label: str


@dataclass(frozen=True)
class AttributeDef:
    key: str
    label: str
    type: str  # "boolean" | "enum"
    source_hint: str
    options: tuple[Option, ...] = ()
    applies_when: Callable[[str, dict], bool] = field(default=lambda kind, answers: True)

    def is_applicable(self, object_kind: str, answers: dict) -> bool:
        return self.applies_when(object_kind, answers)

    def label_for(self, value) -> str:
        if self.type == "boolean":
            return BOOLEAN_LABELS.get(value, str(value))
        for option in self.options:
            if option.value == value:
                return option.label
        return LABELS["owner_status"].get(value, str(value))

    def accepts(self, value) -> bool:
        if self.type == "boolean":
            return isinstance(value, bool)
        return any(option.value == value for option in self.options)


def _has_registered_citizens(object_kind: str, _answers: dict) -> bool:
    """Прописанные граждане не применимы к нежилому объекту."""
    return object_kind != ObjectKind.NONRESIDENTIAL


def _has_heirs_question(_object_kind: str, answers: dict) -> bool:
    """Наследники спрашиваются, только если правообладатель не жив.

    В ТЗ признак присутствует и при статусе «сведения отсутствуют», поэтому
    условие — «не жив», а не «умер».
    """
    status = answers.get("owner_status")
    return status is not None and status != OwnerStatus.ALIVE


BOOLEAN_OPTIONS = (Option(True, "Да"), Option(False, "Нет"))

ATTRIBUTES: tuple[AttributeDef, ...] = (
    AttributeDef(
        key="rights_obj",
        label="Права на объект зарегистрированы",
        type="boolean",
        source_hint="Выписка из ЕГРН об объекте недвижимости (Росреестр) либо выписка "
        "из похозяйственной книги / реестровой книги БТИ",
        options=BOOLEAN_OPTIONS,
    ),
    AttributeDef(
        key="rights_land",
        label="Права на земельный участок зарегистрированы",
        type="boolean",
        source_hint="Выписка из ЕГРН о земельном участке либо выписка из поземельной книги",
        options=BOOLEAN_OPTIONS,
    ),
    AttributeDef(
        key="owner_status",
        label="Статус правообладателя",
        type="enum",
        source_hint="Справка о смерти (ЗАГС) для физических лиц, сведения ЕГРЮЛ "
        "для юридических лиц",
        options=tuple(Option(status, LABELS["owner_status"][status]) for status in INPUT_OWNER_STATUSES),
    ),
    AttributeDef(
        key="taxpayer",
        label="Правообладатель является плательщиком налога",
        type="boolean",
        source_hint="Ответ инспекции ФНС России о плательщике налога на имущество "
        "или земельного налога",
        options=BOOLEAN_OPTIONS,
    ),
    AttributeDef(
        key="registered_citizens",
        label="Есть граждане, зарегистрированные по месту жительства",
        type="boolean",
        source_hint="Выписка из лицевого счёта управляющей компании либо адресная "
        "справка Управления по вопросам миграции ГУ МВД",
        options=BOOLEAN_OPTIONS,
        applies_when=_has_registered_citizens,
    ),
    AttributeDef(
        key="heirs",
        label="Есть наследники, принявшие наследство",
        type="boolean",
        source_hint="Реестр наследственных дел и ответ нотариуса об открытии "
        "наследственного дела",
        options=BOOLEAN_OPTIONS,
        applies_when=_has_heirs_question,
    ),
)

ATTRIBUTES_BY_KEY: dict[str, AttributeDef] = {attr.key: attr for attr in ATTRIBUTES}


def applicable_attributes(object_kind: str, answers: dict) -> list[AttributeDef]:
    """Признаки, которые имеет смысл спрашивать при текущих ответах.

    Порядок фиксирован: применимость ``heirs`` зависит от ``owner_status``, поэтому
    список пересчитывается по мере заполнения.
    """
    return [attr for attr in ATTRIBUTES if attr.is_applicable(object_kind, answers)]


def next_unanswered(object_kind: str, answers: dict) -> AttributeDef | None:
    for attr in applicable_attributes(object_kind, answers):
        if attr.key not in answers:
            return attr
    return None


def prune(object_kind: str, answers: dict) -> dict:
    """Убирает ответы, переставшие быть применимыми.

    Если сотрудник сначала указал «умер», ответил про наследников, а затем
    исправил статус на «жив», ответ про наследников обязан исчезнуть — иначе он
    останется в снимке решения и исказит доказательную базу.
    """
    # ATTRIBUTES is ordered so that every dependency precedes its dependant
    # (owner_status before heirs), which lets one pass settle applicability.
    kept: dict = {}
    for attr in ATTRIBUTES:
        if attr.key in answers and attr.is_applicable(object_kind, kept):
            kept[attr.key] = answers[attr.key]
    return kept


def validate(object_kind: str, answers: dict) -> list[str]:
    errors: list[str] = []
    for key, value in answers.items():
        attr = ATTRIBUTES_BY_KEY.get(key)
        if attr is None:
            errors.append(f"неизвестный признак «{key}»")
        elif not attr.accepts(value):
            errors.append(f"недопустимое значение признака «{attr.label}»: {value!r}")
    for attr in applicable_attributes(object_kind, answers):
        if attr.key not in answers:
            errors.append(f"не заполнен признак «{attr.label}»")
    return errors


def validate_rule_conditions(object_kind: str, conditions: dict) -> list[str]:
    """Проверка условий правила, а не ответов сотрудника.

    Отличие одно: в правиле допустим объединённый статус «умер или ликвидировано»
    — им пользуется само ТЗ для нежилых объектов, и методолог должен иметь право
    выразить то же самое. В ответах сотрудника этот статус недопустим: сотрудник
    выбирает конкретное значение.
    """
    merged = conditions.get("owner_status") == OwnerStatus.DEAD_OR_LIQUIDATED
    if not merged:
        return validate(object_kind, conditions)

    probe = {**conditions, "owner_status": OwnerStatus.DEAD}
    return [error for error in validate(object_kind, probe) if "Статус правообладателя" not in error]


def describe(object_kind: str, answers: dict) -> list[dict]:
    """Человекочитаемый разбор ответов для карточки результата и печати."""
    return [
        {
            "key": attr.key,
            "label": attr.label,
            "value": answers[attr.key],
            "value_label": attr.label_for(answers[attr.key]),
            "source_hint": attr.source_hint,
        }
        for attr in applicable_attributes(object_kind, answers)
        if attr.key in answers
    ]
