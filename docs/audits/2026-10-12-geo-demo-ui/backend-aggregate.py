import asyncio, json
from pathlib import Path
from unittest.mock import patch
import os
assert os.environ.get('GEO_DB_PATH', '').startswith('/tmp/eios-test/'), 'Use a task-specific temporary database'
from app.api.v1 import monitor as M
from app.services.store import get_store, set_tenant
s=json.loads(Path(__file__).with_name('samples.json').read_text())
set_tenant('tenant_geo_demo_audit')
items=[{'monitor_id':'demo-brand','type':'brand','entity':s['company'],'status':'active','config_json':{'company':s['company']}}]
store=get_store()
store.save('monitor_items',items)
store.save('kb',s['materials'])
history=[]
for ri in range(3):
 rows=[r for r in s['rows'] if r['round']==ri]
 questions=[]
 for qi in range(3):
  rr=[r for r in rows if r['query_id']==f'demo-query-{qi+1}']
  for r in rr:
   a=M._analyze_answer(s['company'],r['answer'])
   if r['answer']:
    assert a['recognition']==r['recognition'], (r['id'],a)
    assert (a['sentiment'] or 'unknown')==r['sentiment'], (r['id'],a)
  questions.append({'monitor_id':'demo-brand','query_id':rr[0]['query_id'],'question':rr[0]['question'],'item_type':'brand','citations':sum(len(r['citation_ids']) for r in rr),'engine_detail':[{'engine_name':r['engine'],'answer':r['answer'],'snippet':r['snippet'],'mentioned':r['mentioned'],'rank_est':r['rank_est'],'sentiment':None if r['sentiment']=='unknown' else r['sentiment'],'recognition':r['recognition']} for r in rr]})
 history.append({'id':f'demo-history-{ri}','created_at':rows[0]['ts'],'company_name':s['company'],'questions':questions,'batch':True,'summary':{'coverage_pct':100,'mentioned_questions':3}})
store.save('monitor_history',history)
with patch.object(M,'_identity_gate_for_monitor_ids',return_value='confirmed'):
 # Local aggregation only. This mock does NOT prove controlled extraction identity.
 actual=M._aggregate_overview(history,'demo-brand')
 expected=s['monitor']['overview']
 assert actual['recommend']==expected['recommend'], (actual['recommend'],expected['recommend'])
 assert actual['rank']==expected['rank']
 assert actual['platforms']==expected['platforms']
 sentiment=M._aggregate_sentiment(history,'demo-brand')
 assert sentiment['overview']==s['monitor']['sentiment']['overview']
 assert sentiment['unknown_count']==3
 assert len(sentiment['negative_samples'])==len(s['monitor']['sentiment']['negative_samples'])
 answers=asyncio.run(M.answers(monitor_id='demo-brand'))['data']
 assert answers['group_total']==9
 assert sum(len(g['answers']) for g in answers['groups'])==36
print(json.dumps({'status':'PASS','scope':'isolated local aggregates only; identity gate mocked; no model/knowledge request','groups':9,'slots':36,'sentiment':sentiment['overview'],'unknown':sentiment['unknown_count'],'recommend':actual['recommend'],'rank':actual['rank']},ensure_ascii=False))
