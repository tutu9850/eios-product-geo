"""GEO 存储层最小回归（2026-08-07：JSON → SQLite 后补齐）

覆盖：store roundtrip / 迁移幂等 / 媒体上传 / EIOS 知识适配层契约。
运行：cd ~/eios-geo && .venv/bin/python -m pytest apps/api/tests -v
"""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest
from fastapi.testclient import TestClient



@pytest.fixture()
def store():
    from app.services.store import Store
    from app.models.geo_models import SessionLocal, init_db, engine

    init_db()
    db = SessionLocal()
    yield Store(db)
    db.close()
    engine.dispose()


@pytest.fixture()
def client():
    from app.main import app

    return TestClient(app)


# ── 1. Store roundtrip ──────────────────────────────────────────


def test_roundtrip_save_load(store):
    store.save("questions", [{"question": "测试问题A", "priority": 1}, {"question": "测试问题B"}])
    items = store.load("questions")
    assert len(items) == 2
    assert any(i["question"] == "测试问题A" for i in items)
    # 整表替换语义
    store.save("questions", [{"question": "只有这条"}])
    items = store.load("questions")
    assert len(items) == 1
    assert items[0]["question"] == "只有这条"


def test_reset_all_defaults_to_the_current_cabinet(store):
    """Owner 2026-09-22：账号分柜后，「重置」必须清**当前柜**。

    原实现留空固定清 ``tenant_corp_01``：登录账号点重置，会清掉所有人共用的那个柜，
    而自己的柜一点没动 —— 分柜之后这是个真错。
    """
    from app.services.store import reset_all, set_tenant

    # 用**合成柜名**，不许碰真实账号的柜（acct_human_*）——测试产物不进真柜
    set_tenant("acct_test_alice")
    store.save("kb", [{"title": "alice 的资料", "source_type": "file"}])
    set_tenant("acct_test_carol")
    store.save("kb", [{"title": "carol 的资料", "source_type": "file"}])

    set_tenant("acct_test_alice")
    reset_all()  # 不给租户 = 当前柜

    assert store.load("kb") == []
    set_tenant("acct_test_carol")
    assert [item["title"] for item in store.load("kb")] == ["carol 的资料"]
    set_tenant("acct_test_carol")
    reset_all()  # 测完自己清掉，不留测试产物
    set_tenant("")


def test_insert_delete(store):
    rec = store.insert("gaps", {"question": "缺口X", "impact": "高"})
    assert rec["id"].startswith("gaps_")
    assert len(store.load("gaps")) == 1
    assert store.delete("gaps", rec["id"]) is True
    assert len(store.load("gaps")) == 0


def test_tenant_isolation(store):
    store.save("questions", [{"question": "租户A数据"}], tenant_id="tenant_a")
    store.save("questions", [{"question": "租户B数据"}], tenant_id="tenant_b")
    assert len(store.load("questions", tenant_id="tenant_a")) == 1
    assert len(store.load("questions", tenant_id="tenant_b")) == 1
    assert len(store.load("questions")) == 0  # 默认租户无数据


def test_payload_tenant_cannot_override_write_scope(store):
    """Legacy payload metadata must not redirect a write across product scope."""
    store.insert("questions", {"question": "source", "tenant_id": "tenant_b"}, tenant_id="tenant_a")
    store.save("gaps", [{"question": "gap", "tenant_id": "tenant_b"}], tenant_id="tenant_a")

    assert [row["question"] for row in store.load("questions", tenant_id="tenant_a")] == ["source"]
    assert store.load("questions", tenant_id="tenant_b") == []
    assert [row["question"] for row in store.load("gaps", tenant_id="tenant_a")] == ["gap"]
    assert store.load("gaps", tenant_id="tenant_b") == []


def test_chinese_department_not_default_cabinet():
    from app.services.store import normalize_tenant, set_tenant, current_tenant

    a = normalize_tenant("市场部")
    b = normalize_tenant("市场部")
    c = normalize_tenant("家居部")
    assert a.startswith("dept_") and len(a) == 21
    assert a == b
    assert a != c
    assert a != "tenant_corp_01"
    assert normalize_tenant("sales") == "sales"
    assert normalize_tenant("") == "tenant_corp_01"
    try:
        set_tenant("运营部")
        assert current_tenant() == normalize_tenant("运营部")
        assert current_tenant() != "tenant_corp_01"
    finally:
        set_tenant("tenant_corp_01")


def test_list_tenant_ids_includes_all_cabinets(store):
    from app.services.store import list_tenant_ids

    store.save("questions", [{"question": "A"}], tenant_id="dept_aaa")
    store.save("questions", [{"question": "B"}], tenant_id="dept_bbb")
    ids = list_tenant_ids()
    assert "dept_aaa" in ids
    assert "dept_bbb" in ids


def test_get_entities_reads_the_eios_object_catalog(monkeypatch):
    """知识源从换知识源前的老适配器换成 EIOS 知识库（2026-09-20）后的契约：

    读的是 ``/api/v1/knowledge/objects``（active 对象），租户不再由调用方传 ——
    租户在票上，由部署声明决定。
    """
    import adapters.eios as eios

    captured = {}

    async def fake_request(method, path, **kwargs):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = kwargs.get("params", {})
        return {"items": [], "next_cursor": None}

    monkeypatch.setattr(eios, "_request", fake_request)
    import asyncio

    asyncio.run(eios.get_entities())
    assert captured["path"] == "/api/v1/knowledge/objects"
    assert captured["params"].get("status") == "active"
    assert "tenant_id" not in captured["params"]


def test_evidence_uses_current_geo_tenant(store):
    from app.services.store import set_tenant, current_tenant
    from services.intelligence.adapter import build_evidence

    try:
        set_tenant("市场部")
        ev = build_evidence(
            "h1",
            {"query_id": "q1", "question": "测"},
            {"engine_name": "deepseek", "answer": "有内容"},
            {"created_at": "2026-08-20T00:00:00+00:00"},
        )
        assert ev is not None
        assert ev["tenant_id"] == current_tenant()
        assert ev["tenant_id"] != "tenant_corp_01"
    finally:
        set_tenant("tenant_corp_01")


# ── 2. 迁移幂等 ─────────────────────────────────────────────────


def test_migrate_from_json(tmp_path):
    from app.services.store import migrate_json_to_db

    (tmp_path / "geo_questions.json").write_text(
        json.dumps([{"question": "迁移问题1"}, {"question": "迁移问题2"}], ensure_ascii=False), "utf-8"
    )
    (tmp_path / "geo_gaps.json").write_text(json.dumps([{"question": "迁移缺口"}], ensure_ascii=False), "utf-8")
    result = migrate_json_to_db(str(tmp_path))
    assert "10 条" not in str(result)  # 用临时目录，非真实数据
    assert "2 条" in result.get("geo_questions.json", "")


# ── 3. 媒体上传 ─────────────────────────────────────────────────


def test_media_upload_read(client, tmp_path):
    import app.core.config as cfg

    cfg.GEO_MEDIA_DIR = str(tmp_path)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    r = client.post("/api/v1/knowledge/media/upload", files={"file": ("t.png", png, "image/png")})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["url"].startswith("/api/v1/knowledge/media/")
    r2 = client.get(data["url"])
    assert r2.status_code == 200
    assert r2.content == png


# ── 4. 企业知识库 adapter 契约（top_k 而非 limit）──────────────────


def test_search_knowledge_speaks_the_knowledge_search_contract(monkeypatch):
    """新契约：``eios.knowledge_search/v2``（contract + query + limit + layers）。

    换知识源前的老适配器的 ``top_k`` 已经在权威侧不存在了；``layers`` 取 material|governed，
    ``include_candidates=False`` 必须真的只读 governed（否则「只读正式知识」是句空话）。
    """
    import adapters.eios as eios

    captured = {}

    async def fake_request(method, path, **kwargs):
        captured["path"] = path
        captured["body"] = kwargs.get("json_body", {})
        return {"contract": "eios.knowledge_search_result/v2", "hits": [], "matched": False}

    monkeypatch.setattr(eios, "_request", fake_request)

    import asyncio

    asyncio.run(eios.search_knowledge("测试", top_k=7))
    assert captured["path"] == "/api/v1/knowledge/search"
    assert captured["body"]["contract"] == "eios.knowledge_search/v2"
    assert captured["body"]["query"] == "测试"
    assert captured["body"]["limit"] == 7
    assert captured["body"]["layers"] == ["governed", "material"]
    assert "top_k" not in captured["body"]
    assert "tenant_id" not in captured["body"]
