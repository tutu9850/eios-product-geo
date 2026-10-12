"""Owner 2026-09-21：「本公司是谁」必须只有一个答案。

实测到的错：内容评分 / 内容生成 / 企业画像 各自猜公司名，最松的那版只要名字里带「企业」
就认，于是把知识库里的**素材标题**「企业AI获客入口改造」当成了公司名
（``GET /api/v1/content/score`` 直接回 ``company_name='企业AI获客入口改造'``，
``profile_resolved=True``）——生成出来的内容张冠李戴。

现在解析顺序固定在 ``services.company_identity``：用户点选确认的档案 → brand 监测对象 →
严格公司名规则；都认不出来就返回 None，让上游如实说「未识别到企业名称」。

另外钉住一条同源问题：兜底那版以前按 ``object_type == "company"`` 取频次最高，
而 EIOS 的知识对象只有 entity / fact 两种 type —— 那个条件恒不成立（死代码）。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # apps/api

from services.company_identity import looks_like_company_name, resolve_self_company  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def test_titles_are_not_company_names():
    assert not looks_like_company_name("企业AI获客入口改造")
    assert not looks_like_company_name("GEO 知识库系统")
    assert not looks_like_company_name("客户案例集")
    assert not looks_like_company_name("成都演示间 负责 StoryClaw终端")
    assert not looks_like_company_name("")


def test_real_company_names_pass():
    assert looks_like_company_name("亚宇臻隆科技")
    assert looks_like_company_name("成都笔革家居有限公司")
    assert looks_like_company_name("华夏君成工作室")


def test_profile_comes_first(monkeypatch):
    from app.services import knowledge_snapshot

    monkeypatch.setattr(
        knowledge_snapshot,
        "list_recent",
        lambda kind=None, limit=1: [{"snapshot_id": "s1", "payload": {"companies": ["亚宇臻隆科技", "笔革家居"]}}],
    )
    got = _run(resolve_self_company())
    assert got == {"name": "亚宇臻隆科技", "aliases": ["笔革家居"], "source": "profile"}


def test_brand_monitor_item_is_second(monkeypatch):
    from app.services import knowledge_snapshot, store as store_mod

    monkeypatch.setattr(knowledge_snapshot, "list_recent", lambda kind=None, limit=1: [])
    monkeypatch.setattr(
        store_mod,
        "get_store",
        lambda: type("S", (), {"load": lambda self, name: [
            {"type": "brand", "status": "active", "config_json": {"company": "亚宇臻隆科技", "aliases": ["亚宇臻隆"]}}
        ] if name == "monitor_items" else []})(),
    )
    got = _run(resolve_self_company())
    assert got["name"] == "亚宇臻隆科技"
    assert got["aliases"] == ["亚宇臻隆"]
    assert got["source"] == "monitor_item"


def test_knowledge_scan_skips_titles_and_finds_the_company(monkeypatch):
    import adapters.eios as eios
    from app.services import knowledge_snapshot, store as store_mod

    monkeypatch.setattr(knowledge_snapshot, "list_recent", lambda kind=None, limit=1: [])
    monkeypatch.setattr(store_mod, "get_store", lambda: type("S", (), {"load": lambda self, name: []})())

    async def _entities():
        return [
            {"canonical_name": "企业AI获客入口改造", "object_type": "entity"},
            {"canonical_name": "客户续费结算", "object_type": "entity"},
            {"canonical_name": "亚宇臻隆科技", "object_type": "entity"},
        ]

    monkeypatch.setattr(eios, "get_entities", _entities)
    got = _run(resolve_self_company())
    assert got["name"] == "亚宇臻隆科技", "带「入口/改造」的标题不能被当成公司"
    assert got["source"] == "knowledge_scan"


def test_unresolved_stays_unresolved(monkeypatch):
    import adapters.eios as eios
    from app.services import knowledge_snapshot, store as store_mod

    monkeypatch.setattr(knowledge_snapshot, "list_recent", lambda kind=None, limit=1: [])
    monkeypatch.setattr(store_mod, "get_store", lambda: type("S", (), {"load": lambda self, name: []})())

    async def _entities():
        return [{"canonical_name": "企业AI获客入口改造", "object_type": "entity"}]

    monkeypatch.setattr(eios, "get_entities", _entities)
    got = _run(resolve_self_company())
    assert got == {"name": None, "aliases": [], "source": "unresolved"}


def test_content_auto_company_uses_the_resolver(monkeypatch):
    from services import content as content_mod

    async def _resolved(tenant_id=None):
        return {"name": "亚宇臻隆科技", "aliases": [], "source": "profile"}

    monkeypatch.setattr("services.company_identity.resolve_self_company", _resolved)

    async def _search(name, tenant_id=None, top_k=8, include_candidates=False):
        return {"hits": [{"canonical_name": "亚宇臻隆科技", "value": "做 GEO 与知识库", "layer": "governed"}]}

    monkeypatch.setattr(content_mod, "search_knowledge", _search)
    name, materials = _run(content_mod._auto_company("tenant_corp_01"))
    assert name == "亚宇臻隆科技"
    assert materials and "亚宇臻隆科技" in materials[0]
