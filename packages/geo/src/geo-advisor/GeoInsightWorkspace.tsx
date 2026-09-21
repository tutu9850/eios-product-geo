import { useEffect, useState } from 'react'
import { ArrowRight, CircleAlert, LoaderCircle, RefreshCw, X } from 'lucide-react'
import { geoGet } from './geo-api'
import { GeoBars, GeoKpis, GeoLine, GeoQuote, GeoTable } from './shared'

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
interface HumanizeMetrics { exposure_rate: number; recommendation_rate: number; gap_count: number; gap_dimensions: Array<{ dimension?: string }> }
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
interface SovBrand { brand: string; is_self: boolean; mention_count: number; mention_share: number; recommend_count: number; recommend_share: number; missing_count: number }
interface Sov {
  period_days: number
  total_mention: number
  total_recommend: number
  self: SovBrand | null
  brands: SovBrand[]
  trend: Array<{ period: string; brands: Array<{ brand: string; recommend_share: number }> }>
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

const pct = (value: number | null | undefined) => (value == null ? '—' : `${Math.round(value * 10) / 10}%`)
const BAND_TONE: Record<string, 'good' | 'warn' | 'bad'> = { green: 'good', red: 'bad', watch: 'warn' }

export function GeoInsightWorkspace() {
  const [d, setD] = useState<{
    humanize: Humanize | null
    sov: Sov | null
    'trend-delta': TrendDelta | null
    matrix: Matrix | null
    'factor-gaps': { left: FactorRow[]; right: FactorRow[]; risk_notes: Humanize['risk_notes']; sample_note: SampleNote } | null
    'gap-analysis': GapAnalysis | null
    keywords: { keywords: Keyword[] } | null
    perception: Perception | null
    strategies: Strategies | null
  }>({ humanize: null, sov: null, 'trend-delta': null, matrix: null, 'factor-gaps': null, 'gap-analysis': null, keywords: null, perception: null, strategies: null })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [factor, setFactor] = useState<string | null>(null)
  const [chain, setChain] = useState<EvidenceChain | null>(null)
  const [chainLoading, setChainLoading] = useState(false)
  const [chainError, setChainError] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    const paths = ['humanize', 'sov', 'trend-delta', 'matrix', 'factor-gaps', 'gap-analysis', 'keywords', 'perception', 'strategies'] as const
    const settled = await Promise.allSettled(paths.map((path) => geoGet(`/intelligence/${path}`)))
    const next: typeof d = { ...d }
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
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function openEvidence(nextFactor: string) {
    setFactor(nextFactor)
    setChain(null)
    setChainError('')
    setChainLoading(true)
    try {
      setChain(await geoGet<EvidenceChain>(`/intelligence/evidence?factor=${encodeURIComponent(nextFactor)}`))
    } catch (e) {
      setChainError(e instanceof Error ? e.message : '证据读取失败')
    } finally {
      setChainLoading(false)
    }
  }

  const human = d.humanize
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
  const trendPoints = (sov?.trend ?? []).map((row) => ({
    label: String(row.period ?? '').slice(5),
    value: Number(row.brands.find((b) => b.brand === selfSov?.brand)?.recommend_share ?? 0),
  }))

  return (
    <div className="insight-console">
      <header className="workspace-intro">
        <div>
          <span>PERCEPTION &amp; EVIDENCE</span>
          <h1>认知差距诊断</h1>
          <p>先看经营结论，再进入差距维度，最后回到模型原话与证据。</p>
        </div>
        <button className="geo-btn secondary" onClick={() => void load()}>
          {loading ? <LoaderCircle className="spin" /> : <RefreshCw />}刷新洞察
        </button>
      </header>
      {error && <div className="geo-inline-error"><CircleAlert />{error}</div>}

      <section className="insight-brief">
        <div>
          <span>本期判断</span>
          <h2>{human?.headline?.main ?? (loading ? '正在汇总…' : '还没有可判断的监测数据')}</h2>
          {human?.headline?.sub ? <p>{human.headline.sub}</p> : null}
        </div>
        <GeoKpis
          items={[
            { label: '品牌曝光率', value: pct(human?.metrics.exposure_rate), detail: '回答里出现我方的比例' },
            { label: '推荐率', value: pct(human?.metrics.recommendation_rate), detail: '被正面推荐的比例', tone: (human?.metrics.recommendation_rate ?? 0) > 0 ? 'good' : 'warn' },
            { label: '落后能力点', value: `${human?.metrics.gap_count ?? '—'}`, detail: '竞品有、我方缺', tone: (human?.metrics.gap_count ?? 0) > 0 ? 'warn' : 'good' },
            { label: '声量份额 SOV', value: selfSov ? pct(selfSov.recommend_share) : '—', detail: `${sov?.period_days ?? 30} 天窗口`, tone: 'good' },
          ]}
        />
      </section>

      {note ? <p className="geo-note">样本 {note.total} 条 · 可靠度「{note.reliability}」：{note.note}</p> : null}

      {delta && (delta.gained.length || delta.lost.length || delta.rising.length) ? (
        <section className="insight-panel">
          <div className="geo-subhead"><h3>周期变化</h3><small>{delta.periods.length} 个周期</small></div>
          <GeoBars
            items={[
              ...delta.rising.slice(0, 6).map((row) => ({ label: `${row.brand}（上升）`, value: Math.abs(row.delta), text: `+${row.delta}` })),
              ...delta.falling.slice(0, 6).map((row) => ({ label: `${row.brand}（下降）`, value: Math.abs(row.delta), text: `${row.delta}` })),
            ]}
            empty={delta.note}
          />
        </section>
      ) : null}

      <div className="insight-grid">
        <section className="insight-panel matrix">
          <div className="geo-subhead"><h3>认知差距矩阵</h3><small>按维度看谁被提到更多</small></div>
          {matrix?.dimensions.length ? (
            <div className="insight-list">
              {matrix.dimensions.slice(0, 10).map((row) => (
                <button key={row.dimension} onClick={() => void openEvidence(row.dimension)}>
                  <span className="insight-band" data-tone={BAND_TONE[row.band] ?? 'warn'}>{row.band_label}</span>
                  <b>{row.dimension}</b>
                  <em>我方 {row.self_mentions} · 他方 {row.other_mentions}</em>
                  <ArrowRight />
                </button>
              ))}
            </div>
          ) : (
            <div className="geo-empty">还没有正式维度（同一维度至少被提 2 次才进榜）。</div>
          )}
        </section>

        <section className="insight-panel">
          <div className="geo-subhead"><h3>优先补齐</h3><small>竞品有 · 我方无</small></div>
          {factorGaps?.left.length ? (
            <div className="insight-list">
              {factorGaps.left.slice(0, 7).map((row) => (
                <button key={row.factor} onClick={() => void openEvidence(row.factor)}>
                  <span className="insight-band" data-tone="bad">{row.competitor_mentions}</span>
                  <b>{row.factor}</b>
                  <em>{row.missing_note ?? `${row.competitor_leader} 被提及较多`}</em>
                  <ArrowRight />
                </button>
              ))}
            </div>
          ) : (
            <div className="geo-empty">当前没有「竞品有、我方无」的因子。</div>
          )}
        </section>

        <section className="insight-panel">
          <div className="geo-subhead"><h3>我方优势</h3><small>我方有 · 竞品无</small></div>
          {factorGaps?.right.length ? (
            <div className="insight-list">
              {factorGaps.right.slice(0, 7).map((row) => (
                <button key={row.factor} onClick={() => void openEvidence(row.factor)}>
                  <span className="insight-band" data-tone="good">{row.self_mentions}</span>
                  <b>{row.factor}</b>
                  <em>我方被提及 {row.self_mentions} 次，竞品 0 次</em>
                  <ArrowRight />
                </button>
              ))}
            </div>
          ) : (
            <div className="geo-empty">还没有识别出我方独有优势。</div>
          )}
        </section>

        <section className="insight-panel">
          <div className="geo-subhead"><h3>知识缺口 vs 证据缺口</h3><small>两种缺口的处置方式不同</small></div>
          {gapAnalysis && (gapAnalysis.knowledge_gaps.length || gapAnalysis.evidence_gaps.length) ? (
            <>
              {gapAnalysis.knowledge_gaps.length ? (
                <>
                  <p className="geo-note">知识库没有这条能力记录 —— 要么补齐能力，要么放弃这个维度。</p>
                  <GeoTable
                    columns={['维度', '竞品领先者', '建议动作']}
                    template="minmax(0,1fr) 110px minmax(0,1.4fr)"
                    rows={gapAnalysis.knowledge_gaps.slice(0, 6).map((row) => [<b>{row.dimension}</b>, <em>{row.competitor_leader || '—'}</em>, <em>{row.action}</em>])}
                  />
                </>
              ) : null}
              {gapAnalysis.evidence_gaps.length ? (
                <>
                  <p className="geo-note">能力已在知识库，但外部没有公开证据 —— 该发内容。</p>
                  <GeoTable
                    columns={['维度', '竞品领先者', '建议动作']}
                    template="minmax(0,1fr) 110px minmax(0,1.4fr)"
                    rows={gapAnalysis.evidence_gaps.slice(0, 6).map((row) => [<b>{row.dimension}</b>, <em>{row.competitor_leader || '—'}</em>, <em>{row.action}</em>])}
                  />
                </>
              ) : null}
            </>
          ) : (
            <div className="geo-empty">没有分离出待处置的缺口。</div>
          )}
        </section>

        <section className="insight-panel">
          <div className="geo-subhead"><h3>内容策略</h3><small>{d.strategies?.score_formula ?? '需求 × 差距 × 可改变性 × 证据强度 × 竞争重要性'}</small></div>
          {strategies.length ? (
            <div className="insight-list">
              {strategies.slice(0, 6).map((row) => (
                <button key={row.dimension} onClick={() => void openEvidence(row.dimension)}>
                  <span className="insight-band" data-tone="warn">{row.priority}</span>
                  <b>{row.topic || row.dimension}</b>
                  <em>行动分 {row.score} · {row.self_level_label} · {row.evidence_note}</em>
                  <ArrowRight />
                </button>
              ))}
            </div>
          ) : (
            <div className="geo-empty">暂无可执行的内容策略。</div>
          )}
        </section>

        <section className="insight-panel">
          <div className="geo-subhead"><h3>必备关键词</h3><small>内容生产该围绕的词</small></div>
          <GeoBars items={keywords.slice(0, 12).map((row) => ({ label: row.keyword, value: row.mentions, text: `${row.mentions} 次` }))} empty="还没有高频维度" />
        </section>

        <section className="insight-panel">
          <div className="geo-subhead"><h3>认知标签分布</h3><small>{d.perception?.evidence_count ?? 0} 条已解析回答</small></div>
          {tags.length ? (
            <>
              <GeoBars items={tags.slice(0, 10).map((row) => ({ label: row.tag, value: row.count, text: `${row.count}` }))} />
              {d.perception?.self_tags?.length ? (
                <p className="geo-note">其中直接描述我方的标签：{d.perception.self_tags.map((row) => `${row.tag}(${row.count})`).join('、')}</p>
              ) : null}
            </>
          ) : (
            <div className="geo-empty">还没有解析出认知标签。</div>
          )}
        </section>

        <section className="insight-panel">
          <div className="geo-subhead"><h3>AI 风险提示</h3><small>可转成信任建设素材</small></div>
          {factorGaps?.risk_notes?.length ? (
            factorGaps.risk_notes.slice(0, 5).map((row, index) => (
              <div key={index}>
                <p className="geo-note">{row.factor}{row.brand ? ` · ${row.brand}` : ''}</p>
                <GeoQuote>{row.quote ?? '（该条没有附原话）'}</GeoQuote>
              </div>
            ))
          ) : (
            <div className="geo-empty">没有针对我方的风险性表述。</div>
          )}
        </section>

        <section className="insight-panel">
          <div className="geo-subhead"><h3>现在能做什么</h3><small>按优先级排的行动清单</small></div>
          {human?.actions.length ? (
            <GeoTable
              columns={['优先级', '做什么', '为什么']}
              template="58px minmax(0,1fr) minmax(0,1.3fr)"
              rows={human.actions.map((row) => [<b>{row.priority}</b>, <b>{row.what}</b>, <em>{row.why}</em>])}
            />
          ) : (
            <div className="geo-empty">还没有生成行动建议。</div>
          )}
        </section>
      </div>

      {loading && !human ? <div className="geo-empty"><LoaderCircle className="spin" />正在汇总认知结果…</div> : null}
      {trendPoints.length > 1 ? (
        <section className="insight-panel">
          <div className="geo-subhead"><h3>我方推荐份额趋势</h3><small>{trendPoints.length} 个周期</small></div>
          <GeoLine points={trendPoints} unit="%" />
          <p className="geo-note">{sov?.note}</p>
        </section>
      ) : null}

      {factor ? (
        <aside className="evidence-drawer">
          <button className="drawer-close" onClick={() => { setFactor(null); setChain(null) }} aria-label="关闭证据抽屉">
            <X />
          </button>
          <span>EVIDENCE CHAIN</span>
          <h2>{chain?.dimension ?? factor}</h2>
          {chainLoading ? (
            <div className="market-empty"><LoaderCircle className="spin" />正在取模型原话…</div>
          ) : chainError ? (
            <div className="geo-inline-error"><CircleAlert />{chainError}</div>
          ) : chain ? (
            <>
              <GeoKpis
                items={[
                  { label: '传播强度', value: `${chain.propagation}`, detail: '条回答提到该因子' },
                  { label: '语义归类', value: chain.semantic || '—', detail: chain.dimension || '未归类' },
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
                  <div className="geo-subhead"><h3>关联因子</h3><small>同一维度下的其他因子</small></div>
                  <GeoBars items={chain.related_factors.map((row) => ({ label: row.factor, value: row.mentions }))} />
                </>
              ) : null}
            </>
          ) : null}
        </aside>
      ) : null}
    </div>
  )
}
