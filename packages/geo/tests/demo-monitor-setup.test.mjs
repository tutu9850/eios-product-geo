import test from 'node:test'
import assert from 'node:assert/strict'
import { emptySetup, saveSetupObject, runSetupObject } from '../src/geo-advisor/demo-monitor-setup.ts'

test('object configuration controls every first-round slot, preserves history and isolates subjects',()=>{
 const config={name:'虚构甲企业',competitors:'虚构乙企业',questions:['交付如何？','产品是什么？','交付如何？'],engines:['Kimi','DeepSeek','unknown']}
 let state=saveSetupObject(emptySetup(),config,'object-a')
 assert.equal(state.objects[0].questions.length,2)
 assert.equal(state.objects[0].engines.length,2)
 assert.throws(()=>saveSetupObject(state,config,'duplicate'))
 assert.throws(()=>saveSetupObject(emptySetup(),{...config,questions:[]},'a'))
 assert.throws(()=>saveSetupObject(emptySetup(),{...config,engines:[]},'a'))
 state=runSetupObject(state,'object-a','2026-10-13T01:00:00Z')
 assert.equal(state.objects[0].runs[0].answers.length,4)
 assert.equal(new Set(state.objects[0].runs[0].answers.map(a=>a.id)).size,4)
 assert.ok(state.objects[0].runs[0].answers.every(a=>a.text.includes('虚构甲企业')&&config.questions.includes(a.question)&&config.engines.includes(a.engine)))
 state=saveSetupObject(state,{...config,name:'虚构乙企业',questions:['乙的问题'],engines:['通义']},'object-b')
 state=runSetupObject(state,'object-b','2026-10-13T02:00:00Z')
 assert.equal(state.objects[1].runs[0].answers.length,1)
 assert.equal(state.objects[0].runs[0].answers.length,4)
 state=saveSetupObject(state,{...config,questions:['新问题'],engines:['豆包']},'unused','object-a')
 assert.equal(state.objects[0].runs.length,1)
 state=runSetupObject(state,'object-a','2026-10-13T03:00:00Z')
 assert.equal(state.objects[0].runs[1].answers.length,1)
 assert.equal(state.objects[0].runs[1].answers[0].question,'新问题')
 state={...state,objects:state.objects.map(o=>({...o,status:'paused'}))}
 assert.throws(()=>runSetupObject(state,'object-a','2026-10-13T04:00:00Z'))
 const reopened=JSON.parse(JSON.stringify(state))
 assert.equal(reopened.objects[0].runs.length,2)
})
