import asyncio

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.product.http_auth import (
    AuthContextInvalid,
    AuthContextVerifierUnavailable,
    ProductAuthenticationError,
    auth_context_mode_enabled,
    resolve_http_product_session,
)


def _app_with_verifier(verifier=None):
    app = FastAPI()
    if verifier is not None:
        app.state.auth_context_verifier = verifier

    @app.get("/session")
    async def session(request: Request):
        resolved = await resolve_http_product_session(request)
        return {"enterprise_id": resolved.enterprise_id, "principal_id": resolved.principal_id}

    return app


def test_auth_context_mode_is_explicit(monkeypatch):
    monkeypatch.setenv("GEO_AUTH_MODE", "auth_context")
    assert auth_context_mode_enabled() is True
    monkeypatch.setenv("GEO_AUTH_MODE", "legacy")
    assert auth_context_mode_enabled() is False


def test_http_product_session_requires_bearer_token():
    app = _app_with_verifier(lambda _: None)
    request = type("RequestStub", (), {"headers": {}, "app": app})()
    try:
        asyncio.run(resolve_http_product_session(request))
    except ProductAuthenticationError as exc:
        assert exc.code == "AUTH_CONTEXT_REQUIRED"
    else:
        raise AssertionError("missing bearer token must fail")


def test_http_product_session_uses_injected_verifier_only():
    class Context:
        deployment_id = "dep_test"
        enterprise_id = "enterprise_test"
        subject = "human:alice"
        service_id = "eios-geo"

    app = _app_with_verifier(lambda token: Context() if token == "signed" else None)
    with TestClient(app) as client:
        response = client.get("/session", headers={"Authorization": "Bearer signed"})
    assert response.status_code == 200
    assert response.json()["enterprise_id"] == "enterprise_test"


def test_http_product_session_classifies_invalid_and_unavailable_verifiers():
    request = type("RequestStub", (), {"headers": {"Authorization": "Bearer signed"}})()
    request.app = _app_with_verifier(lambda _: (_ for _ in ()).throw(AuthContextInvalid("bad")))
    try:
        asyncio.run(resolve_http_product_session(request))
    except ProductAuthenticationError as exc:
        assert (exc.code, exc.status_code) == ("AUTH_CONTEXT_INVALID", 401)
    else:
        raise AssertionError("invalid bearer must fail")
    request.app = _app_with_verifier(lambda _: (_ for _ in ()).throw(AuthContextVerifierUnavailable("down")))
    try:
        asyncio.run(resolve_http_product_session(request))
    except ProductAuthenticationError as exc:
        assert (exc.code, exc.status_code) == ("AUTH_CONTEXT_UNAVAILABLE", 503)
    else:
        raise AssertionError("unavailable verifier must fail closed")


def test_strict_http_mode_fails_closed_until_product_storage_is_ready(monkeypatch):
    from app.main import app

    class Context:
        deployment_id = "dep_test"
        enterprise_id = "enterprise_test"
        subject = "human:alice"
        service_id = "eios-geo"

    monkeypatch.setenv("GEO_RUNTIME_MODE", "baseline")
    monkeypatch.setenv("GEO_AUTH_MODE", "auth_context")
    monkeypatch.setenv("GEO_PRODUCT_STORAGE_MODE", "legacy")
    monkeypatch.setattr(app.state, "auth_context_verifier", lambda _: Context(), raising=False)

    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 401
        assert client.get("/api/v1/health", headers={"Authorization": "Bearer signed"}).status_code == 200
        blocked = client.get("/api/v1/meta/engines", headers={"Authorization": "Bearer signed"})

    assert blocked.status_code == 503
    assert blocked.json()["error"]["code"] == "PRODUCT_STORAGE_NOT_READY"
