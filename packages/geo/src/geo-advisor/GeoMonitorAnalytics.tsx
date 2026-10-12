import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, CheckCircle2, CircleAlert, Download, FlaskConical, Info, LoaderCircle, RefreshCw } from 'lucide-react'
import { geoDownloadFile, geoGet } from './geo-api'
import { GeoBars, GeoKpis, GeoLine, GeoQuote, GeoRatio, GeoTable, sentimentText, shortDay, useGeoNav } from './shared'
import { saveBlobToDisk } from '../lib/save-to-disk'
import { MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'
import { GEO_DEMO_ANALYTICS_COVERAGE, GEO_DEMO_ANALYTICS_DIMENSIONS, GEO_DEMO_ANALYTICS_SNAPSHOT, GEO_DEMO_NOTICE } from './demo-fixtures'
import { useGeoDemoMode } from './shared'

/**
 * 专业分析不是六个互不相干的报表。
 *
 * 这里先把六类接口结果压成三个决策问题：
 * 1. 模型有没有看见我，以及在哪些问题/模型上没看见？
 * 2. 模型说的内容有没有企业资料或引用支撑？
 * 3. 最值得执行的下一步是什么，做完如何复测？
 *
 * 详细分析仍然保留在下方，但默认只打开一条判断路径，避免用户在六个
 * 页面之间自己拼结论。监测对象页不在这里修改。
 */

const day = shortDay

type Analysis = 'public-opinion' | 'sentiment' | 'fact-check' | 'competitor' | 'industry' | 'sources'
const TABS: Array<[Analysis, string]> = [
  ['public-opinion', '负面信号'],
  ['sentiment', '评价语气'],
  ['fact-check', '证据核验'],
  ['competitor', '竞品对比'],
  ['industry', '行业提及'],
  ['sources', '模型差异'],
]

interface PublicOpinion {
  scope_required?: boolean
  scope?: { brands?: Array<{ monitor_id: string; name: string }> }
  health: { score: number; label: string; neg_pct: number; total: number }
  metrics: { check_records: number; risk_count: number; positive: number; neutral: number; affected_questions: number; affected_units: number }
  trend: Array<{ ts: string; neg_pct: number; negative: number; total: number }>
  platforms: Array<{ platform: string; negative: number; total: number; neg_pct: number }>
  risk_top: Array<{ question: string; negative: number }>
  details: Array<{ question: string; platform: string; sentiment: string; ts: string }>
  detail_total: number
}
interface Sentiment {
  scope_required?: boolean
  scope?: { brands?: Array<{ monitor_id: string; name: string }> }
  unknown_count?: number
  overview: { total: number; positive: number; negative: number; neutral: number; pos_pct: number; neg_pct: number; neu_pct: number }
  trend: Array<{ ts: string; positive: number; negative: number; neutral: number; total: number }>
  questions: Array<{ question: string; positive: number; negative: number; neutral: number; sentiment: string }>
  top_words: Array<{ word: string; count: number }>
  top_words_note?: string
  negative_samples: Array<{ question: string; platform: string; snippet: string; ts: string }>
}
interface FactCheck {
  scope_required?: boolean
  scope?: { brands?: Array<{ monitor_id: string; name: string }> }
  company_name: string | null
  truth: { available: boolean; hit_kb: number; abnormal_count: number; affected_questions: number; affected_sources: number; total_checked: number; claim_checked?: number; candidate_total?: number; sampled_count?: number; unsupported_count?: number; no_claim_count?: number; knowledge_ok: boolean }
  source_rank: Array<{ rank: number; source: string; count: number; main_type: string }>
  question_rank: Array<{ rank: number; question: string; count: number; main_type: string }>
  details: Array<{ question: string; platform: string; abnormal_type: string; ai_ref: string; ts: string }>
  detail_total: number
}
interface Competitor { pairs: Array<{ target: string; competitor: string; total: number; unanswered?: number; target_mentioned: number; target_pct: number; comp_mentioned: number; comp_pct: number; same_entity_pct: number; samples: Array<{ question: string; engine: string; answer: string }> }>; note?: string }
interface Industry { industry: string | null; objects: number; total_answers: number; total_mention: number; players: Array<{ name: string; category: string; count: number; questions: number; evidence?: Array<{ question: string; engine: string; snippet: string; ts: string }> }>; note?: string; empty: boolean; hint?: string | null }
interface Sources { sources: Array<{ engine: string; total: number; mentioned: number; mention_pct: number; positive: number; negative: number; neutral: number }>; note?: string }
type Snapshot = Partial<Record<Analysis, PublicOpinion | Sentiment | FactCheck | Competitor | Industry | Sources>>
type UnknownRow = Record<string, unknown>

type Finding = {
  key: string
  tone: 'good' | 'warn' | 'bad' | 'neutral'
  title: string
  conclusion: string
  basis: string
  action: string
  actionKind: string
}

function AnalysisEmpty({ title, next }: { title: string; next: string }) {
  return <div className="geo-empty analysis-empty"><b>{title}</b><span>{next}</span></div>
}
function rowsOf<T>(value: T[] | null | undefined): T[] { return Array.isArray(value) ? value : [] }
function unknownRows(value: unknown): UnknownRow[] {
  if (Array.isArray(value)) return value.filter((row): row is UnknownRow => Boolean(row && typeof row === 'object'))
  if (!value || typeof value !== 'object') return []
  const source = value as Record<string, unknown>
  for (const key of ['items', 'stages', 'dimensions', 'dims', 'matrix', 'rows']) {
    if (Array.isArray(source[key])) return unknownRows(source[key])
  }
  return []
}
function numberOf(value: unknown): number | null {
  const n = typeof value === 'number' ? value : typeof value === 'string' && value.trim() ? Number(value) : NaN
  return Number.isFinite(n) ? n : null
}
function labelOf(row: UnknownRow, fallback: string): string {
  const value = row.label ?? row.stage ?? row.dimension ?? row.name
  return typeof value === 'string' && value.trim() ? value : fallback
}
function pct(value: number | null): string { return value == null ? '未判定' : `${Math.round(value)}%` }

function buildFindings(snapshot: Snapshot, coverage: UnknownRow[], identityPending = false): Finding[] {
  const findings: Finding[] = []
  const opinion = snapshot['public-opinion'] as PublicOpinion | undefined
  const fact = snapshot['fact-check'] as FactCheck | undefined
  const competitor = snapshot.competitor as Competitor | undefined
  const sources = snapshot.sources as Sources | undefined
  const topRisk = opinion?.risk_top?.[0]
  const total = opinion?.health?.total ?? (snapshot.sentiment as Sentiment | undefined)?.overview?.total ?? null
  if (opinion?.health && opinion.health.total > 0) {
    const negative = numberOf(opinion.health.neg_pct)
    findings.push({
      key: 'visibility',
      tone: negative != null && negative >= 30 ? 'bad' : negative != null && negative > 0 ? 'warn' : 'good',
      title: topRisk ? `${identityPending ? '核对' : '先处理'}“${topRisk.question}”` : identityPending ? '原始回答里出现负面信号' : '先看品牌被看见的情况',
      conclusion: topRisk ? `${identityPending ? '回答中' : '这是当前'}负面回答最集中的问题（${topRisk.negative} 条）。` : `${identityPending ? '回答中' : '最近一批有效回答中'}，负面占比 ${pct(negative)}。`,
      basis: `${identityPending ? '主体尚未确认 · ' : '最近一批有效回答 · '}${total ?? '—'} 条；提及/情绪是观察结果，不等于事实结论。`,
      action: identityPending ? '核对原始回答' : topRisk ? '去资料缺口核对原因' : '打开负面信号明细',
      actionKind: identityPending ? 'monitor-report' : topRisk ? 'gaps' : 'public-opinion',
    })
  } else if (sources?.sources?.length) {
    const top = [...sources.sources].sort((a, b) => b.mention_pct - a.mention_pct)[0]
    findings.push({
      key: 'visibility', tone: 'neutral', title: '不同模型看到品牌的程度不一致',
      conclusion: `${top.engine} 的提及率最高（${pct(top.mention_pct)}），先按模型差异定位问题。`,
      basis: `模型回答汇总 · ${sources.sources.length} 个模型；不把模型排名当成品牌质量。`,
      action: '查看模型差异', actionKind: 'sources',
    })
  }
  if (fact?.truth && (fact.truth.total_checked > 0 || (fact.truth.candidate_total ?? 0) > 0)) {
    const truth = fact.truth
    if (!truth.knowledge_ok || !truth.available) {
      findings.push({ key: 'evidence', tone: 'warn', title: '当前不能判断模型说法是否可信', conclusion: '企业资料或核验服务不可用，系统不把回答升级为企业事实。', basis: `${truth.total_checked ?? 0} 条完成检查；知识依据状态不可用。`, action: '去企业资料补齐依据', actionKind: 'assets' })
    } else if ((truth.unsupported_count ?? 0) > 0 || truth.abnormal_count > 0) {
      const unsupported = truth.unsupported_count ?? 0
      findings.push({ key: 'evidence', tone: 'bad', title: '有回答缺少足够依据，需要人工复核', conclusion: `${unsupported || truth.abnormal_count} 条回答没有可直接支持的企业证据；“需要复核”不等于已证实错误。`, basis: `抽检 ${truth.sampled_count ?? truth.total_checked} 条，含可比对断言 ${truth.claim_checked ?? '—'} 条。`, action: '查看证据核验', actionKind: 'fact-check' })
    } else {
      findings.push({ key: 'evidence', tone: 'good', title: '本轮抽检暂未发现明显证据缺口', conclusion: '已有资料能支持当前抽检中的企业断言，但仍需查看原始回答和来源。', basis: `完成检查 ${truth.total_checked} 条；命中依据 ${truth.hit_kb} 条。`, action: '查看核验明细', actionKind: 'fact-check' })
    }
  }
  const weakStages = identityPending ? [] : [...coverage]
    .filter((row) => { const raw = numberOf(row.coverage ?? row.coverage_pct ?? row.value); return raw != null && raw < 50 })
    .sort((a, b) => (numberOf(a.coverage ?? a.coverage_pct ?? a.value) ?? 100) - (numberOf(b.coverage ?? b.coverage_pct ?? b.value) ?? 100))
  // 不同来源的阶段汇总使用不同字段：真实监测返回 answered_count，
  // 演示夹具/历史覆盖返回 judged_count。统一后，不能再把有样本的阶段
  // 显示成“0 条”，也不能在没有样本时继续展示一个看似精确的百分比。
  const stageAnswers = (row: UnknownRow) => numberOf(row.answered_count ?? row.count ?? row.judged_count ?? row.question_count) ?? 0
  const weakCoverage = weakStages.find((row) => stageAnswers(row) >= 3) ?? weakStages[0]
  if (weakCoverage) {
    const value = numberOf(weakCoverage.coverage ?? weakCoverage.coverage_pct ?? weakCoverage.value)
    const count = stageAnswers(weakCoverage)
    const stage = labelOf(weakCoverage, '某个决策阶段')
    findings.push(count < 3
      ? { key: 'decision', tone: 'neutral', title: `${stage}${count ? `只有 ${count} 条` : '还没有'}有效回答，暂不能判断覆盖是否稳定`, conclusion: `${count ? '样本太少，暂不展示提及比例；' : '当前没有可计算提及比例的样本；'}先补充这一阶段的客户问题再复测。`, basis: `本批次 ${count} 条有效回答；不与历史认知维度混算。`, action: '去补客户问题', actionKind: 'questions' }
      : { key: 'decision', tone: 'warn', title: `${stage}还没有被稳定覆盖`, conclusion: `当前批次提及覆盖 ${pct(value)}，它代表有效回答中是否出现品牌名，不代表准确认知。`, basis: `${count} 条有效回答；与历史认知维度不混算。`, action: '回到客户会问什么补问题', actionKind: 'questions' })
  } else if (!identityPending && competitor?.pairs?.length) {
    const pair = competitor.pairs[0]
    findings.push({ key: 'decision', tone: 'neutral', title: `对比 ${pair.competitor} 看相对差距`, conclusion: `我方提及率 ${pct(pair.target_pct)}，对方 ${pct(pair.comp_pct)}；样本和问题范围需要一起看。`, basis: `同题对比 · ${pair.total} 条有效回答；不直接等同于推荐率或市场份额。`, action: '查看竞品对比', actionKind: 'competitor' })
  }
  return findings.slice(0, 3)
}

function FindingCard({ finding, onAction }: { finding: Finding; onAction: (kind: string) => void }) {
  const Icon = finding.tone === 'good' ? CheckCircle2 : finding.tone === 'neutral' ? Info : CircleAlert
  return <article className="analysis-finding" data-tone={finding.tone}>
    <div className="analysis-finding-head"><Icon /><span>{finding.key === 'visibility' ? (finding.actionKind === 'sources' ? '被看见' : '负面说法') : finding.key === 'evidence' ? '可信度' : '决策差距'}</span></div>
    <h3>{finding.title}</h3>
    <p>{finding.conclusion}</p>
    <small>{finding.basis}</small>
    <button type="button" onClick={() => onAction(finding.actionKind)}>{finding.action}<ArrowRight /></button>
  </article>
}

function CognitionContext({ coverage, dimensions, identityPending }: { coverage: UnknownRow[]; dimensions: UnknownRow[]; identityPending: boolean }) {
  const stageAnswers = (row: UnknownRow) => numberOf(row.answered_count ?? row.count ?? row.judged_count ?? row.question_count) ?? 0
  const judgedCoverage = identityPending ? [] : coverage.filter((row) => {
    const value = numberOf(row.coverage ?? row.coverage_pct ?? row.value)
    const hasSampleField = row.answered_count != null || row.count != null || row.judged_count != null || row.question_count != null
    return value != null && (!hasSampleField || stageAnswers(row) > 0)
  })
  const judgedDimensions = dimensions.filter((row) => numberOf(row.score) != null)
  return <section className="analysis-context geo-panel">
    <header><div><span className="geo-eyebrow">辅助理解</span><h2>客户怎样理解这家企业</h2><p>当前批次回答告诉你“这次有没有被提到”；历史评估只用来解释认知方面。两组样本不同，不能合成一个总分。</p></div></header>
    <div className="analysis-context-grid">
      <div><h3>当前批次 · 决策阶段</h3>{judgedCoverage.length ? judgedCoverage.slice(0, 6).map((row, index) => { const value = numberOf(row.coverage ?? row.coverage_pct ?? row.value); return <div className="analysis-context-row" key={`${labelOf(row, '阶段')}-${index}`}><span>{labelOf(row, '阶段')}</span><i><em style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }} /></i><b>{pct(value)}</b></div> }) : <div className="geo-empty">{identityPending ? '主体尚未确认，不显示阶段覆盖。' : '暂无可判定的阶段覆盖；有效回答不足时不显示 0%。'}</div>}</div>
      <div><h3>过去评估结果</h3>{judgedDimensions.length ? judgedDimensions.slice(0, 8).map((row, index) => { const value = numberOf(row.score); return <div className="analysis-context-row" key={`${labelOf(row, '维度')}-${index}`}><span>{labelOf(row, '维度')}</span><i><em style={{ width: `${Math.max(0, Math.min(100, value ?? 0))}%` }} /></i><b>{`${Math.round(value ?? 0)}%`}</b></div> }) : <div className="geo-empty">当前没有过去的评估结果，不显示维度分数。</div>}</div>
    </div>
  </section>
}

export function GeoMonitorAnalytics() {
  const loadVersion = useRef(0)
  const [tab, setTab] = useState<Analysis>('public-opinion')
  const [snapshot, setSnapshot] = useState<Snapshot>({})
  const [coverage, setCoverage] = useState<UnknownRow[]>([])
  const [dimensions, setDimensions] = useState<UnknownRow[]>([])
  const [identityStatus, setIdentityStatus] = useState<'confirmed' | 'unconfirmed' | null>(null)
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { enabled: demoMode } = useGeoDemoMode()
  const { query: subjectQuery, loaded: brandsLoaded } = useMonitorSubject()
  const go = useGeoNav()
  // All six views share the same active brand subject.  The backend maps
  // competitor/industry probe objects back to that subject instead of
  // silently reading the whole account.
  const scoped = new Set<Analysis>(TABS.map(([id]) => id))

  async function load() {
    const version = ++loadVersion.current
    setLoading(true)
    setError('')
    if (demoMode) {
      setSnapshot(GEO_DEMO_ANALYTICS_SNAPSHOT as unknown as Snapshot)
      setCoverage(GEO_DEMO_ANALYTICS_COVERAGE)
      setDimensions(GEO_DEMO_ANALYTICS_DIMENSIONS)
      setIdentityStatus('confirmed')
      setLoading(false)
      return
    }
    const paths = TABS.map(([id]) => [id, `/monitor/${id}${subjectQuery ? `?${subjectQuery}` : ''}`] as const)
    const results = await Promise.allSettled(paths.map(([, path]) => geoGet<unknown>(path)))
    if (version !== loadVersion.current) return
    const next: Snapshot = {}
    const failed: string[] = []
    results.forEach((result, index) => {
      const id = paths[index][0]
      if (result.status === 'fulfilled') next[id] = result.value as Snapshot[typeof id]
      else failed.push(TABS[index][1])
    })
    const context = await Promise.allSettled([
      geoGet<unknown>(`/cognition/coverage${subjectQuery ? `?${subjectQuery}` : ''}`),
      geoGet<unknown>(`/cognition/health${subjectQuery ? `?${subjectQuery}` : ''}`),
      geoGet<{ scope?: { identity_status?: 'confirmed' | 'unconfirmed' | null } }>(`/monitor/overview${subjectQuery ? `?${subjectQuery}` : ''}`),
    ])
    if (version !== loadVersion.current) return
    setSnapshot(next)
    setCoverage(context[0].status === 'fulfilled' ? unknownRows(context[0].value) : [])
    setDimensions(context[1].status === 'fulfilled' ? unknownRows(context[1].value) : [])
    setIdentityStatus(context[2].status === 'fulfilled' ? context[2].value.scope?.identity_status ?? null : null)
    if (failed.length === TABS.length) setError('详细分析暂时没有返回结果，请先运行一次监测或检查服务状态。')
    else if (failed.length) setError(`${failed.join('、')}暂时不可用；页面只展示已返回的结果。`)
    setLoading(false)
  }
  useEffect(() => { if (demoMode || brandsLoaded) void load() }, [brandsLoaded, subjectQuery, demoMode])

  async function exportReport() {
    if (demoMode) { setError('演示数据不会导出为正式报告；关闭演示数据后才能导出真实报告。'); return }
    try { await saveBlobToDisk(await geoDownloadFile('/monitor/export'), `GEO-监测报告-${new Date().toISOString().slice(0, 10)}.md`) }
    catch (e) { setError(e instanceof Error ? e.message : '导出失败') }
  }
  const identityPending = identityStatus === 'unconfirmed'
  const findings = useMemo(() => buildFindings(snapshot, coverage, identityPending), [snapshot, coverage, identityPending])
  const selected = snapshot[tab] ?? null
  const rawAnswerCount = (snapshot['public-opinion'] as PublicOpinion | undefined)?.health?.total ?? (snapshot.sentiment as Sentiment | undefined)?.overview?.total ?? null
  const answerCount = rawAnswerCount != null && rawAnswerCount > 0 ? rawAnswerCount : null

  function action(kind: string) {
    const detail = TABS.find(([id]) => id === kind)?.[0]
    if (detail) { setTab(detail); setDetailsOpen(true); return }
    if (go) go(kind)
  }

  return <div className="monitor-analysis">
    <header className="workspace-intro"><div><span>证据到行动</span><h1>监测分析</h1><p>把模型回答汇成三件事：有没有被看见、说法是否有依据、下一步做什么。</p></div><div className="workspace-actions"><button className="geo-btn secondary" onClick={() => void exportReport()}><Download />导出报告</button><button className="geo-btn secondary" onClick={() => void load()}>{loading ? <LoaderCircle className="spin" /> : <RefreshCw />}刷新</button></div></header>
    {demoMode ? <div className="geo-demo-subject"><FlaskConical /><span>演示主体</span><b>云栖示例家居</b><small>固定内测样本；关闭演示数据后恢复真实监测主体。</small></div> : <MonitorSubjectPicker />}
    {demoMode && <div className="geo-demo-banner"><FlaskConical /><span><b>内测演示数据已开启</b>　{GEO_DEMO_NOTICE}</span></div>}
    <div className="analysis-scope-bar"><Info /><span>当前范围：最近一批有效模型回答</span><b>{answerCount == null ? '样本未判定' : `${answerCount} 条回答`}</b><small>{identityPending ? '主体尚未确认：以下只作回答信号，不计入品牌曝光或推荐率。' : '历史认知维度只作解释，不与本批次覆盖率相加。'}</small></div>
    {identityPending ? <div className="geo-identity-gate analysis-identity-gate" role="status"><div><strong>先确认回答里的企业是谁</strong><p>当前回答里出现了名称，但系统还不能确认它对应“{subjectQuery ? '当前所选主体' : '这家企业'}”。确认前只保留原始回答和情绪信号，不生成品牌表现结论。</p></div><button type="button" onClick={() => go?.('monitor-report')}>查看原始回答 <ArrowRight /></button></div> : null}
    <details className="analysis-stage-help"><summary>客户阶段是什么意思？</summary><p>认知 = 先知道你是谁 · 比较 = 和别家比较 · 决策 = 考虑选不选 · 信任 = 担心交付和售后。</p></details>
    {error && <div className="geo-inline-error">{error}</div>}
    {loading ? <div className="market-empty"><LoaderCircle className="spin" />正在整理监测结论…</div> : <>
      <section className="analysis-decision"><header><div><span className="geo-eyebrow">需要优先处理</span><h2>现在最值得处理的三件事</h2><p>每条判断都保留样本范围和证据状态；没有足够数据就保持“未判定”。</p></div></header><div className="analysis-findings">{findings.length ? findings.map((finding) => <FindingCard key={finding.key} finding={finding} onAction={action} />) : <AnalysisEmpty title="还没有可合并的判断" next="先到监测工作台让国产模型回答一轮真实客户问题；有效回答出现后，系统才会生成问题、证据和下一步。" />}</div></section>
      <CognitionContext coverage={coverage} dimensions={dimensions} identityPending={identityPending} />
      <details className="analysis-details" open={detailsOpen} onToggle={(event) => setDetailsOpen(event.currentTarget.open)}><summary>展开核对细节 <span>只在需要核对证据时打开</span></summary><nav className="analysis-tabs">{TABS.map(([id, label]) => <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>{label}</button>)}</nav><section className="analysis-content">{scoped.has(tab) && (snapshot[tab] as { scope_required?: boolean } | null)?.scope_required ? <AnalysisEmpty title="请选择监测主体" next="该分析需要明确统计哪个企业品牌；请在上方监测主体里选择。" /> : <>{tab === 'public-opinion' && <PublicOpinionView data={selected as PublicOpinion | null} />}{tab === 'sentiment' && <SentimentView data={selected as Sentiment | null} />}{tab === 'fact-check' && <FactCheckView data={selected as FactCheck | null} />}{tab === 'competitor' && <CompetitorView data={selected as Competitor | null} />}{tab === 'industry' && <IndustryView data={selected as Industry | null} />}{tab === 'sources' && <SourcesView data={selected as Sources | null} />}</>}</section></details>
    </>}
  </div>
}

/** 负面信号：样本构成 + 负面趋势 + 平台分布 + 高风险问题。这里不再合成一个“健康分”。 */
function PublicOpinionView({ data }: { data: PublicOpinion | null }) {
  if (!data?.health || data.health.total <= 0) return <AnalysisEmpty title="还没有可判断的负面评价" next="当前没有有效模型回答；系统不把分母为零显示成 0% 或健康结论。先运行一轮国产模型监测。" />
  const { health, metrics } = data
  return (
    <div className="analysis-stack">
      <GeoKpis
        items={[
          { label: '负面占比', value: `${health.neg_pct}%`, detail: `${health.total} 条回答`, tone: health.neg_pct > 30 ? 'warn' : 'good' },
          { label: '受影响问题', value: `${metrics.affected_questions}`, detail: '个问题出现负面回答', tone: metrics.affected_questions ? 'warn' : 'good' },
          { label: '需核对信号', value: `${metrics.risk_count}`, detail: `影响 ${metrics.affected_units} 个监测单元`, tone: metrics.risk_count ? 'warn' : 'good' },
          { label: '正面 / 中性', value: `${metrics.positive} / ${metrics.neutral}`, detail: `快速归类 · ${metrics.check_records} 条` },
        ]}
      />
      {metrics.affected_units ? <p className="geo-note">另有 {metrics.affected_units} 个监测单元被负面回答命中。</p> : null}
      <div className="geo-subhead"><h3>负面占比趋势</h3><small>按监测批次</small></div>
      <GeoLine points={rowsOf(data.trend).map((row) => ({ label: day(row.ts).slice(5), value: row.neg_pct }))} unit="%" />
      <p className="geo-note">{rowsOf(data.trend).map((row) => `${day(row.ts)} 负面 ${row.negative}/${row.total}`).join(' · ') || '暂无批次'}</p>
      <div className="geo-subhead"><h3>分平台负面分布</h3><small>快速归类，用于发现线索</small></div>
      <GeoBars
        items={rowsOf(data.platforms).map((row) => ({ label: row.platform, value: row.neg_pct, text: `${row.negative}/${row.total}` }))}
        empty="还没有平台维度数据"
      />
      <div className="geo-subhead"><h3>高风险问题</h3><small>负面回答最多的问题</small></div>
      <GeoTable
        columns={['客户问题', '负面条数']}
        template="minmax(0,1fr) 80px"
        rows={rowsOf(data.risk_top).map((row) => [<b>{row.question}</b>, <em>{row.negative}</em>])}
        empty="没有高风险问题"
      />
    </div>
  )
}

/** 评价分析：正负中分布 + 趋势 + 逐问题评价 + 负面高频词与样例 */
function SentimentView({ data }: { data: Sentiment | null }) {
  if (!data?.overview || data.overview.total <= 0) return <AnalysisEmpty title="还没有可分析的评价" next="当前没有有效模型回答；只有真实作答并完成评价判定后，才进入正面、负面和中性统计。" />
  const { overview } = data
  return (
    <div className="analysis-stack">
      <GeoKpis
        items={[
          { label: '评价样本', value: `${overview.total}`, detail: '条模型回答' },
          { label: '正面占比', value: `${overview.pos_pct}%`, detail: `${overview.positive} 条`, tone: 'good' },
          { label: '负面占比', value: `${overview.neg_pct}%`, detail: `${overview.negative} 条`, tone: overview.neg_pct > 30 ? 'warn' : 'good' },
          { label: '中性占比', value: `${overview.neu_pct}%`, detail: `${overview.neutral} 条` },
        ]}
      />
      <div className="geo-subhead"><h3>整体评价构成</h3><small>全部监测回答</small></div>
      <p className="geo-note">这里先按回答中的表达做快速归类，不能代替人工确认；无法确认企业主体或态度的回答单列为待判定。{data.unknown_count == null ? '待判定数量暂未返回。' : `待判定 ${data.unknown_count} 条。`}</p>
      <GeoRatio
        segments={[
          { label: '正面', value: overview.positive, color: '#638d24' },
          { label: '中性', value: overview.neutral, color: '#c9cec2' },
          { label: '负面', value: overview.negative, color: '#c2703c' },
        ]}
      />
      <div className="geo-subhead"><h3>逐问题评价</h3><small>点开前先看谁最糟</small></div>
      {(['positive', 'neutral', 'negative', 'unknown'] as const).map((kind) => {
        const labels = { positive: '正面', neutral: '中性', negative: '负面', unknown: '待判定' }
        const rows = rowsOf(data.questions).filter((row) => {
          const value = row.sentiment.toLowerCase()
          if (kind === 'unknown') return !['positive', 'negative', 'neutral', '正面', '负面', '中性'].includes(value)
          return value === kind || value === labels[kind]
        })
        return rows.length ? <details key={kind} className="rounded-md border border-[var(--yayu-border)] px-2 py-1" open={kind === 'negative'}>
          <summary className="cursor-pointer text-[11px] font-medium text-[var(--yayu-foreground)]">{labels[kind]} · {rows.length} 个问题</summary>
          <div className="pt-1"><GeoTable columns={['客户问题', '评价', '正 / 负 / 中']} template="minmax(0,1fr) 70px 96px" rows={rows.map((row) => [<b>{row.question}</b>, <em>{sentimentText(row.sentiment)}</em>, <em>{row.positive} / {row.negative} / {row.neutral}</em>])} /></div>
        </details> : null
      })}
      {!rowsOf(data.questions).length ? <p className="geo-note">还没有逐问题评价</p> : null}
      {rowsOf(data.top_words).length ? (
        <>
          <div className="geo-subhead"><h3>高频词</h3><small>负面语境里重复出现的用词（最长优先、不重叠切词）</small></div>
          <GeoBars items={rowsOf(data.top_words).map((row) => ({ label: row.word, value: row.count }))} />
          {data.top_words_note ? <p className="geo-note">{data.top_words_note}</p> : null}
        </>
      ) : <p className="geo-note">没有重复出现的负面用词：负面样本太少，或每处用词都不重复。</p>}
      {rowsOf(data.negative_samples).length ? (
        <>
          <div className="geo-subhead"><h3>负面原话</h3><small>模型原话，未改写</small></div>
          {rowsOf(data.negative_samples).slice(0, 5).map((row, index) => (
            <div key={index}>
              <p className="geo-note">
                {row.question} · {row.platform} · {day(row.ts)}
              </p>
              <GeoQuote>{row.snippet}</GeoQuote>
            </div>
          ))}
        </>
      ) : null}
    </div>
  )
}

/** 事实核验：知识库命中 + 失真排行 + 失真明细 */
function FactCheckView({ data }: { data: FactCheck | null }) {
  if (!data?.truth) return <AnalysisEmpty title="还没有可核验的回答" next="先运行监测，并确保公开内容资产中有可用于核对的企业事实；没有证据时不会生成核验结论。" />
  const { truth } = data
  return (
    <div className="analysis-stack">
      <GeoKpis
        items={[
          // 2026-09-21 口径修正：原来「已核验回答」算的是送检条数（超时/无文本也算），
          // 「知识库命中」把「没有任何事实断言」的回答也算成命中。现在两个数都只算真跑完检查、
          // 且真的有断言可比对的回答；没有断言的条数单独如实写出来。
          // 2026-09-21 二次校正：`total_checked` 里仍包含「跑完检查但没有企业断言」的回答，
          // 拿它当「已核验回答」会读成「10 条都验过了」。真正的核验数改成 claim_checked，
          // 跑完检查的总数挪到小字里。
          {
            label: '完成检查',
            value: `${truth.total_checked}`,
            detail: `抽检 ${truth.sampled_count ?? truth.total_checked} 条 / 候选 ${truth.candidate_total ?? truth.total_checked} 条`,
          },
          { label: '企业资料有依据', value: truth.knowledge_ok ? `${truth.hit_kb}` : '—', detail: truth.knowledge_ok ? '有可匹配依据的断言' : '企业资料暂时不可用，暂不统计', tone: truth.knowledge_ok ? 'good' : 'warn' },
          { label: '需要复核', value: `${truth.abnormal_count}`, detail: `涉及 ${truth.affected_questions} 个问题 / ${truth.affected_sources} 个平台`, tone: truth.abnormal_count ? 'warn' : 'good' },
        ]}
      />
      {truth.candidate_total != null && (truth.candidate_total - (truth.sampled_count ?? truth.total_checked) > 0 || (truth.no_claim_count ?? 0) > 0 || (truth.unsupported_count ?? 0) > 0) ? (
        <p className="geo-note">
          {truth.candidate_total - (truth.sampled_count ?? truth.total_checked) > 0 ? `本次抽检 ${truth.sampled_count ?? truth.total_checked}/${truth.candidate_total} 条候选回答。` : ''}
          {truth.unsupported_count ? `其中 ${truth.unsupported_count} 条缺少依据，无法据此判断对错。` : ''}
          {truth.no_claim_count ? `另有 ${truth.no_claim_count} 条回答里没有可核验的企业断言（既不算命中，也不算失真）。` : ''}
        </p>
      ) : null}
      {!truth.available ? <div className="geo-empty">这一轮没有可用于对照的企业知识，结论先不下。</div> : null}
      {truth.knowledge_ok ? null : <p className="geo-note">企业资料这次读不到，命中/失真两个数不完整。</p>}
      {truth.candidate_total != null ? <p className="geo-note">抽检完成率：{truth.total_checked}/{truth.sampled_count ?? truth.total_checked} 条抽检回答完成检查；其中 {truth.claim_checked ?? truth.total_checked} 条含可比对断言。需要复核不等于已证实错误，请查看每条类型。</p> : null}
      {truth.abnormal_count ? (
        <>
          <div className="geo-subhead"><h3>待复核平台</h3><small>按需要复核的记录数排序</small></div>
          <GeoBars
            items={rowsOf(data.source_rank).map((row) => ({ label: row.source, value: row.count, text: `${row.count} 处` }))}
            empty="本次抽检没有待复核记录"
          />
          <div className="geo-subhead"><h3>待复核问题</h3><small>按需要复核的记录数排序</small></div>
          <GeoTable
            columns={['客户问题', '复核类型', '次数']}
            template="minmax(0,1fr) 120px 56px"
            rows={rowsOf(data.question_rank).map((row) => [<b>{row.question}</b>, <em>{row.main_type}</em>, <em>{row.count}</em>])}
          />
          <div className="geo-subhead"><h3>需复核回答</h3><small>共 {data.detail_total} 条</small></div>
          {rowsOf(data.details).slice(0, 8).map((row, index) => (
            <div key={index}>
              <p className="geo-note">
                {row.question} · {row.platform} · {row.abnormal_type} · {day(row.ts)}
              </p>
              <GeoQuote>{row.ai_ref}</GeoQuote>
            </div>
          ))}
        </>
      ) : (
        <div className="geo-empty">本次抽检未发现需要复核的回答；这不代表所有回答都已核验。</div>
      )}
    </div>
  )
}

/** 竞品分析：我方 vs 竞品提及率对照 + 同题对比原话 */
function CompetitorView({ data }: { data: Competitor | null }) {
  const [visible, setVisible] = useState(8)
  if (!data?.pairs?.length) return <AnalysisEmpty title="还没有竞品对比数据" next="在“监测工作台”新建竞争关系对象，填写我方与竞品名称，然后至少成功运行一次。" />
  const pairs = rowsOf(data.pairs)
  // Owner 2026-09-23：本公司要先单独列出来，再按 1/2/3 列其他公司，
  // 不能每组卡片各印一次「我方 vs 谁」，让人分不清哪张是本公司。
  const selfNames = Array.from(new Set(pairs.map((pair) => pair.target).filter(Boolean)))
  const selfName = selfNames[0] ?? null
  const rivals = pairs.filter((pair) => pair.competitor !== selfName)
  return (
    <div className="analysis-stack">
      <p className="geo-note">比例表示各自回答中出现名称的回答占比（提及回答数 / 有回答数），不代表推荐率或胜负。每组问题和样本可能不同，百分比不能直接横向排名。</p>
      <div className="geo-panel">
        <div className="geo-subhead"><h3>本公司 / 其他公司</h3><small>编号 1 是本企业，后面按监测对象列出对标公司{selfNames.length > 1 ? `（这些监测问题里出现了 ${selfNames.length} 个不同的我方名称：${selfNames.join('、')}，请核对监测对象配置）` : ''}</small></div>
        <ul className="geo-lines">
          <li><b>1. {selfName ?? '（未识别我方名称）'}</b><span className="geo-muted"> · 本公司（判定提及用的名字）</span></li>
          {rivals.slice(0, visible).map((pair, index) => (
            <li key={`${pair.competitor}-${index}`}><b>{index + 2}. {pair.competitor}</b><span className="geo-muted"> · 对标 {selfName ?? '我方'} · 有回答 {pair.total} 条</span></li>
          ))}
        </ul>
      </div>
      {rivals.slice(0, visible).map((pair, index) => (
        <article className="geo-panel" key={index}>
          <div className="geo-subhead">
            <h3>
              {index + 2}. {pair.competitor}
            </h3>
            <small>
              对标 {selfName ?? '我方'} · 有回答 {pair.total} 条
              {pair.unanswered ? `（另 ${pair.unanswered} 条没作答，不计入百分比）` : ''}
            </small>
          </div>
          <GeoBars
            items={[
              { label: `${pair.target} 提及回答占比`, value: pair.target_pct, text: `${pair.target_mentioned}/${pair.total}（${pair.target_pct}%）` },
              { label: `${pair.competitor} 提及回答占比`, value: pair.comp_pct, text: `${pair.comp_mentioned}/${pair.total}（${pair.comp_pct}%）` },
            ]}
            max={100}
          />
          <p className="geo-note">
            名称出现在回答中：{pair.target} {pair.target_mentioned}/{pair.total}，{pair.competitor} {pair.comp_mentioned}/{pair.total}
            {pair.same_entity_pct ? `；另有 ${pair.same_entity_pct}% 的回答把两者当成同一实体` : ''}。
          </p>
          {pair.samples?.length ? (
            <>
              <div className="geo-subhead"><h3>同题对比原话</h3><small>模型怎么同时评价两者</small></div>
              <p className="geo-note">{pair.samples[0].question} · {pair.samples[0].engine}</p>
              <GeoQuote>{pair.samples[0].answer.slice(0, 400)}</GeoQuote>
            </>
          ) : null}
        </article>
      ))}
      {visible < rivals.length ? <button className="geo-btn secondary" onClick={() => setVisible((count) => count + 8)}>显示更多（已显示 {visible}/{rivals.length} 组）</button> : rivals.length > 8 ? <p className="geo-note">已显示全部 {rivals.length} 组</p> : null}
      {data.note ? <p className="geo-note">{data.note}</p> : null}
    </div>
  )
}

/** AI 回答中的企业提及：规则识别结果 + 可核验回答原文 */
function IndustryView({ data }: { data: Industry | null }) {
  if (!data) return <AnalysisEmpty title="还没有企业提及数据" next="先运行行业市场监测对象；这里只展示真实回答中识别到的企业名称。" />
  if (data.empty) return <AnalysisEmpty title="还没有行业市场监测对象" next={data.hint ?? '到“监测工作台”新建行业市场对象并运行一次。'} />
  const players = rowsOf(data.players)
  return (
    <div className="analysis-stack">
      <GeoKpis
        items={[
          { label: '行业', value: data.industry ?? '未标注', detail: `${data.objects} 个行业对象` },
          { label: '行业回答', value: `${data.total_answers}`, detail: '条' },
          { label: '企业提及', value: `${data.total_mention}`, detail: '条回答（规则识别）' },
        ]}
      />
      <div className="geo-subhead"><h3>模型回答中的企业提及</h3><small>按包含企业名的回答数排序，不代表推荐或市场份额</small></div>
      <GeoTable
        columns={['名称', '来源类型', '提及回答', '覆盖问题']}
        template="minmax(0,1fr) 90px 78px 78px"
        rows={players.map((row) => [<b>{row.name}</b>, <em>{row.category === 'self' ? '我方' : row.category === 'competitor' ? '已配置竞品' : '规则识别'}</em>, <em>{row.count}</em>, <em>{row.questions}</em>])}
        empty="接口未返回企业提及明细；请刷新，仍为空时重新运行行业监测"
      />
      {players.flatMap((row) => rowsOf(row.evidence).slice(0, 1).map((sample) => ({ ...sample, name: row.name }))).slice(0, 5).map((sample, index) => <div key={`${sample.name}-${index}`}><p className="geo-note">{sample.name} · {sample.engine} · {sample.question}</p><GeoQuote>{sample.snippet}</GeoQuote></div>)}
      {data.note ? <p className="geo-note">{data.note}</p> : null}
    </div>
  )
}

/** 信源分析：各模型（信源）的表现排行 */
function SourcesView({ data }: { data: Sources | null }) {
  if (!data?.sources?.length) return <AnalysisEmpty title="还没有模型信源数据" next="先运行监测；未接通或调用失败的模型不会被当作 0% 参与排行。" />
  return (
    <div className="analysis-stack">
      <div className="geo-subhead"><h3>模型提及率</h3><small>谁更容易提到我</small></div>
      <GeoBars
        items={rowsOf(data.sources).map((row) => ({ label: row.engine, value: row.mention_pct, text: `${row.mention_pct}%` }))}
        max={100}
      />
      <div className="geo-subhead"><h3>逐信源表现</h3><small>提及与评价分布</small></div>
      <GeoTable
        columns={['信源', '回答数', '提到我', '正面', '负面']}
        template="minmax(0,1fr) 74px 74px 64px 64px"
        rows={rowsOf(data.sources).map((row) => [
          <b>{row.engine}</b>,
          <em>{row.total}</em>,
          <em>{row.mentioned}</em>,
          <em>{row.positive}</em>,
          <em>{row.negative}</em>,
        ])}
      />
      {data.note ? <p className="geo-note">{data.note}</p> : null}
    </div>
  )
}
