import os
from enum import Enum


class AppMode(Enum):
    LIVE = "live"
    SHADOW = "shadow"

    @classmethod
    def get_app_mode(cls) -> "AppMode":

        app_mode = os.getenv("SHADOW_MODE")
        if app_mode is not None:
            app_mode = app_mode.strip().lower()
        else:
            app_mode = "false"

        if app_mode == "true":
            return cls.SHADOW
        else:
            return cls.LIVE
