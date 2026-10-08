"""内容生成/改写共用当前柜上传资料；只用假模型捕获输入，不触发真实 Provider。"""
import asyncio
import hashlib
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def tenant():
    from app.models.geo_models import engine, init_db
    from app.services.store import set_tenant

    init_db()
    name = f"tenant_content_{uuid.uuid4().hex[:8]}"
    set_tenant(name)
    yield name
    set_tenant("tenant_corp_01")
    engine.dispose()


def _asset(asset_id, title, paragraphs, source_type="file"):
    from services.chunking import chunk_material

    content = "\n\n".join(paragraphs)
    item = chunk_material({
        "id": asset_id, "title": title, "source_type": source_type,
        "content": content,
    })
    item["text_chunks"] = [
        {"id": f"{asset_id}#{i}", "ordinal": i, "text": paragraph, "chars": len(paragraph)}
        for i, paragraph in enumerate(paragraphs)
    ]
    return item


def _patch_context_dependencies(monkeypatch, content):
    import services.content as C

    async def no_facts(_question="", _limit=C._MAX_TOPIC_FACTS):
        return []

    async def no_search(*_args, **_kwargs):
        return {"hits": [], "provenance": {"source": "test"}, "warnings": []}

    async def no_company(_tenant):
        return "笔革家居"

    async def no_signals(**_kwargs):
        return {"available": False}

    async def no_gate(_question):
        return {"unverified": []}

    monkeypatch.setattr(C, "_official_fact_lines", no_facts)
    monkeypatch.setattr(C, "search_knowledge", no_search)
    monkeypatch.setattr(C, "_resolve_self_company", no_company)
    monkeypatch.setattr(C, "_fact_gate", no_gate)
    import services.content.signals as signals
    monkeypatch.setattr(signals, "build_market_signals", no_signals)
    return C


@pytest.mark.parametrize("reply", ["【标题】笔革定制 FAQ\n\n正文", "【标题】\n\n笔革定制 FAQ\n正文"])
def test_generation_extracts_title_instead_of_copying_the_whole_request(tenant, monkeypatch, reply):
    C = _patch_context_dependencies(monkeypatch, "")
    async def fake_chat(prompt, **kwargs):
        return reply
    monkeypatch.setattr(C, "chat", fake_chat)
    result = _run(C.generate(question="请回答尺寸颜色面料与周期并核对资料", company_name="笔革家居"))
    assert result["title"] == "笔革定制 FAQ"


def test_generate_and_improve_use_same_full_upload_chunks_and_exclude_generated(tenant, monkeypatch):
    from app.services.store import get_store

    file = _asset("file_a", "笔革访谈", [
        "客户可以DIY选择尺寸、颜色和面料。",
        "常规交付周期为30—45天，当前包含免费设计。",
        "产品提供售后维护服务。",
        "这是无关的木材加工说明。",
    ])
    generated = _asset("draft_old", "旧生成稿", ["伪事实：交付周期仅需三天。"], "generated")
    get_store().save("kb", [file, generated])
    C = _patch_context_dependencies(monkeypatch, file["content"])

    seen = {}

    async def fake_chat(prompt, **_kwargs):
        seen.setdefault("prompts", []).append(prompt)
        if '"content"' in prompt:
            return '{"title":"改稿","content":"改好的内容"}'
        return "【标题】\n笔革家居 FAQ\n正文"

    monkeypatch.setattr(C, "chat", fake_chat)
    question = "可以DIY吗？交付周期多久？设计收费吗？售后如何？"
    result = _run(C.generate(question=question, company_name="笔革家居", length="500"))
    selected = next(s for s in result["context_sources"] if s["kind"] == "uploaded_material")
    excerpts = selected["items"]
    joined = "\n".join(i["content"] for i in excerpts)
    for expected in ("DIY选择尺寸", "30—45天", "免费设计", "售后维护"):
        assert expected in joined
    assert all(item["chunk_id"] != "file_a#3" for item in excerpts)
    assert "伪事实：交付周期仅需三天" not in seen["prompts"][0]
    assert result["source_material_ids"] == ["file_a"]
    assert all(i["source_digest"] == hashlib.sha256(i["content"].encode()).hexdigest() for i in excerpts)

    revised = _run(C.improve(
        title=result["title"], content=result["content"], instruction="缩短并保留准确周期",
        question=question, company_name="笔革家居", source_material_ids=result["source_material_ids"],
    ))
    assert "30—45天" in seen["prompts"][1]
    assert revised["source_material_ids"] == ["file_a"]
    assert any(s["kind"] == "uploaded_material" for s in revised["context_sources"])


def test_explicit_missing_or_cross_cabinet_material_fails_without_substitution(tenant):
    from app.services.store import get_store
    import services.content as C

    local = _asset("local_file", "本柜资料", ["本柜原文有服务周期。"])
    foreign = _asset("foreign_file", "他柜资料", ["别柜原文有不同服务周期。"])
    get_store().save("kb", [local], tenant_id=tenant)
    get_store().save("kb", [foreign], tenant_id="another_cabinet")

    async def empty_facts(_question="", _limit=C._MAX_TOPIC_FACTS):
        return [], "empty", []

    async def empty_search(*_args, **_kwargs):
        return {"hits": [], "provenance": {"source": "test"}, "warnings": []}

    async def empty_signals(**_kwargs):
        return {"available": False}

    import services.content.signals as signals
    C._official_fact_lines = empty_facts
    C.search_knowledge = empty_search
    signals.build_market_signals = empty_signals
    with pytest.raises(ValueError, match="不存在、已失效或不在当前素材柜"):
        _run(C.build_context(question="服务周期", company_name="企业", source_material_ids=["foreign_file"]))
    with pytest.raises(ValueError, match="不存在、已失效或不在当前素材柜"):
        _run(C.build_context(question="服务周期", company_name="企业", source_material_ids=["deleted_file"]))


def test_unrelated_chunks_are_not_selected_and_knowledge_failure_is_not_empty(monkeypatch, tenant):
    import services.content as C

    async def no_facts(_question="", _limit=C._MAX_TOPIC_FACTS):
        return []

    async def fail_search(*_args, **_kwargs):
        raise RuntimeError("Knowledge unavailable")

    async def no_signals(**_kwargs):
        return {"available": False}

    monkeypatch.setattr(C, "_official_fact_lines", no_facts)
    monkeypatch.setattr(C, "search_knowledge", fail_search)
    async def resolve(_tenant):
        return "企业"
    monkeypatch.setattr(C, "_resolve_self_company", resolve)
    import services.content.signals as signals
    monkeypatch.setattr(signals, "build_market_signals", no_signals)
    from app.services.store import get_store
    unrelated = _asset("unrelated_file", "木材加工", ["这份资料只介绍木材表面处理工艺。"])
    get_store().save("kb", [unrelated])
    ctx = _run(C.build_context(question="火星采矿", company_name="企业"))
    assert ctx["knowledge_status"] == "unavailable"
    assert "knowledge_search_failed" in ctx["warnings"]
    assert ctx["source_material_ids"] == []
    assert not any(s["kind"] == "uploaded_material" for s in ctx["context_sources"])
