import asyncio
import copy
import hashlib

import pytest


@pytest.fixture
def cabinet():
    from app.models.geo_models import init_db
    from app.services.store import set_tenant
    init_db()
    set_tenant("provenance_owner")
    yield
    set_tenant("tenant_corp_01")


def run(coro):
    return asyncio.run(coro)


def fixture_source():
    from app.api.v1.knowledge import MaterialIn, add_material
    item = run(add_material(MaterialIn(title="访谈", content="交付周期30-45天；客户可选择尺寸、颜色、面料。", source_type="file")))["data"]["item"]
    chunk = item["text_chunks"][0]
    return item["id"], [{"kind": "uploaded_material", "label": "用户上传资料（相关原文选段，未经独立核验）", "items": [{
        "id": item["id"], "title": "访谈", "source_type": "file", "chunk_id": chunk["id"],
        "chunk_ordinal": chunk["ordinal"], "content": chunk["text"],
        "source_digest": hashlib.sha256(chunk["text"].encode()).hexdigest(),
    }]}]


def test_save_reopens_exact_validated_sources(cabinet):
    from app.api.v1.content import SaveIn, save
    from app.api.v1.knowledge import get_material
    mid, sources = fixture_source()
    saved = run(save(SaveIn(content="交付周期30-45天。", source_material_ids=[mid], context_sources=sources)))
    assert saved["ok"]
    read = run(get_material(saved["data"]["item"]["id"]))["data"]["item"]
    assert read["context_sources"] == sources
    assert read["source_material_ids"] == [mid]
    assert read["claim_check"]["status"] == "no_flags"


@pytest.mark.parametrize("mutation", ["text", "digest", "cabinet", "deleted"])
def test_forged_stale_and_other_cabinet_sources_cannot_save(cabinet, mutation):
    from app.api.v1.content import SaveIn, save
    from app.services.store import get_store, set_tenant
    mid, sources = fixture_source()
    sources = copy.deepcopy(sources)
    if mutation == "text": sources[0]["items"][0]["content"] = "交付当天完成"
    if mutation == "digest": sources[0]["items"][0]["source_digest"] = "forged"
    if mutation == "cabinet": set_tenant("other_owner")
    if mutation == "deleted": get_store().save("kb", [])
    result = run(save(SaveIn(content="正文", source_material_ids=[mid], context_sources=sources)))
    assert not result["ok"]
    assert result["error"]["code"] == "source_unavailable"
    assert not [m for m in get_store().load("kb") if m.get("source_type") == "generated"]


def test_claim_flags_are_screening_not_certification():
    from services.content.claim_check import check_claims
    sources = [{"items": [{"content": "交付周期30-45天。"}]}]
    assert check_claims("1. 交付周期30-45天。", sources)["status"] == "no_flags"
    assert check_claims("**Q8：交付周期多久？**\n交付周期30-45天。", sources)["status"] == "no_flags"
    result = check_claims("服务过1000个客户，获得ISO9001认证。", sources)
    assert result["status"] == "review_required"
    assert result["flags"] and "人工" in result["notice"]
    regional = check_claims("笔革家居是成都及四川地区的品牌，旗下拥有三个品牌。", sources)
    assert regional["status"] == "review_required"
    assert "地域" in regional["flags"][0]["reason"]
    assert "归属" in regional["flags"][0]["reason"]


def test_improve_consumes_handwritten_sources_and_drops_unused_signals(monkeypatch):
    import services.content as content
    seen = {}
    async def context(**kwargs):
        return {"materials": ["企业资料"], "context_sources": [
            {"kind": "asset", "items": [{"title": "服务说明", "content": "客户可以选择面料"}]},
            {"kind": "market_signal", "items": [{"signal": "AI回答", "count": 4}]},
        ]}
    async def chat(prompt, **kwargs):
        seen["prompt"] = prompt
        return '{"title":"改稿","content":"客户可以选择面料"}'
    monkeypatch.setattr(content, "build_context", context)
    monkeypatch.setattr(content, "chat", chat)
    result = run(content.improve(content="正文", instruction="改稿"))
    assert "客户可以选择面料" in seen["prompt"]
    assert all(s["kind"] != "market_signal" for s in result["context_sources"])


def test_improve_keeps_exact_original_excerpts_without_reranking(cabinet, monkeypatch):
    import services.content as C
    from app.api.v1.content import ImproveIn, improve
    mid, sources = fixture_source()
    seen = []

    async def unexpected_context(**kwargs):
        raise AssertionError('pinned uploaded sources must not be reselected')

    async def fake_chat(prompt, **kwargs):
        seen.append(prompt)
        return '{"title":"改稿","content":"交付周期30-45天。"}'

    monkeypatch.setattr(C, 'build_context', unexpected_context)
    monkeypatch.setattr(C, 'chat', fake_chat)
    result = run(improve(ImproveIn(content='原稿', instruction='缩短', question='完全不同的主题',
        source_material_ids=[mid], context_sources=sources)))
    assert result['ok']
    assert result['data']['context_sources'] == sources
    assert sources[0]['items'][0]['content'] in seen[0]


@pytest.mark.parametrize('mutation', ['text', 'digest', 'cabinet', 'deleted'])
def test_improve_rejects_changed_or_invisible_excerpts_before_model(cabinet, monkeypatch, mutation):
    import services.content as C
    from app.api.v1.content import ImproveIn, improve
    from app.services.store import get_store, set_tenant
    mid, sources = fixture_source()
    sources = copy.deepcopy(sources)
    if mutation == 'text': sources[0]['items'][0]['content'] = '当天交付'
    if mutation == 'digest': sources[0]['items'][0]['source_digest'] = 'forged'
    if mutation == 'cabinet': set_tenant('other_owner')
    if mutation == 'deleted': get_store().save('kb', [])
    async def forbidden_chat(*args, **kwargs):
        raise AssertionError('invalid source must fail before model')
    monkeypatch.setattr(C, 'chat', forbidden_chat)
    result = run(improve(ImproveIn(content='原稿', instruction='缩短',
        source_material_ids=[mid], context_sources=sources)))
    assert not result['ok']
    assert result['error']['code'] == 'source_unavailable'


def test_product_door_improve_save_and_reopen_preserve_original_sources(cabinet, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.v1.knowledge import MaterialIn, add_material
    import services.content as C
    monkeypatch.setenv('GEO_PRODUCT_DOOR', 'on')
    monkeypatch.setenv('GEO_AUTH_MODE', 'auth_context')
    monkeypatch.setenv('GEO_PRODUCT_STORAGE_MODE', 'legacy')
    monkeypatch.delenv('GEO_RUNTIME_MODE', raising=False)
    class Context:
        deployment_id = 'dep_rewrite'
        enterprise_id = 'enterprise_rewrite'
        subject = 'human:rewrite_owner'
        service_id = 'eios-geo'
    monkeypatch.setattr(app.state, 'auth_context_verifier', lambda token: Context() if token == 'test-signed' else None, raising=False)
    client = TestClient(app)  # no lifespan/worker
    headers = {'EIOS-Auth-Context': 'test-signed'}
    created = client.post('/api/product/geo/knowledge/materials', headers=headers,
        json={'title':'访谈','content':'交付周期30-45天。','source_type':'file'}).json()
    assert created['ok'], created
    item = created['data']['item']; chunk = item['text_chunks'][0]
    sources = [{'kind':'uploaded_material','label':'用户上传资料（相关原文选段，未经独立核验）','items':[{
        'id':item['id'],'title':item['title'],'source_type':'file','chunk_id':chunk['id'],
        'chunk_ordinal':chunk['ordinal'],'content':chunk['text'],
        'source_digest':hashlib.sha256(chunk['text'].encode()).hexdigest()}]}]
    async def fake_chat(prompt, **kwargs):
        assert chunk['text'] in prompt
        return '{"title":"改稿","content":"交付周期30-45天。"}'
    monkeypatch.setattr(C, 'chat', fake_chat)
    revised = client.post('/api/product/geo/content/improve', headers=headers, json={
        'content':'原稿','instruction':'缩短','source_material_ids':[item['id']], 'context_sources':sources}).json()
    assert revised['ok'], revised
    saved = client.post('/api/product/geo/content/save', headers=headers, json={
        'content':revised['data']['content'], 'source_material_ids':[item['id']],
        'context_sources':revised['data']['context_sources']}).json()
    assert saved['ok'], saved
    reopened = client.get('/api/product/geo/knowledge/materials/'+saved['data']['item']['id'],headers=headers).json()
    assert reopened['data']['item']['context_sources'] == sources
    assert reopened['data']['item']['content'] == revised['data']['content']
