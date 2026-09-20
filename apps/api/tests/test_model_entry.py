"""GEO → EIOS 统一模型入口（Model Capability 服务）的 HTTP 客户端。

Owner 2026-09-21：「Model Capability 是 EIOS 的统一模型入口，不属于 GEO，也不属于
Advisor。企业部署配置模型，所有产品通过这一处调用。」

这个文件钉住四件事：
1. 没有统一入口就如实说这个部署没有入口，**不发**一个没有地址的请求，也不回落；
2. 票按 EIOS-Auth-Context 发出，scope 按路径给（目录读 / 调用各一个）；
3. 服务说什么就是什么：403 / 503 的状态码与 code 原样交给上层，GEO 不重写；
4. 服务不可达 / 答非 JSON 时给出本进程自己的、说得清的码，而不是编一个空答案。
"""
from __future__ import annotations

import httpx
import pytest

import adapters.identity as identity
import adapters.model_entry as model_entry


def _client(handler, url="http://127.0.0.1:8094") -> model_entry.ModelEntryClient:
    return model_entry.ModelEntryClient(url, transport=httpx.MockTransport(handler))


@pytest.fixture()
def signing(monkeypatch):
    monkeypatch.setattr(
        model_entry.identity, "sign", lambda **kwargs: f"ticket:{kwargs['scopes']}"
    )


def test_a_missing_entry_is_reported_as_a_missing_entry_and_nothing_is_sent(monkeypatch):
    """没有入口地址 = 这个部署没说模型在哪：报那句话，**一个请求都不发**。"""

    def explode(_request):  # pragma: no cover - 不该被调用
        raise AssertionError("没有入口地址时不该发出请求")

    monkeypatch.setattr(model_entry, "base_url", lambda: "")
    client = model_entry.ModelEntryClient("", transport=httpx.MockTransport(explode))
    assert client.configured is False
    response = client.catalog(auth_context="t")
    assert response.status == 503
    assert response.body["code"] == "MODEL_CAPABILITY_NOT_CONFIGURED"
    assert "EIOS_MODEL_CAPABILITY_URL" in response.body["message"]


def test_catalog_and_invoke_use_their_own_scope_and_path(signing):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = _client(handler)
    client.catalog(auth_context="ignored")
    client.invoke(request={"contract": "eios.model_invocation/v1"}, auth_context="ignored")

    assert [str(r.url) for r in seen] == [
        "http://127.0.0.1:8094/model/catalog",
        "http://127.0.0.1:8094/model/invoke",
    ]
    assert seen[0].method == "GET"
    assert seen[1].method == "POST"
    assert seen[0].headers["EIOS-Auth-Context"] == "ticket:('model.catalog.read',)"
    assert seen[1].headers["EIOS-Auth-Context"] == "ticket:('model.invoke',)"


def test_the_entrys_own_status_and_code_are_not_rewritten(signing):
    """服务说 403 FORBIDDEN_SCOPE，GEO 就把它交给上层 —— 不换成自己的说法。"""
    client = _client(
        lambda _r: httpx.Response(403, json={"code": "FORBIDDEN_SCOPE", "message": "denied"})
    )
    response = client.invoke(request={}, auth_context="t")
    assert response.status == 403
    assert response.body["code"] == "FORBIDDEN_SCOPE"


def test_an_unreachable_entry_is_a_named_failure_not_an_empty_answer(signing):
    def boom(_request):
        raise httpx.ConnectError("connection refused")

    response = _client(boom).catalog(auth_context="t")
    assert response.status == 503
    assert response.body["code"] == "MODEL_CAPABILITY_UNAVAILABLE"


def test_a_non_json_answer_is_a_named_failure(signing):
    response = _client(lambda _r: httpx.Response(502, text="<html>bad gateway</html>")).catalog(
        auth_context="t"
    )
    assert response.body["code"] == "MODEL_INVALID_RESPONSE"
    assert "502" in response.body["message"]
