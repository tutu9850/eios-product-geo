import { useCallback, useEffect, useState } from 'react'
import { RefreshCw, Trash2 } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoDelete, geoGet, geoPost, type GeoPlan } from './geo-api'
import { GeoCardShell, GeoError, GeoLoading } from './shared'

type Sort = 'priority' | 'created_at'

/** 内容计划卡：列表/排序/删除 + 从缺口一键生成（交互对齐 Builder GeoDistill 计划区） */
export function GeoPlansListCard() {
  const [items, setItems] = useState<GeoPlan[] | null>(null)
  const [sort, setSort] = useState<Sort>('priority')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [genMsg, setGenMsg] = useState<string | null>(null)
  const [confirmId, setConfirmId] = useState<string | null>(null)

  const load = useCallback(async (s: Sort = sort) => {
    setLoading(true)
    setError(null)
    try {
      const d = await geoGet<{ items: GeoPlan[]; total: number }>(`/distill/plans?limit=50&sort=${s}`)
      setItems(d.items)
    } catch (e) {
      setError(e instanceof Error ? e.message : '内容计划加载失败')
    } finally {
      setLoading(false)
    }
  }, [sort])

  useEffect(() => {
    void load()
  }, [load])

  const changeSort = (s: Sort) => {
    setSort(s)
    void load(s)
  }

  const generateFromGaps = async () => {
    setGenerating(true)
    setGenMsg(null)
    try {
      // from-gaps 必须带 body（哪怕是空对象），否则 FastAPI 报 422 missing body
      const d = await geoPost<{ added?: number; total?: number }>('/distill/plans/from-gaps', {})
      setGenMsg(`已从缺口生成内容计划${d?.added !== undefined ? `（新增 ${d.added} 条）` : ''}`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  /** 内容计划 V1（2026-08-19）：48 认知子项压力算法——问题价值×AI缺口→认知节点压力→Top N */
  const generateByAlgorithm = async () => {
    setGenerating(true)
    setGenMsg(null)
    try {
      const d = await geoPost<{ added?: number; total?: number; note?: string }>('/distill/content-plan', { limit: 10 })
      setGenMsg(`算法生成内容计划${d?.added !== undefined && d.added > 0 ? `（新增 ${d.added} 条）` : '（无新增：Top 认知节点均已有计划）'}`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  const removePlan = async (pid: string) => {
    if (confirmId !== pid) {
      setConfirmId(pid)
      setTimeout(() => setConfirmId((cur) => (cur === pid ? null : cur)), 3000)
      return
    }
    setConfirmId(null)
    try {
      await geoDelete(`/distill/plans/${pid}`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  if (loading) return <GeoLoading text="内容计划加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  return (
    <GeoCardShell title={`📝 内容计划（${items?.length ?? 0} 条）`}>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void generateByAlgorithm()} disabled={generating}>
          <RefreshCw className={`size-3.5 ${generating ? 'animate-spin' : ''}`} />
          {generating ? '生成中…' : '算法生成计划'}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => void generateFromGaps()} disabled={generating}>
          从缺口生成计划
        </Button>
        <div className="flex gap-1.5">
          {(
            [
              ['priority', '优先级'],
              ['created_at', '最新'],
            ] as Array<[Sort, string]>
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => changeSort(value)}
              className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
                sort === value
                  ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                  : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-muted)] hover:border-[var(--yayu-muted)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {genMsg ? <span className="text-[11px] text-[var(--yayu-muted)]">{genMsg}</span> : null}
      </div>

      {/* 算法公式说明（2026-08-19：公式可见性） */}
      <div className="mt-1 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-1.5 text-[10px] leading-relaxed text-[var(--yayu-muted)]">
        <span className="text-[var(--yayu-foreground)]">算法：</span>
        问题价值×AI缺口（简化分层 0/1/2 等权，无拍脑袋系数）→ 48 认知节点压力（高优问题共享的节点最值钱）
        → Kernel 知识检查（有事实=待生产，无事实=待补知识）→ 压力 TopN 生成，重复节点跳过
        → 发布登记 + 复测对比（效果落库反哺）。
      </div>

      {!items || items.length === 0 ? (
        <p className="text-[12px] text-[var(--yayu-muted)]">
          暂无内容计划，点「算法生成计划」自动生成（问题价值×AI缺口→认知节点压力）。
        </p>
      ) : (
        <div className="space-y-1.5">
          {items.map((p) => (
            <div key={p.id ?? p.topic} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[12px] leading-snug text-[var(--yayu-foreground)]">{p.topic}</div>
                  {p.reason ? <div className="mt-0.5 text-[11px] leading-snug text-[var(--yayu-muted)]">{p.reason}</div> : null}
                  <div className="mt-0.5 text-[10px] text-[var(--yayu-faint)]">
                    {p.recommended_content_type ?? '通用'} · 来源：{p.source_type ?? p.source ?? '—'}
                    {p.subitem_name ? ` · 认知节点：${p.subitem_name}` : ''}
                    {p.covered_questions ? ` · 覆盖 ${p.covered_questions} 题` : ''}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  {p.state ? (
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] ${
                        p.state === '待生产'
                          ? 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-foreground)]'
                          : p.state === '已发布'
                            ? 'bg-[var(--yayu-surface-raised)] text-[var(--yayu-muted)]'
                            : 'bg-[var(--yayu-surface-raised)] text-[var(--warn,#d97706)]'
                      }`}
                    >
                      {p.state}
                    </span>
                  ) : null}
                  <span className="rounded bg-[var(--yayu-surface-raised)] px-1.5 py-0.5 text-[10px] text-[var(--yayu-muted)]">
                    优先级 {p.priority}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void removePlan(p.id)}
                    aria-label="删除计划"
                    className={confirmId === p.id ? 'text-[var(--yayu-foreground)]' : ''}
                  >
                    {confirmId === p.id ? '确认删除？' : <Trash2 className="size-3.5" />}
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </GeoCardShell>
  )
}
