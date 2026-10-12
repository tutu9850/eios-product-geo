"""Isolated formal consumer, using published Foundation schema fixtures."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from adapters import eios
from app.product.session import ProductSession, bind_product_session


@pytest.fixture
def formal(monkeypatch):
    fixtures = Path(__file__).parent / 'fixtures' / 'formal_content'
    data = {n: json.loads((fixtures / f'{n}.json').read_text())
            for n in ('object', 'objects', 'attributes', 'relations', 'evidence')}
    obj = data['object']
    attrs = data['attributes']
    attrs['object_id'] = obj['id']
    attrs['object_version'] = obj['version']
    attrs['items'][0]['from_ko'] = {'id': obj['id'], 'version': obj['version']}
    calls = []
    failures = {}
    async def request(method, path, **kwargs):
        calls.append((path, kwargs.get('params')))
        if path in failures:
            raise failures[path]
        if path.endswith('/objects'):
            page = deepcopy(data['objects'])
            page['items'] = [deepcopy(obj)]
            return page
        if path.endswith('/canonical-attributes'):
            return deepcopy(attrs)
        if path.endswith('/canonical-relations'):
            return deepcopy(data['relations'])
        if '/evidence/' in path:
            eid = path.rsplit('/', 1)[1]
            refs = [e for f in attrs['items'] + data['relations']['items'] for e in f['evidence']]
            ref = next(e for e in refs if e['evidence_id'] == eid)
            detail = deepcopy(data['evidence'])
            detail['evidence']['id'] = eid
            # The same Evidence id must identify the same source on every fact.
            detail['source']['anchor'].update(document_id=ref['document_id'], document_version=ref['document_version'])
            detail['source']['location'].update(quote=ref['quote'], start=ref['start'], end=ref['end'], paragraph_id=ref['paragraph_id'])
            return detail
        return deepcopy(obj)
    # Use unique evidence ids per independent fixture claim, rather than inventing
    # that the published examples share a common evidence identity.
    for i, ref in enumerate(data['relations']['items'][0]['evidence']):
        ref['evidence_id'] = f'evi_relation{i}'
    monkeypatch.setattr(eios, '_request', request)
    reader_claims = {
        'deployment_id': obj['deployment_id'], 'enterprise_id': obj['enterprise_id'],
        'subject': 'human:isolated'}
    monkeypatch.setattr(eios, '_deployment_claims', lambda: reader_claims)
    session = ProductSession(deployment_id=obj['deployment_id'], enterprise_id=obj['enterprise_id'],
        principal_id='human:isolated', actor_type='human', service_id='eios-product-api')
    with bind_product_session(session):
        yield data, calls, failures, session


def test_exact_formal_sources_and_no_legacy_calls(formal):
    data, calls, _, _ = formal
    sources = asyncio.run(eios.read_formal_content_sources())
    assert {s['fact_id'] for s in sources} == {f['fact_id'] for f in data['attributes']['items'] + data['relations']['items']}
    assert all(s['canonical_fact']['evidence'] and s['evidence_details'][0]['source']['anchor']['document_version_id'] for s in sources)
    assert all('instance-relations' not in path and '/search' not in path for path, _ in calls)
    assert any(q.get('response_contract') == 'eios.canonical_incident_relation_list_result/v5' for _, q in calls)


def test_unbound_reader_never_requests(monkeypatch):
    calls = []
    async def request(*args, **kwargs):
        calls.append(args)
    monkeypatch.setattr(eios, '_request', request)
    with pytest.raises(eios.EIOSKnowledgeError, match='当前用户'):
        asyncio.run(eios.read_formal_content_sources())
    assert calls == []


@pytest.mark.parametrize('field', ['enterprise_id', 'deployment_id'])
def test_wrong_owner_rejected(formal, field):
    data, _, _, session = formal
    # Bind the original trusted context while upstream returns another owner.
    data['object'][field] = 'other'
    with bind_product_session(session), pytest.raises(eios.EIOSKnowledgeError):
        asyncio.run(eios.read_formal_content_sources())


@pytest.mark.parametrize('mutation', ['quote', 'version', 'hash', 'fact_id'])
def test_tampered_draft_sources_rejected(formal, mutation):
    sources = asyncio.run(eios.read_formal_content_sources())
    groups = [{'kind': 'canonical_fact', 'label': '正式事实', 'items': sources}]
    item = groups[0]['items'][0]
    if mutation == 'quote':
        item['evidence_details'][0]['source']['location']['quote'] = '伪造'
    elif mutation == 'version':
        item['evidence_details'][0]['source']['anchor']['document_version'] += 1
    elif mutation == 'hash':
        item['evidence_details'][0]['source']['anchor']['source_hash'] = 'sha256:' + '0' * 64
    else:
        item['fact_id'] = 'fact_' + 'z' * 16
    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        asyncio.run(eios.validate_formal_content_sources(groups))
    assert caught.value.code == 'FORMAL_SOURCE_CHANGED'


@pytest.mark.parametrize('code,status', [('FORBIDDEN_SCOPE',403), ('DEPENDENCY_NOT_ACTIVE',503), ('KNOWLEDGE_INVALID_RESPONSE',502)])
def test_named_failure_never_falls_back(formal, monkeypatch, code, status):
    data, _, failures, _ = formal
    failures[f"/api/v1/knowledge/objects/{data['object']['id']}/canonical-relations"] = eios.EIOSKnowledgeError(code, 'controlled', status)
    monkeypatch.setattr(eios, 'local_search', lambda *a, **k: pytest.fail('snapshot fallback'))
    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        asyncio.run(eios.read_formal_content_sources())
    assert caught.value.code == code


def test_generate_rewrite_save_reopen(formal, monkeypatch):
    from services import content as service
    from app.api.v1.content import GenerateRequest, ImproveIn, SaveIn, generate, improve, save
    from app.api.v1.knowledge import get_material
    from app.models.geo_models import init_db
    from app.services.store import set_tenant
    init_db()
    set_tenant('formal_isolated')
    async def chat(prompt, **kwargs):
        assert 'fact_' in prompt
        return '{"title":"改稿","content":"据正式事实写的稿。"}' if '当前稿子' in prompt else '# 稿件\n据正式事实写的稿。'
    monkeypatch.setattr(service, 'chat', chat)
    async def forbidden(*args, **kwargs):
        pytest.fail('formal entry must not consume legacy materials')
    monkeypatch.setattr(service, 'build_context', forbidden)
    monkeypatch.setattr(service, '_fact_gate', forbidden)
    try:
        generated = asyncio.run(generate(GenerateRequest(structure='geo')))
        assert generated['ok'], generated
        body = generated['data']
        sources = body['context_sources']
        rewritten = asyncio.run(improve(ImproveIn(content=body['content'], instruction='压缩', context_sources=sources)))
        assert rewritten['ok'], rewritten
        assert rewritten['data']['context_sources'] == sources
        saved = asyncio.run(save(SaveIn(content=rewritten['data']['content'], context_sources=sources)))
        assert saved['ok'], saved
        mid = saved['data']['item']['id']
        reopened = asyncio.run(get_material(mid))
        assert reopened['ok']
        assert reopened['data']['item']['context_sources'] == sources
        assert reopened['data']['item']['content'] == rewritten['data']['content']
        # Fresh processes rebuild the controlled reader and reopen the same task DB.
        import os
        import subprocess
        import sys
        script = """import asyncio,importlib.util,json,sys,pytest
spec=importlib.util.spec_from_file_location('formal_test',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
patch=pytest.MonkeyPatch();fixture=module.formal.__wrapped__(patch);next(fixture)
from app.services.store import set_tenant
from app.api.v1.knowledge import get_material
set_tenant('formal_isolated')
print(json.dumps(asyncio.run(get_material(sys.argv[2])),ensure_ascii=False))
try:next(fixture)
except StopIteration:pass
patch.undo()
"""
        for _ in range(2):
            child_env = dict(os.environ)
            child_env['PYTHONPATH'] = os.pathsep.join([
                str(Path(__file__).resolve().parents[1]),
                str(Path(__file__).resolve().parents[3]),
                child_env.get('PYTHONPATH', '')])
            child = json.loads(subprocess.check_output(
                [sys.executable, '-c', script, str(Path(__file__).resolve()), mid],
                env=child_env, text=True, timeout=10))
            assert child['ok']
            assert child['data']['item']['context_sources'] == sources
            assert child['data']['item']['content'] == rewritten['data']['content']
        # Refusal must not turn history into current eligibility or expose detail.
        data, _, failures, _ = formal
        failures[f"/api/v1/knowledge/objects/{data['object']['id']}/canonical-relations"] = eios.EIOSKnowledgeError('FORBIDDEN_SCOPE','撤权',403)
        refused = asyncio.run(get_material(mid))
        assert not refused['ok'] and refused['error']['code'] == 'FORBIDDEN_SCOPE'
        del failures[f"/api/v1/knowledge/objects/{data['object']['id']}/canonical-relations"]
        assert asyncio.run(get_material(mid))['ok']
    finally:
        set_tenant('tenant_corp_01')


def test_empty_is_not_permission_refusal(formal, monkeypatch):
    from services.content import build_formal_context
    async def empty(*args, **kwargs):
        return {'contract': 'eios.knowledge_object_list_result/v2', 'status':'active', 'limit':20, 'items':[], 'next_cursor':None}
    monkeypatch.setattr(eios, '_request', empty)
    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        asyncio.run(build_formal_context())
    assert caught.value.code == 'FORMAL_FACTS_EMPTY'
    assert caught.value.category == 'empty'
    assert not caught.value.authority_refused


def test_foreign_company_label_not_promoted(formal):
    from services.content import build_formal_context
    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        asyncio.run(build_formal_context(company_name='未获依据的另一企业'))
    assert caught.value.code == 'FORMAL_SUBJECT_NOT_FOUND'


def test_incomplete_pages_named_partial(formal, monkeypatch):
    data, calls, _, _ = formal
    async def pages(*args, **kwargs):
        calls.append(args)
        page = deepcopy(data['objects'])
        page['next_cursor'] = f'ko_page{len(calls)}'
        return page
    monkeypatch.setattr(eios, '_request', pages)
    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        asyncio.run(eios.read_formal_content_sources())
    assert caught.value.code == 'FORMAL_READ_PARTIAL'
    assert caught.value.category == 'partial'
    assert len(calls) == 20


def test_timeout_does_not_start_another_read(formal, monkeypatch):
    calls = []
    async def slow(*args, **kwargs):
        calls.append(args)
        await asyncio.sleep(1)
        pytest.fail('late result accepted')
    original_wait = asyncio.wait_for
    async def short_wait(awaitable, timeout):
        return await original_wait(awaitable, min(timeout, 0.005))
    monkeypatch.setattr(eios, '_request', slow)
    monkeypatch.setattr(asyncio, 'wait_for', short_wait)
    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        asyncio.run(eios.read_formal_content_sources())
    assert caught.value.code == 'FORMAL_READ_TIMEOUT'
    assert len(calls) == 1


def test_task_cancel_does_not_start_another_read(formal, monkeypatch):
    calls = []
    async def run():
        started = asyncio.Event()
        async def slow(*args, **kwargs):
            calls.append(args)
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(eios, '_request', slow)
        task = asyncio.create_task(eios.read_formal_content_sources())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
    asyncio.run(run())
    assert len(calls) == 1


def test_tampered_save_never_writes(formal):
    from app.api.v1.content import SaveIn, save
    from app.models.geo_models import init_db
    from app.services.store import get_store, set_tenant
    init_db()
    set_tenant('formal_rejection')
    try:
        sources = asyncio.run(eios.read_formal_content_sources())
        sources[0]['canonical_fact']['value']['raw_text'] = '伪造数字999'
        before = deepcopy(get_store().load('kb'))
        result = asyncio.run(save(SaveIn(content='伪造稿', context_sources=[{'kind':'canonical_fact','label':'来源','items':sources}])))
        assert not result['ok'] and result['error']['code'] == 'FORMAL_SOURCE_CHANGED'
        assert get_store().load('kb') == before
    finally:
        set_tenant('tenant_corp_01')


@pytest.mark.parametrize('status', ['stale', 'invalidated', 'superseded'])
def test_invalid_evidence_not_current_material(formal, status):
    data, _, _, _ = formal
    data['evidence']['evidence']['validity_status'] = status
    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        asyncio.run(eios.read_formal_content_sources())
    assert caught.value.code == 'KNOWLEDGE_INVALID_RESPONSE'  # active-read contracts require current/valid


def test_non_current_reference_rejected(formal):
    data, _, _, _ = formal
    data['attributes']['items'][0]['evidence'][0]['is_current'] = False
    with pytest.raises(eios.EIOSKnowledgeError) as caught:
        asyncio.run(eios.read_formal_content_sources())
    assert caught.value.code == 'KNOWLEDGE_INVALID_RESPONSE'  # active-read contracts require current/valid


def test_attribute_and_relation_keep_actual_contract(formal):
    data, _, _, _ = formal
    sources = asyncio.run(eios.read_formal_content_sources())
    attrs = {f['fact_id'] for f in data['attributes']['items']}
    assert all(s['read_contract'] == ('eios.canonical_attribute_list_result/v1' if s['fact_id'] in attrs
               else 'eios.canonical_incident_relation_list_result/v5') for s in sources)
