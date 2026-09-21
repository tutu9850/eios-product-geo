import { useEffect, useState } from 'react'
import { Download, LoaderCircle, RefreshCw } from 'lucide-react'
import { geoDownloadFile, geoGet } from './geo-api'
import { GeoBars, GeoKpis, GeoLine, GeoQuote, GeoRatio, GeoTable, sentimentText, shortDay } from './shared'
import { saveBlobToDisk } from '../lib/save-to-disk'

/**
 * 监测专业分析（六个页签共用一页）。
 *
 * 2026-09-21 改造：原来这里对任何返回都做「猜字段」——指标名直接把接口的
 * `mention_pct` 加个空格当标题给人看，明细行也从一堆候选键里挑一个。现在每个页签
 * 都对着后端真实结构写死字段（结构取自 apps/api/app/api/v1/monitor.py 各 handler），
 * 显示的一律是业务文字；缺失就是缺失，不再用占位键糊过去。
 */

type Analysis = 'public-opinion' | 'sentiment' | 'fact-check' | 'competitor' | 'industry' | 'sources'
const TABS: Array<[Analysis, string]> = [
  ['public-opinion', '品牌舆情'],
  ['sentiment', '评价分析'],
  ['fact-check', '事实核验'],
  ['competitor', '竞品分析'],
  ['industry', '企业提及'],
  ['sources', '信源分析'],
]

/** 评价倾向等机器值 → 业务文字（映射统一放在 shared，页面不显示英文） */
const day = shortDay

interface PublicOpinion {
  health: { score: number; label: string; neg_pct: number; total: number }
  metrics: {
    check_records: number
    risk_count: number
    positive: number
    neutral: number
    affected_questions: number
    affected_units: number
  }
  trend: Array<{ ts: string; neg_pct: number; negative: number; total: number }>
  platforms: Array<{ platform: string; negative: number; total: number; neg_pct: number }>
  risk_top: Array<{ question: string; negative: number }>
  details: Array<{ question: string; platform: string; sentiment: string; ts: string }>
  detail_total: number
}

interface Sentiment {
  overview: { total: number; positive: number; negative: number; neutral: number; pos_pct: number; neg_pct: number; neu_pct: number }
  trend: Array<{ ts: string; positive: number; negative: number; neutral: number; total: number }>
  questions: Array<{ question: string; positive: number; negative: number; neutral: number; sentiment: string }>
  top_words: Array<{ word: string; count: number }>
  negative_samples: Array<{ question: string; platform: string; snippet: string; ts: string }>
}

interface FactCheck {
  company_name: string | null
  truth: {
    available: boolean
    hit_kb: number
    abnormal_count: number
    affected_questions: number
    affected_sources: number
    total_checked: number
    claim_checked?: number
    /** 本轮拉到的候选回答数（受上限截断），用来解释「已核验」为什么比总回答少 */
    candidate_total?: number
    /** 有回答但没有任何可核验断言（不计命中也不计失真） */
    no_claim_count?: number
    knowledge_ok: boolean
  }
  source_rank: Array<{ rank: number; source: string; count: number; main_type: string }>
  question_rank: Array<{ rank: number; question: string; count: number; main_type: string }>
  details: Array<{ question: string; platform: string; abnormal_type: string; ai_ref: string; ts: string }>
  detail_total: number
}

interface Competitor {
  pairs: Array<{
    target: string
    competitor: string
    total: number
    unanswered?: number
    target_mentioned: number
    target_pct: number
    comp_mentioned: number
    comp_pct: number
    same_entity_pct: number
    samples: Array<{ question: string; engine: string; answer: string }>
  }>
  note?: string
}

interface Industry {
  industry: string | null
  objects: number
  total_answers: number
  total_mention: number
  players: Array<{ name: string; category: string; count: number; questions: number; evidence?: Array<{ question: string; engine: string; snippet: string; ts: string }> }>
  note?: string
  empty: boolean
  hint?: string | null
}

interface Sources {
  sources: Array<{ engine: string; total: number; mentioned: number; mention_pct: number; positive: number; negative: number; neutral: number }>
  note?: string
}

export function GeoMonitorAnalytics() {
  const [tab, setTab] = useState<Analysis>('public-opinion')
  const [data, setData] = useState<PublicOpinion | Sentiment | FactCheck | Competitor | Industry | Sources | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function load() {
    setLoading(true)
    setError('')
    try {
      setData(await geoGet(`/monitor/${tab}`))
    } catch (e) {
      setData(null)
      setError(e instanceof Error ? e.message : '分析加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  async function exportReport() {
    try {
      const blob = await geoDownloadFile('/monitor/export')
      await saveBlobToDisk(blob, `GEO-监测报告-${new Date().toISOString().slice(0, 10)}.md`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '导出失败')
    }
  }

  return (
    <div className="monitor-analysis">
      <header className="workspace-intro">
        <div>
          <span>MONITORING ANALYTICS</span>
          <h1>监测分析</h1>
          <p>用同一套结构查看品牌评价、事实偏差、竞争格局与模型信源表现。</p>
        </div>
        <div className="workspace-actions">
          <button className="geo-btn secondary" onClick={() => void exportReport()}>
            <Download />导出报告
          </button>
          <button className="geo-btn secondary" onClick={() => void load()}>
            {loading ? <LoaderCircle className="spin" /> : <RefreshCw />}刷新
          </button>
        </div>
      </header>
      <nav className="analysis-tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={tab === id ? 'active' : ''} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>
      {error && <div className="geo-inline-error">{error}</div>}
      <section className="analysis-content">
        {loading ? (
          <div className="market-empty">
            <LoaderCircle className="spin" />正在聚合监测结果…
          </div>
        ) : (
          <>
            {tab === 'public-opinion' && <PublicOpinionView data={data as PublicOpinion | null} />}
            {tab === 'sentiment' && <SentimentView data={data as Sentiment | null} />}
            {tab === 'fact-check' && <FactCheckView data={data as FactCheck | null} />}
            {tab === 'competitor' && <CompetitorView data={data as Competitor | null} />}
            {tab === 'industry' && <IndustryView data={data as Industry | null} />}
            {tab === 'sources' && <SourcesView data={data as Sources | null} />}
          </>
        )}
      </section>
    </div>
  )
}

/** 品牌舆情：健康分 + 四指标 + 负面趋势 + 平台分布 + 高风险问题 */
function PublicOpinionView({ data }: { data: PublicOpinion | null }) {
  if (!data?.health) return <div className="geo-empty">还没有监测记录，先跑一轮监测。</div>
  const { health, metrics } = data
  return (
    <div className="analysis-stack">
      <GeoKpis
        items={[
          { label: '舆情健康分', value: `${health.score}`, detail: health.label, tone: health.score >= 80 ? 'good' : health.score >= 60 ? 'warn' : 'bad' },
          { label: '负面占比', value: `${health.neg_pct}%`, detail: `${health.total} 条回答`, tone: health.neg_pct > 30 ? 'warn' : 'good' },
          { label: '风险点', value: `${metrics.risk_count}`, detail: `影响 ${metrics.affected_questions} 个问题`, tone: metrics.risk_count ? 'warn' : 'good' },
          { label: '正面 / 中性', value: `${metrics.positive} / ${metrics.neutral}`, detail: `共 ${metrics.check_records} 条记录` },
        ]}
      />
      {metrics.affected_units ? <p className="geo-note">另有 {metrics.affected_units} 个监测单元被负面回答命中。</p> : null}
      <div className="geo-subhead"><h3>负面占比趋势</h3><small>按监测批次</small></div>
      <GeoLine points={data.trend.map((row) => ({ label: day(row.ts).slice(5), value: row.neg_pct }))} unit="%" />
      <p className="geo-note">{data.trend.map((row) => `${day(row.ts)} 负面 ${row.negative}/${row.total}`).join(' · ') || '暂无批次'}</p>
      <div className="geo-subhead"><h3>分平台负面分布</h3><small>规则估算，非模型精判</small></div>
      <GeoBars
        items={data.platforms.map((row) => ({ label: row.platform, value: row.neg_pct, text: `${row.negative}/${row.total}` }))}
        empty="还没有平台维度数据"
      />
      <div className="geo-subhead"><h3>高风险问题</h3><small>负面回答最多的问题</small></div>
      <GeoTable
        columns={['客户问题', '负面条数']}
        template="minmax(0,1fr) 80px"
        rows={data.risk_top.map((row) => [<b>{row.question}</b>, <em>{row.negative}</em>])}
        empty="没有高风险问题"
      />
    </div>
  )
}

/** 评价分析：正负中分布 + 趋势 + 逐问题评价 + 负面高频词与样例 */
function SentimentView({ data }: { data: Sentiment | null }) {
  if (!data?.overview) return <div className="geo-empty">还没有评价数据，先跑一轮监测。</div>
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
      <GeoRatio
        segments={[
          { label: '正面', value: overview.positive, color: '#638d24' },
          { label: '中性', value: overview.neutral, color: '#c9cec2' },
          { label: '负面', value: overview.negative, color: '#c2703c' },
        ]}
      />
      <div className="geo-subhead"><h3>逐问题评价</h3><small>点开前先看谁最糟</small></div>
      <GeoTable
        columns={['客户问题', '评价', '正 / 负 / 中']}
        template="minmax(0,1fr) 70px 96px"
        rows={data.questions.map((row) => [
          <b>{row.question}</b>,
          <em>{sentimentText(row.sentiment)}</em>,
          <em>
            {row.positive} / {row.negative} / {row.neutral}
          </em>,
        ])}
        empty="还没有逐问题评价"
      />
      {data.top_words.length ? (
        <>
          <div className="geo-subhead"><h3>高频词</h3><small>负面语境里的用词</small></div>
          <GeoBars items={data.top_words.map((row) => ({ label: row.word, value: row.count }))} />
        </>
      ) : null}
      {data.negative_samples.length ? (
        <>
          <div className="geo-subhead"><h3>负面原话</h3><small>模型原话，未改写</small></div>
          {data.negative_samples.slice(0, 5).map((row, index) => (
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
  if (!data?.truth) return <div className="geo-empty">还没有可核验的监测回答。</div>
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
            label: '已核验回答',
            value: `${truth.claim_checked ?? truth.total_checked}`,
            detail: `有企业断言并比对过（共 ${truth.total_checked} 条跑完检查，拉到 ${truth.candidate_total ?? truth.total_checked} 条）`,
          },
          { label: '知识库命中', value: `${truth.hit_kb}`, detail: '断言能在企业知识库对上', tone: truth.knowledge_ok ? 'good' : 'bad' },
          { label: '疑似失真', value: `${truth.abnormal_count}`, detail: `影响 ${truth.affected_questions} 个问题 / ${truth.affected_sources} 个平台`, tone: truth.abnormal_count ? 'warn' : 'good' },
        ]}
      />
      {truth.candidate_total != null && (truth.candidate_total - truth.total_checked > 0 || (truth.no_claim_count ?? 0) > 0) ? (
        <p className="geo-note">
          {truth.candidate_total - truth.total_checked > 0 ? `另有 ${truth.candidate_total - truth.total_checked} 条没跑完检查（超时或没有正文）。` : ''}
          {truth.no_claim_count ? `另有 ${truth.no_claim_count} 条回答里没有可核验的企业断言（既不算命中，也不算失真）。` : ''}
        </p>
      ) : null}
      {!truth.available ? <div className="geo-empty">这一轮没有可用于对照的企业知识，结论先不下。</div> : null}
      {truth.knowledge_ok ? null : <p className="geo-note">知识库这次读不到，命中/失真两个数不完整。</p>}
      {truth.abnormal_count ? (
        <>
          <div className="geo-subhead"><h3>失真平台排行</h3><small>哪个模型最容易说错</small></div>
          <GeoBars
            items={data.source_rank.map((row) => ({ label: row.source, value: row.count, text: `${row.count} 处` }))}
            empty="没有失真记录"
          />
          <div className="geo-subhead"><h3>失真问题排行</h3><small>哪类问题最容易说错</small></div>
          <GeoTable
            columns={['客户问题', '失真类型', '次数']}
            template="minmax(0,1fr) 120px 56px"
            rows={data.question_rank.map((row) => [<b>{row.question}</b>, <em>{row.main_type}</em>, <em>{row.count}</em>])}
          />
          <div className="geo-subhead"><h3>失真原话</h3><small>共 {data.detail_total} 条</small></div>
          {data.details.slice(0, 8).map((row, index) => (
            <div key={index}>
              <p className="geo-note">
                {row.question} · {row.platform} · {row.abnormal_type} · {day(row.ts)}
              </p>
              <GeoQuote>{row.ai_ref}</GeoQuote>
            </div>
          ))}
        </>
      ) : (
        <div className="geo-empty">本轮没有发现与知识库冲突的回答。</div>
      )}
    </div>
  )
}

/** 竞品分析：我方 vs 竞品提及率对照 + 同题对比原话 */
function CompetitorView({ data }: { data: Competitor | null }) {
  if (!data?.pairs?.length) return <div className="geo-empty">还没有竞品对比数据，先建立竞品监测对象并跑一轮。</div>
  return (
    <div className="analysis-stack">
      {data.pairs.slice(0, 8).map((pair, index) => (
        <article className="geo-panel" key={index}>
          <div className="geo-subhead">
            <h3>
              {pair.target} vs {pair.competitor}
            </h3>
            <small>
              共 {pair.total} 条回答
              {pair.unanswered ? `（另 ${pair.unanswered} 条没作答，不计入百分比）` : ''}
            </small>
          </div>
          <GeoBars
            items={[
              { label: `${pair.target}（我方）`, value: pair.target_pct, text: `${pair.target_pct}%` },
              { label: pair.competitor, value: pair.comp_pct, text: `${pair.comp_pct}%` },
            ]}
            max={100}
          />
          <p className="geo-note">
            我方被提及 {pair.target_mentioned} 次，对方 {pair.comp_mentioned} 次
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
      {data.note ? <p className="geo-note">{data.note}</p> : null}
    </div>
  )
}

/** AI 回答中的企业提及：规则识别结果 + 可核验回答原文 */
function IndustryView({ data }: { data: Industry | null }) {
  if (!data) return <div className="geo-empty">还没有行业分析数据。</div>
  if (data.empty) return <div className="geo-empty">{data.hint ?? '还没有行业/关键词类型的监测对象。'}</div>
  return (
    <div className="analysis-stack">
      <GeoKpis
        items={[
          { label: '行业', value: data.industry ?? '未标注', detail: `${data.objects} 个行业对象` },
          { label: '行业回答', value: `${data.total_answers}`, detail: '条' },
          { label: '企业提及', value: `${data.total_mention}`, detail: '条回答（规则识别）' },
        ]}
      />
      <div className="geo-subhead"><h3>AI 回答中的企业提及</h3><small>按包含企业名的回答数排序，不代表推荐或市场份额</small></div>
      <GeoTable
        columns={['名称', '来源类型', '提及回答', '覆盖问题']}
        template="minmax(0,1fr) 90px 78px 78px"
        rows={data.players.map((row) => [<b>{row.name}</b>, <em>{row.category === 'self' ? '我方' : row.category === 'competitor' ? '已配置竞品' : '规则识别'}</em>, <em>{row.count}</em>, <em>{row.questions}</em>])}
        empty="这一轮回答中没有识别到企业名称"
      />
      {data.players.flatMap((row) => (row.evidence ?? []).slice(0, 1).map((sample) => ({ ...sample, name: row.name }))).slice(0, 5).map((sample, index) => <div key={`${sample.name}-${index}`}><p className="geo-note">{sample.name} · {sample.engine} · {sample.question}</p><GeoQuote>{sample.snippet}</GeoQuote></div>)}
      {data.note ? <p className="geo-note">{data.note}</p> : null}
    </div>
  )
}

/** 信源分析：各模型（信源）的表现排行 */
function SourcesView({ data }: { data: Sources | null }) {
  if (!data?.sources?.length) return <div className="geo-empty">还没有信源数据，先跑一轮监测。</div>
  return (
    <div className="analysis-stack">
      <div className="geo-subhead"><h3>模型提及率</h3><small>谁更容易提到我</small></div>
      <GeoBars
        items={data.sources.map((row) => ({ label: row.engine, value: row.mention_pct, text: `${row.mention_pct}%` }))}
        max={100}
      />
      <div className="geo-subhead"><h3>逐信源表现</h3><small>提及与评价分布</small></div>
      <GeoTable
        columns={['信源', '回答数', '提到我', '正面', '负面']}
        template="minmax(0,1fr) 74px 74px 64px 64px"
        rows={data.sources.map((row) => [
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
