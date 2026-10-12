import { useCallback, useEffect, useRef, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoGet, geoPost, type GeoGap } from './geo-api'
import { GeoCardShell, GeoError, GeoList, GeoLoading, geoPriorityLabel } from './shared'
import { ALL_SUBJECTS, MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'

/** 缺口影响×紧急度（规则：关键词映射客户阶段 + 优先级） */
function gapPriority(g: GeoGap): { level: 'P0' | 'P1' | 'P2'; stage: string } {
  const t = `${g.question} ${g.missing_information ?? ''} ${g.source ?? ''}`
  if (/价格|报价|费用|预算|成本|多少钱/.test(t)) return { level: 'P0', stage: '价格' }
  if (/案例|效果|实景|作品|口碑/.test(t)) return { level: 'P0', stage: '案例' }
  if (/资质|团队|专业|认证|证书/.test(t)) return { level: 'P1', stage: '信任' }
  return { level: 'P2', stage: '认知' }
}

const LEVEL_ORDER: Record<string, number> = { P0: 0, P1: 1, P2: 2 }

/** 资料缺口卡：重新检查缺口（重新分析）+ 列表展示（含影响×紧急度） */
export function GeoGapsListCard() {
  const [items, setItems] = useState<GeoGap[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [regenerating, setRegenerating] = useState(false)
  const [regenerateMsg, setRegenerateMsg] = useState<string | null>(null)
  const [gapsOpen, setGapsOpen] = useState(false)
  const { scopeQuery, value: subjectValue } = useMonitorSubject()
  const loadVersion = useRef(0)

  const load = useCallback(async () => {
    const version = ++loadVersion.current
    setLoading(true)
    setError(null)
    try {
      const d = await geoGet<{ items: GeoGap[]; total: number }>(`/distill/gaps?limit=50${scopeQuery ? `&${scopeQuery}` : ''}`)
      if (version === loadVersion.current) setItems(d.items)
    } catch (e) {
      if (version === loadVersion.current) setError(e instanceof Error ? e.message : '资料缺口加载失败')
    } finally {
      if (version === loadVersion.current) setLoading(false)
    }
  }, [scopeQuery])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setGapsOpen((items ?? []).length <= 8)
  }, [items?.length])

  const regenerate = async () => {
    setRegenerating(true)
    setRegenerateMsg(null)
    try {
      const d = await geoPost<{ added: number; total: number; plans_added: number }>(`/distill/gaps?limit=30${scopeQuery ? `&${scopeQuery}` : ''}`)
      setRegenerateMsg(`重新检查完成：新增 ${d.added} 个缺口，共 ${d.total} 个`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '重新检查失败')
    } finally {
      setRegenerating(false)
    }
  }

  if (loading) return <GeoLoading text="资料缺口加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  return (
    <GeoCardShell title="资料缺口" className="geo-growth-workbench">
      <MonitorSubjectPicker note="资料缺口按这里选择的主体筛选；“全部”显示账号汇总。" />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void regenerate()} disabled={regenerating}>
          <RefreshCw className={`size-3.5 ${regenerating ? 'animate-spin' : ''}`} /> {regenerating ? '检查中…' : '重新检查'}
        </Button>
        {regenerateMsg ? <span className="text-[11px] text-[var(--yayu-muted)]">{regenerateMsg}</span> : null}
      </div>
      {!items || items.length === 0 ? (
        <p className="text-[12px] text-[var(--yayu-muted)]">{subjectValue !== ALL_SUBJECTS ? '当前主体还没有已绑定的资料缺口；先完成问题判定，再重新检查。' : '暂无资料缺口，点「重新检查」再看一次。'}</p>
      ) : (
        <details className="geo-long-list" open={gapsOpen} onToggle={(event) => setGapsOpen(event.currentTarget.open)}>
          <summary><span>资料缺口</span><small>{items.length} 条，默认收起长列表</small></summary>
          <div className="geo-long-list-body">
            <GeoList
              items={[...items]
            .sort((a, b) => LEVEL_ORDER[gapPriority(a).level] - LEVEL_ORDER[gapPriority(b).level])
            .map((g) => {
              const p = gapPriority(g)
              // 2026-09-21：这张卡以前把后端检索来源的老名字直接吐给用户，
              // 而且从来不显示「到底缺什么」——用户看不出缺口是不是企业知识库缺的。
              const caps = g.missing_capabilities ?? []
              // 后端 list_gaps 自己就把「missing_information == question」当成「没说清缺什么」
              // （checklist_source 置 null）；页面也照这个口径，不把问题原文当答案显示。
              const rawWhat = (g.missing_information ?? '').trim()
              const what = rawWhat && rawWhat !== (g.question ?? '').trim() ? rawWhat : caps.length ? caps.join('、') : ''
              // 2026-09-21：这个列表里其实混着两种缺口——
              // ① 知识库逐题判定出来的（source=enterprise_knowledge_base，有 judge_basis）；
              // ② 内容覆盖分析产出的（source=coverage_analysis，根本没查知识库）。
              // 原来一律写「来源：企业知识库 / 按文档文本推断」，第②种就被贴上了没做过的判定依据。
              const fromCoverage = g.source === 'coverage_analysis'
              return {
                title: g.question,
                desc: what
                  ? `缺什么：${what}`
                  : '缺什么：尚未判明（这次没有模型能给出「需要补哪类信息」）',
                meta: [
                  `${geoPriorityLabel(p.level)} · ${p.stage}阶段`,
                  ...(fromCoverage
                    ? ['来源：内容覆盖分析（把现有内容与客户问题逐条对了一遍，不是查企业知识库）']
                    : [
                        g.judge_basis === 'fact_triple' ? '按企业事实判定' : '按企业资料推断',
                        g.matched_terms?.length ? `命中「${g.matched_terms.slice(0, 3).join('/')}」` : '',
                        '来源：企业资料',
                      ]),
                ].filter(Boolean).join(' · '),
              }
              })}
            />
          </div>
        </details>
      )}
    </GeoCardShell>
  )
}
