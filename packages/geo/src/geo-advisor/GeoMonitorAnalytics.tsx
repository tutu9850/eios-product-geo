import { useEffect, useState } from 'react'
import { Download, LoaderCircle, RefreshCw } from 'lucide-react'
import { geoDownloadFile, geoGet } from './geo-api'
import { GeoBars, GeoKpis, GeoLine, GeoQuote, GeoRatio, GeoTable, sentimentText, shortDay } from './shared'
import { saveBlobToDisk } from '../lib/save-to-disk'
import { MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'

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
  scope_required?: boolean
  scope?: { brands?: Array<{ monitor_id: string; name: string }> }
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
    sampled_count?: number
    unsupported_count?: number
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

function AnalysisEmpty({ title, next }: { title: string; next: string }) {
  return <div className="geo-empty analysis-empty"><b>{title}</b><span>{next}</span></div>
}

/**
 * API 历史版本、租户缓存或部分失败响应可能暂时缺少列表字段。TypeScript 接口只在
 * 编译期有效，不能把远端 JSON 当成一定完整；所有分析页统一把缺失列表降级为空态，
 * 避免一次 `.map()` 把整个嵌入产品卸载成白屏。
 */
function rowsOf<T>(value: T[] | null | undefined): T[] {
  return Array.isArray(value) ? value : []
}

export function GeoMonitorAnalytics() {
  const [tab, setTab] = useState<Analysis>('public-opinion')
  const [data, setData] = useState<PublicOpinion | Sentiment | FactCheck | Competitor | Industry | Sources | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { query: subjectQuery, loaded: brandsLoaded } = useMonitorSubject()
  const scopedTab = tab === 'public-opinion' || tab === 'sentiment' || tab === 'fact-check'

  async function load() {
    setLoading(true)
    setError('')
    try {
      const query = scopedTab && subjectQuery ? `?${subjectQuery}` : ''
      setData(await geoGet(`/monitor/${tab}${query}`))
    } catch (e) {
      setData(null)
      setError(e instanceof Error ? e.message : '分析加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    if (!brandsLoaded) return
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, brandsLoaded, subjectQuery])

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
      {scopedTab ? <MonitorSubjectPicker /> : null}
      {error && <div className="geo-inline-error">{error}</div>}
      <section className="analysis-content">
        {loading ? (
          <div className="market-empty">
            <LoaderCircle className="spin" />正在聚合监测结果…
          </div>
        ) : (
          scopedTab && (data as { scope_required?: boolean } | null)?.scope_required ? (
            <AnalysisEmpty title="请选择监测主体" next="该分析需要明确统计哪一个企业品牌；请在上方「监测主体」里选一个，或选「全部（全选汇总）」。" />
          ) : (
            <>
              {tab === 'public-opinion' && <PublicOpinionView data={data as PublicOpinion | null} />}
              {tab === 'sentiment' && <SentimentView data={data as Sentiment | null} />}
              {tab === 'fact-check' && <FactCheckView data={data as FactCheck | null} />}
              {tab === 'competitor' && <CompetitorView data={data as Competitor | null} />}
              {tab === 'industry' && <IndustryView data={data as Industry | null} />}
              {tab === 'sources' && <SourcesView data={data as Sources | null} />}
            </>
          )
        )}
      </section>
    </div>
  )
}

/** 品牌舆情：健康分 + 四指标 + 负面趋势 + 平台分布 + 高风险问题 */
function PublicOpinionView({ data }: { data: PublicOpinion | null }) {
  if (!data?.health) return <AnalysisEmpty title="还没有品牌舆情数据" next="先到“监测工作台”运行一个品牌或产品监测对象；模型产生有效回答后，这里会自动汇总。" />
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
      <GeoLine points={rowsOf(data.trend).map((row) => ({ label: day(row.ts).slice(5), value: row.neg_pct }))} unit="%" />
      <p className="geo-note">{rowsOf(data.trend).map((row) => `${day(row.ts)} 负面 ${row.negative}/${row.total}`).join(' · ') || '暂无批次'}</p>
      <div className="geo-subhead"><h3>分平台负面分布</h3><small>规则估算，非模型精判</small></div>
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
  if (!data?.overview) return <AnalysisEmpty title="还没有可分析的评价" next="先运行监测；只有模型真实作答且完成评价判定后，才会进入正面、负面和中性统计。" />
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
      <p className="geo-note">正、负、中为规则估算结果；无法确认企业主体或态度的回答单列为未判定，不计入正负中占比。未判定 {data.unknown_count ?? 0} 条。</p>
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
  if (!data?.truth) return <AnalysisEmpty title="还没有可核验的回答" next="先运行监测，并确保 GEO 内容资产中有可用于核对的企业事实；没有证据时不会生成核验结论。" />
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
          { label: '知识库有依据', value: truth.knowledge_ok ? `${truth.hit_kb}` : '—', detail: truth.knowledge_ok ? '有可匹配依据的断言' : '知识库不可用，暂不统计', tone: truth.knowledge_ok ? 'good' : 'warn' },
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
      {truth.knowledge_ok ? null : <p className="geo-note">知识库这次读不到，命中/失真两个数不完整。</p>}
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
        <div className="geo-subhead"><h3>本公司 / 其他公司</h3><small>编号 1 是本企业，后面按监测对象列出对标公司{selfNames.length > 1 ? `（这些探针里出现了 ${selfNames.length} 个不同的我方名称：${selfNames.join('、')}，请核对监测对象配置）` : ''}</small></div>
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
      <div className="geo-subhead"><h3>AI 回答中的企业提及</h3><small>按包含企业名的回答数排序，不代表推荐或市场份额</small></div>
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
