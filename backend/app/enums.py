"""Domain vocabulary shared by the rule engine, the ORM models and the API.

Values are stored as strings so that a rule edited in the admin panel and a rule
imported from the TZ are indistinguishable to the matcher.
"""
from enum import StrEnum


class ObjectKind(StrEnum):
    """Вид объекта капитального строительства."""

    IZHS = "izhs"
    MKD_APARTMENT = "mkd_apartment"
    NONRESIDENTIAL = "nonresidential"


class ObjectState(StrEnum):
    """Состояние ОКС, установленное при обследовании (этап 1 ТЗ).

    An object can carry several of these at once; the engine resolves every state
    it is given and reports the outcomes in the order of :data:`STATE_PRIORITY`.
    """

    OWNERLESS = "ownerless"
    FPO = "fpo"
    EMERGENCY = "emergency"
    CS_MODE = "cs_mode"


# Threat to life outranks the paperwork route, so an object that is both
# ownerless and in an emergency state is handled as an emergency first.
# Not stated in the TZ — confirmed as a working assumption with the customer.
STATE_PRIORITY: dict[ObjectState, int] = {
    ObjectState.CS_MODE: 0,
    ObjectState.EMERGENCY: 1,
    ObjectState.FPO: 2,
    ObjectState.OWNERLESS: 3,
}


class OwnerStatus(StrEnum):
    """Статус правообладателя.

    ``DEAD_OR_LIQUIDATED`` never appears as user input — it only exists in rules
    imported from the TZ, which merges the two for non-residential objects. The
    matcher expands it to both concrete inputs.
    """

    ALIVE = "alive"
    DEAD = "dead"
    LIQUIDATED = "liquidated"
    UNKNOWN = "unknown"
    DEAD_OR_LIQUIDATED = "dead_or_liquidated"


INPUT_OWNER_STATUSES = (
    OwnerStatus.ALIVE,
    OwnerStatus.DEAD,
    OwnerStatus.LIQUIDATED,
    OwnerStatus.UNKNOWN,
)


class Role(StrEnum):
    OPERATOR = "operator"
    METHODOLOGIST = "methodologist"
    SPECIALIST = "specialist"
    VIEWER = "viewer"


class CaseStatus(StrEnum):
    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    DECIDED = "decided"
    ARCHIVED = "archived"


class AssessmentStatus(StrEnum):
    DRAFT = "draft"
    COMPLETED = "completed"
    APPROVED = "approved"


class RoadmapItemStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    NOT_REQUIRED = "not_required"


class EscalationStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    REJECTED = "rejected"


LABELS: dict[str, dict[str, str]] = {
    "object_kind": {
        ObjectKind.IZHS: "ИЖС",
        ObjectKind.MKD_APARTMENT: "Квартира (комната, доля) в МКД",
        ObjectKind.NONRESIDENTIAL: "Нежилое",
    },
    "state": {
        ObjectState.OWNERLESS: "Бесхозяйное",
        ObjectState.FPO: "Фактически прекративший существование (ФПО)",
        ObjectState.EMERGENCY: "Аварийное",
        ObjectState.CS_MODE: "Режим ЧС или повышенной готовности",
    },
    "owner_status": {
        OwnerStatus.ALIVE: "Жив / действующее",
        OwnerStatus.DEAD: "Умер",
        OwnerStatus.LIQUIDATED: "Ликвидировано",
        OwnerStatus.UNKNOWN: "Сведения отсутствуют",
        OwnerStatus.DEAD_OR_LIQUIDATED: "Умер или ликвидировано",
    },
    "role": {
        Role.OPERATOR: "Оператор системы",
        Role.METHODOLOGIST: "Методолог",
        Role.SPECIALIST: "Специалист ОМСУ",
        Role.VIEWER: "Наблюдатель",
    },
}
