"""GEO ← 知识库（只读 + 快照）与 GEO → 顾问（只读交接面）。

Owner 2026-09-20 拍板：
1. GEO 不允许写知识库；
2. 读到的所有信息存进 GEO 自己的库（快照）；
3. 留一个让顾问查 GEO 库的接口。

这三条各自要有回归，不然「封死了」「记上了」「验签了」都只是说法。
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient



# ── 1. 不写知识库 ───────────────────────────────────────────────


def test_write_candidate_is_refused_with_403():
    from adapters.eios import AuthorityWriteNotAllowed, write_candidate

    with pytest.raises(AuthorityWriteNotAllowed) as exc:
        asyncio.run(write_candidate(canonical_name="甲", predicate="是", value="乙"))
    assert exc.value.status == 403
    assert exc.value.code == "AUTHORITY_WRITE_NOT_ALLOWED"


def test_scope_table_has_no_write_scope():
    """scope 表是写死的常量；它一旦长出写 scope，上面那条 403 就名存实亡。"""
    from adapters.eios import KNOWLEDGE_READ_SCOPES

    assert all(s.endswith((".read", ".search")) for s in KNOWLEDGE_READ_SCOPES)
    assert not any(w in s for s in KNOWLEDGE_READ_SCOPES for w in ("write", "publish", "govern"))


def test_market_confirm_refuses_to_write_the_knowledge_base(monkeypatch):
    """旧的「人工确认 → write_candidate 写知识库」端点必须明确拒绝，而不是静默失败。"""
    import app.api.v1.market as market
    import services.collector as collector

    monkeypatch.setattr(
        collector, "_load_raw", lambda: [{"id": "sig_1", "facts": ["甲|是|乙"]}]
    )
    body = asyncio.run(market.confirm_signal("sig_1"))
    assert body["ok"] is False
    assert body["error"]["code"] == "AUTHORITY_WRITE_NOT_ALLOWED"


# ── 2. 读到的内容落进 GEO 自己的库（快照） ──────────────────────


@pytest.fixture()
def snapshot_db():
    """每个测试一个自己的租户柜。

    测试进程共用一份临时库（``tests/conftest.py`` 钉的 GEO_DB_PATH），所以不换柜的话
    几个测试会互相看见对方的快照 —— 那会让「去重」和「汇总」的断言变成运气。
    """
    import uuid

    from app.models.geo_models import engine, init_db
    from app.services.store import set_tenant

    init_db()
    try:
        set_tenant(f"tenant_test_{uuid.uuid4().hex[:8]}")
        yield
    finally:
        set_tenant("tenant_corp_01")
        engine.dispose()


def test_snapshot_records_and_dedupes(snapshot_db):
    from app.services import knowledge_snapshot as snap

    payload = {
        "contract": "eios.knowledge_search_result/v2",
        "query": "亚宇臻隆",
        "query_id": "q_1",
        "matched": True,
        "hits": [{"object_id": "ko_1", "document_id": "doc_1", "snippet": "…"}],
    }
    first = snap.record("search", payload, source_url="http://127.0.0.1:8040")
    assert first["recorded"] is True
    # 同一次读再来一遍：query_id 每次都变，但它说不出「读到了什么」，不该进哈希
    again = snap.record("search", {**payload, "query_id": "q_2"}, source_url="http://127.0.0.1:8040")
    assert again["recorded"] is False
    assert again["read_count"] == 2
    rows = snap.list_recent(kind="search")
    assert len(rows) == 1
    assert rows[0]["authoritative"] is False
    assert rows[0]["source"] == "eios-knowledge"
    assert rows[0]["payload"]["hits"][0]["object_id"] == "ko_1"


def test_snapshot_hash_ignores_volatile_fields_only(snapshot_db):
    from app.services.knowledge_snapshot import payload_hash

    base = {"contract": "c", "query": "q", "hits": []}
    assert payload_hash(base) == payload_hash({**base, "query_id": "q_9", "read_at": "2026-09-20"})
    assert payload_hash(base) != payload_hash({**base, "query": "别的"})


def test_snapshot_summary_reports_readiness(snapshot_db):
    from app.services import knowledge_snapshot as snap

    snap.record("objects", {"contract": "eios.knowledge_object_list", "count": 120, "items": []})
    snap.record("documents", {"contract": "eios.knowledge_documents", "count": 17, "items": []})
    summary = snap.summary()
    assert summary["read_ever"] is True
    assert summary["objects_seen"] == 120
    assert summary["documents_seen"] == 17
    assert summary["authoritative"] is False


# ── 3. 顾问查 GEO 的只读交接面 ──────────────────────────────────


class _Context:
    deployment_id = "dep_beichen_dev"
    enterprise_id = "enterprise_beichen"
    subject = "system:eios-advisor"
    service_id = "eios-advisor"
    purpose = "product.knowledge_consume"

    def __init__(self, scopes):
        self.scopes = scopes


def _formal_pdp(readers=("eios-advisor",), scopes=("geo.knowledge.read",)):
    """本部署声明的正式读策略：``deployment_reads`` 判业务读取用的就是这一类。"""
    from eios_policy import BusinessReadPolicyDecisionPoint

    return BusinessReadPolicyDecisionPoint(readers=list(readers), scopes=list(scopes))


def _app(verifier, pdp=None):
    from app.api.v1 import geo_consumer
    from app.core.envelope import err
    from app.product.consumer_auth import ConsumerAuthError

    app = FastAPI()
    app.state.consumer_token_verifier = verifier
    if pdp is not None:
        app.state.consumer_pdp = pdp

    @app.exception_handler(ConsumerAuthError)
    async def _failed(_request: Request, exc: ConsumerAuthError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=exc.status_code, content=err(exc.code, exc.message))

    app.include_router(geo_consumer.router)
    return app


def test_consumer_requires_a_token():
    app = _app(lambda token, *, audience: _Context(["geo.knowledge.read"]))
    with TestClient(app) as client:
        response = client.get("/api/v1/geo/consumer/summary")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_CONTEXT_REQUIRED"


def test_consumer_rejects_an_invalid_token():
    def verifier(token, *, audience):
        raise ValueError("signature mismatch")

    app = _app(verifier)
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/geo/consumer/summary", headers={"EIOS-Auth-Context": "bogus"}
        )
    assert response.status_code == 401


def test_consumer_requires_the_read_scope():
    app = _app(lambda token, *, audience: _Context(["knowledge.search"]))
    with TestClient(app) as client:
        response = client.get("/api/v1/geo/consumer/summary", headers={"EIOS-Auth-Context": "t"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "GEO_CONSUMER_SCOPE_REQUIRED"


def test_consumer_serves_summary_for_a_scoped_reader(snapshot_db, monkeypatch):
    from app.services import knowledge_snapshot as snap

    snap.record("objects", {"contract": "eios.knowledge_object_list", "count": 3, "items": []})
    app = _app(lambda token, *, audience: _Context(["geo.knowledge.read"]), pdp=_formal_pdp())
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/geo/consumer/summary", headers={"EIOS-Auth-Context": "signed"}
        )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contract"] == "product.geo_consumer/v1"
    assert data["read_by"]["service_id"] == "eios-advisor"
    assert data["knowledge_snapshots"]["objects_seen"] == 3
    assert "tenant_id" in data  # 租户仍是 legacy 柜，如实报出来
    # 「已授权」必须对回一次真实决策，不能由 GEO 自己拼一个说法。
    assert data["policy"]["decision_id"].startswith("pdec_")
    assert data["policy"]["policy_version"].startswith("eios.business_reads/v1:")
    assert data["policy"]["allow"] is True
    assert data["policy"]["enforcement"] == "enforced"


def test_consumer_default_verifier_fails_closed_without_trust_keys(monkeypatch):
    """没配信任钥 → 503（不是放行，也不是 500）。"""
    from app.product.consumer_auth import ConsumerAuthError, _default_verifier

    monkeypatch.delenv("EIOS_GEO_CONSUMER_TRUST_KEYS", raising=False)
    monkeypatch.delenv("EIOS_AUTH_PUBLIC_KEY_PATH", raising=False)
    with pytest.raises(ConsumerAuthError) as exc:
        _default_verifier("token", audience="eios-geo")
    assert exc.value.status_code == 503
    assert exc.value.code == "GEO_CONSUMER_AUTH_NOT_CONFIGURED"


# ── 3b. 正式 PDP（Owner 2026-09-21）──────────────────────────────


def test_consumer_without_a_pdp_is_503_not_an_allow():
    """没有 PDP = 证明不了「谁可以读」→ 503。放行会把「没人判过」说成「允许」。"""
    app = _app(lambda token, *, audience: _Context(["geo.knowledge.read"]))
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/geo/consumer/summary", headers={"EIOS-Auth-Context": "signed"}
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEPENDENCY_NOT_ACTIVE"


def _read(pdp, *, scopes=("geo.knowledge.read",), service_id="eios-advisor"):
    """用一张形状正确的票打消费面，只有 PDP 不同。"""

    class _Who(_Context):
        pass

    _Who.service_id = service_id
    app = _app(lambda token, *, audience: _Who(list(scopes)), pdp=pdp)
    with TestClient(app) as client:
        return client.get("/api/v1/geo/consumer/summary", headers={"EIOS-Auth-Context": "signed"})


def test_formal_pdp_serves_a_declared_reader_with_a_real_200(snapshot_db):
    response = _read(_formal_pdp())
    assert response.status_code == 200
    assert response.json()["data"]["policy"]["enforcement"] == "enforced"


def test_formal_pdp_refuses_an_undeclared_reader_with_a_real_403(snapshot_db):
    """票上 audience + scope 全对，但本部署没有声明这个读者 → 403，理由照实转述。"""
    response = _read(_formal_pdp(), service_id="eios-other")
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "GEO_CONSUMER_PDP_DENIED"
    assert "eios-other" in error["message"]
    assert "declared business reader" in error["message"]


def test_formal_pdp_refuses_an_undeclared_power_carried_on_the_ticket(snapshot_db):
    """多带一个本部署没声明成「读取」的权力也要被拒 —— 不是只看 required scope 在不在。"""
    response = _read(_formal_pdp(), scopes=("geo.knowledge.read", "knowledge.write"))
    assert response.status_code == 403
    error = response.json()["error"]
    assert error["code"] == "GEO_CONSUMER_PDP_DENIED"
    assert "knowledge.write" in error["message"]


def test_consumer_reports_development_allow_as_not_enforcement(snapshot_db):
    """dev 替身允许一切，但它**不是**强制 —— 响应里必须照原样说出来。"""
    from eios_policy import DevelopmentAllowPolicyDecisionPoint

    app = _app(
        lambda token, *, audience: _Context(["geo.knowledge.read"]),
        pdp=DevelopmentAllowPolicyDecisionPoint(),
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/geo/consumer/summary", headers={"EIOS-Auth-Context": "signed"}
        )
    assert response.status_code == 200
    assert response.json()["data"]["policy"]["enforcement"] == "development_allow"


def test_consumer_refuses_resource_constraints_instead_of_ignoring_them(snapshot_db):
    """这个面按部署级读取判定，裁剪不了资源 —— 收到资源级约束就拒绝，不能忽略。"""
    from eios_policy import PolicyDecision, PolicyUnavailable

    class _Constrained:
        def decide(self, payload):
            return PolicyDecision(True, "pdec_x", "v1", {"resource_ids": ["ko_1"]})

    class _Unavailable:
        def decide(self, payload):
            raise PolicyUnavailable("PDP is not configured")

    constrained = _read(_Constrained())
    assert constrained.status_code == 503
    assert constrained.json()["error"]["code"] == "DEPENDENCY_NOT_ACTIVE"

    unavailable = _read(_Unavailable())
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "DEPENDENCY_NOT_ACTIVE"


def test_pdp_payload_matches_the_foundation_readgate_shape(snapshot_db):
    """payload 形状与 Foundation 各读门逐字段一致，否则两边的策略没法共用一份声明。"""
    seen: dict = {}

    class _Capture:
        def decide(self, payload):
            from eios_policy import PolicyDecision

            seen.update(payload)
            return PolicyDecision(True, "pdec_cap", "v1", {})

    assert _read(_Capture()).status_code == 200
    assert set(seen) == {
        "subject",
        "service_id",
        "purpose",
        "scopes",
        "deployment_id",
        "enterprise_id",
        "action",
        "resource",
    }
    assert seen["action"] == "geo.knowledge.read"
    assert seen["resource"] == {"type": "geo_consumer_store", "id": "eios-geo"}
    assert seen["service_id"] == "eios-advisor"
    assert seen["purpose"] == "product.knowledge_consume"
    assert seen["scopes"] == ["geo.knowledge.read"]


# ── 4. 出站票的签发 fail-closed ─────────────────────────────────


def test_signer_refuses_to_call_without_deployment_claims(monkeypatch):
    import adapters.eios as eios

    for name in (
        "EIOS_DEPLOYMENT_ID",
        "EIOS_ENTERPRISE_ID",
        "EIOS_GEO_SUBJECT",
        "EIOS_AUTH_ISSUER",
        "EIOS_AUTH_KID",
        "EIOS_AUTH_PRIVATE_KEY_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(eios.EIOSKnowledgeError) as exc:
        eios._sign_token()
    assert exc.value.code == "KNOWLEDGE_SIGNER_NOT_CONFIGURED"
    assert exc.value.status == 503


def test_snapshot_failure_marks_the_read_as_unrecorded(monkeypatch):
    """快照记不上不能把读弄失败，但也不能假装记上了。"""
    import adapters.eios as eios

    async def fake_request(method, path, **kwargs):
        return {"contract": "eios.knowledge_search_result/v2", "hits": [], "matched": False}

    monkeypatch.setattr(eios, "_request", fake_request)
    monkeypatch.setattr(eios, "_record", lambda kind, payload: False)
    result = asyncio.run(eios.search_knowledge("测试"))
    assert result["snapshot_recorded"] is False
    assert json.dumps(result, ensure_ascii=False)  # 结果本身照常返回
