import { useEffect, useState } from 'react'
import { ArrowUpRight, CheckCircle2, CircleAlert, LoaderCircle, RefreshCw } from 'lucide-react'
import {
  geoGet,
  type GeoDistillOverview,
  type GeoMonitorOverview,
  type GeoStatsOverview,
} from './geo-api'

type OverviewState = {
  monitor: GeoMonitorOverview | null
  stats: GeoStatsOverview | null
  distill: GeoDistillOverview | null
}

const EMPTY: OverviewState = { monitor: null, stats: null, distill: null }

function pct(value: number | null | undefined) {
  return value == null ? '—' : `${Math.round(value * 10) / 10}%`
}

function Metric({ label, value, detail, tone = 'good' }: { label: string; value: string; detail: string; tone?: 'good' | 'warn' }) {
  return <article className="geo-metric"><span>{label}</span><strong>{value}</strong><small data-tone={tone}>{detail}</small><svg viewBox="0 0 120 28" aria-hidden="true"><path d="M1 23 C18 22 24 17 39 19 S61 10 76 14 S99 6 119 5" /></svg></article>
}

export function GeoEnterpriseOverview({ onNavigate }: { onNavigate: (target: string) => void }) {
  const [data, setData] = useState<OverviewState>(EMPTY)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    const [monitor, stats, distill] = await Promise.allSettled([
      geoGet<GeoMonitorOverview>('/monitor/overview'),
      geoGet<GeoStatsOverview>('/stats/overview'),
      geoGet<GeoDistillOverview>('/distill/overview'),
    ])
    setData({
      monitor: monitor.status === 'fulfilled' ? monitor.value : null,
      stats: stats.status === 'fulfilled' ? stats.value : null,
      distill: distill.status === 'fulfilled' ? distill.value : null,
    })
    if ([monitor, stats, distill].every((item) => item.status === 'rejected')) setError('暂时无法读取 GEO 总览数据。')
    setLoading(false)
  }

  useEffect(() => { void load() }, [])

  const recommend = data.monitor?.recommend.value
  const recommendDelta = data.monitor?.recommend.delta ?? 0
  const avgRank = data.monitor?.rank.value
  const citeRate = data.monitor?.cite_rate
  const gaps = data.distill?.funnel?.find((item) => item.stage.includes('缺口'))?.question_count
  const platformRows = Object.entries(data.monitor?.platforms ?? {}).map(([name, rows]) => ({
    name,
    value: rows.at(-1)?.recommend_pct ?? 0,
  })).sort((a, b) => b.value - a.value)

  return <div className="geo-dashboard">
    <div className="geo-page-head"><div><span>AI DISCOVERY INTELLIGENCE</span><h1>企业 AI 可见度总览</h1><p>看见品牌在国产大模型回答中的位置，找到差距，并推动下一步增长。</p></div><button className="geo-btn secondary" onClick={() => void load()} disabled={loading}>{loading ? <LoaderCircle className="spin" /> : <RefreshCw />}刷新数据</button></div>
    {error && <div className="geo-inline-error"><CircleAlert />{error}</div>}
    <div className="geo-metrics">
      {/* 2026-09-21 口径修正（Owner：「输出正常但不正确」）：
          这两个数原来的名字会让人读成「AI 推荐我们」，实际口径是「AI 回答里提到过我们的问题占比」，
          以及「我们的名字第一次出现在第几句」。改名字，并在副标里写清真实含义。 */}
      <Metric label="AI 提及率" value={pct(recommend)} detail={`提及 ≠ 推荐 · ${recommendDelta >= 0 ? '↑' : '↓'} ${Math.abs(recommendDelta)} 较上周期`} tone={recommendDelta >= 0 ? 'good' : 'warn'} />
      <Metric label="首次出现句序" value={avgRank == null ? '—' : String(Math.round(avgRank * 10) / 10)} detail="名字出现在第几句 · 估算" />
      <Metric label="引用率" value={pct(citeRate)} detail={`${data.monitor?.citations_count ?? 0} 次内容引用`} />
      <Metric label="待补知识缺口" value={gaps == null ? '—' : String(gaps)} detail={`${data.stats?.knowledge.materials ?? 0} 份企业素材`} tone={gaps ? 'warn' : 'good'} />
    </div>
    <div className="geo-overview-grid">
      <article className="geo-panel trend-panel"><header><div><h2>国产大模型表现</h2><p>各平台最近一次监测的 AI 提及率（提到≠推荐）</p></div><span>最近批次</span></header>
        {platformRows.length ? <div className="geo-platform-chart">{platformRows.slice(0, 6).map((item) => <div className="geo-platform" key={item.name}><div className="geo-platform-bar"><i style={{ height: `${Math.max(8, item.value)}%` }} /></div><b>{pct(item.value)}</b><span>{item.name}</span></div>)}</div> : <div className="geo-chart-empty">完成一次监测后，这里会展示各国产大模型的真实表现。</div>}
      </article>
      <article className="geo-panel action-panel"><header><div><h2>现在最值得做</h2><p>从监测结论直接进入业务动作</p></div></header>
        <button onClick={() => onNavigate('profile')}><span className="action-index">1</span><span><b>补齐企业资料</b><small>检查 8 大类企业事实与问题覆盖</small></span><ArrowUpRight /></button>
        <button onClick={() => onNavigate('insight')}><span className="action-index">2</span><span><b>查看认知差距</b><small>找到竞品有、我方缺的认知因子</small></span><ArrowUpRight /></button>
        <button onClick={() => onNavigate('growth')}><span className="action-index">3</span><span><b>推进内容闭环</b><small>从问题和缺口生成内容计划</small></span><ArrowUpRight /></button>
      </article>
      <article className="geo-panel health-panel"><header><div><h2>数据与引擎状态</h2><p>当前部署的真实可用情况</p></div></header><div className="health-list"><span><CheckCircle2 /><b>{data.stats?.engines.answered ?? '—'} / {data.stats?.engines.total ?? '—'}</b><small>模型已回答 / 已登记</small></span><span><CheckCircle2 /><b>{data.stats?.monitor.runs ?? '—'}</b><small>累计监测批次</small></span><span><CheckCircle2 /><b>{data.stats?.links.indexed ?? '—'} / {data.stats?.links.total ?? '—'}</b><small>已收录 / 全部链接</small></span></div></article>
      <article className="geo-panel funnel-panel"><header><div><h2>问题覆盖漏斗</h2><p>从客户问题到可用企业知识</p></div></header>{data.distill?.funnel?.length ? <div className="funnel-list">{data.distill.funnel.map((row) => <div key={row.stage}><span>{row.stage}</span><i><em style={{ width: `${Math.max(3, row.coverage_pct)}%` }} /></i><b>{row.question_count} · {pct(row.coverage_pct)}</b></div>)}</div> : <div className="geo-chart-empty">生成问题池并检测知识缺口后显示。</div>}</article>
    </div>
  </div>
}
