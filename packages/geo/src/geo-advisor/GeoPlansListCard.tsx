import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2, Plus, RefreshCw, RotateCcw, Trash2 } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoDelete, geoGet, geoPost, type GeoPlan } from './geo-api'
import { GeoCardShell, GeoError, GeoLoading, askGeoConfirm, useGeoNav, useGeoNavParams } from './shared'
import { ALL_SUBJECTS, MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'

type Sort = 'priority' | 'created_at'

/**
 * 计划来源是后端枚举（distill.py 写死的 source 值），页面上不给用户看英文。
 * 2026-09-21：这张卡以前直接打印「来源：subitem_pressure」这种字段值。
 */
const PLAN_SOURCE_LABEL: Record<string, string> = {
  subitem_pressure: '模型回答缺口分析',
  monitor_weak: '监测薄弱问题',
  customer_agent_gap: '客户问题缺口',
  coverage_analysis: '内容覆盖分析',
  assistant: '手动创建 / 助手建议',
}
const planSourceText = (value: string | undefined | null) => (value ? PLAN_SOURCE_LABEL[value] ?? `其他来源（${value}）` : '—')

/** 内容计划卡：列表/排序/删除 + 从缺口一键生成（交互对齐 Builder GeoDistill 计划区） */
export function GeoPlansListCard() {
  const [items, setItems] = useState<GeoPlan[] | null>(null)
  const go = useGeoNav()
  const { focus: navFocus, nonce: navNonce } = useGeoNavParams()
  const { scopeQuery, value: subjectValue } = useMonitorSubject()
  const [sort, setSort] = useState<Sort>('priority')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [genMsg, setGenMsg] = useState<string | null>(null)
  const [runningId, setRunningId] = useState<string | null>(null)
  const [impact, setImpact] = useState<Record<string, string>>({})
  const [manualOpen, setManualOpen] = useState(false)
  const [manualTopic, setManualTopic] = useState('')
  const [manualQuestion, setManualQuestion] = useState('')
  // 发布登记（Owner 2026-09-21）：登记时补发布链接与时间
  const [publishFor, setPublishFor] = useState<string | null>(null)
  const [pubUrl, setPubUrl] = useState('')
  const [pubAt, setPubAt] = useState('')
  const [plansOpen, setPlansOpen] = useState(false)
  const loadVersion = useRef(0)

  const load = useCallback(async (s: Sort = sort) => {
    const version = ++loadVersion.current
    setLoading(true)
    setError(null)
    try {
      const d = await geoGet<{ items: GeoPlan[]; total: number }>(`/distill/plans?limit=50&sort=${s}${scopeQuery ? `&${scopeQuery}` : ''}`)
      if (version === loadVersion.current) setItems(d.items)
    } catch (e) {
      if (version === loadVersion.current) setError(e instanceof Error ? e.message : '内容计划加载失败')
    } finally {
      if (version === loadVersion.current) setLoading(false)
    }
  }, [sort, scopeQuery])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    setPlansOpen((items ?? []).length <= 5)
  }, [items?.length])

  const changeSort = (s: Sort) => {
    setSort(s)
    void load(s)
  }

  /** 内容计划 V1（2026-08-19）：按客户问题价值与模型回答缺口生成 Top N 计划。 */
  const generateByAlgorithm = async () => {
    setGenerating(true)
    setGenMsg(null)
    try {
      const d = await geoPost<{ added?: number; total?: number; note?: string }>(`/distill/content-plan?limit=10${scopeQuery ? `&${scopeQuery}` : ''}`)
      setGenMsg(`按缺口生成内容计划${d?.added !== undefined && d.added > 0 ? `（新增 ${d.added} 条）` : '（暂无新的缺口需要安排）'}`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成失败')
    } finally {
      setGenerating(false)
    }
  }

  // 从市场信号跳过来时：先刷新（那条计划是刚建的），再高亮滚过去（2026-09-21）
  useEffect(() => {
    if (!navNonce) return
    void load().then(() => {
      if (!navFocus) return
      const target = document.querySelector<HTMLElement>('[data-nav-focus="on"]')
      target?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    })
  }, [navNonce])

  const removePlan = async (pid: string) => {
    if (!(await askGeoConfirm('删除后这条内容计划与其用例不再保留；已经生成并存进素材库的内容不受影响。'))) return
    try {
      await geoDelete(`/distill/plans/${pid}`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  const publishPlan = async (pid: string) => {
    setRunningId(pid)
    try {
      const d = await geoPost<{ published?: boolean; error?: string }>('/distill/content-publish', {
        plan_id: pid,
        published_url: pubUrl.trim(),
        published_at: pubAt.trim(),
      })
      setGenMsg(d.error || '已登记为发布；GEO 只记录发布，不会自动上线。')
      if (!d.error) {
        setPublishFor(null)
        setPubUrl('')
        setPubAt('')
      }
      await load()
    } catch (e) { setError(e instanceof Error ? e.message : '发布登记失败') } finally { setRunningId(null) }
  }

  const recheckPlan = async (pid: string) => {
    setRunningId(pid)
    try {
      const d = await geoPost<{ impact?: { level?: string; note?: string; delta?: number | null }; error?: string }>('/distill/content-recheck', { plan_id: pid })
      setImpact((current) => ({ ...current, [pid]: d.error || d.impact?.note || `复测完成${d.impact?.delta == null ? '' : `，变化 ${d.impact.delta}`}` }))
    } catch (e) { setError(e instanceof Error ? e.message : '复测失败') } finally { setRunningId(null) }
  }

  const addManualPlan = async () => {
    if (!manualTopic.trim()) return
    setGenerating(true)
    try { const d = await geoPost<{ added?: boolean; dup?: boolean; error?: string }>('/distill/plans/manual', { topic: manualTopic.trim(), target_question: manualQuestion.trim(), reason: '用户手动创建', recommended_content_type: 'FAQ+案例文章', priority: 60, monitor_id: subjectValue !== ALL_SUBJECTS ? subjectValue : null }); setGenMsg(d.error || (d.dup ? '已有相同计划，未重复添加' : '计划已创建')); setManualTopic(''); setManualQuestion(''); setManualOpen(false); await load() }
    catch (e) { setError(e instanceof Error ? e.message : '创建计划失败') } finally { setGenerating(false) }
  }

  if (loading) return <GeoLoading text="内容计划加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  return (
    <GeoCardShell title={`内容计划 · ${items?.length ?? 0} 条`} className="geo-growth-workbench">
      <MonitorSubjectPicker note="内容计划按这里选择的主体筛选；“全部”显示账号汇总。" />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void generateByAlgorithm()} disabled={generating}>
          <RefreshCw className={`size-3.5 ${generating ? 'animate-spin' : ''}`} />
          {generating ? '生成中…' : '按缺口生成计划'}
        </Button>
        <Button size="sm" variant="secondary" onClick={() => setManualOpen(!manualOpen)}><Plus className="size-3.5" />手动新建</Button>
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

      {manualOpen ? <div className="manual-plan"><input value={manualTopic} onChange={(e)=>setManualTopic(e.target.value)} placeholder="计划主题（必填）"/><input value={manualQuestion} onChange={(e)=>setManualQuestion(e.target.value)} placeholder="要回答的客户问题（可选）"/><Button size="sm" disabled={!manualTopic.trim()||generating} onClick={()=>void addManualPlan()}>创建计划</Button></div> : null}

      <details className="plan-method-note">
        <summary>计划如何排序</summary>
        <p>系统会把客户问题的重要程度、模型回答里的缺口和多个问题共同需要的资料合并排序，再跳过重复计划。发布后可回到国产模型监测复测，结果会保留在计划里。</p>
      </details>

      {!items || items.length === 0 ? (
        <p className="text-[12px] text-[var(--yayu-muted)]">
          {subjectValue !== ALL_SUBJECTS ? '当前主体还没有已绑定的内容计划；先完成监测并确认主体，再按本主体生成。' : '暂无内容计划，点「按缺口生成计划」自动生成。'}
        </p>
      ) : (
        <details className="geo-long-list" open={plansOpen} onToggle={(event) => setPlansOpen(event.currentTarget.open)}>
          <summary><span>内容计划</span><small>{items.length} 条，默认收起长列表</small></summary>
          <div className="geo-long-list-body space-y-1.5">
          {items.map((p) => (
            <div
              key={p.id ?? p.topic}
              data-nav-focus={navFocus && p.topic === navFocus ? 'on' : undefined}
              className={`rounded-md border px-2 py-1 ${navFocus && p.topic === navFocus ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-surface-raised)]' : 'border-[var(--yayu-border)] bg-[var(--yayu-input)]'}`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-[12px] leading-snug text-[var(--yayu-foreground)]">{p.topic}</div>
                  {p.reason ? <div className="mt-0.5 text-[11px] leading-snug text-[var(--yayu-muted)]">{p.reason}</div> : null}
                  <div className="mt-0.5 text-[10px] text-[var(--yayu-faint)]">
                    {p.recommended_content_type ?? '通用'} · 来源：{planSourceText(p.source_type ?? p.source)}
                    {p.subitem_name ? ` · 相关主题：${p.subitem_name}` : ''}
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
                  <Button variant="secondary" size="sm" onClick={() => go?.('content', { seed: p.topic })} disabled={!go}>进入内容生成</Button>
                  {p.status === 'published' || p.state === '已发布' ? (
                    <Button variant="secondary" size="sm" disabled={runningId === p.id} onClick={() => void recheckPlan(p.id)}><RotateCcw className="size-3.5" />复测</Button>
                  ) : (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={runningId === p.id}
                      onClick={() => {
                        const next = publishFor === p.id ? null : p.id
                        setPublishFor(next)
                        setPubUrl('')
                        setPubAt('')
                      }}
                    >
                      <CheckCircle2 className="size-3.5" />登记发布
                    </Button>
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => void removePlan(p.id)}
                    aria-label="删除计划"
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </div>
              </div>
              {publishFor === p.id ? (
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <input
                    value={pubUrl}
                    onChange={(e) => setPubUrl(e.target.value)}
                    placeholder="发布链接（可选，http(s)://…）"
                    className="min-w-0 flex-1 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[11px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
                  />
                  <input
                    value={pubAt}
                    onChange={(e) => setPubAt(e.target.value)}
                    placeholder="发布时间（可选，如 2026-09-21）"
                    className="w-44 shrink-0 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[11px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
                  />
                  <Button size="sm" disabled={runningId === p.id} onClick={() => void publishPlan(p.id)}>
                    {runningId === p.id ? '登记中…' : '确认登记'}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setPublishFor(null)}>
                    取消
                  </Button>
                </div>
              ) : null}
              {p.published_at || p.published_url ? (
                <div className="mt-0.5 text-[10px] text-[var(--yayu-faint)]">
                  已发布：{p.published_at ? p.published_at.slice(0, 16).replace('T', ' ') : '（未记时间）'}
                  {p.published_url ? (
                    <>
                      {' · '}
                      <a href={p.published_url} target="_blank" rel="noreferrer" className="underline">
                        查看链接
                      </a>
                    </>
                  ) : null}
                </div>
              ) : null}
              {impact[p.id] ? <div className="plan-impact">复测结论：{impact[p.id]}</div> : null}
            </div>
          ))}
          </div>
        </details>
      )}
    </GeoCardShell>
  )
}
