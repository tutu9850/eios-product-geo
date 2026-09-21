import { useEffect, useState } from 'react'
import { Download, RefreshCw } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoDownload, geoGet, geoPost, type GeoOnboardStatus } from './geo-api'
import { GeoBars, GeoButtonRow, GeoCardShell, GeoError, GeoKpis, GeoList, GeoLoading, GeoQuote, GeoTable } from './shared'
import { saveBlobToDisk } from '../lib/save-to-disk'

/** 报告证据来源枚举 → 业务文字（后端 reasoning.py / prompts.py 固定写 ["ai_answer"]） */
const REPORT_SCOPE_LABEL: Record<string, string> = { ai_answer: 'AI 回答（监测证据）' }
const reportScopeText = (value: string) => REPORT_SCOPE_LABEL[value] ?? `其他来源（${value}）`

/** 阶段报告卡：自动配置/监测整体状态汇总 + 导出 */
export function GeoReportCard() {
  const [status, setStatus] = useState<GeoOnboardStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<{ company?: string; created_at?: string; report?: GeoReport | null } | null>(null)
  const [generating, setGenerating] = useState(false)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, latest] = await Promise.all([geoGet<GeoOnboardStatus>('/onboard/status'), geoGet<{ company?: string; created_at?: string; report?: GeoReport | null }>('/intelligence/reports/latest').catch(() => null)])
      setStatus(s)
      setReport(latest)
    } catch (e) {
      setError(e instanceof Error ? e.message : '报告加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  if (loading) return <GeoLoading text="阶段报告加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  const exportReport = async () => {
    setExporting(true)
    setError(null)
    try {
      // 真实 PDF 路由是 v1 的 /intelligence/reports/latest/pdf（2026-08-15 新增）；
      // 走 geoDownload 才既用得上产品门基址，又不会被「200 + JSON 暂无报告」骗成一个假 .pdf。
      const blob = await geoDownload('/intelligence/reports/latest/pdf')
      await saveBlobToDisk(blob, `GEO-AI认知报告-${new Date().toISOString().slice(0, 10)}.pdf`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const generateReport = async () => {
    setGenerating(true); setError(null)
    try { const d = await geoPost<{ skipped?: string }>('/intelligence/reports/run', { days: 30 }); if (d.skipped) setError('报告刚刚生成过，请稍后再试。'); else await load() }
    catch (e) { setError(e instanceof Error ? e.message : '报告生成失败') } finally { setGenerating(false) }
  }

  // 三种「素材」不是一回事，分开如实报（2026-09-20 修标签错位）：
  // 企业资料来自企业知识库（GEO 只读，读到的留在自己的快照表里），
  // GEO 素材库是 GEO 自己的内容资产，监测对象是 GEO 在监测谁。
  // 后端在还没建过报告时会把公司名写成 "unknown"，直接当标题显示等于把占位符给用户看（2026-09-21 修）
  const body = report?.report ?? null
  const reportCompany = (body?.company ?? '').trim() || ((report?.company ?? '').trim() === 'unknown' ? '' : (report?.company ?? '').trim())

  const knowledge = status?.knowledge
  const knowledgeLine = !knowledge
    ? '未检测'
    : knowledge.read_ever
      ? `历史快照 · 曾读取知识对象 ${knowledge.objects_seen} / 文档 ${knowledge.documents_seen}`
      : '尚未读取知识库'

  return (
    <GeoCardShell title="阶段成果摘要" className="geo-report-workbench">
      <GeoList
        items={[
          { title: '企业知识历史快照', meta: knowledgeLine },
          { title: 'GEO 素材库', meta: `${status?.materials ?? 0} 个` },
          { title: '监测对象', meta: `${status?.items ?? 0} 个` },
          { title: '客户问题池', meta: `${status?.questions ?? 0} 个` },
        ]}
      />
      {knowledge ? (
        <p className="pt-1 text-[11px] text-[var(--yayu-muted)]">
          {knowledge.read_ever
            ? `这里只记录 GEO 历史上读到过什么，不代表知识库当前仍有这些资料；删除或退休正本不会删除历史快照${knowledge.last_read_at ? `，最后读取 ${knowledge.last_read_at.slice(0, 10)}` : ''}。`
            : 'GEO 还没从企业知识库读到过内容；GEO 只读知识库，不写。'}
        </p>
      ) : null}
      <div className="latest-report">
        <div>
          <span>最新周期报告</span>
          <b>{body ? (reportCompany ? `${reportCompany} · 企业 AI 可见性报告` : '企业 AI 可见性报告') : '尚未生成'}</b>
          <small>{report?.created_at ? `生成于 ${report.created_at.slice(0, 16).replace('T', ' ')}` : '生成后可查看管理摘要并导出 PDF'}</small>
        </div>
        {body ? <ReportBody report={body} /> : null}
      </div>
      <GeoButtonRow>
        <Button variant="secondary" size="sm" disabled={generating} onClick={() => void generateReport()}><RefreshCw className={`size-3.5 ${generating?'animate-spin':''}`} />{generating?'生成中…':'生成本期报告'}</Button>
        <Button size="sm" disabled={exporting} onClick={() => void exportReport()}>
          <Download className="size-3.5" /> {exporting ? '生成中…' : '导出 PDF 报告'}
        </Button>
      </GeoButtonRow>
      {error ? <p className="pt-1 text-[11px] text-[var(--yayu-muted)]">{error}</p> : null}
    </GeoCardShell>
  )
}

/* ── 周期报告正文（2026-09-21）────────────────────────────────────────────
   后端把整份报告作为一个 JSON 对象存下来（report_json），字段口径见
   apps/api/app/services/report_pdf.py 的渲染逻辑。原来这一块是把整个 JSON
   截 1800 字丢在用户面前；现在按章节翻译成诊断结论、品牌对比、认知标签、
   竞品原因、认知偏差、知识缺口、内容建议。
   报告本身就是 LLM 生成的自由结构，所以这里对缺字段只做「不显示」，不猜。 */
interface GeoReportBrand {
  brand?: string
  name?: string
  mention_count?: number
  mentions?: number
  exposure_rate?: number
  recommendation_rate?: number
}
interface GeoReport {
  schema_version?: string
  company?: string | null
  period_days?: number
  source_scope?: string[]
  model?: string
  prompt_version?: string
  diagnosis?: string
  perception?: { tags?: Array<{ tag?: string; share?: number }> }
  brand_overview?: { total_evidence?: number; self_name?: string; brands?: GeoReportBrand[] }
  capability_gap?: { external_perceives?: string[] }
  gap_matrix?: Array<{ dimension?: string; factor?: string; competitor?: string; us?: string }>
  why_competitors_win?: Array<{ competitor?: string; brand?: string; reason?: string; summary?: string }>
  knowledge_gaps?: Array<{ dimension?: string; competitor?: string; suggestion?: string }>
  actions?: Array<{ priority?: number; task?: string; angle?: string; reason?: string }>
  missing?: unknown[]
  keywords?: unknown[]
}

/** 自由结构里的可见文字：命中业务键就取，取不到就整条不显示，不把字段名漏给用户 */
const reportText = (value: unknown): string => {
  if (value == null) return ''
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (typeof value === 'object') {
    const row = value as Record<string, unknown>
    for (const key of ['question', 'keyword', 'factor', 'dimension', 'brand', 'task', 'topic', 'text', 'name', 'suggestion', 'quote']) {
      const hit = row[key]
      if (typeof hit === 'string' && hit.trim()) return hit.trim()
    }
  }
  return ''
}

function ReportBody({ report }: { report: GeoReport }) {
  const tags = report.perception?.tags ?? []
  const brands = report.brand_overview?.brands ?? []
  const gaps = report.gap_matrix ?? []
  const bias = gaps.filter((row) => (row.us ?? '') && (row.competitor ?? '') && row.us !== row.competitor)
  const reasons = report.why_competitors_win ?? []
  const knowledgeGaps = report.knowledge_gaps ?? []
  const actions = report.actions ?? []
  const missing = (report.missing ?? []).map(reportText).filter(Boolean)
  const keywords = (report.keywords ?? []).map(reportText).filter(Boolean)
  const period = report.period_days ? `统计周期 ${report.period_days} 天` : ''
  // 2026-09-21：source_scope 是证据来源枚举（后端固定 ai_answer = 监测到的 AI 回答），
  // 页面上不打印英文代号（原来显示「来源 ai_answer」）。
  const scope = report.source_scope?.length ? `来源 ${report.source_scope.map(reportScopeText).join(' / ')}` : ''
  const meta = [period, scope, report.model ? `模型 ${report.model}` : '', report.prompt_version ? `提示词 v${report.prompt_version}` : ''].filter(Boolean).join(' · ')

  return (
    <div className="report-body">
      <div className="geo-subhead"><h3>诊断结论</h3><small>{meta}</small></div>
      <GeoQuote>{report.diagnosis || '这份报告没有给出诊断结论（通常是监测证据不足）。'}</GeoQuote>

      <GeoKpis
        items={[
          { label: '分析的回答', value: `${report.brand_overview?.total_evidence ?? 0} 条`, detail: '报告引用的 AI 回答数' },
          { label: '认知标签', value: `${tags.length} 个`, detail: 'AI 回答里出现的认知词', tone: tags.length ? 'good' : 'warn' },
          { label: '认知偏差', value: `${bias.length} 处`, detail: '我方与竞品被提及方式不一致', tone: bias.length ? 'warn' : 'good' },
          { label: '知识缺口（报告口径）', value: `${knowledgeGaps.length} 个`, detail: '竞品有、我方缺的能力——与「增长行动 → 知识缺口」不是同一个东西' },
        ]}
      />

      {brands.length ? (
        <>
          <div className="geo-subhead"><h3>品牌提及对比</h3><small>{report.brand_overview?.self_name ? `我方登记名 ${report.brand_overview.self_name}` : 'AI 回答里的品牌出现次数'}</small></div>
          <GeoTable
            columns={['品牌', '提及', '曝光率', '推荐率']}
            template="minmax(0,1.4fr) 64px 74px 74px"
            rows={brands.map((row) => [
              <b>{row.brand ?? row.name ?? '未具名'}</b>,
              <em>{row.mention_count ?? row.mentions ?? '—'}</em>,
              <em>{row.exposure_rate == null ? '—' : `${row.exposure_rate}%`}</em>,
              <em>{row.recommendation_rate == null ? '—' : `${row.recommendation_rate}%`}</em>,
            ])}
          />
        </>
      ) : null}

      {tags.length ? (
        <>
          <div className="geo-subhead"><h3>AI 眼中的认知标签</h3><small>占比越高说明这个印象越强</small></div>
          <GeoBars
            items={tags.slice(0, 8).map((row) => ({
              label: row.tag ?? '未命名标签',
              value: Math.round((row.share ?? 0) * 1000) / 10,
              text: `${Math.round((row.share ?? 0) * 1000) / 10}%`,
            }))}
          />
        </>
      ) : null}

      {reasons.length ? (
        <>
          <div className="geo-subhead"><h3>AI 为什么推荐竞品</h3><small>报告给出的原因</small></div>
          <GeoTable
            columns={['竞品', '原因']}
            template="minmax(0,110px) minmax(0,2fr)"
            rows={reasons.slice(0, 6).map((row) => [
              <b>{row.competitor ?? row.brand ?? '竞品'}</b>,
              <em>{row.reason ?? row.summary ?? '报告没写原因'}</em>,
            ])}
          />
        </>
      ) : null}

      {bias.length ? (
        <>
          <div className="geo-subhead"><h3>认知偏差</h3><small>同一维度上竞品与我方被提到的说法不同</small></div>
          <GeoTable
            columns={['维度', '竞品说法', '我方说法']}
            template="minmax(0,1fr) minmax(0,1fr) minmax(0,1fr)"
            rows={bias.slice(0, 6).map((row) => [
              <b>{row.dimension ?? row.factor ?? '—'}</b>,
              <em>{row.competitor}</em>,
              <em>{row.us}</em>,
            ])}
          />
        </>
      ) : null}

      {report.capability_gap?.external_perceives?.length ? (
        <>
          <div className="geo-subhead"><h3>外部怎么感知我们</h3><small>来自公开信息的说法</small></div>
          <ul className="geo-lines">
            {report.capability_gap.external_perceives.slice(0, 6).map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        </>
      ) : null}

      {knowledgeGaps.length ? (
        <>
          {/* 2026-09-21：这份报告里的「知识缺口」和「增长行动 → 知识缺口」是同名不同物——
              这里是模型读完监测证据后自己写的能力差距，上面 KPI 已经标明「报告口径」，
              正文章节也跟上，免得用户拿两边的数字对账。 */}
          <div className="geo-subhead"><h3>知识缺口（报告口径）</h3><small>竞品有、我方缺的能力 · 与「增长行动 → 知识缺口」不是同一个东西</small></div>
          <GeoTable
            columns={['维度', '竞品', '补法']}
            template="minmax(0,1fr) 110px minmax(0,1.6fr)"
            rows={knowledgeGaps.slice(0, 8).map((row) => [
              <b>{row.dimension ?? '—'}</b>,
              <em>{row.competitor ?? '—'}</em>,
              <em>{row.suggestion ?? '报告没给补法'}</em>,
            ])}
          />
        </>
      ) : null}

      {actions.length ? (
        <>
          <div className="geo-subhead"><h3>内容建设建议</h3><small>按优先级排序</small></div>
          <GeoTable
            columns={['优先级', '做什么', '从哪个角度', '为什么']}
            template="58px minmax(0,1fr) minmax(0,1fr) minmax(0,1.2fr)"
            rows={actions.slice(0, 8).map((row) => [
              <b>{`P${row.priority ?? 1}`}</b>,
              <b>{row.task ?? '—'}</b>,
              <em>{row.angle ?? '—'}</em>,
              <em>{row.reason ?? '—'}</em>,
            ])}
          />
        </>
      ) : null}

      {missing.length ? (
        <>
          <div className="geo-subhead"><h3>还没有覆盖的问题</h3><small>AI 回答里我方缺席的提问</small></div>
          <ul className="geo-lines">
            {missing.slice(0, 8).map((line, index) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
          {missing.length > 8 ? <p className="geo-note">另有 {missing.length - 8} 条未展开。</p> : null}
        </>
      ) : null}

      {keywords.length ? (
        <>
          <div className="geo-subhead"><h3>报告提到的关键词</h3><small>下一轮内容该围绕的词</small></div>
          <p className="geo-note">{keywords.slice(0, 16).join('、')}</p>
        </>
      ) : null}

      {!tags.length && !brands.length && !actions.length && !knowledgeGaps.length ? (
        <div className="geo-empty">这份报告正文里没有可用条目（诊断结论见上），等监测积累到足够回答后重新生成本期报告。</div>
      ) : null}
    </div>
  )
}
