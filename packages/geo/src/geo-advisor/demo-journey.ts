import { DEMO_OBSERVATIONS, DEMO_MATERIALS, type DemoObservation } from './demo-monitor-samples.ts'

export const JOURNEY_KEY = 'geo.ui-review.journey.v1'
export const SAMPLE_GAPS = [
  { id: 'delivery', title: '交付周期与售后说明', question: 1, detail: '回答没有统一时限依据；保留按订单排期，补齐客户确认流程。', material: 1 },
  { id: 'case', title: '住宅案例的预算与结果', question: 2, detail: '已有案例摘要，但预算与结果缺失；待确认字段不能写成承诺。', material: 2 },
]
export type SamplePlan = { id: string; gap: string; title: string; draft: string; saved: string; publishedAt: string | null; url: string }
export type JourneyState = { plans: SamplePlan[]; selected: string | null; extra: DemoObservation[] }
export const emptyJourney = (): JourneyState => ({ plans: [], selected: null, extra: [] })
export type JourneyAction = { type: 'plan'; gap: string } | { type: 'select'; id: string } | { type: 'generate' } | { type: 'edit'; text: string } | { type: 'save' } | { type: 'reopen' } | { type: 'publish'; url: string; at: string } | { type: 'round'; at: string } | { type: 'reset' }
export function journeyReducer(state: JourneyState, action: JourneyAction): JourneyState {
  if (action.type === 'reset') return emptyJourney()
  if (action.type === 'plan') {
    const gap = SAMPLE_GAPS.find(g => g.id === action.gap)
    if (!gap) return state
    const id = `sample-plan-${gap.id}`
    return { ...state, selected: id, plans: state.plans.some(p => p.id === id) ? state.plans : [...state.plans, { id, gap: gap.id, title: gap.title, draft: '', saved: '', publishedAt: null, url: '' }] }
  }
  if (action.type === 'select') return state.plans.some(p => p.id === action.id) ? { ...state, selected: action.id } : state
  const plan = state.plans.find(p => p.id === state.selected)
  if (!plan) return state
  const gap = SAMPLE_GAPS.find(g => g.id === plan.gap)!
  if (action.type === 'round') {
    if (!plan.publishedAt || Date.parse(action.at) <= Date.parse(plan.publishedAt)) return state
    const existing = state.extra.filter(r => r.query_id === `demo-query-${gap.question + 1}`)
    if (existing.length) return state
    const baseline = DEMO_OBSERVATIONS.filter(r => r.round === 2 && r.query_id === `demo-query-${gap.question + 1}`)
    return { ...state, extra: [...state.extra, ...baseline.map(r => ({ ...r, id: `${plan.id}-post-${r.engine}`, round: 3, ts: action.at, answer: r.answer ? `${r.answer}\n（发布后模拟回答；用于演练操作，不表示真实效果。）` : '', snippet: r.snippet }))] }
  }
  let next = plan
  if (action.type === 'generate' && !plan.publishedAt) next = { ...plan, draft: `【演示草稿】${gap.title}\n\n${DEMO_MATERIALS[gap.material].text}\n\n客户确认清单：核对订单、约定范围与适用条件。具体时限、预算和结果待企业确认，不作统一承诺。\n\n样例出处：${DEMO_MATERIALS[gap.material].id}` }
  if (action.type === 'edit' && !plan.publishedAt) next = { ...plan, draft: action.text }
  if (action.type === 'save' && plan.draft.trim() && !plan.publishedAt) next = { ...plan, saved: plan.draft }
  if (action.type === 'reopen') next = { ...plan, draft: plan.saved }
  if (action.type === 'publish' && plan.saved.trim() && plan.saved === plan.draft && !plan.publishedAt && Number.isFinite(Date.parse(action.at))) {
    try { const u = new URL(action.url); if (['http:', 'https:'].includes(u.protocol)) next = { ...plan, publishedAt: action.at, url: u.href } } catch { return state }
  }
  return { ...state, plans: state.plans.map(p => p.id === next.id ? next : p) }
}
export function sampleComparison(state: JourneyState, plan: SamplePlan) {
  const gap = SAMPLE_GAPS.find(g => g.id === plan.gap)!
  const query = `demo-query-${gap.question + 1}`
  const before = DEMO_OBSERVATIONS.filter(r => r.round === 2 && r.query_id === query && r.answer)
  const after = state.extra.filter(r => r.query_id === query && r.answer && plan.publishedAt && Date.parse(r.ts) > Date.parse(plan.publishedAt))
  const rate = (rows: DemoObservation[]) => rows.filter(r => r.mentioned === true).length / rows.length * 100
  return after.length && before.length ? { before: rate(before), after: rate(after), delta: rate(after) - rate(before), beforeCount: before.length, afterCount: after.length } : null
}
