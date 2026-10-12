import { useEffect, useRef, useState } from 'react'
import { ArrowRight, CircleAlert, LoaderCircle, RefreshCw, X } from 'lucide-react'
import { geoGet, geoPost } from './geo-api'
import { GeoBars, GeoKpis, GeoLine, GeoQuote, GeoTable, geoPriorityLabel, useGeoDemoMode, useGeoNav } from './shared'
import { GEO_DEMO_EVIDENCE, GEO_DEMO_INSIGHT, GEO_DEMO_NOTICE } from './demo-fixtures'
import { MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'

/**
 * 认知洞察工作区（2026-09-21 改造）。
 *
 * 原来这一页对十个接口的返回一律「猜键」：`label(row,['summary','headline',...])` 这种写法
 * 遇到 `headline` 是个对象就静默落回占位文案——于是即使后端已经算出
 * 「AI 回答里还没提到过你」，页面上仍然写着「完成监测后这里会形成一句话结论」。
 * 现在每个区块对着 services/intelligence 的真实结构写死字段：
 *   humanize / sov / trend-delta → 汇报层
 *   matrix / factor-gaps / gap-analysis → 差距层与缺口层
 *   keywords / perception / strategies → 素材层
 *   evidence_chain → 证据抽屉（点任一因子两次点击内拿到模型原话）
 */

interface SampleNote { total: number; reliability: string; note: string }
interface Headline { main: string; sub: string; tone: string }
interface HumanizeMetrics { exposure_rate: number | null; recommendation_rate: number | null; gap_count: number; gap_dimensions: Array<{ dimension?: string }> }
interface FactorRow {
  factor: string
  dimension: string
  self_mentions: number
  competitor_mentions: number
  competitor_leader: string
  missing_note?: string
  quotes?: Array<{ quote: string; brand?: string }>
}
interface Humanize {
  headline: Headline
  metrics: HumanizeMetrics
  left: FactorRow[]
  right: FactorRow[]
  risk_notes: Array<{ factor: string; quote?: string; brand?: string }>
  actions: Array<{ priority: string; score: number; what: string; why: string; keywords: string[] }>
  sample_note: SampleNote
}
interface SovBrand { brand: string; is_self: boolean; mention_count: number; mention_share: number; recommend_count: number; recommend_share: number | null; missing_count: number; identity_status?: 'confirmed' | 'unconfirmed'; unconfirmed_count?: number }
interface BrandOverview { company: string | null; mode: string; total_evidence: number; self_name: string; brands: Array<{ name: string; is_self: boolean; mentions: number; rate: number; identity_status?: 'confirmed' | 'unconfirmed' }> }
interface Sov {
  period_days: number
  total_mention: number
  total_recommend: number
  self: SovBrand | null
  brands: SovBrand[]
  trend: Array<{ period: string; brands: Array<{ brand: string; recommend_share: number | null }> }>
  note: string
}
interface MatrixDim {
  dimension: string
  band: string
  band_label: string
  verdict: 'win' | 'loss' | 'tie'
  total_mentions: number
  self_mentions: number
  other_mentions: number
  quotes: Array<{ brand: string; quote: string }>
}
interface Matrix { dimensions: MatrixDim[]; observation: MatrixDim[]; missing: Array<{ brand: string; quote: string }>; evidence_count: number }
interface GapItem { dimension: string; competitor_leader: string; action: string; gap_type: string }
interface GapAnalysis { knowledge_gaps: GapItem[]; evidence_gaps: GapItem[]; sample_note: SampleNote }
interface Strategy {
  dimension: string
  score: number
  priority: string
  topic: string
  self_level_label: string
  competitor_leader: string
  keywords: string[]
  evidence_note: string
  comp_quotes: Array<{ quote: string; brand: string }>
}
interface Strategies { strategies: Strategy[]; score_formula: string; sample_note: SampleNote }
interface Keyword { keyword: string; mentions: number; band: string }
interface Tag { tag: string; count: number; subjects?: string[] }
interface Perception { tags: Tag[]; self_tags: Tag[]; evidence_count: number }
interface TrendDelta {
  periods: Array<{ period: string; brands: Record<string, number> }>
  gained: Array<{ brand: string; from: number; to: number; delta: number }>
  lost: Array<{ brand: string; from: number; to: number; delta: number }>
  rising: Array<{ brand: string; from: number; to: number; delta: number }>
  falling: Array<{ brand: string; from: number; to: number; delta: number }>
  note: string
}
interface EvidenceChain {
  factor: string
  semantic: string
  dimension: string
  propagation: number
  sources: Array<{ evidence_id: string; platform: string; observed_at: string; mention_type: string; intent: string; quote: string; brand: string }>
  related_factors: Array<{ factor: string; mentions: number }>
}

interface IntelligenceProgress {
  parse?: { succeeded?: number; failed?: number; running?: number; total?: number; queue_size?: number; deferred?: number }
  harvest?: { status?: string; written?: number; error?: string }
  note?: string
}

interface IntelligenceStats {
  evidence?: number
  extraction?: number
  succeeded?: number
  failed?: number
  mentions?: number
}

const pct = (value: number | null | undefined) => (value == null ? '—' : `${Math.round(value * 10) / 10}%`)
const BAND_TONE: Record<string, 'good' | 'warn' | 'bad'> = { green: 'good', red: 'bad', watch: 'warn' }

function readableHeadlineSub(value: string | undefined): string | undefined {
  if (!value) return value
  return value
    .replace('重复了名称，但同时表示无法确认对应企业', '提到了名称，但无法确认是不是当前企业')
    .replace('重复了名称', '提到了名称')
    .replace('同时表示无法确认对应企业', '无法确认是不是当前企业')
}

export function GeoInsightWorkspace() {
  const { enabled: demoMode } = useGeoDemoMode()
  const go = useGeoNav()
  const { query: subjectQuery, loaded: subjectsLoaded } = useMonitorSubject()
  const [d, setD] = useState<{
    humanize: Humanize | null
    overview: BrandOverview | null
    sov: Sov | null
    'trend-delta': TrendDelta | null
    matrix: Matrix | null
    'factor-gaps': { left: FactorRow[]; right: FactorRow[]; risk_notes: Humanize['risk_notes']; sample_note: SampleNote } | null
    'gap-analysis': GapAnalysis | null
    keywords: { keywords: Keyword[] } | null
    perception: Perception | null
    strategies: Strategies | null
  }>({ humanize: null, overview: null, sov: null, 'trend-delta': null, matrix: null, 'factor-gaps': null, 'gap-analysis': null, keywords: null, perception: null, strategies: null })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [factor, setFactor] = useState<string | null>(null)
  const [chain, setChain] = useState<EvidenceChain | null>(null)
  const [chainLoading, setChainLoading] = useState(false)
  const [chainError, setChainError] = useState('')
  const [pipeline, setPipeline] = useState<{ progress: IntelligenceProgress | null; stats: IntelligenceStats | null }>({ progress: null, stats: null })
  const [recovering, setRecovering] = useState(false)
  const loadSeq = useRef(0)
  const evidenceSeq = useRef(0)

  async function load() {
    const requestId = ++loadSeq.current
    setLoading(true)
    setError('')
    if (demoMode) {
      if (requestId !== loadSeq.current) return
      setD(GEO_DEMO_INSIGHT as typeof d)
      setLoading(false)
      return
    }
    setD({ humanize: null, overview: null, sov: null, 'trend-delta': null, matrix: null, 'factor-gaps': null, 'gap-analysis': null, keywords: null, perception: null, strategies: null })
    const paths = ['humanize', 'overview', 'sov', 'trend-delta', 'matrix', 'factor-gaps', 'gap-analysis', 'keywords', 'perception', 'strategies'] as const
    const [settled, progress, stats] = await Promise.all([
      Promise.allSettled(paths.map((path) => geoGet(`/intelligence/${path}${subjectQuery ? `?${subjectQuery}` : ''}`))),
      geoGet<IntelligenceProgress>(`/intelligence/progress${subjectQuery ? `?${subjectQuery}` : ''}`).catch(() => null),
      geoGet<IntelligenceStats>(`/intelligence/stats${subjectQuery ? `?${subjectQuery}` : ''}`).catch(() => null),
    ])
    if (requestId !== loadSeq.current) return
    setPipeline({ progress, stats })
    const next: typeof d = { humanize: null, overview: null, sov: null, 'trend-delta': null, matrix: null, 'factor-gaps': null, 'gap-analysis': null, keywords: null, perception: null, strategies: null }
    paths.forEach((path, index) => {
      const result = settled[index]
      // 每个面各自成败：一个面没数据不该让整页变成占位文案
      if (result.status === 'fulfilled') (next as Record<string, unknown>)[path] = result.value
      else (next as Record<string, unknown>)[path] = null
    })
    setD(next)
    if (settled.every((item) => item.status === 'rejected')) setError('暂时无法读取认知洞察数据。')
    setLoading(false)
  }
  useEffect(() => {
    evidenceSeq.current += 1
    setFactor(null)
    setChain(null)
    setChainError('')
    setChainLoading(false)
    if (demoMode || subjectsLoaded) void load()
  }, [demoMode, subjectsLoaded, subjectQuery])

  useEffect(() => {
    if (!factor) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setFactor(null)
      setChain(null)
      setChainError('')
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [factor])

  async function openEvidence(nextFactor: string) {
    const requestId = ++evidenceSeq.current
    setFactor(nextFactor)
    setChain(null)
    setChainError('')
    setChainLoading(true)
    try {
      if (demoMode) {
        const demoEvidence = GEO_DEMO_EVIDENCE[nextFactor] ?? {
          factor: nextFactor,
          semantic: '演示证据',
          dimension: nextFactor,
          propagation: 0,
          sources: [],
          related_factors: [],
        }
        if (requestId === evidenceSeq.current) setChain(demoEvidence as EvidenceChain)
        return
      }
      const nextChain = await geoGet<EvidenceChain>(`/intelligence/evidence?factor=${encodeURIComponent(nextFactor)}${subjectQuery ? `&${subjectQuery}` : ''}`)
      if (requestId === evidenceSeq.current) setChain(nextChain)
    } catch (e) {
      if (requestId === evidenceSeq.current) setChainError(e instanceof Error ? e.message : '证据读取失败')
    } finally {
      if (requestId === evidenceSeq.current) setChainLoading(false)
    }
  }

  async function recoverPipeline() {
    if (demoMode || recovering) return
    setRecovering(true)
    setError('')
    try {
      const params = new URLSearchParams(subjectQuery || '')
      params.set('limit', '30')
      params.set('auto_report', 'false')
      await geoPost(`/intelligence/recover?${params.toString()}`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '解析任务启动失败')
    } finally {
      setRecovering(false)
    }
  }

  const human = d.humanize
  const brandOverview = d.overview
  const sov = d.sov
  const delta = d['trend-delta']
  const matrix = d.matrix
  const factorGaps = d['factor-gaps']
  const gapAnalysis = d['gap-analysis']
  const strategies = d.strategies?.strategies ?? []
  const keywords = d.keywords?.keywords ?? []
  const tags = d.perception?.tags ?? []
  const note = human?.sample_note ?? factorGaps?.sample_note ?? gapAnalysis?.sample_note
  const selfSov = sov?.self ?? null
  const trendPoints = (sov?.trend ?? []).flatMap((row) => {
    const share = row.brands.find((b) => b.brand === selfSov?.brand)?.recommend_share
    // 没有可判定的推荐率时不画 0%，避免把“没有样本/主体未确认”误读成明确的零推荐。
    return share == null ? [] : [{ label: String(row.period ?? '').slice(5), value: Number(share) }]
  })
  const evidenceTotal = Math.max(note?.total ?? 0, matrix?.evidence_count ?? 0, d.perception?.evidence_count ?? 0)
  const hasInsightData = evidenceTotal > 0
  const parse = pipeline.progress?.parse
  const evidenceCount = pipeline.stats?.evidence ?? null
  const parsedCount = pipeline.stats?.succeeded ?? parse?.succeeded ?? null
  const failedCount = pipeline.stats?.failed ?? parse?.failed ?? null
  const processingCount = (parse?.running ?? 0) + (parse?.queue_size ?? 0) + (parse?.deferred ?? 0)
  const identityUnconfirmed = selfSov?.identity_status === 'unconfirmed'
    || Boolean(brandOverview?.brands.some((row) => row.is_self && row.identity_status === 'unconfirmed'))
  const conclusionsAvailable = hasInsightData && !identityUnconfirmed
  const headline = identityUnconfirmed
    ? '主体识别不足，暂不判断品牌表现'
    : human?.headline?.main ?? (loading ? '正在汇总…' : '还没有可判断的监测数据')

  return (
    <div className="insight-console">
      <header className="workspace-intro">
        <div>
          <span>模型回答与证据</span>
          <h1>品牌认知差距</h1>
          <p>先看结论，再看哪里缺证据，最后回到模型原话核对。</p>
        </div>
        <button className="geo-btn secondary" onClick={() => void load()}>
          {loading ? <LoaderCircle className="spin" /> : <RefreshCw />}刷新洞察
        </button>
      </header>
      {!demoMode ? <MonitorSubjectPicker note="洞察分析已绑定这个主体；选择“全部”时只做账号级汇总，不替你猜某一家企业。" /> : null}
      {demoMode && <div className="geo-demo-banner"><CircleAlert /><span><b>内测演示数据已开启</b>　{GEO_DEMO_NOTICE}</span></div>}
      {error && <div className="geo-inline-error"><CircleAlert />{error}</div>}

      <section className="insight-brief">
        <div className="insight-brief-hero">
          <span>本期判断</span>
          <h2>{headline}</h2>
          {human?.headline?.sub ? <p>{readableHeadlineSub(human.headline.sub)}</p> : null}
          <div className="insight-hero-meta">
            <span>主体：{brandOverview?.self_name ?? selfSov?.brand ?? '当前监测主体'}</span>
            <span>时间范围：{sov?.period_days == null ? '—' : `${sov.period_days} 天`}</span>
            <span>已理解回答：{note?.total == null ? '—' : `${note.total} 条`}</span>
          </div>
        </div>
        <div className="insight-brief-metrics">
          <GeoKpis
            items={[
              { label: '品牌曝光率', value: identityUnconfirmed ? '—' : pct(human?.metrics.exposure_rate), detail: identityUnconfirmed ? '主体未确认，暂不判断' : '回答里出现我方的比例' },
              // 2026-09-21：recommendation_rate 的口径是「回答里明确推荐了我方」（认知层级到了
              // recommended，需要带推荐理由），与「正面评价」不是一回事——原文写「被正面推荐」会
              // 让用户以为这里做了情感判断。改成口径原话。
              { label: '推荐率', value: identityUnconfirmed ? '—' : pct(human?.metrics.recommendation_rate), detail: identityUnconfirmed ? '主体未确认，暂不判断' : '回答里明确推荐了我方（不只是被提及）', tone: identityUnconfirmed ? 'warn' : (human?.metrics.recommendation_rate ?? 0) > 0 ? 'good' : 'warn' },
              { label: '落后能力点', value: !hasInsightData || identityUnconfirmed ? '—' : `${human?.metrics.gap_count ?? '—'}`, detail: identityUnconfirmed ? '主体未确认，暂不判断' : '竞品有、我方缺', tone: identityUnconfirmed ? 'warn' : hasInsightData && (human?.metrics.gap_count ?? 0) > 0 ? 'warn' : 'good' },
            ]}
          />
        </div>
      </section>

      {identityUnconfirmed ? (
        <section className="insight-panel insight-identity-gate" role="status">
          <div>
            <h3>先确认回答里的企业是谁</h3>
            <p>有些回答提到了名称，但系统还不能确认它是不是“{brandOverview?.self_name ?? selfSov?.brand ?? '当前主体'}”。确认前不生成曝光率、推荐率、竞品差距或行动建议。</p>
            <small className="geo-note">先核对企业资料和监测对象名称，再回到监测工作台重新运行一轮；系统会在新回答与主体一致后自动确认，不把不确定回答计入品牌指标。</small>
          </div>
          <div className="flex shrink-0 flex-wrap gap-1.5">
            <button type="button" className="geo-btn secondary" onClick={() => go?.('monitor-report')}>查看模型原话 <ArrowRight /></button>
            <button type="button" className="geo-btn secondary" onClick={() => go?.('profile-overview')}>核对企业资料 <ArrowRight /></button>
            <button type="button" className="geo-btn secondary" onClick={() => go?.('monitor')}>回到监测工作台 <ArrowRight /></button>
          </div>
        </section>
      ) : null}

      {(brandOverview?.brands.length && brandOverview.brands.length > 1) || (delta && (delta.gained.length || delta.lost.length || delta.rising.length || delta.falling.length)) || trendPoints.length > 1 ? <details className="insight-details insight-comparison-details">
        <summary><span><b>核对品牌比较与变化</b><small>提及、推荐次数和推荐份额分别计算</small></span><ArrowRight /></summary>
        <div className="insight-details-grid">
      {brandOverview?.brands.length && brandOverview.brands.length > 1 ? <section className="insight-panel insight-brand-panel">
        <div className="geo-subhead"><h3>品牌出现情况</h3><small>{brandOverview.total_evidence} 条可比较的模型回答</small></div>
        <GeoTable
          columns={['品牌', '身份', '被提及回答', '提及率']}
          template="minmax(0,1fr) 84px 96px 80px"
          rows={brandOverview.brands.slice(0, 12).map((row) => [<b>{row.name}</b>, <em>{row.identity_status === 'unconfirmed' ? '主体未确认' : row.is_self ? '我方' : '其他企业'}</em>, <em>{row.mentions}</em>, <b>{row.identity_status === 'unconfirmed' ? '—' : `${row.rate}%`}</b>])}
        />
        <p className="geo-note">提及表示回答中出现该品牌，不等于推荐或正面评价。</p>
      </section> : null}

      {delta && (delta.gained.length || delta.lost.length || delta.rising.length) ? (
        <section className="insight-panel insight-delta-panel">
          <div className="geo-subhead"><h3>推荐性提及次数变化</h3><small>最近 {delta.periods.length} 个周期；这里比较次数，不是推荐率</small></div>
          <GeoBars
            items={[
              ...delta.rising.slice(0, 6).map((row) => ({ label: `${row.brand}（上升）`, value: Math.abs(row.delta), text: `+${row.delta} 次` })),
              ...delta.falling.slice(0, 6).map((row) => ({ label: `${row.brand}（下降）`, value: Math.abs(row.delta), text: `${row.delta} 次` })),
            ]}
            empty={delta.note}
          />
        </section>
      ) : null}
      {trendPoints.length > 1 ? (
        <section className="insight-panel insight-trend-panel">
          <div className="geo-subhead"><h3>我方推荐份额趋势</h3><small>{trendPoints.length} 个周期；我方推荐次数占全部品牌推荐次数</small></div>
          <GeoLine points={trendPoints} unit="%" />
          <p className="geo-note">{sov?.note}</p>
        </section>
      ) : null}
        </div>
      </details> : null}

      {!demoMode && pipeline.stats ? (
        <details className="insight-pipeline" role="status" open={(evidenceCount ?? 0) > 0 && (parsedCount ?? 0) === 0}>
          <summary className="insight-pipeline-head">
            <span><b>回答处理进度</b><small>{parsedCount ?? '—'} / {evidenceCount ?? '—'} 条已完成理解</small></span>
          </summary>
          <div className="insight-pipeline-metrics">
            <span><b>{evidenceCount ?? '—'}</b><small>原始回答</small></span>
            <span><b>{parsedCount ?? '—'}</b><small>已完成理解</small></span>
            <span><b>{processingCount}</b><small>等待处理</small></span>
            <span><b>{failedCount ?? '—'}</b><small>处理失败</small></span>
          </div>
          {(evidenceCount ?? 0) > 0 && (parsedCount ?? 0) === 0 ? <><p>已有监测回答，但还没有一条完成理解；当前不会生成差距、策略或确定性结论。先处理 30 条受控样本，完成后再看洞察。</p>{processingCount === 0 ? <button className="geo-btn secondary insight-pipeline-action" disabled={recovering} onClick={() => void recoverPipeline()}>{recovering ? <LoaderCircle className="spin" /> : <RefreshCw />}{recovering ? '正在加入处理队列…' : '先处理 30 条样本'}</button> : null}</> : failedCount ? <p>有 {failedCount} 条回答处理失败，失败记录不会被当成洞察依据。</p> : null}
        </details>
      ) : null}

      {!loading && !hasInsightData && !identityUnconfirmed ? (
        <section className="insight-panel insight-start-empty">
          <CircleAlert />
          <div><h3>还没有足够的有效回答形成判断</h3><p>先在“监测工作台”运行品牌、产品或竞品对象。模型成功返回回答并被系统读懂后，这里才会展示差距、优势、风险和行动建议。</p></div>
        </section>
      ) : null}

      {conclusionsAvailable ? <>
        <div className="insight-grid insight-decision-grid">
        {matrix?.dimensions.length ? (
        <section className="insight-panel matrix insight-matrix-panel">
          <div className="geo-subhead"><h3>各主题对比</h3><small>按主题看谁被提到更多</small></div>
          <div className="insight-list">
              {matrix.dimensions.slice(0, 5).map((row) => (
                <button key={row.dimension} onClick={() => void openEvidence(row.dimension)}>
                  <span className="insight-band" data-tone={BAND_TONE[row.band] ?? 'warn'}>{row.band_label}</span>
                  <b>{row.dimension}</b>
                  <em>我方 {row.self_mentions} · 他方 {row.other_mentions}</em>
                  <ArrowRight />
                </button>
              ))}
          </div>
        </section>
        ) : null}

              {factorGaps?.left.length ? (
        <section className="insight-panel insight-priority-panel">
          <div className="geo-subhead"><h3>最该补的地方</h3><small>竞品有 · 我方还没有</small></div>
          <div className="insight-list">
              {factorGaps.left.slice(0, 3).map((row) => (
                <button key={row.factor} onClick={() => void openEvidence(row.factor)}>
                  <span className="insight-band" data-tone="bad">竞品 {row.competitor_mentions} 次</span>
                  <b>{row.factor}</b>
                  <em>{row.missing_note ?? `${row.competitor_leader} 被提及较多`}</em>
                  <ArrowRight />
                </button>
              ))}
          </div>
        </section>
        ) : null}

        {factorGaps?.right.length ? (
        <section className="insight-panel insight-advantage-panel">
          <div className="geo-subhead"><h3>已经被认可的地方</h3><small>我方有 · 竞品没有</small></div>
          <div className="insight-list">
              {factorGaps.right.slice(0, 3).map((row) => (
                <button key={row.factor} onClick={() => void openEvidence(row.factor)}>
                  <span className="insight-band" data-tone="good">我方 {row.self_mentions} 次</span>
                  <b>{row.factor}</b>
                  <em>我方被提及 {row.self_mentions} 次，竞品 {row.competitor_mentions} 次</em>
                  <ArrowRight />
                </button>
              ))}
          </div>
        </section>
        ) : null}

        </div>
        <details className="insight-details">
          <summary>
            <span><b>查看更多依据和行动</b><small>缺什么资料、要补什么公开内容、下一步做什么</small></span>
            <ArrowRight />
          </summary>
          <div className="insight-details-grid">

        {gapAnalysis && (gapAnalysis.knowledge_gaps.length || gapAnalysis.evidence_gaps.length) ? (
        <section className="insight-panel insight-gap-panel">
          <div className="geo-subhead"><h3>缺什么资料，缺什么公开证据</h3><small>两种问题的解决方式不同</small></div>
          <>
              {gapAnalysis.knowledge_gaps.length ? (
                <>
                  <p className="geo-note">企业资料里没有这项能力记录：补齐资料，或暂时不对外承诺。</p>
                  <GeoTable
                    columns={['维度', '竞品领先者', '建议动作']}
                    template="minmax(0,1fr) 110px minmax(0,1.4fr)"
                    rows={gapAnalysis.knowledge_gaps.slice(0, 6).map((row) => [<b>{row.dimension}</b>, <em>{row.competitor_leader || '—'}</em>, <em>{row.action}</em>])}
                  />
                </>
              ) : null}
              {gapAnalysis.evidence_gaps.length ? (
                <>
                  <p className="geo-note">企业资料里有这项能力，但公开内容还不足：需要发布可核对的说明。</p>
                  <GeoTable
                    columns={['维度', '竞品领先者', '建议动作']}
                    template="minmax(0,1fr) 110px minmax(0,1.4fr)"
                    rows={gapAnalysis.evidence_gaps.slice(0, 6).map((row) => [<b>{row.dimension}</b>, <em>{row.competitor_leader || '—'}</em>, <em>{row.action}</em>])}
                  />
                </>
              ) : null}
          </>
        </section>
        ) : null}

        {strategies.length ? (
        <section className="insight-panel insight-strategy-panel">
          <div className="geo-subhead"><h3>内容建设方向</h3><small>优先补最影响客户选择的主题</small></div>
          <div className="insight-list">
              {strategies.slice(0, 3).map((row) => (
                <button key={row.dimension} onClick={() => void openEvidence(row.dimension)}>
                  <span className="insight-band" data-tone="warn">{geoPriorityLabel(row.priority)}</span>
                  <b>{row.topic || row.dimension}</b>
                  <em>行动分 {row.score} · {row.self_level_label} · {row.evidence_note}</em>
                  <ArrowRight />
                </button>
              ))}
          </div>
        </section>
        ) : null}

        {keywords.length ? (
        <section className="insight-panel insight-keyword-panel">
          <div className="geo-subhead"><h3>客户常用说法</h3><small>下一轮内容可以围绕这些词</small></div>
          <GeoBars items={keywords.slice(0, 5).map((row) => ({ label: row.keyword, value: row.mentions, text: `${row.mentions} 次` }))} empty="还没有高频维度" />
        </section>
        ) : null}

        {tags.length ? (
        <section className="insight-panel insight-perception-panel">
          <div className="geo-subhead"><h3>模型常用的描述</h3><small>{d.perception?.evidence_count == null ? '—' : `${d.perception.evidence_count} 条已完成理解的回答`}</small></div>
          <>
              <GeoBars items={tags.slice(0, 5).map((row) => ({ label: row.tag, value: row.count, text: `${row.count}` }))} />
              {d.perception?.self_tags?.length ? (
                <p className="geo-note">其中直接描述我方的标签：{d.perception.self_tags.map((row) => `${row.tag}(${row.count})`).join('、')}</p>
              ) : null}
          </>
        </section>
        ) : null}

        {factorGaps?.risk_notes?.length ? (
        <section className="insight-panel insight-risk-panel">
          <div className="geo-subhead"><h3>需要核对的说法</h3><small>可转成信任建设内容</small></div>
          {factorGaps.risk_notes.slice(0, 3).map((row, index) => (
              <div key={index}>
                <p className="geo-note">{row.factor}{row.brand ? ` · ${row.brand}` : ''}</p>
                <GeoQuote>{row.quote ?? '（该条没有附原话）'}</GeoQuote>
              </div>
            ))}
        </section>
        ) : null}

        {human?.actions.length ? (
        <section className="insight-panel insight-action-panel">
          <div className="geo-subhead"><h3>下一步行动</h3><small>按优先级排列</small></div>
          <GeoTable
              columns={['优先级', '做什么', '为什么']}
              template="58px minmax(0,1fr) minmax(0,1.3fr)"
              rows={human.actions.slice(0, 4).map((row) => [<b>{geoPriorityLabel(row.priority)}</b>, <b>{row.what}</b>, <em>{row.why}</em>])}
          />
        </section>
        ) : null}
          </div>
        </details>
      </> : null}

      {loading && !human ? <div className="geo-empty"><LoaderCircle className="spin" />正在汇总认知结果…</div> : null}
      {factor ? (
        <>
        <button className="evidence-backdrop" onClick={() => { setFactor(null); setChain(null) }} aria-label="关闭证据抽屉" />
        <aside className="evidence-drawer" role="dialog" aria-modal="true" aria-label={`${chain?.dimension ?? factor} 判断依据`}>
          <button className="drawer-close" onClick={() => { setFactor(null); setChain(null) }} aria-label="关闭证据抽屉">
            <X />
          </button>
          <span>判断依据</span>
          <h2>{chain?.dimension ?? factor}</h2>
          {chainLoading ? (
            <div className="market-empty"><LoaderCircle className="spin" />正在取模型原话…</div>
          ) : chainError ? (
            <div className="geo-inline-error"><CircleAlert />{chainError}</div>
          ) : chain ? (
            <>
              <GeoKpis
                items={[
                  { label: '出现次数', value: `${chain.propagation}`, detail: '条回答提到这个主题' },
                  { label: '归类', value: chain.semantic || '—', detail: chain.dimension || '未归类' },
                ]}
              />
              <div className="geo-subhead"><h3>模型原话</h3><small>共 {chain.sources.length} 条</small></div>
              {chain.sources.length ? (
                chain.sources.map((row, index) => (
                  <div key={index}>
                    <p className="geo-note">{row.platform} · {row.observed_at} · {row.brand || '未标注主体'}</p>
                    <GeoQuote>{row.quote || '（该条没有原话）'}</GeoQuote>
                  </div>
                ))
              ) : (
                <div className="geo-empty">这个因子还没有可引用的原话。</div>
              )}
              {chain.related_factors.length ? (
                <>
                  <div className="geo-subhead"><h3>相关主题</h3><small>同一主题下的其他说法</small></div>
                  <GeoBars items={chain.related_factors.map((row) => ({ label: row.factor, value: row.mentions }))} />
                </>
              ) : null}
            </>
          ) : null}
        </aside>
        </>
      ) : null}
    </div>
  )
}
