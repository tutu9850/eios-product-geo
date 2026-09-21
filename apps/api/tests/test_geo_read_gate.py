"""Owner 2026-09-22：除了手动的「知识库同步」，不让 GEO 去知识库里找东西。

这个文件钉住四件事（不然「堵掉了」只是说法）：

1. **默认关**：运行时的实时读直接被拒（``KnowledgeReadBlocked``，fail-closed），
   不是静默降级、也不是「读不到就当空的」；
2. **只有手动同步能开门**：``knowledge_read_grant("kb_sync")`` 里才放行，
   出了这个块立刻关回去；
3. **闸门关着时读的是 GEO 自己柜里的快照**（同步带回来的那份）；没同步过就如实空着，
   不许回头去打 :8040；
4. **本地检索不许凑数**：没命中就是空的，不拿「最新资料」顶（Owner 2026-09-22 拍板）。
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def tenant():
    """每个测试一个自己的柜（快照台账按 tenant 分区）。"""
    from app.models.geo_models import engine, init_db
    from app.services.store import set_tenant

    init_db()
    try:
        set_tenant(f"tenant_gate_{uuid.uuid4().hex[:8]}")
        yield
    finally:
        set_tenant("tenant_corp_01")
        engine.dispose()


def test_live_read_is_refused_by_default(monkeypatch):
    """闸门默认关：运行时那几次实时读必须当场被拒，而不是走到网络上。"""
    import adapters.eios as eios

    def _no_http(*_a, **_kw):  # pragma: no cover - 真调用会失败
        raise AssertionError("闸门关着还发了 HTTP 请求")

    monkeypatch.setattr(eios.httpx, "AsyncClient", _no_http)
    with pytest.raises(eios.KnowledgeReadBlocked) as caught:
        _run(eios._request("GET", "/api/v1/knowledge/objects"))
    assert caught.value.code == "KNOWLEDGE_READ_NOT_GRANTED"
    assert caught.value.status == 403
    assert not eios.reads_granted()


def test_only_the_grant_opens_the_door(monkeypatch):
    """开门只在 ``with`` 块里有效；出来就关回去（不是进程级开关）。"""
    import adapters.eios as eios

    seen: list[str] = []

    async def _fake_request(method: str, path: str, **_kw):
        seen.append(path)
        return {"items": [], "next_cursor": None}

    monkeypatch.setattr(eios, "_request", _fake_request)
    with eios.knowledge_read_grant("kb_sync"):
        assert eios.reads_granted() is True
        assert eios.current_grant() == "kb_sync"
        _run(eios.list_knowledge_objects(limit=5))
    assert seen == ["/api/v1/knowledge/objects"]
    assert eios.reads_granted() is False
    assert eios.current_grant() is None


def test_the_deployment_switch_is_explicit_not_silent(monkeypatch):
    """排障开关只认 ``on``；没设过就是关（不许「默认放宽」）。"""
    import adapters.eios as eios

    monkeypatch.delenv("GEO_KNOWLEDGE_READ", raising=False)
    assert eios.runtime_reads_enabled() is False
    monkeypatch.setenv("GEO_KNOWLEDGE_READ", "on")
    assert eios.runtime_reads_enabled() is True


def test_entities_come_from_geos_own_snapshot_when_the_gate_is_shut(monkeypatch):
    """闸门关着：读 GEO 自己柜里同步回来的对象，一个字节都不去打知识库。"""
    import adapters.eios as eios
    from app.services import knowledge_snapshot

    monkeypatch.setattr(eios, "_request", lambda *a, **k: pytest.fail("闸门关着还打了知识库"))
    monkeypatch.setattr(
        knowledge_snapshot,
        "objects",
        lambda **kw: [
            {
                "object_id": "obj_1",
                "canonical_name": "亚宇臻隆科技",
                "object_type": "entity",
                "status": "active",
                "evidence_ids": [],
            }
        ],
    )
    got = _run(eios.get_entities())
    assert [e["canonical_name"] for e in got] == ["亚宇臻隆科技"]
    assert got[0]["source"] == "geo_snapshot"


def test_facts_come_from_geos_own_snapshot_too(monkeypatch):
    import adapters.eios as eios
    from app.services import knowledge_snapshot

    monkeypatch.setattr(eios, "_request", lambda *a, **k: pytest.fail("闸门关着还打了知识库"))
    monkeypatch.setattr(
        knowledge_snapshot,
        "objects",
        lambda **kw: [{"object_id": "f1", "canonical_name": "吴鑫宇 负责人 自媒体运营", "object_type": "fact"}],
    )
    facts = _run(eios.list_enterprise_facts())
    assert [f["canonical_name"] for f in facts] == ["吴鑫宇 负责人 自媒体运营"]


def test_local_search_returns_nothing_rather_than_padding(monkeypatch):
    """没命中就是空的 —— 不许拿「最新资料」凑数。"""
    import adapters.eios as eios
    from app.services import knowledge_snapshot

    monkeypatch.setattr(eios, "_request", lambda *a, **k: pytest.fail("闸门关着还打了知识库"))
    monkeypatch.setattr(
        knowledge_snapshot,
        "all_chunks",
        lambda **kw: [
            {
                "chunk_id": "chk_1",
                "document_id": "doc_1",
                "document_title": "08_薪酬制度",
                "text": "销售中心的直客销售与续费政策",
            }
        ],
    )
    monkeypatch.setattr(knowledge_snapshot, "objects", lambda **kw: [])

    missed = _run(eios.search_knowledge("无锡演示间哪家好"))
    assert missed["hits"] == []
    assert missed["matched"] is False

    hit = _run(eios.search_knowledge("直客销售与续费"))
    assert [h["chunk_id"] for h in hit["hits"]] == ["chk_1"]
    assert hit["matched"] is True
    assert hit["provenance"]["source"] == "geo_snapshot"


def test_document_chunks_fall_back_to_geos_own_copy_when_the_door_is_shut(monkeypatch):
    """文档切块：门关着（这里是真的闸门）就用 GEO 存下来的那份，并如实标来源。"""
    import adapters.eios as eios
    from app.services import knowledge_snapshot

    monkeypatch.setattr(
        knowledge_snapshot,
        "chunks_for_document",
        lambda doc: [
            {
                "document_id": doc,
                "chunk_id": "chk_a",
                "text": "GEO 同步时存下来的切块原文",
                "document_title": "产品说明",
                "source": "geo_snapshot",
            }
        ],
    )
    got = _run(eios.list_document_chunks("doc_1"))
    assert got["source"] == "geo_snapshot"
    assert got["items"][0]["text"] == "GEO 同步时存下来的切块原文"
    assert got["warnings"][0] == "authority_document_chunks_denied"


def test_the_manual_sync_is_the_one_place_that_opens_the_door(monkeypatch, tenant):
    """「知识库同步」这一步开着门；它之外是关的。"""
    import adapters.eios as eios
    from app.api.v1 import kb_init, onboard

    seen: dict = {}

    async def _detect():
        seen["granted"] = eios.reads_granted()
        seen["grant"] = eios.current_grant()
        return {
            "company": [], "aliases": [], "products": [], "services": [],
            "industry": None, "keywords": [], "empty": True, "error": None,
            "classification_source": None, "hint": None,
        }

    async def _empty_documents(limit: int = 50):
        return []

    async def _no_entities():
        return []

    async def _no_facts():
        return []

    async def _no_relations(*_a, **_kw):
        return []

    monkeypatch.setattr(onboard, "_step_detect_from_knowledge", _detect)
    monkeypatch.setattr(eios, "list_documents", _empty_documents)
    monkeypatch.setattr(eios, "get_entities", _no_entities)
    monkeypatch.setattr(eios, "list_enterprise_facts", _no_facts)
    monkeypatch.setattr(eios, "search_relations", _no_relations)

    _run(kb_init.kb_init_scan())
    assert seen["granted"] is True
    assert seen["grant"] == "kb_sync"
    assert eios.reads_granted() is False, "出了同步这一步，闸门必须关回去"
