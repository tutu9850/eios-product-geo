import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, Minus, RefreshCw, ShieldCheck } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoGet, geoPost } from './geo-api'
import { GeoError, GeoLoading, useGeoDemoMode, useGeoNav } from './shared'
import { MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'
import { GEO_DEMO_COGNITION_PROFILE, GEO_DEMO_HEALTH, GEO_DEMO_NOTICE, GEO_DEMO_PORTRAIT } from './demo-fixtures'

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

/** 认知画像（资料 vs 模型回答 + 偏差）结构 */
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

/** 模型认知卡：8 个认知方面 + 认知画像 + 证据构成 + 错误认知 */
export function GeoCognitionCard() {
  const { enabled: demoMode } = useGeoDemoMode()
  const [profile, setProfile] = useState<CognitionV2 | null>(null)
  const [health, setHealth] = useState<HealthResult | null>(null)
  const [portrait, setPortrait] = useState<{ items: PortraitItem[]; ai_health: number | null; material_count?: number; evaluated_at?: string | null; note?: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [evaluating, setEvaluating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const loadSeq = useRef(0)
  const { query: subjectQuery, loaded: subjectsLoaded } = useMonitorSubject()

  const load = async () => {
    const requestId = ++loadSeq.current
    setLoading(true)
    setError(null)
    try {
      if (demoMode) {
        setProfile(GEO_DEMO_COGNITION_PROFILE as CognitionV2)
        setHealth(GEO_DEMO_HEALTH as HealthResult)
        setPortrait(GEO_DEMO_PORTRAIT as { items: PortraitItem[]; ai_health: number | null; material_count?: number; evaluated_at?: string | null; note?: string })
        return
      }
      setProfile(null)
      setHealth(null)
      setPortrait(null)
      const [d, h, p] = await Promise.all([
        geoGet<CognitionV2>('/distill/cognition/profile'),
        geoGet<HealthResult>(`/cognition/health${subjectQuery ? `?${subjectQuery}` : ''}`),
        geoGet<{ items: PortraitItem[]; ai_health: number | null; material_count?: number; evaluated_at?: string | null; note?: string }>('/cognition/portrait'),
      ])
      if (requestId !== loadSeq.current) return
      setProfile(d)
      setHealth(h)
      setPortrait(p)
    } catch (e) {
      if (requestId === loadSeq.current) setError(e instanceof Error ? e.message : '认知结果加载失败')
    } finally {
      if (requestId === loadSeq.current) setLoading(false)
    }
  }

  useEffect(() => { if (demoMode || subjectsLoaded) void load() }, [demoMode, subjectsLoaded, subjectQuery])

  const runEvaluate = async () => {
    if (demoMode) return
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

  if (loading) return <GeoLoading text="认知结果加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  const go = useGeoNav()
  const total = health?.total ?? null
  const assessmentAvailable = (health?.sample_size ?? 0) > 0 && health?.subject_status !== 'pending'
  const errorsAvailable = (profile?.total ?? 0) > 0 && health?.subject_status !== 'pending'
  const dims = health?.dims ?? []
  const subjectLabel = health?.subject_name ?? null
  const subjectPendingNote = health?.subject_error ?? '主体待确认，请先在上方选择监测主体'
  const evaluatedAt = health?.evaluated_at ? new Date(health.evaluated_at).toLocaleString('zh-CN', { hour12: false }) : null
  const weakestDim = dims.filter((dim) => dim.score != null).sort((a, b) => Number(a.score) - Number(b.score))[0]
  const verdictNote = demoMode
    ? weakestDim
      ? `当前最低的是「${weakestDim.label}」（${weakestDim.score}），优先补齐相关资料后再复测。`
      : '当前样本只用于说明判断方式，关闭演示数据后才能评估真实主体。'
    : health?.note ?? '需要有效认知评估后才能形成判断。'

  const metricItems = [
    ['品牌认知', assessmentAvailable ? profile?.metrics.awareness : null], ['理解准确', assessmentAvailable ? profile?.metrics.understanding : null],
    ['推荐意愿', assessmentAvailable ? profile?.metrics.recommendation : null], ['模型无依据风险', assessmentAvailable ? profile?.metrics.hallucination : null],
  ] as const
  return <div className="cognition-workbench">
    <header className="cognition-head"><div><span>品牌认知</span><h1>模型如何理解你的企业</h1><p>从国产大模型的真实回答中，识别稳定理解、缺失信息和需要核对的说法。</p></div><Button disabled={evaluating || demoMode || health?.subject_status === 'pending'} title={demoMode ? '演示数据不会执行真实评估；关闭演示模式后才能操作' : health?.subject_status === 'pending' ? '请先在上方选择监测主体' : undefined} onClick={() => void runEvaluate()}><RefreshCw className={`size-3.5 ${evaluating ? 'animate-spin' : ''}`} />{evaluating ? '评估中…' : assessmentAvailable ? '重新评估' : '开始认知评估'}</Button></header>
    {demoMode && <div className="geo-demo-banner"><AlertTriangle /><span><b>内测演示数据已开启</b>　{GEO_DEMO_NOTICE}</span></div>}
    {demoMode ? <div className="geo-demo-subject"><span>演示主体</span><b>云栖示例家居</b><small>演示夹具固定主体；关闭演示模式后才能按监测对象筛选。</small></div> : <MonitorSubjectPicker />}
    {!demoMode ? <p className="geo-note">{subjectLabel ? `当前主体：${subjectLabel}（来自上方「监测主体」；换主体后本页八个认知方面会按新主体重算）` : subjectPendingNote}</p> : null}
    <section className="cognition-summary"><div className="health-score"><span>品牌理解度</span><strong>{total ?? '—'}</strong><small>{health?.subject_status === 'pending' ? subjectPendingNote : !assessmentAvailable ? '暂无已完成的认知评估' : total == null ? '有效维度不足' : total >= 70 ? '整体认知稳定' : total >= 40 ? '存在明显差距（不等于曝光率）' : '需要优先治理（不等于曝光率）'}</small></div>{metricItems.map(([label, value]) => <div className="cognition-kpi" key={label}><span>{label}</span><strong>{value == null ? '—' : `${Math.round(value)}%`}</strong><i><em style={{ width: `${value ?? 0}%` }} /></i></div>)}</section>
    <div className="cognition-layout"><section className="cognition-panel dimension-panel"><header><div><h2>品牌被理解的八个方面</h2><p>{assessmentAvailable ? `过去回答评估 ${health?.sample_size} 条${evaluatedAt ? ` · ${evaluatedAt}` : ''}；不保证与最近品牌批次一致` : health?.subject_status === 'pending' ? subjectPendingNote : '完成一次评估后显示'}</p></div><span className="cognition-legend">评估结果</span></header>{assessmentAvailable ? <div className="dimension-grid">{dims.map((d) => <article key={d.key}><div><span>{d.label}</span><strong>{d.score != null ? d.score : '—'}</strong></div><i><em data-score={d.score == null ? 'empty' : d.score >= 70 ? 'good' : d.score >= 40 ? 'mid' : 'low'} style={{ width: `${d.score == null ? 0 : Math.min(100,d.score)}%` }} /></i><p>{d.basis}</p></article>)}</div> : <div className="cognition-empty cognition-start-state"><Minus /><b>{health?.subject_status === 'pending' ? subjectPendingNote : '还没有可用的认知评估'}</b><p>先完成一轮监测并让系统读懂回答；系统不会用“出现过品牌名”代替“正确理解品牌”。</p>{health?.subject_status !== 'pending' ? <button type="button" onClick={() => go?.('monitor')}>去运行监测</button> : null}</div>}</section>
      <aside className="cognition-panel verdict-panel"><header><div><h2>本期判断</h2><p>给业务团队的直接结论</p></div></header><div className="verdict"><ShieldCheck /><div><b>{!assessmentAvailable ? health?.subject_status === 'pending' ? subjectPendingNote : '暂无可用认知评估' : total !== null && total >= 70 ? '核心定位已形成稳定认知' : '核心认知尚未完全建立'}</b><p>{assessmentAvailable ? verdictNote : '完成监测并让系统读懂回答后，系统才会判断品牌认知、产品理解和需要核对的说法。'}</p></div></div><div className="verdict"><AlertTriangle /><div><b>{errorsAvailable ? `${profile?.errors.length ?? 0} 条需要核对的说法` : '尚未评估需要核对的说法'}</b><p>{errorsAvailable ? '优先修正影响购买决策或企业可信度的说法。' : '完成认知评估后，才会判断是否存在需要核对的说法。'}</p></div></div></aside>
    </div>
    <section className="cognition-panel portrait-panel"><header><div><h2>资料与模型回答对照</h2><p>{assessmentAvailable ? portrait?.material_count ? `当前 ${portrait.material_count} 份公开内容资产；与同一批模型回答对照` : '当前没有公开内容资产，不判断资料覆盖情况' : '完成认知评估后再比较，不先下结论'}</p></div></header>{assessmentAvailable ? <div className="portrait-table"><div className="portrait-row portrait-header"><span>理解方面</span><span>当前公开内容</span><span>模型回答情况</span><span>判断</span></div>{portrait?.items.map((row) => <div className="portrait-row" key={row.key}><b>{row.label}</b><span title={row.evidence?.map((item) => item.title).join('、')}>{row.profile}</span><span>{row.ai_status} · {row.ai_grounded}/{row.ai_claims}</span>{/* 2026-09-21：「未评估」不是问题，别给它挂警示三角；只有真出现偏差才提示。 */}
                <em data-ok={row.deviation === '一致'}>
                  {row.deviation === '一致' ? <CheckCircle2 /> : row.deviation === '未评估' ? <Minus /> : <AlertTriangle />}
                  {row.deviation}
                </em></div>)}</div> : <div className="cognition-empty"><Minus /><span>{portrait?.material_count ? `当前有 ${portrait.material_count} 份公开内容资产，但模型还没有完成认知评估。` : '当前没有公开内容资产。'}</span><small>评估完成后，这里才会比较资料是否被模型正确理解。</small></div>}</section>
    <div className="cognition-layout bottom"><section className="cognition-panel matrix-panel"><header><div><h2>证据是否充足</h2><p>{assessmentAvailable ? '有依据、部分有依据和无依据内容的占比' : '暂无可用评估样本'}</p></div></header>{assessmentAvailable ? profile?.matrix.filter((row) => row.claims > 0).map((row) => <div className="matrix-row" key={row.key}><span>{row.label}</span><i><em className="grounded" style={{ width: `${row.grounded/row.claims*100}%` }} /><em className="partial" style={{ width: `${row.partial/row.claims*100}%` }} /><em className="hallucination" style={{ width: `${row.hallucination/row.claims*100}%` }} /></i><b>{row.status}</b></div>) : <div className="cognition-empty"><Minus />尚未评估，无法判断说法是否有依据</div>}</section><section className="cognition-panel errors-panel"><header><div><h2>需要核对的说法</h2><p>{demoMode ? '演示模式只读；关闭后才能进入真实内容生成。' : '点一条直接带进内容生成，主题就是这句要核对的说法'}</p></div></header>{profile?.errors.length && errorsAvailable ? profile.errors.slice(0,4).map((item,index) => <button key={index} disabled={demoMode} onClick={()=>go?.('content',{seed:item.claim})} title={demoMode ? '演示模式只读；关闭演示模式后才能进入真实内容生成' : '用它作为主题去生成核对内容'}><span>{item.claim}</span><small>{item.engine} · {item.question}</small>{demoMode ? <ShieldCheck /> : <ArrowRight />}</button>) : <div className="cognition-empty"><Minus />尚未评估，无法判断是否存在需要核对的说法</div>}</section></div>
  </div>
}
