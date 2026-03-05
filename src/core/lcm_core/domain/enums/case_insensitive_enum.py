"""Case-insensitive string enum base class.

Provides automatic case normalization via _missing_() so that
CMLWorkerStatus("RUNNING"), CMLWorkerStatus("Running"), and
CMLWorkerStatus("running") all resolve to the same enum member.

This eliminates the need for .lower() band-aids at service boundaries
where one service sends UPPERCASE and another stores lowercase.
"""

from enum import Enum


class CaseInsensitiveStrEnum(str, Enum):
    """String enum with case-insensitive lookup.

    All enum values are stored as lowercase (the canonical form).
    Lookup is case-insensitive: MyEnum("RUNNING") == MyEnum("running").

    Usage::

        class MyStatus(CaseInsensitiveStrEnum):
            ACTIVE = "active"
            STOPPED = "stopped"

        # All of these return MyStatus.ACTIVE:
        MyStatus("active")
        MyStatus("ACTIVE")
        MyStatus("Active")
    """

    @classmethod
    def _missing_(cls, value: object) -> "CaseInsensitiveStrEnum | None":
        """Resolve enum members case-insensitively."""
        if isinstance(value, str):
            lower_value = value.lower()
            for member in cls:
                if member.value == lower_value:
                    return member
        return None
