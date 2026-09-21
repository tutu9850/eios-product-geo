import { useEffect, useState } from 'react'
import { AlertTriangle, ArrowRight, CheckCircle2, Minus, RefreshCw, ShieldCheck } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoGet, geoPost } from './geo-api'
import { GeoError, GeoLoading, useGeoNav } from './shared'

/** V2 认知评估结构（:3002 /distill/cognition/profile 返回） */
interface CognitionV2 {
  total: number
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
}

/** 认知健康 8 维度（报告 01）结构 */
interface HealthDim {
  key: string
  label: string
  score: number
  basis: string
}

interface HealthResult {
  total: number
  dims: HealthDim[]
  note?: string
}

/** AI 认知卡（升级自认知评估）：8 维度健康度 + 认知画像 + 维度矩阵 + 错误认知 + 官网分析（空态） */
export function GeoCognitionCard() {
  const [profile, setProfile] = useState<CognitionV2 | null>(null)
  const [health, setHealth] = useState<HealthResult | null>(null)
  const [portrait, setPortrait] = useState<{ items: PortraitItem[]; ai_health: number | null; note?: string } | null>(null)
  const [loading, setLoading] = useState(true)
  const [evaluating, setEvaluating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [d, h, p] = await Promise.all([
        geoGet<CognitionV2>('/distill/cognition/profile'),
        geoGet<HealthResult>('/cognition/health'),
        geoGet<{ items: PortraitItem[]; ai_health: number | null; note?: string }>('/cognition/portrait'),
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
    void load()
  }, [])

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
  const dims = health?.dims ?? []

  const metricItems = [
    ['品牌认知', profile?.metrics.awareness], ['理解准确', profile?.metrics.understanding],
    ['推荐意愿', profile?.metrics.recommendation], ['幻觉风险', profile?.metrics.hallucination],
  ] as const
  return <div className="cognition-workbench">
    <header className="cognition-head"><div><span>BRAND PERCEPTION</span><h1>AI 如何理解你的企业</h1><p>从国产大模型的真实回答中，识别稳定认知、缺失认知和错误认知。</p></div><Button disabled={evaluating} onClick={() => void runEvaluate()}><RefreshCw className={`size-3.5 ${evaluating ? 'animate-spin' : ''}`} />{evaluating ? '评估中…' : '重新评估'}</Button></header>
    <section className="cognition-summary"><div className="health-score"><span>认知健康度</span><strong>{total ?? '—'}</strong><small>{total == null ? '等待监测数据' : total >= 70 ? '整体认知稳定' : total >= 40 ? '存在明显差距' : '需要优先治理'}</small></div>{metricItems.map(([label, value]) => <div className="cognition-kpi" key={label}><span>{label}</span><strong>{value == null ? '—' : `${Math.round(value)}%`}</strong><i><em style={{ width: `${value ?? 0}%` }} /></i></div>)}</section>
    <div className="cognition-layout"><section className="cognition-panel dimension-panel"><header><div><h2>八维认知表现</h2><p>分数越低，越需要补充权威事实或公开证据</p></div><span className="cognition-legend">真实监测结果</span></header><div className="dimension-grid">{dims.map((d) => <article key={d.key}><div><span>{d.label}</span><strong>{d.score}</strong></div><i><em data-score={d.score >= 70 ? 'good' : d.score >= 40 ? 'mid' : 'low'} style={{ width: `${Math.min(100,d.score)}%` }} /></i><p>{d.basis}</p></article>)}</div></section>
      <aside className="cognition-panel verdict-panel"><header><div><h2>本期判断</h2><p>给业务团队的直接结论</p></div></header><div className="verdict"><ShieldCheck /><div><b>{total !== null && total >= 70 ? '核心定位已形成稳定认知' : '核心认知尚未完全建立'}</b><p>{health?.note ?? '持续监测并补齐低分维度的事实与证据。'}</p></div></div><div className="verdict"><AlertTriangle /><div><b>{profile?.errors.length ?? 0} 条错误认知待处理</b><p>优先修正影响购买决策或企业可信度的错误信息。</p></div></div></aside>
    </div>
    <section className="cognition-panel portrait-panel"><header><div><h2>企业资料与 AI 认知偏差</h2><p>资料中已经明确表达，但模型仍未正确理解的内容</p></div></header><div className="portrait-table"><div className="portrait-row portrait-header"><span>认知维度</span><span>企业正式资料</span><span>AI 当前状态</span><span>判断</span></div>{portrait?.items.map((row) => <div className="portrait-row" key={row.key}><b>{row.label}</b><span>{row.profile || '暂无正式资料'}</span><span>{row.ai_status} · {row.ai_grounded}/{row.ai_claims}</span>{/* 2026-09-21：「未评估」不是问题，别给它挂警示三角；只有真出现偏差才提示。 */}
                <em data-ok={row.deviation === '一致'}>
                  {row.deviation === '一致' ? <CheckCircle2 /> : row.deviation === '未评估' ? <Minus /> : <AlertTriangle />}
                  {row.deviation}
                </em></div>)}</div></section>
    <div className="cognition-layout bottom"><section className="cognition-panel matrix-panel"><header><div><h2>认知证据构成</h2><p>正确、部分正确与幻觉内容的占比</p></div></header>{profile?.matrix.map((row) => <div className="matrix-row" key={row.key}><span>{row.label}</span><i><em className="grounded" style={{ width: `${row.grounded/Math.max(1,row.claims)*100}%` }} /><em className="partial" style={{ width: `${row.partial/Math.max(1,row.claims)*100}%` }} /><em className="hallucination" style={{ width: `${row.hallucination/Math.max(1,row.claims)*100}%` }} /></i><b>{row.status}</b></div>)}</section><section className="cognition-panel errors-panel"><header><div><h2>错误认知</h2><p>点一条直接带进内容生成，主题就是这句要纠正的说法</p></div></header>{profile?.errors.length ? profile.errors.slice(0,4).map((item,index) => <button key={index} onClick={()=>go?.('content',{seed:item.claim})} title="用它作为主题去生成纠正内容"><span>{item.claim}</span><small>{item.engine} · {item.question}</small><ArrowRight /></button>) : <div className="cognition-empty"><CheckCircle2 />当前没有检测到明确错误认知</div>}</section></div>
  </div>
}
