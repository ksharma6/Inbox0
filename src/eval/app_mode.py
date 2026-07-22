import os
from enum import Enum

SHADOW_MODE_ENV = "SHADOW_MODE"

_TRUE_VALUES = frozenset[str]({"1", "true", "yes", "on"})


class AppMode(Enum):
    """Controls how the pipeline handles outbound email.

    LIVE sends emails through Gmail. SHADOW runs the same pipeline but suppresses
    writes from `send_draft` and `send_reply`, ensuring no email is sent. Allows
    outcomes and metrics to be recorded for dataset creation and evaluation.
    """

    LIVE = "live"
    SHADOW = "shadow"

    @property
    def is_shadow(self) -> bool:
        return self is AppMode.SHADOW


def get_app_mode() -> AppMode:
    """Resolve the app mode from the environment.

    Reads SHADOW_MODE. Absent, empty, or any non-truthy value resolves to
    AppMode.LIVE so shadow mode is strictly opt-in.
    """
    raw = os.getenv(SHADOW_MODE_ENV, "").strip().lower()
    return AppMode.SHADOW if raw in _TRUE_VALUES else AppMode.LIVE
