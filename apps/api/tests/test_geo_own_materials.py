"""Owner 2026-09-22：「本公司是谁」和「自动配置」都从 GEO 自己的内容资产来。

三件事：
1. 从内容资产里**猜**公司名（不严格，但只认像名字的，不拿标题硬顶）；
2. 自动配置的候选来自内容资产的文章，**不打知识库**；
3. 删一份内容资产就连它切好的段一起删（都存 GEO 自己库里，删了就是删了）。

以及一条同名同源的边界：没有内容资产时如实说「还没有」，不编造候选。
"""
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

import pytest  # noqa: E402

from services.company_identity import company_candidates_from_materials  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def tenant():
    from app.models.geo_models import engine, init_db
    from app.services.store import set_tenant

    init_db()
    try:
        set_tenant(f"tenant_own_{uuid.uuid4().hex[:8]}")
        yield
    finally:
        set_tenant("tenant_corp_01")
        engine.dispose()


# ── 1. 从内容资产猜公司 ────────────────────────────────────

def test_candidates_come_from_titles_and_body_and_ignore_prose():
    materials = [
        {
            "title": "笔革家居整套全屋定制要多久？行业内部流程拆解，看完心里有数",
            "content": "笔革家居是一家做全屋定制的家装公司。笔革家居的工期通常是……" * 3,
        },
        {"title": "亚宇臻隆科技介绍", "content": "亚宇臻隆科技做AI获客。"},
    ]
    got = company_candidates_from_materials(materials)
    assert "笔革家居" in got and "亚宇臻隆科技" in got
    # 「家装公司」「AI获客公司」这种行业泛称不是公司名
    assert not any(c.endswith("公司") and c[:-2] in {"家装", "定制", "全屋定制", "获客", "AI获客"} for c in got)


def test_ranking_prefers_the_name_that_repeats_and_sits_in_a_title():
    repeating = "亚宇臻隆科技是一家公司。" * 8 + "笔革家居是全屋定制公司。" * 2
    got = company_candidates_from_materials([{"title": "公司资料", "content": repeating}])
    assert got[0] == "亚宇臻隆科技", "出现得多的排前面"
    titled = company_candidates_from_materials(
        [
            {"title": "公司资料", "content": "亚宇臻隆科技是一家公司。" * 8},
            {"title": "笔革家居整套全屋定制要多久", "content": "笔革家居的工期。"},
        ]
    )
    assert titled[0] in {"亚宇臻隆科技", "笔革家居"}


def test_no_materials_means_no_candidate():
    assert company_candidates_from_materials([]) == []
    assert company_candidates_from_materials([{"title": "全屋定制要多久", "content": "定制流程。"}]) == []


def test_resolve_self_company_uses_own_materials(monkeypatch, tenant):
    """第 3 档：档案 / 监测对象都没有时，从内容资产猜，来源如实写 ``own_materials``。"""
    from app.services import knowledge_snapshot, store as store_mod

    monkeypatch.setattr(knowledge_snapshot, "list_recent", lambda kind=None, limit=1: [])

    class _Store:
        def load(self, name):
            if name == "kb":
                return [{"title": "笔革家居整套全屋定制要多久", "content": "笔革家居的工期……"}]
            return []

    monkeypatch.setattr(store_mod, "get_store", lambda: _Store())

    import adapters.eios as eios

    async def _must_not_read_knowledge(*_a, **_kw):
        raise AssertionError("本公司识别不该去打知识库")

    monkeypatch.setattr(eios, "get_entities", _must_not_read_knowledge)

    from services.company_identity import resolve_self_company

    got = _run(resolve_self_company())
    assert got == {"name": "笔革家居", "aliases": [], "source": "own_materials"}


# ── 2. 自动配置从内容资产来 ────────────────────────────────

def test_auto_config_detect_reads_content_assets_and_never_the_knowledge_base(monkeypatch, tenant):
    from app.api.v1 import onboard
    from app.services.store import get_store

    get_store().save(
        "kb",
        [
            {
                "id": "m_1",
                "title": "笔革家居整套全屋定制要多久",
                "content": "笔革家居是一家做全屋定制的公司，主推全案定制。",
                "source_type": "file",
            }
        ],
    )
    import adapters.eios as eios
    import adapters.llm as llm

    monkeypatch.setattr(eios, "_request", lambda *a, **k: pytest.fail("自动配置不该打知识库"))

    async def _chat(prompt: str, **_kw):
        assert "笔革家居整套全屋定制要多久" in prompt, "候选池要来自内容资产的标题"
        return (
            '{"company": ["笔革家居"], "products": ["全案定制"], "services": [], '
            '"industry": "全屋定制家装", "keywords": ["全屋定制", "家装设计"]}'
        )

    monkeypatch.setattr(llm, "chat", _chat)

    got = _run(onboard._step_detect_from_materials())
    assert got["company"] == ["笔革家居"]
    assert got["products"] == ["全案定制"]
    assert got["industry"] == "全屋定制家装"
    assert got["empty"] is False
    assert got["classification_source"] == "llm"


def test_a_material_title_is_not_offered_as_a_product(monkeypatch, tenant):
    """标题是「这份材料叫什么」，不是「企业在卖什么」——不许混进产品候选。"""
    from app.api.v1 import onboard
    from app.services.store import get_store

    get_store().save(
        "kb",
        [
            {
                "id": "m_1",
                "title": "笔革家居整套全屋定制要多久",
                "content": "笔革家居主推全案定制服务。",
                "source_type": "file",
            }
        ],
    )
    import adapters.llm as llm

    async def _chat(prompt: str, **_kw):
        return (
            '{"company": ["笔革家居"], "products": ["笔革家居整套全屋定制要多久", "全案定制"], '
            '"services": [], "industry": "全屋定制家装", "keywords": []}'
        )

    monkeypatch.setattr(llm, "chat", _chat)

    got = _run(onboard._step_detect_from_materials())
    assert got["products"] == ["全案定制"], "标题不该被当成产品名"


def test_auto_config_detect_says_so_when_there_is_no_content_asset(tenant):
    from app.api.v1 import onboard

    got = _run(onboard._step_detect_from_materials())
    assert got["empty"] is True
    assert got["error"] is None
    assert "内容资产" in (got["hint"] or "")


# ── 3. 删素材连切块一起删 ──────────────────────────────────

def test_deleting_a_material_removes_its_chunks_too(monkeypatch, tenant):
    from app.api.v1 import knowledge
    from app.services.store import get_store
    import services.embed as embed

    async def _no_vectors(_material_id: str) -> bool:
        return True

    monkeypatch.setattr(embed, "delete_vectors", _no_vectors)

    body = _run(
        knowledge.add_material(
            knowledge.MaterialIn(title="笔革家居整套全屋定制要多久", content=("笔革家居的工期通常是三十到四十五天。" * 20 + "\n\n") * 3)
        )
    )
    item = body["data"]["item"]
    assert item["chunks"] >= 2, "正文够长就该切成多段"
    assert len(get_store().load("kb")) == 1

    deleted = _run(knowledge.delete_material(item["id"]))["data"]
    assert deleted["chunks_removed"] == item["chunks"]
    assert deleted["title"] == "笔革家居整套全屋定制要多久"
    assert get_store().load("kb") == [], "素材行连同它的切块一起没了"


def test_deleting_a_missing_material_is_reported_not_silently_ok(tenant):
    from app.api.v1 import knowledge

    body = _run(knowledge.delete_material("m_not_there"))
    assert body["ok"] is True
    assert body["data"]["error"] == "素材不存在"
