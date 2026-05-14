"""Runtime feature-flag accessors.

Centralizes environment-variable reads for cross-cutting flags so callers never
parse `os.getenv` strings inline. Each accessor is a function (not a constant)
so tests can monkeypatch the environment and re-call without re-importing.
"""

import os

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_shadow_mode() -> bool:
    """Return True when Inbox0 is running in evaluation-only shadow mode.

    Shadow mode suppresses outbound Gmail sends so the rest of the pipeline
    (drafting, Slack review, metric collection) can be exercised against a real
    inbox without producing real email side effects. Default is False so live
    behavior is preserved when the variable is unset.
    """
    return os.getenv("SHADOW_MODE", "false").strip().lower() in _TRUTHY
