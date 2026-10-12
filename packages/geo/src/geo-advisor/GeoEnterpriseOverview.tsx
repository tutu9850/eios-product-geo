import { useEffect, useState } from 'react'
import { ArrowUpRight, CheckCircle2, CircleAlert, FlaskConical, LoaderCircle, RefreshCw } from 'lucide-react'
import {
  geoGet,
  type GeoDistillOverview,
  type GeoMonitorOverview,
  type GeoStatsOverview,
} from './geo-api'
import { ALL_SUBJECTS, MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'
import { GEO_DEMO_NOTICE, GEO_DEMO_OVERVIEW } from './demo-fixtures'
import { useGeoDemoMode } from './shared'

type OverviewState = {
  monitor: GeoMonitorOverview | null
  stats: GeoStatsOverview | null
  distill: GeoDistillOverview | null
  profile?: { data_status?: { knowledge_ready?: boolean | null } } | null
}

const EMPTY: OverviewState = { monitor: null, stats: null, distill: null, profile: null }

function pct(value: number | null | undefined) {
  return value == null ? '—' : `${Math.round(value * 10) / 10}%`
}

function customerStageLabel(value: string) {
  return ({ 采购: '购买', 留存: '使用与留存' } as Record<string, string>)[value] ?? value
}

function Metric({ label, value, detail, tone = 'good' }: { label: string; value: string; detail: string; tone?: 'good' | 'warn' }) {
  return <article className="geo-metric"><span>{label}</span><strong>{value}</strong><small data-tone={tone}>{detail}</small></article>
}

function readableIdentityNote(note: string | null | undefined): string | null {
  if (!note) return null
  // 兼容尚未重启的旧 API，让已发布的 Client 也不会把内部处理词展示给用户。
  return note
    .replace('已有回答，但主体身份尚未确认；先完成语义解析后再显示品牌表现。', '已有回答，但还不能确认对应的是哪家企业；先完成回答理解后再显示品牌表现。')
}

export function GeoEnterpriseOverview({ onNavigate }: { onNavigate: (target: string) => void }) {
  const [data, setData] = useState<OverviewState>(EMPTY)
  const { enabled: demoMode } = useGeoDemoMode()
  const { value: selectedBrandId, query: subjectQuery, loaded: brandsLoaded } = useMonitorSubject()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [journeyOpen, setJourneyOpen] = useState(() => window.localStorage.getItem('eios-geo-journey-open') !== 'closed')

  async function load() {
    setLoading(true)
    setError(null)
    if (demoMode) {
      setData(GEO_DEMO_OVERVIEW as OverviewState)
      setLoading(false)
      return
    }
    const [monitor, stats, distill, profile] = await Promise.allSettled([
      subjectQuery ? geoGet<GeoMonitorOverview>(`/monitor/overview?${subjectQuery}`) : Promise.resolve(null),
      geoGet<GeoStatsOverview>('/stats/overview'),
      geoGet<GeoDistillOverview>('/distill/overview'),
      geoGet<{ data_status?: { knowledge_ready?: boolean | null } }>('/enterprise-profile/overview'),
    ])
    setData({
      monitor: monitor.status === 'fulfilled' ? monitor.value : null,
      stats: stats.status === 'fulfilled' ? stats.value : null,
      distill: distill.status === 'fulfilled' ? distill.value : null,
      profile: profile.status === 'fulfilled' ? profile.value : null,
    })
    if ([monitor, stats, distill, profile].every((item) => item.status === 'rejected')) setError('暂时无法读取 GEO 总览数据。')
    setLoading(false)
  }

  useEffect(() => { if (demoMode || brandsLoaded) void load() }, [brandsLoaded, subjectQuery, demoMode])

  const recommend = data.monitor?.recommend.value
  const recommendDelta = data.monitor?.recommend.delta
  const avgRank = data.monitor?.rank.value
  const citeRate = data.monitor?.cite_rate
  const gaps = data.distill?.open_gaps_count
  const enterpriseKnowledgeReady = data.profile?.data_status?.knowledge_ready ?? null
  const identityPending = !demoMode && data.monitor?.scope?.identity_status === 'unconfirmed'
  const latestBatchAt = data.monitor?.latest_batch_at
  const latestBatchLabel = demoMode ? '演示样本 · 2026-09-25' : !selectedBrandId ? '尚未选择主体' : latestBatchAt ? latestBatchAt.slice(0, 16).replace('T', ' ') : '该主体暂无监测批次'
  const publishedCount = data.monitor?.published_count
  const citedCount = data.monitor?.cited_count
  const citationCount = data.monitor?.citations_count
  const citationDetail = data.monitor?.scope?.citations_attribution_available === false
    ? '历史引用未按监测主体记录，暂不能归属'
    : citeRate == null && publishedCount == null
      ? '完成监测并登记发布链接后显示可归属引用'
      : `${citedCount == null ? '—' : citedCount} / ${publishedCount == null ? '—' : publishedCount} 份已发布素材曾被引用；累计 ${citationCount == null ? '—' : citationCount} 次`
  const materialDetail = data.stats?.knowledge.materials == null
    ? '工作区尚未返回内容资产统计'
    : data.stats.knowledge.materials === 0
      ? '当前还没有可用于补齐的内容资产'
      : `${data.stats.knowledge.materials} 份内容资产可用于补齐`
  const actionSteps = identityPending
    ? [
        { target: 'monitor-report', title: '核对模型原话', detail: '先确认回答里的名称是不是当前企业' },
        { target: 'monitor', title: '核对主体并重新监测', detail: '名称和资料一致后再跑一轮，系统才计算曝光率、推荐率和竞品差距' },
        { target: 'profile', title: '补齐企业资料', detail: '让企业名称、产品和证据可以被逐条核对' },
      ]
    : [
        { target: 'profile', title: '补齐企业资料', detail: '检查 8 大类企业事实与问题覆盖' },
        { target: 'insight', title: '查看认知差距', detail: '找到竞品有、我方缺的认知因子' },
        { target: 'growth', title: '推进内容闭环', detail: '从问题和缺口生成内容计划' },
      ]
  const platformRows = Object.entries(data.monitor?.platforms ?? {}).flatMap(([name, rows]) => {
    const latest = rows.filter((row) => row.ts === latestBatchAt).at(-1)
    // 兼容尚未重启的旧 API：旧响应会给未回答模型塞 configured=0 的 0% 点。
    return latest && latest.configured > 0 ? [{ name, value: latest.recommend_pct }] : []
  }).sort((a, b) => b.value - a.value)

  return <div className="geo-dashboard">
    <div className="geo-page-head"><div><span>总览</span><h1>客户问模型时，品牌是否会被提到</h1><p>看品牌有没有被看见、被正确理解，再决定下一步补什么。</p></div><button className="geo-btn secondary" onClick={() => void load()} disabled={loading}>{loading ? <LoaderCircle className="spin" /> : <RefreshCw />}刷新</button></div>
    {demoMode ? <div className="geo-demo-subject"><FlaskConical /><span>演示主体</span><b>笔革家居</b><small>固定内测样本；关闭演示数据后恢复真实监测对象。</small></div> : <MonitorSubjectPicker />}
    {error && <div className="geo-inline-error"><CircleAlert />{error}</div>}
    {demoMode && <div className="geo-demo-banner"><FlaskConical /><span><b>内测演示数据已开启</b>　{GEO_DEMO_NOTICE}</span></div>}
    <p className="geo-note">{readableIdentityNote(data.monitor?.scope?.identity_note) ?? (selectedBrandId ? `提及率、句序和平台表现来自${selectedBrandId === ALL_SUBJECTS ? '全选汇总的' : '所选'}主体最近批次（${latestBatchLabel}）。` : '请选择企业品牌后查看该主体的监测指标。')}资料缺口、内容资产与系统状态为当前工作空间汇总，不与品牌监测指标直接比较。</p>
    <details className="geo-journey-guide" open={journeyOpen} onToggle={(event) => { const open = (event.currentTarget as HTMLDetailsElement).open; setJourneyOpen(open); window.localStorage.setItem('eios-geo-journey-open', open ? 'open' : 'closed') }}>
      <summary><span>第一次使用？按这条路径走</span><small>准备资料 → 运行监测 → 看懂差距 → 推进行动</small></summary>
      <div className="geo-journey-grid">
        <button type="button" onClick={() => onNavigate('profile')}><b>1. 准备企业资料</b><span>让系统知道你是谁、卖什么、有什么证据。</span></button>
        <button type="button" onClick={() => onNavigate('monitor')}><b>2. 运行国产模型监测</b><span>把客户问题交给模型，看回答里有没有提到你。</span></button>
        <button type="button" onClick={() => onNavigate('insight')}><b>3. 看懂认知差距</b><span>区分被提到、被推荐和有证据支持。</span></button>
        <button type="button" onClick={() => onNavigate('growth')}><b>4. 变成增长动作</b><span>补资料、做内容，再回到监测验证变化。</span></button>
      </div>
    </details>
    {identityPending ? <section className="geo-identity-gate" role="status">
      <div><strong>品牌指标暂不计算</strong><p>已有模型回答，但目前还不能确认回答里的名称对应哪家企业。先查看模型原话并完成回答理解，再判断曝光率、推荐率和竞品差距。</p></div>
      <button type="button" onClick={() => onNavigate('monitor-report')}>先看模型回答 <ArrowUpRight /></button>
    </section> : <div className="geo-metrics">
      {/* 2026-09-21 口径修正（Owner：「输出正常但不正确」）：
          这两个数原来的名字会让人读成「AI 推荐我们」，实际口径是「AI 回答里提到过我们的问题占比」，
          以及「我们的名字第一次出现在第几句」。改名字，并在副标里写清真实含义。 */}
      <Metric
        label="品牌被提到"
        value={pct(recommend)}
        detail={recommendDelta == null ? '模型回答里出现品牌的比例 · 暂无可比上周期' : `模型回答里出现品牌的比例 · ${recommendDelta >= 0 ? '↑' : '↓'} ${Math.abs(recommendDelta)} 个百分点较上周期`}
        tone={recommendDelta == null || recommendDelta >= 0 ? 'good' : 'warn'}
      />
      <Metric label="品牌出现位置" value={avgRank == null ? '—' : `第 ${Math.round(avgRank * 10) / 10} 句`} detail="回答平均从第几句开始提到品牌 · 越靠前越显眼" />
      <Metric label="公开内容被引用" value={pct(citeRate)} detail={citationDetail} />
      <Metric label="需要补的资料" value={gaps == null ? '—' : String(gaps)} detail={`工作区汇总 · ${materialDetail}`} tone={gaps ? 'warn' : 'good'} />
    </div>}
    <div className="geo-overview-grid">
      <article className="geo-panel trend-panel"><header><div><h2>不同模型的表现</h2><p>最近一批回答里，各模型提到品牌的比例；没有回答的不算 0%</p></div><span>{latestBatchLabel}</span></header>
    {platformRows.length ? <div className="geo-platform-chart">{platformRows.slice(0, 6).map((item) => <div className="geo-platform" key={item.name}><div className="geo-platform-bar"><i style={{ height: `${Math.max(8, item.value)}%` }} /></div><b>{pct(item.value)}</b><span>{item.name}</span></div>)}</div> : <div className="geo-chart-empty">{latestBatchAt ? '最近批次没有平台返回可判定回答。' : '该主体完成一次监测后，这里会展示各国产大模型的真实表现。'}</div>}
      </article>
      <article className="geo-panel action-panel"><header><div><h2>现在最值得做</h2><p>{identityPending ? '先确认主体，再把结论变成行动' : '从监测结论直接进入业务动作'}</p></div></header>
        {actionSteps.map((step, index) => <button key={`${step.target}-${step.title}`} onClick={() => onNavigate(step.target)}><span className="action-index">{index + 1}</span><span><b>{step.title}</b><small>{step.detail}</small></span><ArrowUpRight /></button>)}
      </article>
      <article className="geo-panel health-panel"><header><div><h2>系统准备情况</h2><p>这些是工作区记录，不代表当前主体已有可判定回答</p></div></header><div className="health-list"><span>{data.stats?.engines.total ? <CheckCircle2 /> : <CircleAlert />}<b>{data.stats?.engines.total ? `${data.stats.engines.answered} / ${data.stats.engines.total}` : '暂无可统计回答'}</b><small>最近有回答的模型 / 当前已登记模型</small></span><span>{data.stats?.monitor.runs ? <CheckCircle2 /> : <CircleAlert />}<b>{data.stats?.monitor.runs ? `${data.stats.monitor.runs} 批历史运行` : '暂无运行记录'}</b><small>工作区累计；请到监测页核对当前主体的回答</small></span><span>{data.stats?.links.total ? <CheckCircle2 /> : <CircleAlert />}<b>{data.stats?.links.total ? `${data.stats.links.indexed} / ${data.stats.links.total}` : '尚未登记链接'}</b><small>已收录链接 / 已登记发布链接</small></span></div></article>
      <article className="geo-panel funnel-panel"><header><div><h2>资料能回答哪些客户问题</h2><p>当前工作区的客户问题，有多少能被企业资料回答；这不是品牌曝光或推荐指标</p></div></header>{!demoMode && enterpriseKnowledgeReady === false ? <div className="geo-chart-empty">还没有同步可核实的企业资料；先去企业资料完成同步，再看问题覆盖。</div> : !demoMode && enterpriseKnowledgeReady == null ? <div className="geo-chart-empty">当前无法确认资料状态，暂不显示覆盖数字。</div> : data.distill?.funnel?.length ? <div className="funnel-list">{data.distill.funnel.map((row) => <div key={row.stage}><span>{customerStageLabel(row.stage)}</span><i><em style={{ width: `${row.coverage_pct == null ? 0 : Math.max(3, row.coverage_pct)}%` }} /></i><b>{row.question_count} 个问题 · {row.judged_count ? `${row.judged_count} 个已判定 · ${pct(row.coverage_pct)}` : '未判定'}</b></div>)}</div> : <div className="geo-chart-empty">生成客户问题并检查企业资料后，这里会显示覆盖情况。</div>}</article>
    </div>
  </div>
}
