from types import SimpleNamespace

import pytest


def test_production_defaults_to_auth_context(monkeypatch):
    from app.product.http_auth import auth_mode

    monkeypatch.delenv("GEO_AUTH_MODE", raising=False)
    monkeypatch.setenv("EIOS_ENVIRONMENT", "production")
    assert auth_mode() == "auth_context"


def test_legacy_client_guard_is_loopback_only():
    from app.product.http_auth import legacy_client_allowed

    assert legacy_client_allowed(SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")))
    assert legacy_client_allowed(SimpleNamespace(client=SimpleNamespace(host="::1")))
    assert not legacy_client_allowed(SimpleNamespace(client=SimpleNamespace(host="10.0.0.8")))
    assert not legacy_client_allowed(SimpleNamespace(client=SimpleNamespace(host="testclient")))


def test_verified_context_scopes_are_carried_to_product_session():
    from app.product.session import product_session_from_verified_auth_context

    context = SimpleNamespace(
        deployment_id="dep",
        enterprise_id="ent",
        subject="human:alice",
        service_id="geo",
        scopes=("geo.read", "geo.admin"),
    )
    session = product_session_from_verified_auth_context(context)
    assert session.scopes == ("geo.read", "geo.admin")


def test_outbound_url_rejects_private_and_non_http_targets():
    from app.security.url import UnsafeURL, validate_public_url

    with pytest.raises(UnsafeURL):
        validate_public_url("http://127.0.0.1/admin")
    with pytest.raises(UnsafeURL):
        validate_public_url("file:///etc/passwd")
