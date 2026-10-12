"""Content must preserve read failures and never regrant rejected cached sources."""
import asyncio
import pytest


@pytest.mark.parametrize('code,http,expected', [
    ('FORBIDDEN_SCOPE',403,'refused'),
    ('KNOWLEDGE_UNAVAILABLE',503,'unavailable'),
    ('KNOWLEDGE_INVALID_RESPONSE',502,'invalid_response'),
])
def test_context_preserves_named_read_failure(monkeypatch, code, http, expected):
    import services.content as content
    from adapters.eios import EIOSKnowledgeError
    async def facts(*args):
        content._fact_context_status.set(('empty', []))
        return []
    async def search(*args, **kwargs):
        raise EIOSKnowledgeError(code, 'controlled failure', http)
    seen=[]
    def snapshots(*args, **kwargs):
        seen.append(True)
        return ['- 文档切块《旧》：旧权限下读到的正文']
    monkeypatch.setattr(content, '_official_fact_lines', facts)
    monkeypatch.setattr(content, 'search_knowledge', search)
    monkeypatch.setattr(content, '_chunk_lines_from_snapshot', snapshots)
    result=asyncio.run(content.build_context(question='企业介绍', company_name='隔离企业'))
    assert result['knowledge_status']==expected
    assert result['knowledge_error']['code']==code
    assert result['knowledge_error']['status']==http
    if expected=='refused':
        assert not seen
        assert not any(s['items'] for s in result['context_sources'] if s['kind'] in {'enterprise_fact','document_chunk','entity'})


@pytest.mark.parametrize('state', ['not_synced','empty','partial'])
def test_context_distinguishes_snapshot_read_states(monkeypatch, state):
    import services.content as content
    async def facts(*args):
        content._fact_context_status.set(('empty', []))
        return []
    async def search(*args, **kwargs):
        return {'hits': [], 'layers': ['governed'], 'status':state}
    monkeypatch.setattr(content, '_official_fact_lines', facts)
    monkeypatch.setattr(content, 'search_knowledge', search)
    monkeypatch.setattr(content, '_chunk_lines_from_snapshot', lambda *a,**k: [])
    result=asyncio.run(content.build_context(question='企业介绍',company_name='隔离企业'))
    assert result['knowledge_status']==state


def test_local_search_preserves_partial_snapshot(monkeypatch):
    from adapters.eios import local_search
    from app.services import knowledge_snapshot
    monkeypatch.setattr(knowledge_snapshot, 'read_status', lambda kind: {'status': 'partial'})
    monkeypatch.setattr(knowledge_snapshot, 'all_chunks', lambda: [])
    monkeypatch.setattr(knowledge_snapshot, 'objects', lambda: [])
    result = local_search('隔离企业')
    assert result['status'] == 'partial'
