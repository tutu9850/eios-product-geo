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


#: 一个够真的 detect 结果（形状与 ``onboard._step_detect`` 一致）
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


def _patch_kb(monkeypatch, *, detect=None, documents=None, documents_error=None):
    from app.api.v1 import onboard
    import adapters.eios as eios

    async def _detect():
        return dict(detect if detect is not None else DETECT)

    async def _list_documents(limit: int = 50):
        if documents_error is not None:
            raise RuntimeError(documents_error)
        return list(documents if documents is not None else DOCS)

    monkeypatch.setattr(onboard, "_step_detect", _detect)
    monkeypatch.setattr(eios, "list_documents", _list_documents)


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


def test_apply_refuses_an_empty_selection(monkeypatch, tenant):
    """一项都没选就不落库 —— 空选择不是「初始化」。"""
    from app.api.v1 import kb_init

    _patch_kb(monkeypatch)
    body = asyncio.run(kb_init.kb_init_apply(kb_init.KbInitApplyIn()))

    assert body["ok"] is False
    assert body["error"]["code"] == "empty_selection"


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
