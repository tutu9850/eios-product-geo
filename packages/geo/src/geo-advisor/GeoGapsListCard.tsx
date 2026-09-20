import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoGet, geoPost, type GeoGap } from './geo-api'
import { GeoCardShell, GeoError, GeoList, GeoLoading } from './shared'

/** 缺口影响×紧急度（规则：关键词映射客户阶段 + 优先级） */
function gapPriority(g: GeoGap): { level: 'P0' | 'P1' | 'P2'; stage: string } {
  const t = `${g.question} ${g.missing_information ?? ''} ${g.source ?? ''}`
  if (/价格|报价|费用|预算|成本|多少钱/.test(t)) return { level: 'P0', stage: '价格' }
  if (/案例|效果|实景|作品|口碑/.test(t)) return { level: 'P0', stage: '案例' }
  if (/资质|团队|专业|认证|证书/.test(t)) return { level: 'P1', stage: '信任' }
  return { level: 'P2', stage: '认知' }
}

const LEVEL_ORDER: Record<string, number> = { P0: 0, P1: 1, P2: 2 }

/** 知识缺口卡：重新生成缺口（重新分析）+ 列表展示（含影响×紧急度） */
export function GeoGapsListCard() {
  const [items, setItems] = useState<GeoGap[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [regenerating, setRegenerating] = useState(false)
  const [regenerateMsg, setRegenerateMsg] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await geoGet<{ items: GeoGap[]; total: number }>('/distill/gaps?limit=50')
      setItems(d.items)
    } catch (e) {
      setError(e instanceof Error ? e.message : '知识缺口加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const regenerate = async () => {
    setRegenerating(true)
    setRegenerateMsg(null)
    try {
      const d = await geoPost<{ added: number; total: number; plans_added: number }>('/distill/gaps')
      setRegenerateMsg(`重新分析完成：新增 ${d.added} 个缺口，共 ${d.total} 个`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '重新生成失败')
    } finally {
      setRegenerating(false)
    }
  }

  if (loading) return <GeoLoading text="知识缺口加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  return (
    <GeoCardShell title="🧩 知识缺口（回答客户问题缺的资料）">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void regenerate()} disabled={regenerating}>
          <RefreshCw className={`size-3.5 ${regenerating ? 'animate-spin' : ''}`} /> {regenerating ? '分析中…' : '重新筛选'}
        </Button>
        {regenerateMsg ? <span className="text-[11px] text-[var(--yayu-muted)]">{regenerateMsg}</span> : null}
      </div>
      {!items || items.length === 0 ? (
        <p className="text-[12px] text-[var(--yayu-muted)]">暂无缺口，点「重新筛选」分析一次。</p>
      ) : (
        <GeoList
          items={[...items]
            .sort((a, b) => LEVEL_ORDER[gapPriority(a).level] - LEVEL_ORDER[gapPriority(b).level])
            .map((g) => {
              const p = gapPriority(g)
              return {
                title: g.question,
                desc: g.matched_refs?.length
                  ? `相关素材：${g.matched_refs.map((r) => r.name).slice(0, 2).join('、')}`
                  : g.source
                    ? `来源：${g.source}`
                    : undefined,
                meta: `${p.level} · ${p.stage}阶段 · 检索 ${Math.round((g.retrieval_score ?? 0) * 100)}%`,
              }
            })}
        />
      )}
    </GeoCardShell>
  )
}
