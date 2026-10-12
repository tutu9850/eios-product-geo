"""Isolated wiring probe. Run with GEO_DB_PATH under /tmp/eios-test/ only.
External catalog/knowledge/model boundaries are substitutes, not live proof.
"""
import asyncio, json, os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

assert Path(os.environ['GEO_DB_PATH']).resolve().is_relative_to(Path('/tmp/eios-test').resolve())
from app.services.store import get_store, set_tenant
from app.api.v1 import monitor, stats, cognition, distill, intelligence
from services.intelligence import adapter, repo, extractor

async def main():
    set_tenant('audit_isolated')
    store = get_store()
    company = '审计样例甲公司'
    now = datetime.now(timezone.utc).isoformat()
    subject = {'monitor_id':'audit-brand','type':'brand','status':'active',
               'entity':company,'config_json':{'company':company,'industry':'家居'}}
    store.save('monitor_items',[subject])
    question = '有哪些家居企业值得选择？'
    answer = f'推荐{company}，提供家居服务。'
    history = {'id':'audit-history','created_at':now,'batch':True,'company_name':company,
      'summary':{'mentioned_questions':1,'coverage_pct':100},'questions':[
       {'query_id':'audit-query','monitor_id':'audit-brand','item_type':'brand','question':question,
        'configured_count':1,'engine_detail':[
         {'engine_name':'AuditModel','answer':answer,'snippet':answer,'mentioned':True,'sentiment':'positive','rank_est':1},
         {'engine_name':'FailedModel','answer':'','snippet':'','mentioned':False,'error':'isolated failure'}]}]}
    async def catalog(): return [{'id':'audit-model','name':'AuditModel'}]
    async def no_entities(*args,**kwargs): return []
    async def unavailable(*args,**kwargs): raise RuntimeError('isolated knowledge unavailable')
    results = {'boundaries':['synthetic history','model output substitute','catalog substitute','knowledge unavailable substitute'], 'phases':{}}
    with patch('adapters.engines.list_engines',catalog), patch('adapters.eios.get_entities',no_entities), patch('adapters.eios.search_knowledge',unavailable):
      # Persist with the existing monitor hook; defer actual parsing to avoid outbound work.
      queued=[]
      with patch('services.intelligence.queue.enqueue',lambda eid,**kw: queued.append(eid)):
        monitor._append_history(history)
      assert len(store.load('monitor_history'))==1 and len(queued)==1
      results['hook']={'history':1,'queued':len(queued),'reingest_new':adapter.ingest_one_history(history,enqueue_parsing=False)}
      async def read_phase():
        out={}
        for key,fn in [('stats',stats.overview),('answers',lambda:monitor.answers(monitor_id='audit-brand')),
          ('sentiment',lambda:monitor.sentiment(monitor_id='audit-brand')),('monitor',lambda:monitor.overview(monitor_id='audit-brand')),
          ('intelligence',lambda:intelligence.overview(monitor_id='audit-brand')),
          ('profile',distill.cognition_profile_v2),('health',lambda:cognition.health(monitor_id='audit-brand')),
          ('distill',distill.distill_overview)]:
          value=fn()
          if hasattr(value,'__await__'):value=await value
          out[key]=value
        return out
      results['phases']['history_only']=await read_phase()
      async def fake_chat(*args,**kwargs):
        return json.dumps({'brands':[{'name':company,'reasons':[{'factor':'家居服务','evidence_quote':answer,'confidence':0.9}]}],
          'self_brand':{'name':company,'mentioned':True,'recommended':True,'evidence_quote':answer},'intent':'recommendation'},ensure_ascii=False)
      with patch('adapters.llm.chat',fake_chat):
        results['extraction']=await extractor.analyze_evidence(queued[0])
      assert results['extraction']['status']=='succeeded'
      assert repo.get_evidence(queued[0])['raw_text']==answer
      assert repo.list_mentions(evidence_id=queued[0])[0]['evidence_quote']==answer
      results['phases']['parsed']=await read_phase()
      assert results['phases']['parsed']['profile']['data']['total']==0
      # Existing cognitive evaluation storage is account-wide and has no monitor linkage.
      store.save('cognition_evaluations',[{'id':'isolated-evaluation','answer_id':'random-evaluation-id',
        'engine':'AuditModel','question':question,'answer_text':answer,'mention_status':'mentioned',
        'question_contains_company':False,'claims':[{'claim':'提供家居服务','claim_type':'product','status':'grounded'}],
        'recommendation':'positive','created_at':now}])
      results['phases']['evaluated']=await read_phase()
      results['question_stats']=distill._question_monitor_stats(question)
      assert results['question_stats']['freq']==2 # Includes failed model slots in this legacy statistic.
      store.save('monitor_items',[subject,{'monitor_id':'audit-other','type':'brand','status':'active','entity':'审计样例乙公司','config_json':{'company':'审计样例乙公司'}}])
      results['other_subject_health']=await cognition.health(monitor_id='audit-other')
      assert results['other_subject_health']['data']['sample_size']==1 # Same account-wide evaluation leaks scope.
      store.save('content_plans',[{'id':'audit-plan','topic':'家居服务','target_question':question,'status':'planned'}])
      results['publish_registration']=await distill.content_publish(distill.PublishIn(plan_id='audit-plan',published_url='https://example.invalid/audit'))
      results['recheck_without_new_run']=await distill.content_recheck(distill.RecheckIn(plan_id='audit-plan'))
      assert results['publish_registration']['data']['published']
      assert store.load('content_plans')[0]['status']=='published'
      results['formal_reader_unbound']=None
      from adapters.eios import read_formal_content_sources, EIOSKnowledgeError
      try: await read_formal_content_sources()
      except EIOSKnowledgeError as exc:results['formal_reader_unbound']=exc.code
      assert results['formal_reader_unbound']=='FORMAL_READER_NOT_BOUND'
    print(json.dumps(results,ensure_ascii=False,indent=2,default=str))

asyncio.run(main())
