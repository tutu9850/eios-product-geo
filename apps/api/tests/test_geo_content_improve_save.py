"""Owner 2026-09-22 要的两件：内容能**按提示词改**、改完能**存进企业资料**。

- `/content/improve`：只在用户给了修改要求时改；改稿不得新增企业事实（提示词里钉死）。
- `/content/save`：存进**GEO 自己的内容资产**（source_type=generated，会切块），
  不是知识库 —— 存完在「内容资产」里能看到。
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
    from app.models.geo_models import engine, init_db
    from app.services.store import set_tenant

    init_db()
    try:
        set_tenant(f"tenant_improve_{uuid.uuid4().hex[:8]}")
        yield
    finally:
        set_tenant("tenant_corp_01")
        engine.dispose()


def test_improve_refuses_without_an_instruction():
    from services.content import improve

    with pytest.raises(ValueError):
        _run(improve(title="t", content="正文", instruction="   "))


def test_improve_refuses_without_content():
    from services.content import improve

    with pytest.raises(ValueError):
        _run(improve(title="t", content="  ", instruction="压缩到三句"))


def test_improve_rewrites_the_draft_with_the_users_instruction(monkeypatch, tenant):
    import services.content as C

    async def _ctx(**_kw):
        return {"materials": ["- 公司: 亚宇臻隆科技"]}

    seen: dict = {}

    async def _chat(prompt: str, **_kw):
        seen["prompt"] = prompt
        return '{"title": "改后的标题", "content": "改后的正文。"}'

    monkeypatch.setattr(C, "build_context", _ctx)
    monkeypatch.setattr(C, "chat", _chat)

    got = _run(
        C.improve(
            title="原题",
            content="原正文。",
            instruction="第二段太啰嗦，压到三句",
            question="亚宇臻隆是什么",
        )
    )
    assert {k: got[k] for k in ("title", "content", "source_title")} == {
        "title": "改后的标题", "content": "改后的正文。", "source_title": "原题"
    }
    assert got["source_material_ids"] == [] and got["context_sources"] == []
    # 提示词里必须带上修改要求与「不得新增企业事实」的约束
    assert "第二段太啰嗦，压到三句" in seen["prompt"]
    assert "禁止编造" in seen["prompt"]


def test_improve_reports_a_bad_model_reply_instead_of_pretending(monkeypatch, tenant):
    import services.content as C

    async def _ctx(**_kw):
        return {"materials": []}

    async def _chat(prompt: str, **_kw):
        return "好的，我改完了"  # 没有 JSON

    monkeypatch.setattr(C, "build_context", _ctx)
    monkeypatch.setattr(C, "chat", _chat)

    with pytest.raises(ValueError):
        _run(C.improve(title="t", content="正文", instruction="改一下"))


def test_save_writes_the_generated_content_into_our_own_assets(tenant):
    from app.api.v1.content import SaveIn, save
    from app.services.store import get_store

    body = _run(save(SaveIn(title="笔革家居为什么贵", content="正文内容。" * 40, question="q")))
    assert body["ok"] is True
    item = body["data"]["item"]
    assert item["source_type"] == "generated"
    assert item["title"] == "笔革家居为什么贵"
    items = get_store().load("kb")
    assert [m["id"] for m in items] == [item["id"]], "存进了内容资产，不是别的地方"


def test_save_refuses_an_empty_body(tenant):
    from app.api.v1.content import SaveIn, save

    body = _run(save(SaveIn(title="空稿", content="   ")))
    assert body["ok"] is False
    assert body["error"]["code"] == "empty_content"
