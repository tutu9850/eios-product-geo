import os

import pytest


def test_auth_mode_legacy_compatibility_is_explicitly_overridable(monkeypatch):
    from app.product import http_auth

    monkeypatch.delenv("GEO_AUTH_MODE", raising=False)
    assert http_auth.auth_mode() == "legacy"
    monkeypatch.setenv("GEO_AUTH_MODE", "auth_context")
    assert http_auth.auth_mode() == "auth_context"


def test_content_cabinet_ignores_explicit_tenant(monkeypatch):
    from app.api.v1.content import _cabinet
    from app.services import store

    monkeypatch.setattr(store, "current_tenant", lambda: "cabinet_verified")
    assert _cabinet("attacker-selected") == "cabinet_verified"


def test_public_url_rejects_loopback_and_private(monkeypatch):
    from app.security.url import UnsafeURL, validate_public_url

    with pytest.raises(UnsafeURL):
        validate_public_url("http://127.0.0.1/metadata")
    with pytest.raises(UnsafeURL):
        validate_public_url("http://192.168.1.20/internal")


def test_public_url_rejects_non_http_and_credentials():
    from app.security.url import UnsafeURL, validate_public_url

    with pytest.raises(UnsafeURL):
        validate_public_url("file:///etc/passwd")
    with pytest.raises(UnsafeURL):
        validate_public_url("https://user:pass@example.com/")


def test_redirect_target_is_revalidated(monkeypatch):
    from app.security import url as url_security
    from app.security.url import UnsafeURL, redirect_url

    monkeypatch.setattr(url_security.socket, "getaddrinfo", lambda *args, **kwargs: [(None, None, None, None, ("93.184.216.34", 0))])
    assert redirect_url("https://example.com/start", "/next") == "https://example.com/next"
    with pytest.raises(UnsafeURL):
        redirect_url("https://example.com/start", "http://127.0.0.1/admin")
