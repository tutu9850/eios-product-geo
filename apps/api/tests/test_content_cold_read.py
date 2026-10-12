"""Saved GEO draft excerpts survive two fresh reader processes, using a task DB."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def test_saved_draft_and_sources_survive_fresh_reader_processes():
    from app.models.geo_models import init_db
    from app.services.store import set_tenant
    from app.api.v1.content import SaveIn, save
    from app.api.v1.knowledge import MaterialIn, add_material
    init_db()
    set_tenant('cold_read_owner')
    try:
        item=asyncio.run(add_material(MaterialIn(title='隔离资料',content='允许选择面料。',source_type='file')))['data']['item']
        chunk=item['text_chunks'][0]
        sources=[{'kind':'uploaded_material','label':'用户上传资料（相关原文选段，未经独立核验）','items':[{
            'id':item['id'],'title':item['title'],'source_type':'file','chunk_id':chunk['id'],
            'chunk_ordinal':chunk['ordinal'],'content':chunk['text'],
            'source_digest':hashlib.sha256(chunk['text'].encode()).hexdigest()}]}]
        saved=asyncio.run(save(SaveIn(content='允许选择面料。',source_material_ids=[item['id']],context_sources=sources)))
        assert saved['ok']
        draft_id=saved['data']['item']['id']
        env=dict(os.environ)
        root=Path(__file__).resolve().parents[3]
        env['PYTHONPATH']=os.pathsep.join([str(root/'apps/api'),str(root),env.get('PYTHONPATH','')])
        script='''import asyncio,json,sys
from app.services.store import set_tenant
from app.api.v1.knowledge import get_material
set_tenant('cold_read_owner')
print(json.dumps(asyncio.run(get_material(sys.argv[1])),ensure_ascii=False))
'''
        for _ in range(2):
            body=json.loads(subprocess.check_output([sys.executable,'-c',script,draft_id],env=env,text=True,timeout=10))
            assert body['ok']
            read=body['data']['item']
            assert read['content']=='允许选择面料。'
            assert read['context_sources']==sources
            assert read['source_material_ids']==[item['id']]
    finally:
        set_tenant('tenant_corp_01')
