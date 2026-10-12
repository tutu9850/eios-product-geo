/** UI 验收用虚构观察。没有模型调用、正式知识写入或真实核验。 */
export const DEMO_COMPANY = '云栖示例家居'
export const DEMO_COMPETITOR = '星禾示例家居'
export const DEMO_SUBJECTS = [{ monitor_id: 'demo-brand', name: DEMO_COMPANY }, { monitor_id: 'demo-secondary', name: '月白示例家居' }]
export const DEMO_ENGINES = ['DeepSeek', 'Kimi', '豆包', '通义']
export const DEMO_ROUNDS = ['2026-09-28', '2026-10-05', '2026-10-12']
export const DEMO_QUESTIONS = [
  '成都适合年轻家庭的家居品牌有哪些？',
  `${DEMO_COMPANY}交付和售后怎么样？`,
  `${DEMO_COMPANY}与${DEMO_COMPETITOR}有哪些案例差异？`,
]
export const DEMO_MATERIALS = [
  { id: 'demo-material-brand', title: '演示·品牌与产品说明', text: `${DEMO_COMPANY}提供空间规划、沙发与柜类组合建议。`, published_at: DEMO_ROUNDS[0] },
  { id: 'demo-material-service', title: '演示·交付与售后说明', text: `${DEMO_COMPANY}交付安排以订单排期为准，售后受理后先核对订单。`, published_at: DEMO_ROUNDS[1] },
  { id: 'demo-material-case', title: '演示·住宅案例摘要', text: `${DEMO_COMPANY}有一份住宅收纳案例摘要，预算与结果仍待补充。`, published_at: null },
]

type Sentiment = 'positive' | 'neutral' | 'negative' | 'unknown'
export type DemoObservation = {
  id: string; monitor_id: string; query_id: string; question: string; round: number; ts: string; engine: string
  mentioned: boolean | null; recognition: string; sentiment_status: string; sentiment: Sentiment
  rank_est: number | null; answer: string; snippet: string; error: string | null
  competitor_mentioned: boolean; citation_ids: string[]; factor: string
  // 人工编排的模拟解析，绝非真实事实核验结果。
  check: 'supported' | 'unsupported' | 'review' | 'no_claim' | 'not_checked'
}

/** 三轮固定问题，36 个槽位；失败/无法识别与未提及分别保留。 */
export const DEMO_OBSERVATIONS: DemoObservation[] = DEMO_ROUNDS.flatMap((date, round) =>
  DEMO_QUESTIONS.flatMap((question, q) => DEMO_ENGINES.map((engine, e) => {
    const failed = q === 2 && e === 3
    const ambiguous = q === 1 && e === 3
    const absent = q === 0 && e === 3 && round < 2
    const negative = !failed && !ambiguous && q === 1 && (round === 0 || (round === 1 && e < 2))
    const sentiment: Sentiment = failed || ambiguous || absent ? 'unknown' : negative ? 'negative' : q === 0 || (q === 2 && e === 0) ? 'positive' : 'neutral'
    const check = failed || ambiguous || absent ? 'not_checked' : q === 0 ? 'supported' : q === 2 ? 'no_claim' : round === 0 && e === 0 ? 'review' : round < 2 ? 'unsupported' : 'supported'
    const answer = failed ? '' : ambiguous ? `${DEMO_COMPANY}可能指同名企业，无法确认这家企业；不评价其交付服务。`
      : absent ? `${DEMO_COMPETITOR}可以作为比较对象，请核对空间规划案例。`
      : q === 0 ? `${DEMO_COMPANY}提供空间规划、沙发与柜类组合建议，推荐给需要组合规划的家庭。[演示来源](https://example.invalid/brand)仅为虚构资料，选择前仍需确认预算和户型。`
      : q === 1 ? negative ? check === 'review' ? `${DEMO_COMPANY}承诺所有订单7天交付。演示资料只写按订单排期，不推荐采信这项承诺，需要复核。` : `${DEMO_COMPANY}交付与售后公开说明不足，不推荐直接采信交付承诺；具体响应时间缺少依据。`
        : `${DEMO_COMPANY}交付安排以订单排期为准，售后受理后先核对订单。[演示来源](https://example.invalid/service)不包含统一交付时限。`
      : `${DEMO_COMPANY}有住宅收纳案例摘要${e === 0 ? '，推荐作为住宅收纳的初步参考' : ''}；${DEMO_COMPETITOR}在演示样例里有预算与结果字段。两者案例完整度不同，仍需补齐同口径材料。`
    const mentioned = failed ? null : !ambiguous && !absent
    return {
      id: `demo-answer-r${round + 1}-q${q + 1}-e${e + 1}`, monitor_id: 'demo-brand', query_id: `demo-query-${q + 1}`,
      question, round, ts: `${date}T09:00:00+08:00`, engine, mentioned,
      recognition: ambiguous ? 'not_recognised' : mentioned ? 'recognised' : 'not_mentioned',
      sentiment_status: ambiguous ? 'unknown' : mentioned ? 'classified' : 'not_applicable', sentiment,
      rank_est: mentioned ? 1 : null, answer, snippet: answer.slice(0, 240), error: failed ? '演示：模型请求超时' : null,
      competitor_mentioned: !failed && (q === 2 || absent), citation_ids: mentioned && check === 'supported' ? [DEMO_MATERIALS[q === 0 ? 0 : 1].id] : [],
      factor: ['空间规划', '交付售后', '客户案例'][q], check,
    }
  })),
)

const count = (rows: DemoObservation[], fn: (row: DemoObservation) => boolean) => rows.filter(fn).length
const percent = (n: number, total: number) => total ? Math.round(n / total * 100) : 0
const unique = (values: string[]) => new Set(values).size
const classified = (rows: DemoObservation[]) => rows.filter(r => r.sentiment_status === 'classified')
const tally = (rows: DemoObservation[]) => {
  const records = classified(rows)
  const positive = count(records, r => r.sentiment === 'positive')
  const negative = count(records, r => r.sentiment === 'negative')
  const neutral = count(records, r => r.sentiment === 'neutral')
  return { total: records.length, positive, negative, neutral, pos_pct: percent(positive, records.length), neg_pct: percent(negative, records.length), neu_pct: percent(neutral, records.length) }
}

/** 同一份原始样本生成所有监测视图；空集合也保留 null/空状态。 */
export function buildDemoMonitor(rows: DemoObservation[] = DEMO_OBSERVATIONS, monitorId = 'demo-brand') {
  rows = rows.filter(r => r.monitor_id === monitorId)
  const company = DEMO_SUBJECTS.find(s => s.monitor_id === monitorId)?.name ?? '未知演示主体'
  const questionTexts = [...new Set(rows.map(r => r.question))]
  const answered = rows.filter(r => r.answer)
  const recognised = rows.filter(r => r.mentioned === true)
  const negative = rows.filter(r => r.sentiment === 'negative')
  const unknown = rows.filter(r => r.sentiment_status === 'unknown')
  const rounds = [...new Set(rows.map(r => r.round))].sort((a, b) => a - b)
  const groups = [...new Set(rows.map(r => `${r.round}|${r.query_id}|${r.monitor_id}`))].map(key => {
    const answers = rows.filter(r => `${r.round}|${r.query_id}|${r.monitor_id}` === key)
    const first = answers[0]
    return { group_id: `demo-group-${key}`, monitor_id: first.monitor_id, ts: first.ts, query: first.question, item_type: 'brand', answers }
  }).reverse()
  const period = (round: number) => rows.filter(r => r.round === round)
  const scopeCoverage = (subset: DemoObservation[]) => {
    const questions = [...new Set(subset.map(r => r.query_id))]
    const eligible = questions.filter(id => subset.some(r => r.query_id === id && r.answer))
    const mentioned = eligible.filter(id => subset.some(r => r.query_id === id && r.mentioned === true))
    return { answered: eligible.length, mentioned: mentioned.length, coverage: percent(mentioned.length, eligible.length) }
  }
  const latest = period(rounds.at(-1) ?? -1)
  const prev = period(rounds.at(-2) ?? -1)
  const currentCoverage = scopeCoverage(latest)
  const rankAverage = (subset: DemoObservation[]) => {
    const ranked = subset.filter(r => r.rank_est !== null)
    return ranked.length ? Math.round(ranked.reduce((n, r) => n + r.rank_est!, 0) / ranked.length * 10) / 10 : null
  }
  const citations = DEMO_MATERIALS.map(m => ({ material_id: m.id, title: m.title, count: rows.reduce((n, r) => n + Number(r.citation_ids.includes(m.id)), 0) })).filter(m => m.count)
  const published = DEMO_MATERIALS.filter(m => m.published_at)
  const publishedCited = published.filter(m => citations.some(c => c.material_id === m.id))
  const sentiment = {
    overview: tally(rows), unknown_count: unknown.length,
    trend: rounds.map(round => ({ ts: `${DEMO_ROUNDS[round]}T09:00:00+08:00`, ...tally(period(round)) })),
    questions: questionTexts.map(question => { const t = tally(rows.filter(r => r.question === question)); return { question, ...t, sentiment: t.negative > t.positive ? 'negative' : t.positive > t.negative ? 'positive' : 'neutral' } }),
    top_words: ['交付', '售后'].map(word => ({ word, count: count(negative, r => r.answer.includes(word)) })).filter(w => w.count >= 2),
    negative_samples: negative.map(r => ({ question: r.question, platform: r.engine, snippet: r.snippet, ts: r.ts })),
  }
  const sources = DEMO_ENGINES.map(engine => {
    const records = rows.filter(r => r.engine === engine && r.answer)
    return { engine, ...tally(records), total: records.length, mentioned: count(records, r => r.mentioned === true), mention_pct: percent(count(records, r => r.mentioned === true), records.length) }
  })
  const checked = recognised.filter(r => r.check !== 'not_checked')
  const review = checked.filter(r => r.check === 'review')
  const unsupported = checked.filter(r => r.check === 'unsupported')
  const factCheck = {
    company_name: company,
    truth: { available: checked.length > 0, hit_kb: count(checked, r => r.check === 'supported'), abnormal_count: review.length,
      affected_questions: unique(review.map(r => r.question)), affected_sources: unique(review.map(r => r.engine)),
      total_checked: checked.length, claim_checked: count(checked, r => r.check !== 'no_claim'), candidate_total: recognised.length,
      sampled_count: checked.length, unsupported_count: unsupported.length, no_claim_count: count(checked, r => r.check === 'no_claim'), knowledge_ok: checked.length > 0 },
    source_rank: DEMO_ENGINES.map(source => ({ source, count: count(review, r => r.engine === source), main_type: '模拟：与资料口径冲突' })).filter(r => r.count).map((r, i) => ({ rank: i + 1, ...r })),
    question_rank: questionTexts.map(question => ({ question, count: count(review, r => r.question === question), main_type: '模拟：与资料口径冲突' })).filter(r => r.count).map((r, i) => ({ rank: i + 1, ...r })),
    details: review.map(r => ({ question: r.question, platform: r.engine, abnormal_type: '模拟：与资料口径冲突', ai_ref: r.answer, ts: r.ts })), detail_total: review.length,
  }
  const compare = rows.filter(r => r.query_id === 'demo-query-3' && r.answer)
  const publicOpinion = {
    health: { score: classified(rows).length ? 100 - sentiment.overview.neg_pct : null, label: classified(rows).length ? negative.length ? '需要关注' : '暂无负面信号' : '未判定', neg_pct: sentiment.overview.neg_pct, total: classified(rows).length },
    metrics: { check_records: classified(rows).length, risk_count: negative.length, positive: sentiment.overview.positive, neutral: sentiment.overview.neutral,
      affected_questions: unique(negative.map(r => r.question)), affected_units: unique(negative.map(r => r.engine)) },
    trend: sentiment.trend.map(t => ({ ts: t.ts, neg_pct: t.neg_pct, negative: t.negative, total: t.total })),
    platforms: sources.map(s => ({ platform: s.engine, negative: s.negative, total: s.positive + s.negative + s.neutral, neg_pct: percent(s.negative, s.positive + s.negative + s.neutral) })),
    risk_top: questionTexts.map(question => ({ question, negative: count(negative, r => r.question === question) })).filter(r => r.negative),
    details: negative.map(r => ({ question: r.question, platform: r.engine, sentiment: r.sentiment, ts: r.ts })), detail_total: negative.length,
  }
  const answeredCount = answered.length
  const summary = { slots: rows.length, answered: answeredCount, failed: rows.length - answeredCount, recognised: recognised.length,
    not_mentioned: count(rows, r => r.recognition === 'not_mentioned' && Boolean(r.answer)), unknown: unknown.length, rounds: rounds.length, groups: groups.length,
    mention_pct: percent(recognised.length, answeredCount), recommendation_pct: percent(count(recognised, r => r.sentiment === 'positive'), answeredCount) }
  return {
    summary, groups, citations, sentiment, sources,
    overview: {
      scope: { monitor_id: monitorId, identity_status: 'confirmed', identity_note: '虚构主体；主体未知不计提及，失败不计成功回答。', citations_attribution_available: true },
      recommend: { value: currentCoverage.answered ? currentCoverage.coverage : null, delta: prev.length && currentCoverage.coverage !== scopeCoverage(prev).coverage ? currentCoverage.coverage - scopeCoverage(prev).coverage : null },
      rank: { value: rankAverage(latest), delta: prev.length && rankAverage(latest) !== null && rankAverage(prev) !== null && rankAverage(latest) !== rankAverage(prev) ? rankAverage(latest)! - rankAverage(prev)! : null },
      citations_count: citations.reduce((n, c) => n + c.count, 0), cite_rate: answeredCount ? percent(publishedCited.length, published.length) : null,
      published_count: rows.length ? published.length : 0, cited_count: publishedCited.length, latest_batch_at: latest[0]?.ts ?? null,
      platforms: Object.fromEntries(DEMO_ENGINES.map(engine => [engine, rounds.flatMap(round => {
        const records = period(round).filter(r => r.engine === engine && r.answer)
        return records.length ? [{ ts: records[0].ts, recommend_pct: percent(count(records, r => r.mentioned === true), records.length), mentioned: count(records, r => r.mentioned === true), configured: records.length }] : []
      })])),
    },
    stats: { runs: rounds.length, mentioned: rounds.reduce((n, round) => n + scopeCoverage(period(round)).mentioned, 0), avg_score: rounds.length ? Math.round(rounds.reduce((n, round) => n + scopeCoverage(period(round)).coverage, 0) / rounds.length * 10) / 10 : 0 },
    analytics: { 'public-opinion': publicOpinion, sentiment, 'fact-check': factCheck,
      competitor: { pairs: compare.length ? [{ target: company, competitor: DEMO_COMPETITOR, total: compare.length, unanswered: count(rows.filter(r => r.query_id === 'demo-query-3'), r => !r.answer), target_mentioned: count(compare, r => r.mentioned === true), target_pct: percent(count(compare, r => r.mentioned === true), compare.length), comp_mentioned: count(compare, r => r.competitor_mentioned), comp_pct: percent(count(compare, r => r.competitor_mentioned), compare.length), same_entity_pct: 0, samples: compare.map(r => ({ question: r.question, engine: r.engine, answer: r.answer })) }] : [], note: '虚构比较回答；提及不等于推荐。' },
      industry: { industry: '家居家具（演示）', objects: rows.length ? 1 : 0, total_answers: answeredCount, total_mention: recognised.length, players: [company, DEMO_COMPETITOR].map((name, i) => { const records = rows.filter(r => i ? r.competitor_mentioned : r.mentioned === true); return { name, category: '虚构企业', count: records.length, questions: unique(records.map(r => r.question)), evidence: records.map(r => ({ question: r.question, engine: r.engine, snippet: r.snippet, ts: r.ts })) } }).filter(p => p.count), empty: !answeredCount },
      sources: { sources, note: '成功回答作分母；主体未知不计提及，失败不计成功回答。' },
    },
  }
}

export const DEMO_MONITOR = buildDemoMonitor()
/** 多主体隔离验收附加样本；不混入默认主体的36个槽位。 */
export const DEMO_SECONDARY_OBSERVATIONS = DEMO_OBSERVATIONS.filter(r => r.round === 2).map(r => ({ ...r,
  id: `${r.id}-secondary`, monitor_id: 'demo-secondary',
  question: r.question.replaceAll(DEMO_COMPANY, DEMO_SUBJECTS[1].name),
  answer: r.answer.replaceAll(DEMO_COMPANY, DEMO_SUBJECTS[1].name),
  snippet: r.snippet.replaceAll(DEMO_COMPANY, DEMO_SUBJECTS[1].name),
}))
export const DEMO_EMPTY_MONITOR = buildDemoMonitor([])
export const DEMO_FAILED_MONITOR = buildDemoMonitor(DEMO_OBSERVATIONS.map(r => ({ ...r, answer: '', snippet: '', mentioned: null, recognition: 'not_mentioned', sentiment_status: 'not_applicable', sentiment: 'unknown', rank_est: null, error: '演示：模型请求超时', citation_ids: [], competitor_mentioned: false, check: 'not_checked' })))
