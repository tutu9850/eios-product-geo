import { DEMO_COMPANY, DEMO_COMPETITOR, DEMO_MONITOR, DEMO_MATERIALS, DEMO_OBSERVATIONS, DEMO_ROUNDS } from './demo-monitor-samples'

/**
 * GEO 内测演示夹具。
 *
 * 这些内容是前端演示数据，不是企业事实、监测证据或 Foundation canonical 数据。
 * 只有用户显式打开“内测演示数据”开关时才会读取；关闭后页面只读真实产品门。
 */
export const GEO_DEMO_NOTICE = '内测演示数据 · 虚构企业与回答；解析、核验和行动为模拟结果，不进入正式统计或证据链'

const simulatedProfileOverview = {
  overall_coverage_pct: 68,
  total_items: 8,
  enough_count: 3,
  partial_count: 3,
  too_little_count: 2,
  note: GEO_DEMO_NOTICE,
}

export const GEO_DEMO_PROFILE_CATEGORIES = [
  { category: 'brand', name: '品牌与定位', items: [
    { id: 'demo-brand-positioning', name: '品牌定位', level: '足够', related_state: 'covered', coverage_pct: 86, related_count: 7 },
    { id: 'demo-brand-difference', name: '差异化优势', level: '部分', related_state: 'partial', coverage_pct: 58, related_count: 5 },
  ] },
  { category: 'product', name: '产品与服务', items: [
    { id: 'demo-product-lines', name: '产品线与规格', level: '足够', related_state: 'covered', coverage_pct: 79, related_count: 8 },
    { id: 'demo-product-quality', name: '品质与工艺', level: '部分', related_state: 'partial', coverage_pct: 52, related_count: 6 },
  ] },
  { category: 'scene', name: '场景与客户', items: [
    { id: 'demo-use-scenes', name: '适用场景', level: '部分', related_state: 'partial', coverage_pct: 61, related_count: 4 },
    { id: 'demo-customer-case', name: '客户案例', level: '太少', related_state: 'uncovered', coverage_pct: 24, related_count: 3 },
  ] },
  { category: 'trust', name: '信任与交付', items: [
    { id: 'demo-after-sale', name: '交付与售后', level: '太少', related_state: 'uncovered', coverage_pct: 18, related_count: 4 },
    { id: 'demo-certification', name: '认证与保障', level: '足够', related_state: 'covered', coverage_pct: 74, related_count: 3 },
  ] },
]

const simulatedProfileDetails: Record<string, Record<string, unknown>> = {
  'demo-brand-positioning': {
    id: 'demo-brand-positioning', name: '品牌定位', level: '足够', reason: '演示：品牌主张和目标客户已经有可直接引用的资料。',
    knowledge: { summary: '已有 4 条可引用的定位事实', counts: { entities: 1, facts: 4, relations: 2, doc_chunks: 4 }, doc_chunks: [
      { text: '云栖示例家居面向正在改善居住空间的年轻家庭，提供从产品选择到交付的一体化家居方案。', source: '演示·品牌介绍 v2' },
      { text: '品牌主张：把复杂的家居选择讲清楚，让用户能按预算、空间和生活方式做决定。', source: '演示·品牌手册 v1' },
    ] },
    uncovered_questions: [], partial_questions: [{ question: '云栖示例家居和传统定制家居有什么不同？' }],
  },
  'demo-brand-difference': {
    id: 'demo-brand-difference', name: '差异化优势', level: '部分', reason: '演示：有定位描述，但缺少可核验的对比案例。',
    knowledge: { summary: '定位有资料，差异化证据不完整', counts: { entities: 1, facts: 3, relations: 1, doc_chunks: 3 }, doc_chunks: [
      { text: '提供空间规划、材质建议和安装交付协同服务。', source: '演示·服务说明 v1' },
    ] },
    uncovered_questions: [{ question: '为什么选择云栖示例家居而不是星禾示例家居？' }], partial_questions: [{ question: '云栖示例家居有哪些独特工艺？' }],
  },
  'demo-product-lines': {
    id: 'demo-product-lines', name: '产品线与规格', level: '足够', reason: '演示：核心产品与规格信息可被当前问题池检索到。',
    knowledge: { summary: '产品资料覆盖 8 个问题', counts: { entities: 6, facts: 12, relations: 4, doc_chunks: 7 }, doc_chunks: [
      { text: '产品覆盖沙发、软床、柜类定制及配套小件，支持按空间尺寸进行组合。', source: '演示·产品目录 v3' },
      { text: '定制柜体可选门板、五金、内部收纳和颜色方案，具体以门店确认单为准。', source: '演示·定制说明 v2' },
    ] },
    uncovered_questions: [], partial_questions: [],
  },
  'demo-product-quality': {
    id: 'demo-product-quality', name: '品质与工艺', level: '部分', reason: '演示：工艺描述存在，但检测标准和批次证据不足。',
    knowledge: { summary: '工艺说明 3 条，检测依据 1 条', counts: { entities: 4, facts: 7, relations: 2, doc_chunks: 4 }, doc_chunks: [
      { text: '木作产品在出厂前执行外观、尺寸和五金开合检查。', source: '演示·质量流程 v1' },
    ] },
    uncovered_questions: [{ question: '云栖示例家居的板材和环保等级可靠吗？' }], partial_questions: [{ question: '云栖示例家居的定制误差怎么处理？' }],
  },
  'demo-use-scenes': {
    id: 'demo-use-scenes', name: '适用场景', level: '部分', reason: '演示：住宅场景有描述，商业空间和小户型案例尚未覆盖。',
    knowledge: { summary: '已有住宅场景资料', counts: { entities: 3, facts: 6, relations: 2, doc_chunks: 3 }, doc_chunks: [{ text: '适用于新房入住、旧房改善和局部空间升级。', source: '演示·场景手册 v1' }] },
    uncovered_questions: [{ question: '小户型如何选择云栖示例家居的柜类定制？' }], partial_questions: [],
  },
  'demo-customer-case': {
    id: 'demo-customer-case', name: '客户案例', level: '太少', reason: '演示：案例标题有记录，但缺少完整过程、预算和结果。',
    knowledge: { summary: '只有 1 个可检索案例片段', counts: { entities: 2, facts: 2, relations: 1, doc_chunks: 1 }, doc_chunks: [{ text: '成都某三居室完成客餐厅和主卧收纳改造。', source: '演示·案例摘要（待补全）' }] },
    uncovered_questions: [{ question: '有没有和我家面积相近的云栖示例家居案例？' }, { question: '云栖示例家居整套全屋定制要多久？' }], partial_questions: [],
  },
  'demo-after-sale': {
    id: 'demo-after-sale', name: '交付与售后', level: '太少', reason: '演示：当前缺少交付周期、验收和售后响应的公开说明。',
    knowledge: { summary: '没有足够资料支撑交付承诺', counts: { entities: 1, facts: 1, relations: 0, doc_chunks: 1 }, doc_chunks: [{ text: '交付安排需以具体订单和门店排期为准。', source: '演示·服务条款（片段）' }] },
    uncovered_questions: [{ question: '云栖示例家居延期交付怎么办？' }, { question: '云栖示例家居售后多久响应？' }], partial_questions: [],
  },
  'demo-certification': {
    id: 'demo-certification', name: '认证与保障', level: '足够', reason: '演示：已有可展示的材料来源，但仍需在正式环境核验有效期。',
    knowledge: { summary: '已有 3 条保障资料', counts: { entities: 2, facts: 5, relations: 1, doc_chunks: 3 }, doc_chunks: [
      { text: '演示材料：主要板材和五金供应商信息已登记，正式上线前需要补充有效期和原件链接。', source: '演示·供应商档案' },
    ] },
    uncovered_questions: [], partial_questions: [{ question: '云栖示例家居有哪些售后保障？' }],
  },
}

const simulatedHealth = {
  total: 64, sample_size: 36, subject_status: 'confirmed', subject_name: '云栖示例家居', evaluated_at: '2026-10-12T09:00:00+08:00', evaluation_scope: '内测演示样本', note: GEO_DEMO_NOTICE,
  dims: [
    { key: 'brand', label: '品牌认知', score: 72, basis: '36 条演示回答中有 26 条正确识别品牌定位' },
    { key: 'product', label: '产品认知', score: 58, basis: '产品线可识别，但规格描述不完整' },
    { key: 'scene', label: '场景覆盖', score: 61, basis: '住宅改善场景有回答，小户型案例不足' },
    { key: 'trust', label: '信任证据', score: 43, basis: '交付和售后证据不足' },
    { key: 'cases', label: '案例覆盖', score: 29, basis: '案例数量少，缺少结果字段' },
    { key: 'price', label: '价格透明度', score: 47, basis: '价格区间出现，但套餐条件不完整' },
    { key: 'difference', label: '差异化认知', score: 54, basis: '有服务差异描述，缺少对比证据' },
    { key: 'defense', label: '竞品防御力', score: 51, basis: '部分问题上竞品被提及更早' },
  ],
}

/** 总览与分析共用原始回答；资料覆盖为独立的模拟判定。 */
export const GEO_DEMO_ANALYTICS_COVERAGE = [
  { stage: '认知', coverage_pct: 100, question_count: 1, judged_count: 1 },
  { stage: '比较', coverage_pct: 0, question_count: 1, judged_count: 1 },
  { stage: '信任', coverage_pct: 100, question_count: 1, judged_count: 1 },
]
export const GEO_DEMO_OVERVIEW = {
  monitor: DEMO_MONITOR.overview,
  stats: {
    knowledge: { materials: DEMO_MATERIALS.length, text_blocks: DEMO_MATERIALS.length, bytes: new TextEncoder().encode(DEMO_MATERIALS.map(m => m.text).join('')).length },
    links: { total: 2, indexed: 1, failed: 0, pending: 1, unknown: 0 },
    monitor: DEMO_MONITOR.stats,
    engines: { total: 4, answered: new Set(DEMO_OBSERVATIONS.filter(r => r.round === 2 && r.answer).map(r => r.engine)).size },
  },
  distill: { funnel: GEO_DEMO_ANALYTICS_COVERAGE, ai_judgment: { stage: '比较', coverage_pct: 0, reason: '模拟：案例结果资料待补', samples: ['案例预算与结果'] }, open_gaps_count: 2 },
  notice: GEO_DEMO_NOTICE,
}
export const GEO_DEMO_ANALYTICS_SNAPSHOT = DEMO_MONITOR.analytics
export const GEO_DEMO_ANALYTICS_DIMENSIONS = [
  { dimension: '品牌定位', score: 72 }, { dimension: '产品能力', score: 58 },
  { dimension: '交付售后', score: 43 }, { dimension: '客户案例', score: 29 },
]
export const GEO_DEMO_MONITOR_ANSWERS = {
  groups: DEMO_MONITOR.groups, group_total: DEMO_MONITOR.groups.length, page: 1, pages: 1, notice: GEO_DEMO_NOTICE,
}
export const GEO_DEMO_REPORT_SENTIMENT = {
  ...DEMO_MONITOR.sentiment,
  trend: DEMO_MONITOR.sentiment.trend.map(r => ({ ...r, date: r.ts })),
  questions: DEMO_MONITOR.sentiment.questions.map(r => r.question),
}
export const GEO_DEMO_REPORT_SOURCES = DEMO_MONITOR.sources.map(r => ({ label: r.engine, count: DEMO_OBSERVATIONS.filter(a => a.engine === r.engine && a.answer).length, share: Math.round(DEMO_OBSERVATIONS.filter(a => a.engine === r.engine && a.answer).length / DEMO_MONITOR.summary.answered * 100) }))
export const GEO_DEMO_REPORT_CITATIONS = DEMO_MONITOR.citations

export const GEO_DEMO_ACTIONS = [
  { level: 'P0' as const, name: '《交付周期与售后说明》', bound: '云栖示例家居交付和售后怎么样？', stage: '信任', channel: '官网 + 知乎', status: '规划中' },
  { level: 'P0' as const, name: '《住宅案例预算与结果》', bound: '云栖示例家居与星禾示例家居有哪些案例差异？', stage: '比较', channel: '官网 + 小红书', status: '未开始' },
]

export const GEO_DEMO_MARKET = {
  watch: [
    { id: 'demo-watch-1', type: 'website', name: '星禾示例家居官网', url: 'https://example.invalid/sofia', created_at: '2026-09-20' },
    { id: 'demo-watch-2', type: 'news', name: '家居行业动态', url: 'https://example.invalid/home-news', created_at: '2026-09-20' },
  ],
  signals: [
    { id: 'demo-signal-1', status: 'new', source_name: '家居行业动态', source_type: '媒体', title: '定制家居开始公开交付节点和验收方式', summary: '行业头部品牌近期把交付周期、验收节点和售后响应写进公开内容，客户比较时会优先寻找这些信息。', facts: ['交付节点更容易被客户直接比较', '售后响应时间成为信任信号'], created_at: '2026-09-25' },
    { id: 'demo-signal-2', status: 'planned', source_name: '星禾示例家居官网', source_type: '官网', title: '完整案例被用于解释不同户型的方案差异', summary: '竞品案例内容同时呈现户型、预算、周期和结果，帮助模型给出更具体的推荐。', facts: ['案例结果比口号更容易被引用'], created_at: '2026-09-23' },
  ],
  links: [
    { id: 'demo-link-1', name: '成都三居室收纳改造案例', url: 'https://example.invalid/case-01', index_status: 'indexed', status_note: '已收录', created_at: '2026-09-22' },
    { id: 'demo-link-2', name: '交付与售后说明', url: 'https://example.invalid/service-01', index_status: 'pending', status_note: '等待检测', created_at: '2026-09-25' },
  ],
} as const

/** 解析维度/策略为人工编排；样本总数、提及与引用回绑真实的演示原话。 */
const observed = DEMO_MONITOR.summary
const sampleNote = { total: observed.answered, reliability: '模拟解析', note: GEO_DEMO_NOTICE }
const latestAt = `${DEMO_ROUNDS.at(-1)}T09:00:00+08:00`
const factors = ['交付售后', '客户案例', '空间规划']
const factorRows = factors.map(factor => {
  const records = DEMO_OBSERVATIONS.filter(r => r.factor === factor && r.answer)
  const self = records.filter(r => r.mentioned === true)
  const other = records.filter(r => r.competitor_mentioned)
  return { factor, dimension: factor, self_mentions: self.length, competitor_mentions: other.length,
    competitor_leader: other.length ? DEMO_COMPETITOR : DEMO_COMPANY,
    missing_note: factor === '空间规划' ? '模拟：有产品组合依据' : factor === '客户案例' ? '模拟：案例缺少预算和结果' : '模拟：仍缺统一交付时限',
    quotes: records.slice(0, 2).map(r => ({ quote: r.answer, brand: r.competitor_mentioned ? DEMO_COMPETITOR : DEMO_COMPANY })) }
})
const left = factorRows.filter(r => r.factor !== '空间规划')
const right = factorRows.filter(r => r.factor === '空间规划')
const riskNotes = DEMO_OBSERVATIONS.filter(r => r.check === 'review').map(r => ({ factor: r.factor, quote: r.answer, brand: DEMO_COMPANY }))
const competitorMentions = DEMO_OBSERVATIONS.filter(r => r.competitor_mentioned).length
const recommended = DEMO_OBSERVATIONS.filter(r => r.sentiment === 'positive').length
const trend = DEMO_ROUNDS.map((period, round) => {
  const records = DEMO_OBSERVATIONS.filter(r => r.round === round && r.answer)
  // 该样例仅我方有明确推荐句；推荐份额=我方推荐/全部品牌推荐。
  return { period, brands: [{ brand: DEMO_COMPANY, recommend_share: records.some(r => r.sentiment === 'positive') ? 100 : 0 }] }
})
export const GEO_DEMO_INSIGHT = {
  humanize: {
    headline: { main: '品牌能被看见，案例与交付口径仍需补齐', sub: '模拟解析：比较完整案例、复核统一交付承诺，再用同一组问题复测。', tone: 'watch' },
    metrics: { exposure_rate: observed.mention_pct, recommendation_rate: observed.recommendation_pct, gap_count: left.length, gap_dimensions: left.map(r => ({ dimension: r.dimension })) },
    left, right, risk_notes: riskNotes,
    actions: [{ priority: 'P0', score: 91, what: '复核交付承诺并补案例结果', why: '人工编排的模拟行动建议', keywords: ['交付', '案例'] }], sample_note: sampleNote,
  },
  overview: { company: DEMO_COMPANY, mode: 'demo', total_evidence: observed.answered, self_name: DEMO_COMPANY, brands: [
    { name: DEMO_COMPANY, is_self: true, mentions: observed.recognised, rate: observed.mention_pct },
    { name: DEMO_COMPETITOR, is_self: false, mentions: competitorMentions, rate: Math.round(competitorMentions / observed.answered * 100) },
  ] },
  sov: { period_days: 15, total_mention: observed.recognised + competitorMentions, total_recommend: recommended,
    self: { brand: DEMO_COMPANY, is_self: true, mention_count: observed.recognised, mention_share: Math.round(observed.recognised / (observed.recognised + competitorMentions) * 100), recommend_count: recommended, recommend_share: 100, missing_count: observed.not_mentioned },
    brands: [], trend, note: '模拟解析；提及率以成功回答为分母，推荐率以成功回答为分母，推荐份额以全部品牌推荐次数为分母。' },
  'trend-delta': { periods: trend.slice(-2).map(r => ({ period: r.period, brands: { [DEMO_COMPANY]: r.brands[0].recommend_share } })), gained: [], lost: [], rising: [], falling: [], note: '同一批样例的推荐份额；不要与推荐回答占比混用。' },
  matrix: { evidence_count: observed.answered, dimensions: factorRows.map(r => ({ dimension: r.dimension, band: r.factor === '空间规划' ? 'green' : 'red', band_label: r.factor === '空间规划' ? '优势' : '资料待补', verdict: r.factor === '空间规划' ? 'win' : 'loss', total_mentions: r.self_mentions + r.competitor_mentions, self_mentions: r.self_mentions, other_mentions: r.competitor_mentions, quotes: r.quotes })), observation: [], missing: [] },
  'factor-gaps': { left, right, risk_notes: riskNotes, sample_note: sampleNote },
  'gap-analysis': { knowledge_gaps: [{ dimension: '交付售后', competitor_leader: DEMO_COMPETITOR, action: '模拟：核对并补齐交付口径', gap_type: 'knowledge' }], evidence_gaps: [{ dimension: '客户案例', competitor_leader: DEMO_COMPETITOR, action: '模拟：补齐预算和结果', gap_type: 'evidence' }], sample_note: sampleNote },
  keywords: { keywords: factors.map(keyword => ({ keyword, mentions: DEMO_OBSERVATIONS.filter(r => r.factor === keyword && r.answer).length, band: keyword === '空间规划' ? 'green' : 'red' })) },
  perception: { evidence_count: observed.answered, tags: factors.map(tag => ({ tag, count: DEMO_OBSERVATIONS.filter(r => r.factor === tag && r.answer).length })), self_tags: factorRows.map(r => ({ tag: r.factor, count: r.self_mentions })) },
  strategies: { score_formula: '模拟优先级；非真实算法评估', sample_note: sampleNote, strategies: [{ dimension: '交付售后', score: 91, priority: 'P0', topic: '把交付口径讲清楚', self_level_label: '资料待补', competitor_leader: DEMO_COMPETITOR, keywords: ['交付', '售后'], evidence_note: '模拟解析：统一承诺缺依据', comp_quotes: factorRows[0].quotes }] },
}
export const GEO_DEMO_EVIDENCE: Record<string, unknown> = Object.fromEntries(factors.map(factor => {
  const rows = DEMO_OBSERVATIONS.filter(r => r.factor === factor && r.answer)
  return [factor, { factor, semantic: '模拟解析', dimension: factor, propagation: rows.length,
    sources: rows.map(r => ({ evidence_id: r.id, platform: r.engine, observed_at: r.ts, mention_type: r.check === 'supported' ? 'win' : 'gap', intent: r.factor === '客户案例' ? '比较' : '选择', quote: r.answer, brand: DEMO_COMPANY })), related_factors: [] }]
}))
const claimRows = DEMO_OBSERVATIONS.filter(r => r.check === 'supported' || r.check === 'unsupported' || r.check === 'review')
const cognitionMatrix = factors.map(factor => {
  const claims = claimRows.filter(r => r.factor === factor)
  const grounded = claims.filter(r => r.check === 'supported').length
  return { key: factor, label: factor, claims: claims.length, grounded, partial: claims.filter(r => r.check === 'unsupported').length,
    hallucination: claims.filter(r => r.check === 'review').length, status: claims.length ? `模拟：${Math.round(grounded / claims.length * 100)}% 有依据` : '模拟：无可核验断言' }
})
export const GEO_DEMO_COGNITION_PROFILE = {
  total: observed.answered, evaluated_at: latestAt, health: 64,
  metrics: { awareness: observed.mention_pct, understanding: Math.round(claimRows.filter(r => r.check === 'supported').length / claimRows.length * 100), hallucination: Math.round(claimRows.filter(r => r.check !== 'supported').length / claimRows.length * 100), recommendation: observed.recommendation_pct },
  matrix: cognitionMatrix,
  errors: DEMO_OBSERVATIONS.filter(r => r.check === 'review' || r.check === 'unsupported').map(r => ({ claim: r.answer, type: r.check === 'review' ? '模拟口径冲突' : '模拟缺少依据', engine: r.engine, question: r.question })), note: GEO_DEMO_NOTICE,
}
export const GEO_DEMO_HEALTH = { ...simulatedHealth, sample_size: observed.answered, evaluated_at: latestAt, dims: simulatedHealth.dims.map(d => d.key === 'brand' ? { ...d, score: observed.mention_pct, basis: `${observed.slots} 个演示槽位：${observed.answered} 条回答、${observed.recognised} 条确认提及、${observed.unknown} 条主体未知、${observed.failed} 条失败；语义评分为模拟。` } : d) }
export const GEO_DEMO_PORTRAIT = {
  ai_health: 64, material_count: DEMO_MATERIALS.length, evaluated_at: latestAt, note: GEO_DEMO_NOTICE,
  items: cognitionMatrix.filter(r => r.claims > 0).map(r => ({ key: r.key, label: r.label, profile: '模拟资料对照', ai_status: r.status, ai_grounded: r.grounded, ai_claims: r.claims, deviation: r.grounded === r.claims ? '一致' : '资料待补', evidence_count: 1, evidence: [{ title: DEMO_MATERIALS[r.key === '空间规划' ? 0 : 1].title }] })),
}

export const GEO_DEMO_PROFILE_OVERVIEW = {
  ...simulatedProfileOverview,
  overall_coverage_pct: Math.round(GEO_DEMO_PROFILE_CATEGORIES.flatMap(c => c.items).reduce((n, i) => n + i.coverage_pct, 0) / simulatedProfileOverview.total_items),
  note: `${GEO_DEMO_NOTICE}；覆盖率为8项模拟评分的均值。`,
}
export const GEO_DEMO_PROFILE_DETAILS: Record<string, Record<string, unknown>> = Object.fromEntries(Object.entries(simulatedProfileDetails).map(([id, item]) => {
  const material = DEMO_MATERIALS[id.includes('case') || id.includes('scene') ? 2 : id.includes('sale') || id.includes('certification') ? 1 : 0]
  return [id, { ...item, knowledge: { summary: '模拟资料匹配；不代表已读取正式Fact', counts: { entities: 0, facts: 0, relations: 0, doc_chunks: 1 }, doc_chunks: [{ text: material.text, source: material.title }] } }]
}))
