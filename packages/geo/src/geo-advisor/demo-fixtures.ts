/**
 * GEO 内测演示夹具。
 *
 * 这些内容是前端演示数据，不是企业事实、监测证据或 Foundation canonical 数据。
 * 只有用户显式打开“内测演示数据”开关时才会读取；关闭后页面只读真实产品门。
 */
export const GEO_DEMO_NOTICE = '内测演示数据 · 虚构内容，不进入正式统计、报告或证据链'

export const GEO_DEMO_PROFILE_OVERVIEW = {
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

export const GEO_DEMO_PROFILE_DETAILS: Record<string, Record<string, unknown>> = {
  'demo-brand-positioning': {
    id: 'demo-brand-positioning', name: '品牌定位', level: '足够', reason: '演示：品牌主张和目标客户已经有可直接引用的资料。',
    knowledge: { summary: '已有 4 条可引用的定位事实', counts: { entities: 1, facts: 4, relations: 2, doc_chunks: 4 }, doc_chunks: [
      { text: '笔革家居面向正在改善居住空间的年轻家庭，提供从产品选择到交付的一体化家居方案。', source: '演示·品牌介绍 v2' },
      { text: '品牌主张：把复杂的家居选择讲清楚，让用户能按预算、空间和生活方式做决定。', source: '演示·品牌手册 v1' },
    ] },
    uncovered_questions: [], partial_questions: [{ question: '笔革家居和传统定制家居有什么不同？' }],
  },
  'demo-brand-difference': {
    id: 'demo-brand-difference', name: '差异化优势', level: '部分', reason: '演示：有定位描述，但缺少可核验的对比案例。',
    knowledge: { summary: '定位有资料，差异化证据不完整', counts: { entities: 1, facts: 3, relations: 1, doc_chunks: 3 }, doc_chunks: [
      { text: '提供空间规划、材质建议和安装交付协同服务。', source: '演示·服务说明 v1' },
    ] },
    uncovered_questions: [{ question: '为什么选择笔革家居而不是索菲亚？' }], partial_questions: [{ question: '笔革家居有哪些独特工艺？' }],
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
    uncovered_questions: [{ question: '笔革家居的板材和环保等级可靠吗？' }], partial_questions: [{ question: '笔革家居的定制误差怎么处理？' }],
  },
  'demo-use-scenes': {
    id: 'demo-use-scenes', name: '适用场景', level: '部分', reason: '演示：住宅场景有描述，商业空间和小户型案例尚未覆盖。',
    knowledge: { summary: '已有住宅场景资料', counts: { entities: 3, facts: 6, relations: 2, doc_chunks: 3 }, doc_chunks: [{ text: '适用于新房入住、旧房改善和局部空间升级。', source: '演示·场景手册 v1' }] },
    uncovered_questions: [{ question: '小户型如何选择笔革家居的柜类定制？' }], partial_questions: [],
  },
  'demo-customer-case': {
    id: 'demo-customer-case', name: '客户案例', level: '太少', reason: '演示：案例标题有记录，但缺少完整过程、预算和结果。',
    knowledge: { summary: '只有 1 个可检索案例片段', counts: { entities: 2, facts: 2, relations: 1, doc_chunks: 1 }, doc_chunks: [{ text: '成都某三居室完成客餐厅和主卧收纳改造。', source: '演示·案例摘要（待补全）' }] },
    uncovered_questions: [{ question: '有没有和我家面积相近的笔革家居案例？' }, { question: '笔革家居整套全屋定制要多久？' }], partial_questions: [],
  },
  'demo-after-sale': {
    id: 'demo-after-sale', name: '交付与售后', level: '太少', reason: '演示：当前缺少交付周期、验收和售后响应的公开说明。',
    knowledge: { summary: '没有足够资料支撑交付承诺', counts: { entities: 1, facts: 1, relations: 0, doc_chunks: 1 }, doc_chunks: [{ text: '交付安排需以具体订单和门店排期为准。', source: '演示·服务条款（片段）' }] },
    uncovered_questions: [{ question: '笔革家居延期交付怎么办？' }, { question: '笔革家居售后多久响应？' }], partial_questions: [],
  },
  'demo-certification': {
    id: 'demo-certification', name: '认证与保障', level: '足够', reason: '演示：已有可展示的材料来源，但仍需在正式环境核验有效期。',
    knowledge: { summary: '已有 3 条保障资料', counts: { entities: 2, facts: 5, relations: 1, doc_chunks: 3 }, doc_chunks: [
      { text: '演示材料：主要板材和五金供应商信息已登记，正式上线前需要补充有效期和原件链接。', source: '演示·供应商档案' },
    ] },
    uncovered_questions: [], partial_questions: [{ question: '笔革家居有哪些售后保障？' }],
  },
}

export const GEO_DEMO_COGNITION_PROFILE = {
  total: 36,
  evaluated_at: '2026-09-25T09:00:00+08:00',
  health: 64,
  metrics: { awareness: 72, understanding: 58, hallucination: 21, recommendation: 46 },
  matrix: [
    { key: 'positioning', label: '品牌定位', claims: 8, grounded: 6, partial: 2, hallucination: 0, status: '75% 有依据' },
    { key: 'product', label: '产品能力', claims: 9, grounded: 5, partial: 3, hallucination: 1, status: '56% 有依据' },
    { key: 'delivery', label: '交付售后', claims: 6, grounded: 2, partial: 2, hallucination: 2, status: '33% 有依据' },
    { key: 'cases', label: '客户案例', claims: 5, grounded: 1, partial: 2, hallucination: 2, status: '20% 有依据' },
  ],
  errors: [
    { claim: '把演示中的行业常识当成笔革家居的具体承诺', type: 'unsupported', engine: 'DeepSeek', question: '笔革家居有哪些缺点？' },
    { claim: '无法从公开回答确认真实交付周期', type: 'insufficient_evidence', engine: '豆包', question: '笔革家居整套全屋定制要多久？' },
  ],
  note: GEO_DEMO_NOTICE,
}

export const GEO_DEMO_HEALTH = {
  total: 64, sample_size: 36, subject_status: 'confirmed', subject_name: '笔革家居', evaluated_at: '2026-09-25T09:00:00+08:00', evaluation_scope: '内测演示样本', note: GEO_DEMO_NOTICE,
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

export const GEO_DEMO_PORTRAIT = {
  ai_health: 64, material_count: 12, evaluated_at: '2026-09-25T09:00:00+08:00', note: GEO_DEMO_NOTICE,
  items: [
    { key: 'brand', label: '品牌定位', profile: '已有 4 份定位资料', ai_status: '基本一致', ai_grounded: 6, ai_claims: 8, deviation: '一致', evidence_count: 4, evidence: [{ title: '演示·品牌手册 v1' }] },
    { key: 'product', label: '产品能力', profile: '已有产品目录和定制说明', ai_status: '部分覆盖', ai_grounded: 5, ai_claims: 9, deviation: '部分缺口', evidence_count: 2, evidence: [{ title: '演示·产品目录 v3' }] },
    { key: 'trust', label: '交付售后', profile: '缺少公开交付承诺', ai_status: '依据不足', ai_grounded: 2, ai_claims: 6, deviation: '证据不足', evidence_count: 0, evidence: [] },
    { key: 'cases', label: '客户案例', profile: '1 个案例片段', ai_status: '案例不足', ai_grounded: 1, ai_claims: 5, deviation: '明显缺口', evidence_count: 1, evidence: [{ title: '演示·案例摘要（待补全）' }] },
  ],
}

export const GEO_DEMO_INSIGHT = {
  humanize: {
    headline: { main: '品牌已经能被看见，但交付证据还没有形成稳定认知', sub: '演示样本显示：产品定位能被复述，案例、售后和差异化证据是下一步重点。', tone: 'watch' },
    metrics: { exposure_rate: 72, recommendation_rate: 46, gap_count: 3, gap_dimensions: [{ dimension: '交付售后' }, { dimension: '客户案例' }, { dimension: '差异化优势' }] },
    left: [
      { factor: '交付周期说明', dimension: '交付售后', self_mentions: 1, competitor_mentions: 7, competitor_leader: '索菲亚', missing_note: '竞品有明确时间口径，我方缺少可引用说明', quotes: [{ quote: '竞品回答里会先说明交付节点和影响因素。', brand: '索菲亚' }] },
      { factor: '真实案例结果', dimension: '客户案例', self_mentions: 1, competitor_mentions: 6, competitor_leader: '全友家居', missing_note: '只有案例标题，没有预算、周期和结果', quotes: [{ quote: '回答通常会引用完整案例来说明适用场景。', brand: '全友家居' }] },
      { factor: '定制差异化', dimension: '差异化优势', self_mentions: 2, competitor_mentions: 5, competitor_leader: '掌上明珠', missing_note: '服务描述存在，缺少可比较的结果证据', quotes: [{ quote: '对比回答更容易相信有明确流程和结果的一方。', brand: '掌上明珠' }] },
    ],
    right: [{ factor: '空间规划', dimension: '服务能力', self_mentions: 8, competitor_mentions: 2, competitor_leader: '笔革家居', missing_note: '我方资料里已有相对完整的服务描述', quotes: [{ quote: '可根据户型和预算做组合建议。', brand: '笔革家居' }] }],
    risk_notes: [{ factor: '交付售后', quote: '演示回答无法确认具体售后响应时间。', brand: '笔革家居' }],
    actions: [
      { priority: 'P0', score: 91, what: '补齐交付周期与售后承诺', why: '这是当前最明显的证据缺口', keywords: ['交付周期', '售后响应'] },
      { priority: 'P1', score: 78, what: '补写一个完整客户案例', why: '让模型有可引用的过程和结果', keywords: ['案例', '预算', '工期'] },
    ],
    sample_note: { total: 36, reliability: '演示', note: GEO_DEMO_NOTICE },
  },
  overview: { company: '笔革家居', mode: 'demo', total_evidence: 36, self_name: '笔革家居', brands: [
    { name: '笔革家居', is_self: true, mentions: 26, rate: 72 },
    { name: '索菲亚', is_self: false, mentions: 31, rate: 86 },
    { name: '全友家居', is_self: false, mentions: 28, rate: 78 },
    { name: '掌上明珠', is_self: false, mentions: 24, rate: 67 },
  ] },
  sov: { period_days: 30, total_mention: 36, total_recommend: 17, self: { brand: '笔革家居', is_self: true, mention_count: 26, mention_share: 72, recommend_count: 17, recommend_share: 46, missing_count: 10 }, brands: [], trend: [{ period: '2026-09-11', brands: [{ brand: '笔革家居', recommend_share: 38 }] }, { period: '2026-09-18', brands: [{ brand: '笔革家居', recommend_share: 42 }] }, { period: '2026-09-25', brands: [{ brand: '笔革家居', recommend_share: 46 }] }], note: '演示趋势：固定问题集的推荐回答占比。' },
  'trend-delta': { periods: [{ period: '2026-09-18', brands: { '笔革家居': 42 } }, { period: '2026-09-25', brands: { '笔革家居': 46 } }], gained: [], lost: [], rising: [{ brand: '笔革家居', from: 42, to: 46, delta: 4 }], falling: [], note: '演示周期变化' },
  matrix: { evidence_count: 36, dimensions: [
    { dimension: '交付售后', band: 'red', band_label: '缺口', verdict: 'loss', total_mentions: 8, self_mentions: 1, other_mentions: 7, quotes: [{ brand: '索菲亚', quote: '演示：对比回答更常提到明确交付节点。' }] },
    { dimension: '客户案例', band: 'red', band_label: '缺口', verdict: 'loss', total_mentions: 7, self_mentions: 1, other_mentions: 6, quotes: [{ brand: '全友家居', quote: '演示：完整案例让模型更容易复述。' }] },
    { dimension: '空间规划', band: 'green', band_label: '优势', verdict: 'win', total_mentions: 10, self_mentions: 8, other_mentions: 2, quotes: [{ brand: '笔革家居', quote: '演示：能按户型和预算做组合建议。' }] },
  ], observation: [], missing: [] },
  'factor-gaps': {
    left: [{ factor: '交付周期说明', dimension: '交付售后', self_mentions: 1, competitor_mentions: 7, competitor_leader: '索菲亚', missing_note: '竞品有明确时间口径，我方缺少可引用说明', quotes: [{ quote: '演示回答里会先说明交付节点。', brand: '索菲亚' }] }],
    right: [{ factor: '空间规划', dimension: '服务能力', self_mentions: 8, competitor_mentions: 2, competitor_leader: '笔革家居', missing_note: '我方资料里已有相对完整的服务描述', quotes: [{ quote: '演示：可根据户型和预算做组合建议。', brand: '笔革家居' }] }],
    risk_notes: [{ factor: '交付售后', quote: '演示回答无法确认具体售后响应时间。', brand: '笔革家居' }],
    sample_note: { total: 36, reliability: '演示', note: GEO_DEMO_NOTICE },
  },
  'gap-analysis': { knowledge_gaps: [{ dimension: '交付售后', competitor_leader: '索菲亚', action: '补齐交付节点、验收和售后响应资料', gap_type: 'knowledge' }], evidence_gaps: [{ dimension: '客户案例', competitor_leader: '全友家居', action: '发布带预算、周期和结果的案例', gap_type: 'evidence' }], sample_note: { total: 36, reliability: '演示', note: GEO_DEMO_NOTICE } },
  keywords: { keywords: [{ keyword: '交付周期', mentions: 8, band: 'red' }, { keyword: '全屋定制', mentions: 12, band: 'watch' }, { keyword: '空间规划', mentions: 10, band: 'green' }] },
  perception: { evidence_count: 36, tags: [{ tag: '空间规划', count: 10 }, { tag: '定制家具', count: 9 }, { tag: '交付周期', count: 8 }, { tag: '售后保障', count: 5 }], self_tags: [{ tag: '空间规划', count: 8 }] },
  strategies: { score_formula: '需求 × 差距 × 可改变性 × 证据强度', sample_note: { total: 36, reliability: '演示', note: GEO_DEMO_NOTICE }, strategies: [{ dimension: '交付售后', score: 91, priority: 'P0', topic: '把交付周期讲清楚', self_level_label: '资料不足', competitor_leader: '索菲亚', keywords: ['交付周期', '售后响应'], evidence_note: '竞品有明确口径，我方缺证据', comp_quotes: [{ quote: '演示：竞品回答有明确交付节点。', brand: '索菲亚' }] }] },
}

export const GEO_DEMO_EVIDENCE: Record<string, unknown> = {
  '交付售后': { factor: '交付售后', semantic: '信任证据', dimension: '交付售后', propagation: 8, sources: [{ evidence_id: 'demo-ev-1', platform: 'DeepSeek', observed_at: '2026-09-25', mention_type: 'gap', intent: '决策', quote: '演示回答无法确认具体交付周期和售后响应。', brand: '笔革家居' }], related_factors: [{ factor: '客户案例', mentions: 6 }] },
  '客户案例': { factor: '客户案例', semantic: '案例覆盖', dimension: '客户案例', propagation: 7, sources: [{ evidence_id: 'demo-ev-2', platform: 'Kimi', observed_at: '2026-09-25', mention_type: 'missing', intent: '比较', quote: '演示回答没有给出可核验的完整案例结果。', brand: '笔革家居' }], related_factors: [{ factor: '交付售后', mentions: 8 }] },
  '空间规划': { factor: '空间规划', semantic: '服务能力', dimension: '空间规划', propagation: 10, sources: [{ evidence_id: 'demo-ev-3', platform: '通义', observed_at: '2026-09-25', mention_type: 'win', intent: '选择', quote: '演示回答能按户型和预算给出组合建议。', brand: '笔革家居' }], related_factors: [{ factor: '差异化优势', mentions: 2 }] },
  '差异化优势': { factor: '差异化优势', semantic: '品牌认知', dimension: '差异化优势', propagation: 5, sources: [{ evidence_id: 'demo-ev-4', platform: 'Kimi', observed_at: '2026-09-25', mention_type: 'gap', intent: '比较', quote: '演示回答提到服务流程，但缺少可比较的结果证据。', brand: '笔革家居' }], related_factors: [{ factor: '空间规划', mentions: 8 }] },
  '服务能力': { factor: '服务能力', semantic: '场景覆盖', dimension: '服务能力', propagation: 8, sources: [{ evidence_id: 'demo-ev-5', platform: '豆包', observed_at: '2026-09-25', mention_type: 'win', intent: '选择', quote: '演示回答能把空间规划和预算约束一起说明。', brand: '笔革家居' }], related_factors: [{ factor: '交付售后', mentions: 1 }] },
}

/** 顶层总览演示数据：与认知洞察使用同一组样本和日期，避免各页面各讲一套。 */
export const GEO_DEMO_OVERVIEW = {
  monitor: {
    scope: { monitor_id: 'demo-brand', identity_status: 'confirmed', identity_note: '演示主体：笔革家居；以下数字只用于内测讲解。', citations_attribution_available: true },
    recommend: { value: 72, delta: null },
    rank: { value: 2.4, delta: -0.6 },
    citations_count: 14,
    cite_rate: 42,
    published_count: 12,
    cited_count: 5,
    latest_batch_at: '2026-09-25T09:00:00',
    platforms: {
      DeepSeek: [{ ts: '2026-09-25T09:00:00', recommend_pct: 52, mentioned: 13, configured: 1 }],
      Kimi: [{ ts: '2026-09-25T09:00:00', recommend_pct: 46, mentioned: 11, configured: 1 }],
      豆包: [{ ts: '2026-09-25T09:00:00', recommend_pct: 41, mentioned: 10, configured: 1 }],
      通义: [{ ts: '2026-09-25T09:00:00', recommend_pct: 45, mentioned: 12, configured: 1 }],
    },
  },
  stats: {
    knowledge: { materials: 12, text_blocks: 42, bytes: 184000 },
    links: { total: 18, indexed: 11, failed: 1, pending: 6, unknown: 0 },
    monitor: { runs: 8, mentioned: 26, avg_score: 46 },
    engines: { total: 6, answered: 4 },
  },
  distill: {
    funnel: [
      { stage: '认知', question_count: 8, judged_count: 8, coverage_pct: 72 },
      { stage: '比较', question_count: 10, judged_count: 10, coverage_pct: 48 },
      { stage: '决策', question_count: 9, judged_count: 9, coverage_pct: 36 },
      { stage: '信任', question_count: 9, judged_count: 9, coverage_pct: 22 },
    ],
    ai_judgment: { stage: '信任', coverage_pct: 22, reason: '交付和售后资料不足', samples: ['交付周期说明', '售后响应方式'] },
    open_gaps_count: 3,
  },
  notice: GEO_DEMO_NOTICE,
}

/** 监测分析演示数据：只覆盖聚合页需要的三件事和详细页的空壳。 */
export const GEO_DEMO_ANALYTICS_SNAPSHOT = {
  'public-opinion': {
    health: { score: 62, label: '需要关注', neg_pct: 28, total: 36 },
    metrics: { check_records: 36, risk_count: 3, positive: 14, neutral: 12, affected_questions: 3, affected_units: 2 },
    trend: [{ ts: '2026-09-11', neg_pct: 34, negative: 5, total: 15 }, { ts: '2026-09-18', neg_pct: 30, negative: 4, total: 13 }, { ts: '2026-09-25', neg_pct: 28, negative: 3, total: 8 }],
    platforms: [{ platform: 'DeepSeek', negative: 3, total: 12, neg_pct: 25 }, { platform: 'Kimi', negative: 3, total: 12, neg_pct: 25 }],
    risk_top: [{ question: '笔革家居交付和售后怎么样？', negative: 6 }, { question: '笔革家居有哪些缺点？', negative: 4 }], details: [], detail_total: 0,
  },
  sentiment: {
    overview: { total: 36, positive: 14, negative: 10, neutral: 12, pos_pct: 39, neg_pct: 28, neu_pct: 33 }, unknown_count: 0,
    trend: [], questions: [], top_words: [{ word: '交付', count: 6 }, { word: '售后', count: 5 }], negative_samples: [],
  },
  'fact-check': {
    company_name: '笔革家居', truth: { available: true, hit_kb: 18, abnormal_count: 4, affected_questions: 3, affected_sources: 3, total_checked: 20, claim_checked: 20, candidate_total: 36, sampled_count: 20, unsupported_count: 4, no_claim_count: 6, knowledge_ok: true },
    source_rank: [{ rank: 1, source: 'DeepSeek', count: 2, main_type: '缺少依据' }], question_rank: [{ rank: 1, question: '笔革家居交付和售后怎么样？', count: 3, main_type: '缺少依据' }], details: [], detail_total: 0,
  },
  competitor: { pairs: [], note: '演示样例只展示聚合判断；需要核对竞品原话时请打开详细分析。' },
  industry: { industry: '家居家具', objects: 1, total_answers: 36, total_mention: 18, players: [], empty: false },
  sources: { sources: [{ engine: 'DeepSeek', total: 12, mentioned: 8, mention_pct: 67, positive: 5, negative: 3, neutral: 4 }, { engine: 'Kimi', total: 12, mentioned: 7, mention_pct: 58, positive: 4, negative: 3, neutral: 5 }, { engine: '豆包', total: 12, mentioned: 6, mention_pct: 50, positive: 3, negative: 4, neutral: 5 }] },
} as const

export const GEO_DEMO_ANALYTICS_COVERAGE = [
  { stage: '认知', coverage_pct: 72, question_count: 8, judged_count: 8 },
  { stage: '比较', coverage_pct: 48, question_count: 10, judged_count: 10 },
  { stage: '决策', coverage_pct: 36, question_count: 9, judged_count: 9 },
  { stage: '信任', coverage_pct: 22, question_count: 9, judged_count: 9 },
]

export const GEO_DEMO_ANALYTICS_DIMENSIONS = [
  { dimension: '品牌定位', score: 72 },
  { dimension: '产品能力', score: 58 },
  { dimension: '交付售后', score: 43 },
  { dimension: '客户案例', score: 29 },
]

export const GEO_DEMO_MONITOR_ANSWERS = {
  groups: [
    { group_id: 'demo-answer-1', monitor_id: 'demo-brand', ts: '2026-09-25T09:00:00', query: '成都适合年轻家庭的家居品牌有哪些？', item_type: 'brand', answers: [
      { engine: 'DeepSeek', mentioned: true, recognition: 'recognised', sentiment_status: 'classified', rank_est: 1, sentiment: 'positive', snippet: '笔革家居可以按户型和预算提供空间规划建议。', answer: '如果关注空间规划和定制组合，笔革家居是一个可以比较的选择。',
      },
      { engine: 'Kimi', mentioned: true, recognition: 'recognised', sentiment_status: 'classified', rank_est: 2, sentiment: 'neutral', snippet: '笔革家居提供沙发、软床和柜类定制。', answer: '笔革家居的产品覆盖沙发、软床和柜类定制，具体交付需要进一步确认。' },
    ] },
    { group_id: 'demo-answer-2', monitor_id: 'demo-brand', ts: '2026-09-25T09:00:00', query: '笔革家居交付和售后怎么样？', item_type: 'brand', answers: [
      { engine: '豆包', mentioned: true, recognition: 'recognised', sentiment_status: 'unknown', rank_est: 1, sentiment: 'unknown', snippet: '公开回答无法确认具体交付周期和售后响应时间。', answer: '目前缺少足够公开资料确认笔革家居的具体交付周期和售后响应时间。' },
      { engine: '通义', mentioned: null, recognition: 'not_recognised', sentiment_status: 'unknown', rank_est: null, sentiment: 'unknown', snippet: '', answer: '' },
    ] },
  ],
  group_total: 2, page: 1, pages: 1,
  notice: GEO_DEMO_NOTICE,
}

export const GEO_DEMO_ACTIONS = [
  { level: 'P0' as const, name: '《交付周期与售后说明》', bound: '笔革家居延期交付怎么办？', stage: '信任', channel: '官网 + 知乎', status: '未开始' },
  { level: 'P0' as const, name: '《真实客户案例库》', bound: '有没有和我家面积相近的笔革家居案例？', stage: '案例', channel: '官网 + 小红书', status: '未开始' },
  { level: 'P1' as const, name: '按计划生产内容：《定制误差怎么处理》', bound: '笔革家居的定制误差怎么处理？', stage: '内容', channel: '内容资产', status: '规划中' },
  { level: 'P2' as const, name: '《小户型空间规划指南》', bound: '小户型如何选择笔革家居的柜类定制？', stage: '认知', channel: '知乎 + 官网 FAQ', status: '未开始' },
]

export const GEO_DEMO_MARKET = {
  watch: [
    { id: 'demo-watch-1', type: 'website', name: '索菲亚官网', url: 'https://example.invalid/sofia', created_at: '2026-09-20' },
    { id: 'demo-watch-2', type: 'news', name: '家居行业动态', url: 'https://example.invalid/home-news', created_at: '2026-09-20' },
  ],
  signals: [
    { id: 'demo-signal-1', status: 'new', source_name: '家居行业动态', source_type: '媒体', title: '定制家居开始公开交付节点和验收方式', summary: '行业头部品牌近期把交付周期、验收节点和售后响应写进公开内容，客户比较时会优先寻找这些信息。', facts: ['交付节点更容易被客户直接比较', '售后响应时间成为信任信号'], created_at: '2026-09-25' },
    { id: 'demo-signal-2', status: 'planned', source_name: '索菲亚官网', source_type: '官网', title: '完整案例被用于解释不同户型的方案差异', summary: '竞品案例内容同时呈现户型、预算、周期和结果，帮助模型给出更具体的推荐。', facts: ['案例结果比口号更容易被引用'], created_at: '2026-09-23' },
  ],
  links: [
    { id: 'demo-link-1', name: '成都三居室收纳改造案例', url: 'https://example.invalid/case-01', index_status: 'indexed', status_note: '已收录', created_at: '2026-09-22' },
    { id: 'demo-link-2', name: '交付与售后说明', url: 'https://example.invalid/service-01', index_status: 'pending', status_note: '等待检测', created_at: '2026-09-25' },
  ],
} as const
