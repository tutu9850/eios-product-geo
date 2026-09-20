import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoGet, geoPost } from './geo-api'
import { GeoButtonRow, GeoCardShell, GeoError, GeoLoading } from './shared'

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

  const total = health?.total ?? null
  const dims = health?.dims ?? []

  return (
    <GeoCardShell title="🧠 AI 认知（8 维度健康度 + 画像 + 官网分析）">
      {/* 健康度总分 + 8 维度 */}
      <div className="flex items-center gap-3">
        <div
          className="flex size-14 shrink-0 flex-col items-center justify-center rounded-full border-4"
          style={{ borderColor: total !== null && total >= 70 ? 'var(--good)' : total !== null && total >= 40 ? 'var(--warn)' : 'var(--bad)' }}
        >
          <span className="text-base font-bold text-[var(--yayu-foreground)]">{total ?? '—'}</span>
          <span className="text-[9px] text-[var(--yayu-faint)]">健康度</span>
        </div>
        <div className="min-w-0 flex-1 space-y-1">
          {dims.map((d) => (
            <div key={d.key} className="flex items-center gap-2" title={d.basis}>
              <span className="w-14 shrink-0 text-[10.5px] text-[var(--yayu-muted)]">{d.label}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--yayu-surface-raised)]">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${Math.min(100, d.score)}%`, background: d.score >= 70 ? 'var(--good)' : d.score >= 40 ? 'var(--warn)' : 'var(--bad)' }}
                />
              </div>
              <span className="w-8 shrink-0 text-right text-[10.5px] text-[var(--yayu-foreground)]">{d.score}</span>
            </div>
          ))}
        </div>
      </div>
      {health?.note ? <p className="pt-0.5 text-[9.5px] text-[var(--yayu-faint)]">{health.note}</p> : null}
      {profile && profile.total === 0 ? (
        <p className="text-[11px] text-[var(--yayu-faint)]">暂无评估——先跑一次监测，再点「运行 AI 认知评估」。</p>
      ) : null}

      {/* 认知画像：资料侧 vs AI 侧 + 偏差 */}
      {portrait && portrait.items.length > 0 ? (
        <div className="pt-1">
          <div className="mb-1 text-[12px] font-medium text-[var(--yayu-foreground)]">认知画像（资料 vs AI）</div>
          <div className="space-y-1">
            {portrait.items.map((row) => (
              <div key={row.key} className="flex items-center gap-2">
                <span className="w-16 shrink-0 text-[11px] text-[var(--yayu-muted)]">{row.label}</span>
                <span className="min-w-0 flex-1 truncate text-[11px] text-[var(--yayu-foreground)]">{row.profile}</span>
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${
                  row.deviation === '一致'
                    ? 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-muted)]'
                    : row.deviation === '资料有但 AI 未认知'
                      ? 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-foreground)]'
                      : 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-faint)]'
                }`}>
                  {row.deviation}
                </span>
              </div>
            ))}
          </div>
          {portrait.note ? <p className="pt-0.5 text-[9.5px] text-[var(--yayu-faint)]">{portrait.note}</p> : null}
        </div>
      ) : null}

      {/* 维度矩阵 */}
      {profile && profile.matrix.length > 0 ? (
        <div className="pt-1">
          <div className="mb-1 text-[12px] font-medium text-[var(--yayu-foreground)]">认知维度矩阵</div>
          <div className="space-y-1">
            {profile.matrix.map((row) => (
              <div key={row.key} className="flex items-center gap-2">
                <span className="w-16 shrink-0 text-[11px] text-[var(--yayu-muted)]">{row.label}</span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--yayu-surface-raised)]">
                  <div className="flex h-full">
                    <div className="bg-[var(--good)]" style={{ width: `${(row.grounded / Math.max(1, row.claims)) * 100}%` }} />
                    <div className="bg-[var(--warn)]" style={{ width: `${(row.partial / Math.max(1, row.claims)) * 100}%` }} />
                    <div className="bg-[var(--bad)]" style={{ width: `${(row.hallucination / Math.max(1, row.claims)) * 100}%` }} />
                  </div>
                </div>
                <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${row.status === '已理解' ? 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-foreground)]' : row.status === '幻觉风险' ? 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-muted)]' : 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-muted)]'}`}>
                  {row.status}
                </span>
              </div>
            ))}
          </div>
          <p className="pt-0.5 text-[9.5px] text-[var(--yayu-faint)]">绿=已理解 · 黄=部分理解 · 红=幻觉风险（占比按 claim 数）</p>
        </div>
      ) : null}

      {/* 错误认知 */}
      {profile && profile.errors.length > 0 ? (
        <div className="pt-1">
          <div className="mb-1 text-[12px] font-medium text-[var(--yayu-muted)]">错误认知（AI 说错的）</div>
          <div className="space-y-1">
            {profile.errors.slice(0, 4).map((e, i) => (
              <div key={i} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1">
                <div className="text-[11px] text-[var(--yayu-foreground)]">{e.claim}</div>
                <div className="text-[9.5px] text-[var(--yayu-faint)]">
                  {e.type} · {e.engine} · {e.question}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* 官网分析（空态：客户提供官网资料后分析；无官网保留模块引导开发） */}
      <div className="rounded-lg border border-dashed border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
        <div className="text-[11px] font-medium text-[var(--yayu-muted)]">🌐 官网分析</div>
        <p className="mt-0.5 text-[10.5px] leading-relaxed text-[var(--yayu-faint)]">
          未提供官网资料，暂无法分析。上传官网介绍/页面资料后，可分析官网对 AI 认知的贡献（时效/缺失信息/影响维度）。
        </p>
      </div>

      <GeoButtonRow>
        <Button size="sm" disabled={evaluating} onClick={() => void runEvaluate()}>
          <RefreshCw className={`size-3.5 ${evaluating ? 'animate-spin' : ''}`} /> {evaluating ? '评估中…' : '运行 AI 认知评估'}
        </Button>
      </GeoButtonRow>
    </GeoCardShell>
  )
}
