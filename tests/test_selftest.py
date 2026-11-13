"""The build check notices when a piece the app needs at runtime, but not
to open its window, is missing: HTTPS for the update check, and the
window icon."""

import ssl

import pytest

pytest.importorskip("PySide6")

from maphide.qt.app import bundle_problems  # noqa: E402


def test_a_complete_bundle_has_no_problems(qt_app):
    assert bundle_problems() == []


def test_missing_https_support_is_reported(qt_app, monkeypatch):
    def broken():
        raise ssl.SSLError("no certificates")

    monkeypatch.setattr(ssl, "create_default_context", broken)

    assert bundle_problems() == ["HTTPS support did not load, so update checks would fail"]


def test_a_missing_icon_is_reported(qt_app, tmp_path):
    assert bundle_problems(icon_path=tmp_path / "missing.ico") == ["the window icon did not load"]
