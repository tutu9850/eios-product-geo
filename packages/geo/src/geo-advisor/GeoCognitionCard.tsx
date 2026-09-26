import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, Minus, RefreshCw, ShieldCheck } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoGet, geoPost } from './geo-api'
import { GeoError, GeoLoading, useGeoNav } from './shared'
import { MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'

/** V2 认知评估结构（:3002 /distill/cognition/profile 返回） */
interface CognitionV2 {
  total: number
  evaluated_at?: string | null
  health: number | null
  metrics: {
    awareness: number | null
    understanding: number | null
    hallucination: number | null
    recommendation: number | null
  }
  matrix: Array<{
    key: string
    label: string
    claims: number
    grounded: number
    partial: number
    hallucination: number
    status: string
  }>
  errors: Array<{ claim: string; type: string; engine: string; question: string }>
  note?: string
}

/** 认知画像（资料 vs AI + 偏差）结构 */
interface PortraitItem {
  key: string
  label: string
  profile: string
  ai_status: string
  ai_grounded: number
  ai_claims: number
  deviation: string
  evidence_count: number
  evidence?: Array<{ id?: string; title: string }>
}

/** 认知健康 8 维度（报告 01）结构 */
interface HealthDim {
  key: string
  label: string
  score: number | null
  basis: string
}

interface HealthResult {
  total: number | null
  dims: HealthDim[]
  sample_size?: number
  subject_status?: 'confirmed' | 'pending'
  subject_name?: string | null
  subject_error?: string | null
  scope_mode?: string
  evaluation_scope?: string
  evaluated_at?: string | null
  note?: string
}

/** AI 认知卡（升级自认知评估）：8 维度健康度 + 认知画像 + 维度矩阵 + 错误认知 + 官网分析（空态） */
export function GeoCognitionCard() {
  const [profile, setProfile] = useState<CognitionV2 | null>(null)
  const [health, setHealth] = useState<HealthResult | null>(null)
  const [portrait, setPortrait] = useState<{ items: PortraitItem[]; ai_health: number | null; material_count?: number; evaluated_at?: string | null; note?: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [evaluating, setEvaluating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { query: subjectQuery, loaded: subjectsLoaded } = useMonitorSubject()

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [d, h, p] = await Promise.all([
        geoGet<CognitionV2>('/distill/cognition/profile'),
        geoGet<HealthResult>(`/cognition/health${subjectQuery ? `?${subjectQuery}` : ''}`),
        geoGet<{ items: PortraitItem[]; ai_health: number | null; material_count?: number; evaluated_at?: string | null; note?: string }>('/cognition/portrait'),
      ])
      setProfile(d)
      setHealth(h)
      setPortrait(p)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'AI 认知加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!subjectsLoaded) return
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subjectsLoaded, subjectQuery])

  const runEvaluate = async () => {
    setEvaluating(true)
    setError(null)
    try {
      await geoPost('/distill/cognition/evaluate')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '评估失败')
    } finally {
      setEvaluating(false)
    }
  }

  if (loading) return <GeoLoading text="AI 认知加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  const go = useGeoNav()
  const total = health?.total ?? null
  const assessmentAvailable = (health?.sample_size ?? 0) > 0 && health?.subject_status !== 'pending'
  const errorsAvailable = (profile?.total ?? 0) > 0 && health?.subject_status !== 'pending'
  const dims = health?.dims ?? []
  const subjectLabel = health?.subject_name ?? null
  const subjectPendingNote = health?.subject_error ?? '主体待确认，请先在上方选择监测主体'
  const evaluatedAt = health?.evaluated_at ? new Date(health.evaluated_at).toLocaleString('zh-CN', { hour12: false }) : null

  const metricItems = [
    ['品牌认知', assessmentAvailable ? profile?.metrics.awareness : null], ['理解准确', assessmentAvailable ? profile?.metrics.understanding : null],
    ['推荐意愿', assessmentAvailable ? profile?.metrics.recommendation : null], ['幻觉风险', assessmentAvailable ? profile?.metrics.hallucination : null],
  ] as const
  return <div className="cognition-workbench">
    <header className="cognition-head"><div><span>品牌认知</span><h1>AI 如何理解你的企业</h1><p>从国产大模型的真实回答中，识别稳定认知、缺失认知和错误认知。</p></div><Button disabled={evaluating || health?.subject_status === 'pending'} title={health?.subject_status === 'pending' ? '请先在上方选择监测主体' : undefined} onClick={() => void runEvaluate()}><RefreshCw className={`size-3.5 ${evaluating ? 'animate-spin' : ''}`} />{evaluating ? '评估中…' : '重新评估'}</Button></header>
    <MonitorSubjectPicker />
    <p className="geo-note">{subjectLabel ? `当前主体：${subjectLabel}（来自上方「监测主体」；换主体后本页 8 个维度的提及样本按新主体重算）` : subjectPendingNote}</p>
    <section className="cognition-summary"><div className="health-score"><span>认知健康度</span><strong>{total ?? '—'}</strong><small>{health?.subject_status === 'pending' ? subjectPendingNote : !assessmentAvailable ? '暂无已完成的认知评估' : total == null ? '有效维度不足' : total >= 70 ? '整体认知稳定' : total >= 40 ? '存在明显差距' : '需要优先治理'}</small></div>{metricItems.map(([label, value]) => <div className="cognition-kpi" key={label}><span>{label}</span><strong>{value == null ? '—' : `${Math.round(value)}%`}</strong><i><em style={{ width: `${value ?? 0}%` }} /></i></div>)}</section>
    <div className="cognition-layout"><section className="cognition-panel dimension-panel"><header><div><h2>八维认知表现</h2><p>{assessmentAvailable ? `历史语义评估 ${health?.sample_size} 条${evaluatedAt ? ` · ${evaluatedAt}` : ''}；不保证与最近品牌批次一致` : health?.subject_status === 'pending' ? subjectPendingNote : '暂无已完成的认知评估'}</p></div><span className="cognition-legend">认知评估</span></header><div className="dimension-grid">{dims.map((d) => <article key={d.key}><div><span>{d.label}</span><strong>{assessmentAvailable && d.score != null ? d.score : '—'}</strong></div><i><em data-score={!assessmentAvailable || d.score == null ? 'empty' : d.score >= 70 ? 'good' : d.score >= 40 ? 'mid' : 'low'} style={{ width: `${!assessmentAvailable || d.score == null ? 0 : Math.min(100,d.score)}%` }} /></i><p>{d.basis}</p></article>)}</div></section>
      <aside className="cognition-panel verdict-panel"><header><div><h2>本期判断</h2><p>给业务团队的直接结论</p></div></header><div className="verdict"><ShieldCheck /><div><b>{!assessmentAvailable ? health?.subject_status === 'pending' ? subjectPendingNote : '暂无可用认知评估' : total !== null && total >= 70 ? '核心定位已形成稳定认知' : '核心认知尚未完全建立'}</b><p>{health?.note ?? '需要有效认知评估后才能形成判断。'}</p></div></div><div className="verdict"><AlertTriangle /><div><b>{errorsAvailable ? `${profile?.errors.length ?? 0} 条错误认知待处理` : '尚未评估错误认知'}</b><p>{errorsAvailable ? '优先修正影响购买决策或企业可信度的错误信息。' : '当前样本不足以判断是否存在错误认知。'}</p></div></div></aside>
    </div>
    <section className="cognition-panel portrait-panel"><header><div><h2>GEO 内容资产与 AI 认知偏差</h2><p>{portrait?.material_count ? `当前 ${portrait.material_count} 份 GEO 内容资产；与同一批 AI 认知评估对照` : '当前没有 GEO 内容资产，不判断资料覆盖情况'}</p></div></header><div className="portrait-table"><div className="portrait-row portrait-header"><span>认知维度</span><span>当前 GEO 内容资产</span><span>AI 当前状态</span><span>判断</span></div>{portrait?.items.map((row) => <div className="portrait-row" key={row.key}><b>{row.label}</b><span title={row.evidence?.map((item) => item.title).join('、')}>{row.profile}</span><span>{row.ai_status} · {row.ai_grounded}/{row.ai_claims}</span>{/* 2026-09-21：「未评估」不是问题，别给它挂警示三角；只有真出现偏差才提示。 */}
                <em data-ok={row.deviation === '一致'}>
                  {row.deviation === '一致' ? <CheckCircle2 /> : row.deviation === '未评估' ? <Minus /> : <AlertTriangle />}
                  {row.deviation}
                </em></div>)}</div></section>
    <div className="cognition-layout bottom"><section className="cognition-panel matrix-panel"><header><div><h2>认知证据构成</h2><p>{assessmentAvailable ? '正确、部分正确与幻觉内容的占比' : '暂无可用评估样本'}</p></div></header>{assessmentAvailable ? profile?.matrix.filter((row) => row.claims > 0).map((row) => <div className="matrix-row" key={row.key}><span>{row.label}</span><i><em className="grounded" style={{ width: `${row.grounded/row.claims*100}%` }} /><em className="partial" style={{ width: `${row.partial/row.claims*100}%` }} /><em className="hallucination" style={{ width: `${row.hallucination/row.claims*100}%` }} /></i><b>{row.status}</b></div>) : <div className="cognition-empty"><Minus />尚未评估，无法判断认知正确率</div>}</section><section className="cognition-panel errors-panel"><header><div><h2>错误认知</h2><p>点一条直接带进内容生成，主题就是这句要纠正的说法</p></div></header>{profile?.errors.length && errorsAvailable ? profile.errors.slice(0,4).map((item,index) => <button key={index} onClick={()=>go?.('content',{seed:item.claim})} title="用它作为主题去生成纠正内容"><span>{item.claim}</span><small>{item.engine} · {item.question}</small><ArrowRight /></button>) : <div className="cognition-empty"><Minus />尚未评估，无法判断是否存在错误认知</div>}</section></div>
  </div>
}
