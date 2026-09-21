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


class _SignedContext:
    deployment_id = "dep_test"
    enterprise_id = "enterprise_test"
    subject = "human:alice"
    service_id = "eios-geo"


def test_auth_context_mode_serves_the_callers_own_cabinet(monkeypatch):
    """Owner 2026-09-22：「登录账号分柜、清掉旧柜、先把 GEO 自己的柜做对」。

    改判之前，auth_context 模式下业务面直接 503 ``PRODUCT_STORAGE_NOT_READY``
    （P1 拒绝把正式身份绑到旧 SQLite 的 tenant 列）。现在验过签之后业务面照常服务，
    只是落在**这个账号自己的柜**上：柜号由已验证的 principal 推出，调用方给的头不参与。
    """
    from fastapi import Request

    from app.main import app
    from app.services.store import current_tenant

    monkeypatch.setenv("GEO_RUNTIME_MODE", "baseline")
    monkeypatch.setenv("GEO_AUTH_MODE", "auth_context")
    monkeypatch.setenv("GEO_PRODUCT_STORAGE_MODE", "legacy")
    monkeypatch.setattr(app.state, "auth_context_verifier", lambda _: _SignedContext(), raising=False)

    @app.get("/__test/cabinet")
    async def _cabinet_probe(request: Request):  # pragma: no cover - 只被这个测试调用
        return {"cabinet": current_tenant(), "principal": request.state.product_session.principal_id}

    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/health").status_code == 401
            assert client.get("/api/v1/health", headers={"Authorization": "Bearer signed"}).status_code == 200
            served = client.get("/__test/cabinet", headers={"Authorization": "Bearer signed"})
            # 调用方自己给的柜号不许生效，柜由已验证身份决定
            spoofed = client.get(
                "/__test/cabinet",
                headers={"Authorization": "Bearer signed", "X-Tenant-Id": "tenant_someone_else"},
            )
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/__test/cabinet"]

    assert served.status_code == 200, served.text
    assert served.json() == {"cabinet": "acct_human_alice", "principal": "human:alice"}
    assert spoofed.json()["cabinet"] == "acct_human_alice"


def test_consumer_face_keeps_its_own_identity_seam(monkeypatch):
    """顾问读 GEO 的交接面自带身份门，不属于宿主门，也不因为 auth_context 模式被套上宿主票。

    两边都可能回 401 ``AUTH_CONTEXT_REQUIRED``（错误码撞名），所以这里看**文案**：
    回答的是消费面那道门（它要 ``EIOS-Auth-Context`` 头），不是宿主门（那条要 bearer）。
    """
    from app.main import app

    monkeypatch.setenv("GEO_AUTH_MODE", "auth_context")
    monkeypatch.setattr(app.state, "auth_context_verifier", lambda _: _SignedContext(), raising=False)

    with TestClient(app) as client:
        response = client.get("/api/v1/geo/consumer/summary")

    body = response.json()
    assert response.status_code == 401
    assert body["error"]["code"] == "AUTH_CONTEXT_REQUIRED"
    assert "EIOS-Auth-Context" in body["error"]["message"]
