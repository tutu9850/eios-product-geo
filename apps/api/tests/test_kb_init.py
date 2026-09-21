"""内测「从知识库初始化本公司资料」：候选要真来自知识库，落库要真落进 GEO 自己的库。

Owner 2026-09-21 拍板：搜知识库 → 筛选公司/产品/相关文档 → 用户点选 → 单独一个按钮
（内测）→ 第一次全量，之后增量刷新 → 落**快照**。

这些断言守的就是这句话里的三件不能只停留在说法上的事：
1. 候选确实来自知识库（读不到 ≠ 知识库是空的）；
2. 落的是 GEO 自己的快照台账，不是知识库（GEO 只读）；
3. 「增量刷新」是真的增量：同一份选择不堆行，新增的才记新增。
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest


@pytest.fixture()
def tenant():
    """每个测试一个自己的租户柜：快照台账按 tenant 分区，不换柜会互相看见。"""
    from app.models.geo_models import engine, init_db
    from app.services.store import set_tenant

    init_db()
    try:
        set_tenant(f"tenant_test_{uuid.uuid4().hex[:8]}")
        yield
    finally:
        set_tenant("tenant_corp_01")
        engine.dispose()


#: 一个够真的 detect 结果（形状与 ``onboard._step_detect_from_knowledge`` 一致）
DETECT = {
    "company": ["亚宇臻隆"],
    "aliases": [],
    "products": ["GEO+知识库版"],
    "services": ["陪跑服务"],
    "industry": "企业服务",
    "keywords": ["GEO"],
    "empty": False,
    "error": None,
    "classification_source": "llm",
    "hint": None,
}

DOCS = [
    {"document_id": "doc_1", "title": "08_薪酬制度_亚宇臻隆2026", "status": "active", "version": 3},
    {"document_id": "doc_2", "title": "GEO+知识库版产品说明", "status": "active", "version": 1},
]


def _patch_kb(monkeypatch, *, detect=None, documents=None, documents_error=None,
              chunks=None, chunks_error=None, chunks_truncated=False, entities=None):
    from app.api.v1 import onboard
    import adapters.eios as eios

    async def _detect():
        return dict(detect if detect is not None else DETECT)

    async def _list_documents(limit: int = 50):
        if documents_error is not None:
            raise RuntimeError(documents_error)
        return list(documents if documents is not None else DOCS)

    async def _list_document_chunks(document_id: str, *, limit: int = 20):
        """文档切块读接口：测试里不许打真网络（8040 是活的，会真发请求）。"""
        if chunks_error is not None:
            raise RuntimeError(chunks_error)
        return {
            "document_id": document_id,
            "source": "knowledge",
            "items": list((chunks or {}).get(document_id, [])),
            "truncated": chunks_truncated,
            "warnings": [],
        }

    async def _entities():
        rows = entities if entities is not None else [
            {"canonical_name": "亚宇臻隆", "object_type": "entity", "status": "active"}
        ]
        return list(rows)

    async def _facts():
        return [{"canonical_name": "吴鑫宇 负责人 自媒体运营", "object_type": "fact", "status": "active"}]

    async def _relations(query: str = "", **kwargs):
        return [{"source_name": query, "target_name": "自媒体运营", "relation_type": "负责"}]

    # 「知识库同步」那一档现在叫 _step_detect_from_knowledge（另一档是内容资产）
    monkeypatch.setattr(onboard, "_step_detect_from_knowledge", _detect)
    monkeypatch.setattr(eios, "list_documents", _list_documents)
    monkeypatch.setattr(eios, "list_document_chunks", _list_document_chunks)
    # 同步要把对象/事实/关系一并带进 GEO 的柜；这里全部打桩，测试不打真网络
    monkeypatch.setattr(eios, "get_entities", _entities)
    monkeypatch.setattr(eios, "list_enterprise_facts", _facts)
    monkeypatch.setattr(eios, "search_relations", _relations)


def test_scan_offers_companies_products_and_documents(monkeypatch, tenant):
    """三桶候选都要有：公司、产品（含服务）、相关文档；并且如实标出哪些已经在我的库里。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch)
    body = asyncio.run(kb_init.kb_init_scan())

    assert body["ok"] is True
    data = body["data"]
    assert data["contract"] == "product.geo_kb_init/v1"
    assert data["initialized"] is False  # 还没初始化过
    assert [c["name"] for c in data["candidates"]["companies"]] == ["亚宇臻隆"]
    assert [p["name"] for p in data["candidates"]["products"]] == ["GEO+知识库版", "陪跑服务"]
    assert [d["document_id"] for d in data["candidates"]["documents"]] == ["doc_1", "doc_2"]
    assert all(c["in_profile"] is False for c in data["candidates"]["companies"])
    assert data["classification_source"] == "llm"


def test_scan_keeps_unreadable_knowledge_apart_from_an_empty_one(monkeypatch, tenant):
    """读不到知识库 ≠ 知识库是空的：前者必须原样报错，不能显示成「请去上传资料」。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch, detect={**DETECT, "company": [], "products": [], "services": [],
                                   "empty": True, "error": "票签不出来（EIOS_AUTH_PRIVATE_KEY_PATH 未配置）"})
    body = asyncio.run(kb_init.kb_init_scan())

    assert body["ok"] is False
    assert body["error"]["code"] == "knowledge_unreadable"
    assert "票签不出来" in body["error"]["message"]


def test_scan_says_so_when_only_the_document_bucket_is_unreadable(monkeypatch, tenant):
    """文档那一桶读不到：其余两桶照给，但如实把 error 带出来，不假装三桶齐全。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch, documents_error="知识库 503")
    data = asyncio.run(kb_init.kb_init_scan())["data"]

    assert data["candidates"]["companies"]
    assert data["candidates"]["documents"] == []
    assert "知识库 503" in data["error"]


def test_first_apply_is_the_full_load_and_lands_in_geos_own_snapshot_ledger(monkeypatch, tenant):
    """第一次 = 全量：选中的都记成新增，并且真落进 GEO 自己的快照台账（不是知识库）。"""
    from app.api.v1 import kb_init
    from app.services import knowledge_snapshot as snap

    _patch_kb(monkeypatch)
    body = asyncio.run(
        kb_init.kb_init_apply(kb_init.KbInitApplyIn(
            companies=["亚宇臻隆"], products=["GEO+知识库版"], documents=["doc_2"]))
    )

    assert body["ok"] is True
    data = body["data"]
    assert data["first_time"] is True
    assert data["recorded"] is True
    assert data["added"] == {
        "companies": ["亚宇臻隆"],
        "products": ["GEO+知识库版"],
        "documents": [{"document_id": "doc_2", "title": "GEO+知识库版产品说明", "version": 1}],
    }
    assert data["total"] == {"companies": 1, "products": 1, "documents": 1}

    rows = snap.list_recent(kind=kb_init.PROFILE_KIND)
    assert len(rows) == 1
    assert rows[0]["authoritative"] is False  # 正本仍在知识库
    assert rows[0]["payload"]["companies"] == ["亚宇臻隆"]
    # 落库的文档标题是 GEO 自己去知识库核来的
    assert rows[0]["payload"]["documents"][0]["title"] == "GEO+知识库版产品说明"


def test_re_applying_the_same_selection_is_not_a_new_revision(monkeypatch, tenant):
    """增量刷新：同一份选择再提交一次不堆行（台账按 payload_hash 去重），read_count 前进。"""
    from app.api.v1 import kb_init
    from app.services import knowledge_snapshot as snap

    _patch_kb(monkeypatch)
    selection = kb_init.KbInitApplyIn(companies=["亚宇臻隆"], documents=["doc_1"])
    first = asyncio.run(kb_init.kb_init_apply(selection))["data"]
    again = asyncio.run(kb_init.kb_init_apply(selection))["data"]

    assert first["recorded"] is True
    assert again["recorded"] is False      # 增量刷新里什么都没变，这不是错误
    assert again["first_time"] is False
    assert again["added"] == {"companies": [], "products": [], "documents": []}
    assert again["kept"] == {"companies": 1, "products": 0, "documents": 1}
    assert again["revision"] == first["revision"]
    assert again["read_count"] == 2
    assert len(snap.list_recent(kind=kb_init.PROFILE_KIND)) == 1


def test_a_later_apply_only_reports_what_is_new(monkeypatch, tenant):
    """后面那次只报新增：老的原样留着，新勾的才出现在 added 里。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch)
    asyncio.run(kb_init.kb_init_apply(kb_init.KbInitApplyIn(companies=["亚宇臻隆"])))
    later = asyncio.run(
        kb_init.kb_init_apply(kb_init.KbInitApplyIn(companies=["亚宇臻隆"], products=["GEO+知识库版"]))
    )["data"]

    assert later["recorded"] is True          # 选择变了 = 新修订
    assert later["first_time"] is False
    assert later["added"] == {"companies": [], "products": ["GEO+知识库版"], "documents": []}
    assert later["kept"] == {"companies": 1, "products": 0, "documents": 0}
    assert later["total"] == {"companies": 1, "products": 1, "documents": 0}


def test_scan_shows_what_is_already_mine_after_the_first_apply(monkeypatch, tenant):
    """初始化过之后，再扫一遍要能看出「哪些已经是我的」——增量就靠这个显示。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch)
    asyncio.run(kb_init.kb_init_apply(kb_init.KbInitApplyIn(companies=["亚宇臻隆"], documents=["doc_1"])))
    data = asyncio.run(kb_init.kb_init_scan())["data"]

    assert data["initialized"] is True
    assert data["revision"]
    assert data["last_applied_at"]
    assert data["candidates"]["companies"][0]["in_profile"] is True
    assert data["candidates"]["documents"][0]["in_profile"] is True
    assert data["candidates"]["documents"][1]["in_profile"] is False
    assert data["existing"]["documents"][0]["title"] == "08_薪酬制度_亚宇臻隆2026"


def test_an_unknown_document_id_is_reported_not_silently_dropped(monkeypatch, tenant):
    """客户端报了一个知识库里没有的文档 id：如实列进 unknown_documents，不静默吞掉。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch)
    data = asyncio.run(
        kb_init.kb_init_apply(kb_init.KbInitApplyIn(companies=["亚宇臻隆"], documents=["doc_1", "doc_ghost"]))
    )["data"]

    assert data["unknown_documents"] == ["doc_ghost"]
    assert [d["document_id"] for d in data["added"]["documents"]] == ["doc_1"]


def test_an_empty_selection_still_initializes_the_workspace_when_the_base_has_objects(monkeypatch, tenant):
    """Owner 2026-09-22：公司 / 产品 / 相关文档**都可以不选**。

    「20 个知识库对象 + 0 个文档」这种情形仍然要把 GEO 工作空间初始化出来：不勾选不是
    「拒绝」，只是这一次没往公司/产品/文档三张清单里记东西；企业对象/事实照样带回自己的柜。
    """
    from app.api.v1 import kb_init

    # 知识库里有对象（这里 20 个），一个文档都没有
    _patch_kb(monkeypatch, documents=[], entities=[
        {"canonical_name": f"对象{i}", "object_type": "entity", "status": "active"} for i in range(20)
    ])
    body = asyncio.run(kb_init.kb_init_apply(kb_init.KbInitApplyIn()))

    assert body["ok"] is True
    data = body["data"]
    assert data["first_time"] is True          # 工作空间是这次建起来的
    assert data["selection_empty"] is True     # 如实说这次没勾选
    assert data["total"] == {"companies": 0, "products": 0, "documents": 0}
    assert data["captured"]["objects"] == 20   # 对象真带回 GEO 自己的柜
    assert data["revision"]                    # 台账里真落了修订
    assert "没勾选" in data["note"]


def test_apply_still_refuses_an_empty_selection_when_the_base_is_actually_empty(monkeypatch, tenant):
    """知识库里真的什么都没有 → 仍然拒：不做一个空壳初始化（读不到 ≠ 是空的）。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch, documents=[], entities=[])
    body = asyncio.run(kb_init.kb_init_apply(kb_init.KbInitApplyIn()))

    assert body["ok"] is False
    assert body["error"]["code"] == "empty_selection"
    assert "知识库里也没有" in body["error"]["message"]


def test_apply_refuses_to_store_document_titles_it_could_not_verify(monkeypatch, tenant):
    """文档标题要 GEO 自己去知识库核：核不了就明确失败，而不是把客户端传的当权威存下。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch, documents_error="知识库读不到")
    body = asyncio.run(kb_init.kb_init_apply(kb_init.KbInitApplyIn(documents=["doc_1"])))

    assert body["ok"] is False
    assert body["error"]["code"] == "knowledge_unreadable"


def test_kb_init_never_touches_the_knowledge_write_path():
    """这个面只准读知识库：源码里不许出现写路径。"""
    import inspect

    from app.api.v1 import kb_init

    source = inspect.getsource(kb_init)
    assert "write_candidate" not in source
    assert "publish" not in source


def test_scan_offers_documents_geo_already_read_but_the_knowledge_base_has_not_published(monkeypatch, tenant):
    """Owner 2026-09-21 的发现：两份未发布的 docx，切块检索得到、文档读接口被拒。

    「未发布」意味着它不在知识库的文档列表里；但 GEO 已经读到过它的切块并存在自己台账里，
    所以同步时它也必须在候选里出现（``listed: false`` 如实标出来处）。
    """
    from app.api.v1 import kb_init
    from app.services.knowledge_snapshot import chunk_snapshot_payload, record

    _patch_kb(monkeypatch)
    record(
        kind="chunks",
        payload=chunk_snapshot_payload([{
            "document_id": "doc_unpublished",
            "document_title": "亚宇臻隆_商业模式方案V3_纯利润500万.docx",
            "chunk_id": "chk_1",
            "text": "OPC孵化园 × 三大渠道 × 纯利润保底500万",
            "layer": "material",
        }]),
    )
    data = asyncio.run(kb_init.kb_init_scan())["data"]

    docs = {d["document_id"]: d for d in data["candidates"]["documents"]}
    assert docs["doc_1"]["listed"] is True
    assert docs["doc_unpublished"]["listed"] is False
    assert docs["doc_unpublished"]["chunks_stored"] == 1
    assert docs["doc_unpublished"]["title"].endswith("纯利润500万.docx")
    assert [d["document_id"] for d in data["documents_from_snapshot"]] == ["doc_unpublished"]
    assert "没发布" in data["snapshot_note"]


def test_apply_accepts_a_document_it_only_knows_from_geos_own_chunk_snapshot(monkeypatch, tenant):
    """只在自己快照里的未发布文档：不是 unknown，切块也要一并带过来存下。"""
    from app.api.v1 import kb_init
    from app.services.knowledge_snapshot import chunk_snapshot_payload, record

    _patch_kb(monkeypatch, chunks={"doc_unpublished": [{"chunk_id": "chk_1", "text": "读到过的正文"}]})
    record(
        kind="chunks",
        payload=chunk_snapshot_payload([{
            "document_id": "doc_unpublished",
            "document_title": "亚宇臻隆_商业模式方案V3_纯利润500万.docx",
            "chunk_id": "chk_1",
            "text": "读到过的正文",
        }]),
    )
    data = asyncio.run(
        kb_init.kb_init_apply(kb_init.KbInitApplyIn(documents=["doc_unpublished"]))
    )["data"]

    assert data["unknown_documents"] == []
    assert [d["document_id"] for d in data["added"]["documents"]] == ["doc_unpublished"]
    assert data["chunks_pulled"] == [{"document_id": "doc_unpublished", "chunks": 1}]
    assert data["chunks_total"] == 1


def test_apply_reports_the_chunks_it_brought_over_for_every_picked_document(monkeypatch, tenant):
    """「同步的时候一并带过来存起来」：选中的每份文档都要报带回了多少块。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch, chunks={
        "doc_1": [{"chunk_id": "chk_a", "text": "薪酬制度正文"}],
        "doc_2": [{"chunk_id": "chk_b", "text": "产品说明正文"}, {"chunk_id": "chk_c", "text": "又一段"}],
    })
    data = asyncio.run(
        kb_init.kb_init_apply(kb_init.KbInitApplyIn(documents=["doc_1", "doc_2"]))
    )["data"]

    assert data["chunks_pulled"] == [
        {"document_id": "doc_1", "chunks": 1},
        {"document_id": "doc_2", "chunks": 2},
    ]
    assert data["chunks_total"] == 3


def test_a_document_whose_chunks_cannot_be_read_is_still_recorded_but_reported(monkeypatch, tenant):
    """切块拉不到（门关着又没有快照）不能把「选中文档」这件事弄失败，但必须如实报 0。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch, chunks_error="resource is not available in the caller's view")
    data = asyncio.run(kb_init.kb_init_apply(kb_init.KbInitApplyIn(documents=["doc_1"])))["data"]

    assert [d["document_id"] for d in data["added"]["documents"]] == ["doc_1"]
    assert data["chunks_pulled"] == [{"document_id": "doc_1", "chunks": 0}]
    assert data["chunks_total"] == 0


def test_apply_reports_when_a_documents_chunks_were_only_partly_brought_over(monkeypatch, tenant):
    """切块翻页到上限只带回一部分：如实标 ``truncated``，不把少带说成带全了。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch, chunks={"doc_1": [{"chunk_id": "chk_a", "text": "只带回来的一块"}]},
              chunks_truncated=True)
    data = asyncio.run(kb_init.kb_init_apply(kb_init.KbInitApplyIn(documents=["doc_1"])))["data"]

    assert data["chunks_pulled"] == [{"document_id": "doc_1", "chunks": 1, "truncated": True}]
    assert data["chunks_truncated"] == ["doc_1"]
