import pytest
from src.eval.app_mode import AppMode


@pytest.mark.parametrize("value", ["true", "TRUE", " TrUe "])
def test_true_variants_return_shadow(monkeypatch, value):
    """Verify that normalized true values enable shadow mode."""
    monkeypatch.setenv("SHADOW_MODE", value)

    assert AppMode.get_app_mode() is AppMode.SHADOW


@pytest.mark.parametrize("value", ["false", "FALSE", " FAlse "])
def test_false_returns_live(monkeypatch, value):
    """Verify that normalized false values select live mode."""
    monkeypatch.setenv("SHADOW_MODE", value)

    assert AppMode.get_app_mode() is AppMode.LIVE


def test_none_returns_live(monkeypatch):
    """Verify that a missing setting defaults to live mode."""
    monkeypatch.delenv("SHADOW_MODE", raising=False)

    assert AppMode.get_app_mode() is AppMode.LIVE


def test_non_true_returns_live(monkeypatch):
    """Verify that an unrecognized value defaults to live mode."""
    monkeypatch.setenv("SHADOW_MODE", "TrrUUUUe")

    assert AppMode.get_app_mode() is AppMode.LIVE
