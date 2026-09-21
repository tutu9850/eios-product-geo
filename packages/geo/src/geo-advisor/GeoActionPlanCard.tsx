import { useCallback, useEffect, useState } from 'react'
import { geoGet, type GeoGap, type GeoPlan } from './geo-api'
import { GeoCardShell, GeoError, GeoLoading } from './shared'

interface ActionItem {
  level: 'P0' | 'P1' | 'P2'
  name: string
  bound: string
  stage: string
  channel: string
  status: string
}

/** 从缺口生成行动方案名（规则） */
function actionOf(g: GeoGap): { level: 'P0' | 'P1' | 'P2'; name: string; stage: string; channel: string } {
  const t = `${g.question} ${g.missing_information ?? ''}`
  if (/价格|报价|费用|预算|成本|多少钱/.test(t)) {
    return { level: 'P0', name: '《透明报价指南》', stage: '价格', channel: '官网 + 知乎' }
  }
  if (/案例|效果|实景|作品|口碑/.test(t)) {
    return { level: 'P0', name: '《真实案例库》', stage: '案例', channel: '官网 + 小红书' }
  }
  if (/资质|团队|专业|认证|证书/.test(t)) {
    return { level: 'P1', name: '《团队与资质介绍》', stage: '信任', channel: '官网' }
  }
  return { level: 'P2', name: `《${g.question.replace(/[？?，,。.：:]/g, '').slice(0, 14)}》内容补齐`, stage: '认知', channel: '知乎 + 官网 FAQ' }
}

const LEVEL_ORDER: Record<string, number> = { P0: 0, P1: 1, P2: 2 }

/** 行动计划卡（报告 09/10 章）：从缺口+内容计划生成 P0/P1/P2 行动总表 + 下一周期基线/目标 */
export function GeoActionPlanCard() {
  const [actions, setActions] = useState<ActionItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [g, p] = await Promise.all([
        geoGet<{ items: GeoGap[]; total: number }>('/distill/gaps?limit=50'),
        geoGet<{ items: GeoPlan[]; total: number }>('/distill/plans?status=planned&limit=50'),
      ])
      const list: ActionItem[] = (g.items ?? []).map((gap) => {
        const a = actionOf(gap)
        return { level: a.level, name: a.name, bound: gap.question, stage: a.stage, channel: a.channel, status: '未开始' }
      })
      for (const plan of p.items ?? []) {
        list.push({
          level: 'P1',
          name: `按计划生产内容：《${plan.topic.slice(0, 16)}》`,
          bound: plan.target_question ?? plan.topic,
          stage: '内容',
          channel: '内容资产',
          status: '规划中',
        })
      }
      list.sort((a, b) => LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level])
      setActions(list)
    } catch (e) {
      setError(e instanceof Error ? e.message : '行动计划加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  if (loading) return <GeoLoading text="行动计划加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  const groups: Array<{ level: 'P0' | 'P1' | 'P2'; label: string; items: ActionItem[] }> = [
    { level: 'P0', label: 'P0 · 立即补（影响价格/案例阶段）', items: (actions ?? []).filter((a) => a.level === 'P0') },
    { level: 'P1', label: 'P1 · 近期补（信任/内容）', items: (actions ?? []).filter((a) => a.level === 'P1') },
    { level: 'P2', label: 'P2 · 长期建设（认知/长尾）', items: (actions ?? []).filter((a) => a.level === 'P2') },
  ]

  return (
    <GeoCardShell title="30 天行动计划" className="geo-growth-workbench">
      {!actions || actions.length === 0 ? (
        <p className="text-[12px] text-[var(--yayu-muted)]">暂无行动项——先跑蒸馏（生成缺口与内容计划），行动会自动生成。</p>
      ) : (
        <div className="space-y-2">
          {groups.map((grp) =>
            grp.items.length === 0 ? null : (
              <div key={grp.level}>
                <div className="mb-1 text-[11px] font-medium text-[var(--yayu-foreground)]">{grp.label}</div>
                <div className="space-y-1.5">
                  {grp.items.slice(0, 6).map((a, i) => (
                    <div key={i} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-[12px] text-[var(--yayu-foreground)]">{a.name}</span>
                        <span className="shrink-0 rounded bg-[var(--yayu-surface-raised)] px-1.5 py-0.5 text-[10px] text-[var(--yayu-muted)]">
                          {a.status}
                        </span>
                      </div>
                      <div className="mt-0.5 truncate text-[10px] text-[var(--yayu-faint)]">
                        绑定缺口：{a.bound} · {a.stage}阶段 · 渠道：{a.channel}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ),
          )}
        </div>
      )}

      {/* 下一周期：基线 → 目标 */}
      <div className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
        <div className="mb-1 text-[11px] font-medium text-[var(--yayu-muted)]">下一周期目标</div>
        {/* 2026-09-21：这一块原来写着「价格阶段覆盖：20% → ≥70%」「案例阶段覆盖：15% → ≥60%」，
            那两个 20%/15% 是**写在前端代码里的常量**，不是量出来的基线，读起来却像实测值；
            「AI 提及率：基线实测」那句更是连值都没有。而底下那句「下次监测自动核对…」
            在代码里没有任何实现——系统不会去做这件事。全部删掉，只留能兑现的一句话。 */}
        <p className="text-[11px] leading-relaxed text-[var(--yayu-muted)]">
          行动上线后，回到「AI 监测」重跑一轮，对比提及率与各阶段覆盖的变化——核对由你触发，系统不会自动宣布达标。
        </p>
      </div>
    </GeoCardShell>
  )
}
