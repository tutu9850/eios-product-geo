import test from 'node:test'
import assert from 'node:assert/strict'
import { emptyJourney, journeyReducer as step, sampleComparison } from '../src/geo-advisor/demo-journey.ts'

test('sample action preserves evidence, refuses unsaved publication, and requires a later round', () => {
 let state=step(emptyJourney(),{type:'plan',gap:'case'})
 state=step(state,{type:'plan',gap:'case'})
 assert.equal(state.plans.length,1)
 state=step(state,{type:'generate'})
 assert.match(state.plans[0].draft,/demo-material-case/)
 const at='2026-10-12T10:00:00Z'
 state=step(state,{type:'publish',url:'https://example.invalid/sample',at})
 assert.equal(state.plans[0].publishedAt,null)
 state=step(state,{type:'save'})
 const saved=state.plans[0].saved
 state=step(state,{type:'edit',text:'unsaved'})
 state=step(state,{type:'publish',url:'https://example.invalid/sample',at})
 assert.equal(state.plans[0].publishedAt,null)
 state=step(state,{type:'reopen'})
 assert.equal(state.plans[0].draft,saved)
 state=step(state,{type:'publish',url:'javascript:alert(1)',at})
 assert.equal(state.plans[0].publishedAt,null)
 state=step(state,{type:'publish',url:'https://example.invalid/sample',at})
 assert.equal(sampleComparison(state,state.plans[0]),null)
 state=step(state,{type:'round',at})
 assert.equal(state.extra.length,0)
 state=step(state,{type:'round',at:'2026-10-12T11:00:00Z'})
 const result=sampleComparison(state,state.plans[0])
 assert.equal(result.beforeCount,3)
 assert.equal(result.afterCount,3)
 assert.equal(state.extra.length,4)
 assert.equal(new Set(state.extra.map(r=>r.id)).size,4)
 assert.equal(step(state,{type:'round',at:'2026-10-12T12:00:00Z'}).extra.length,4)
 const reopened=JSON.parse(JSON.stringify(state))
 assert.equal(reopened.plans[0].saved,saved)
 assert.deepEqual(step(reopened,{type:'reset'}),emptyJourney())
})
