import { useEffect, useMemo, useState } from 'react'
import { BarChart3, Play, Plus, Search, Trash2 } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoDelete, geoGet, geoPatch, geoPost, type GeoMonitorItem, type GeoTasks } from './geo-api'
import { formatMonitorProductLine } from './monitor-item-label'
import { GeoButtonRow, GeoCardShell, GeoError, GeoKpis, GeoLine, GeoLoading, GeoQuote, GeoRow, GeoTable, askGeoConfirm, monitorTypeText, shortDay, statusText } from './shared'

type Schedule = 'daily' | 'weekly'

interface TaskRunResult {
  summary?: { total_questions?: number; mentioned_questions?: number; score?: number }
}
interface QuickCheckResult {
  summary?: { mentioned?: number; not_mentioned?: number; score?: number; rank_avg?: number | null }
  results?: Array<{ engine_name?: string; mentioned?: boolean | null; error?: string | null }>
}

/** 跨次趋势（GET /monitor/items/{id}/trend）：每次监测一个点，指标口径见 monitor.py */
interface TrendPoint {
  ts: string
  visibility: number | null
  answered?: number
  mention: number
  position: number | null
  positive: number
  negative: number
  citation: number
  snippet: string
}
interface TrendData {
  monitor_id: string
  entity: string | null
  points: TrendPoint[]
  count: number
}
/** 任务表现（GET /monitor/tasks/{id}/overview）：任务下每个对象的最新状态 + 最近一次运行汇总 */
interface TaskOverview {
  task: { name?: string; type?: string; status?: string; schedule?: string }
  item_count: number
  item_states: Array<{
    monitor_id: string
    type: string
    entity: string
    status: string
    last_visibility: number | null
    last_mentioned: number | null
    last_run_at: string
  }>
  last_run_at: string
  last_summary: { coverage_pct?: number; mentioned_questions?: number; total_questions?: number; rank_avg?: number } | null
}

type DetailPanel =
  | { kind: 'trend'; title: string; data: TrendData | null; error?: string }
  | { kind: 'task'; title: string; data: TaskOverview | null; error?: string }

/** 监测对象 + 定时任务卡（拆自原监测卡前半）：对象勾选/运行/暂停/删除 + 任务开关/运行/归档/新建 */
export function GeoMonitorObjectsCard() {
  const [items, setItems] = useState<GeoMonitorItem[] | null>(null)
  const [tasks, setTasks] = useState<GeoTasks | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [creatingItem, setCreatingItem] = useState(false)
  const [newItemType, setNewItemType] = useState('product')
  const [newItemForm, setNewItemForm] = useState<Record<string, string>>({})
  const [newItemPreview, setNewItemPreview] = useState<number | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [schedule, setSchedule] = useState<Schedule>('daily')
  const [busy, setBusy] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [msg, setMsg] = useState<string | null>(null)
  const [runningId, setRunningId] = useState<string | null>(null)
  const [compLabels, setCompLabels] = useState<Record<string, string>>({})
  const [detailPanel, setDetailPanel] = useState<DetailPanel | null>(null)
  const [quickQuestion, setQuickQuestion] = useState('')
  const [quickResult, setQuickResult] = useState<QuickCheckResult | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const [m, t, comps] = await Promise.all([
        geoGet<{ items: GeoMonitorItem[] }>('/monitor/items'),
        geoGet<GeoTasks>('/monitor/tasks'),
        geoGet<{ groups: Array<{ type: string; label: string; items: Array<{ name: string }> }> }>('/cognition/competitors').catch(() => null),
      ])
      setItems(Array.isArray(m?.items) ? m.items : [])
      setTasks(t && Array.isArray(t.tasks) ? t : { tasks: [], total: 0 })
      const map: Record<string, string> = {}
      for (const g of comps?.groups ?? []) for (const c of g.items) map[c.name] = g.label
      setCompLabels(map)
    } catch (e) {
      setError(e instanceof Error ? e.message : '监测数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const toggleSelect = (mid: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(mid)) next.delete(mid)
      else next.add(mid)
      return next
    })
  }

  const toggleSelectAll = () => {
    setSelected((prev) => {
      const ids = (items ?? []).map((i) => i.monitor_id)
      return prev.size === ids.length && ids.length > 0 ? new Set<string>() : new Set(ids)
    })
  }

  const runSelected = async () => {
    const mids = (items ?? []).filter((i) => selected.has(i.monitor_id)).map((i) => i.monitor_id)
    if (mids.length === 0) return
    setBusy(true)
    setMsg(null)
    let ok = 0
    try {
      for (const mid of mids) {
        try {
          await geoPost(`/monitor/items/${mid}/run`)
          ok += 1
        } catch {
          // 单个失败不中断
        }
      }
      setMsg(`已触发 ${ok}/${mids.length} 个监测对象运行，结果稍后入库`)
      setSelected(new Set())
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '运行失败')
    } finally {
      setBusy(false)
    }
  }

  const runQuickQuestion = async () => {
    const question = quickQuestion.trim()
    if (!question) return
    const brand = (items ?? []).find((item) => item.type === 'brand')
    const company = brand?.config_json?.company || brand?.entity
    if (!company) { setMsg('请先创建企业品牌监测对象，明确要判断哪家企业是否被提及'); return }
    setRunningId('quick-check')
    setQuickResult(null)
    try {
      const result = await geoPost<QuickCheckResult>('/monitor/check', { question, company_name: company, full: false })
      setQuickResult(result)
      setMsg(`即时监测完成：${result.results?.filter((row) => row.mentioned != null).length ?? 0} 个模型有效回答`)
    } catch (e) {
      setMsg(`即时监测失败：${e instanceof Error ? e.message : '未知错误'}`)
    } finally { setRunningId(null) }
  }

  const runItem = async (it: GeoMonitorItem) => {
    setRunningId(it.monitor_id)
    setMsg(null)
    try {
      await geoPost(`/monitor/items/${it.monitor_id}/run`)
      setMsg(`「${it.entity || it.type}」监测完成`)
      await load()
    } catch (e) {
      setMsg(`运行失败：${e instanceof Error ? e.message : '未知'}`)
    } finally {
      setRunningId(null)
    }
  }

  const toggleItemStatus = async (it: GeoMonitorItem) => {
    const next = it.status === 'active' ? 'paused' : 'active'
    try {
      await geoPatch(`/monitor/items/${it.monitor_id}`, { status: next })
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换失败')
    }
  }

  const archiveItem = async (it: GeoMonitorItem) => {
    // 这是软删除（后端 status → archived，历史趋势保留），文案不能写成「不能恢复」（2026-09-21 核过 monitor.py）
    if (!(await askGeoConfirm(`确认删除监测对象「${it.entity}」？它会转为归档、不再参与监测；历史趋势会保留。`))) return
    try {
      await geoDelete(`/monitor/items/${it.monitor_id}`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  const runTask = async (tid: string) => {
    setRunningId(tid)
    setMsg(null)
    try {
      const d = await geoPost<TaskRunResult>(`/monitor/tasks/${tid}/run`)
      setMsg(`任务运行完成（${d.summary?.total_questions ?? 0} 个探针）`)
      await load()
    } catch (e) {
      setMsg(`运行失败：${e instanceof Error ? e.message : '未知'}`)
    } finally {
      setRunningId(null)
    }
  }

  const archiveTask = async (tid: string, name: string) => {
    if (!(await askGeoConfirm(`归档任务「${name}」后，这个任务下的探针不再按计划运行。`, '确认归档'))) return
    try {
      await geoDelete(`/monitor/tasks/${tid}`)
      setMsg(`任务「${name}」已归档`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '归档失败')
    }
  }

  const toggleTask = async (taskId: string, current: string) => {
    setBusy(true)
    try {
      await geoPatch(`/monitor/tasks/${taskId}`, { status: current === 'active' ? 'paused' : 'active' })
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换失败')
    } finally {
      setBusy(false)
    }
  }

  const showTrend = async (item: GeoMonitorItem) => {
    setRunningId(`trend-${item.monitor_id}`)
    try {
      setDetailPanel({ kind: 'trend', title: `${item.entity} · 跨次趋势`, data: await geoGet<TrendData>(`/monitor/items/${item.monitor_id}/trend`) })
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '趋势加载失败')
      setDetailPanel({ kind: 'trend', title: `${item.entity} · 跨次趋势`, data: null, error: e instanceof Error ? e.message : '趋势加载失败' })
    } finally { setRunningId(null) }
  }

  const showTaskOverview = async (taskId: string, name: string) => {
    setRunningId(`overview-${taskId}`)
    try {
      setDetailPanel({ kind: 'task', title: `${name} · 任务表现`, data: await geoGet<TaskOverview>(`/monitor/tasks/${taskId}/overview`) })
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '任务详情加载失败')
      setDetailPanel({ kind: 'task', title: `${name} · 任务表现`, data: null, error: e instanceof Error ? e.message : '任务详情加载失败' })
    } finally { setRunningId(null) }
  }

  // ── 新建监测对象（交互搬自 Builder GeoReport：类型 → 表单 → 探针预览 → 创建）──
  const ITEM_TYPE_META: Record<string, { name: string; emoji: string; fields: Array<{ key: string; label: string; list?: boolean }> }> = {
    brand: {
      name: '企业品牌',
      emoji: '🏢',
      fields: [
        { key: 'company', label: '公司名' },
        { key: 'aliases', label: '别名（逗号分隔）', list: true },
        { key: 'product', label: '产品（逗号分隔）', list: true },
        { key: 'industry', label: '行业' },
        { key: 'customer', label: '目标客户' },
        { key: 'competitors', label: '竞品（逗号分隔）', list: true },
        { key: 'tier', label: '规模档位' },
      ],
    },
    product: {
      name: '产品服务',
      emoji: '📦',
      fields: [
        { key: 'product', label: '产品/服务名' },
        { key: 'company', label: '公司名' },
        { key: 'competitors', label: '竞品（逗号分隔）', list: true },
      ],
    },
    competitor: {
      name: '竞争关系',
      emoji: '⚔️',
      fields: [
        { key: 'target', label: '竞品/对象名' },
        { key: 'aliases', label: '别名（逗号分隔）', list: true },
        { key: 'product', label: '产品（逗号分隔）', list: true },
        { key: 'industry', label: '行业' },
        { key: 'competitors', label: '竞品（逗号分隔）', list: true },
        { key: 'competitorAliases', label: '竞品别名（逗号分隔）', list: true },
      ],
    },
    keyword: {
      name: '行业市场',
      emoji: '🔍',
      fields: [
        { key: 'keyword', label: '关键词' },
        { key: 'extras', label: '补充词（逗号分隔）', list: true },
      ],
    },
    review: {
      name: '用户认知',
      emoji: '👥',
      fields: [
        { key: 'audience', label: '受众' },
        { key: 'scenario', label: '场景' },
        { key: 'pains', label: '痛点（逗号分隔）', list: true },
      ],
    },
    question: {
      name: '客户问题',
      emoji: '💬',
      fields: [{ key: 'query', label: '问题' }],
    },
  }

  const buildItemConfig = (type: string, f: Record<string, string>): Record<string, unknown> => {
    const split = (s?: string) => (s || '').split(/[,，\n]/).map((x) => x.trim()).filter(Boolean)
    if (type === 'brand') {
      return { company: f.company, aliases: split(f.aliases), product: split(f.product), industry: f.industry, customer: f.customer, competitor: split(f.competitors), tier: f.tier || 'standard' }
    }
    if (type === 'product') return { product: f.product, company: f.company, competitor: split(f.competitors) }
    if (type === 'competitor') {
      return { company: f.target, target: f.target, aliases: split(f.aliases), product: split(f.product), industry: f.industry, competitor: split(f.competitors), competitor_aliases: split(f.competitorAliases) }
    }
    if (type === 'keyword') return { keyword: f.keyword, extras: split(f.extras) }
    if (type === 'review') return { audience: f.audience, scenario: f.scenario, pains: split(f.pains) }
    return { query: f.query }
  }

  const previewItem = async () => {
    const cfg = buildItemConfig(newItemType, newItemForm)
    if (!Object.values(cfg).some((v) => (Array.isArray(v) ? v.length > 0 : v))) return
    setPreviewLoading(true)
    try {
      const d = await geoPost<{ query_count?: number }>('/monitor/items/preview', { type: newItemType, config_json: cfg })
      setNewItemPreview(d.query_count ?? 0)
    } catch {
      setNewItemPreview(0)
    } finally {
      setPreviewLoading(false)
    }
  }

  const createItem = async () => {
    const cfg = buildItemConfig(newItemType, newItemForm)
    if (!Object.values(cfg).some((v) => (Array.isArray(v) ? v.length > 0 : v))) {
      setMsg('请填写必填信息')
      return
    }
    setBusy(true)
    try {
      await geoPost('/monitor/items', { type: newItemType, config_json: cfg })
      setCreatingItem(false)
      setNewItemForm({})
      setNewItemPreview(null)
      setMsg('监测对象已创建')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
    } finally {
      setBusy(false)
    }
  }

  const createTask = async () => {
    setBusy(true)
    try {
      await geoPost('/monitor/tasks', {
        name: 'GEO 自动监测',
        schedule,
        item_ids: (items ?? []).map((i) => i.monitor_id),
      })
      setCreating(false)
      setMsg('定时任务已创建')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <GeoLoading text="监测对象加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  return (
    <GeoCardShell title="📡 监测对象与定时任务" className="sm:flex-1">
      {msg ? <p className="text-[12px] text-[var(--yayu-muted)]">{msg}</p> : null}

      <GeoRow label="监测对象" value={`${items?.length ?? 0} 个`} />
      <div className="monitor-quick-check">
        <div><b>单问题即时监测</b><span>以企业品牌对象为判断主体，立即询问当前已接通的国产模型</span></div>
        <div><input value={quickQuestion} onChange={(event) => setQuickQuestion(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') void runQuickQuestion() }} placeholder="例如：国内 GEO 服务商有哪些？" /><Button size="sm" disabled={!quickQuestion.trim() || runningId === 'quick-check'} onClick={() => void runQuickQuestion()}><Search className="size-3" />{runningId === 'quick-check' ? '监测中…' : '立即监测'}</Button></div>
        {quickResult?.summary ? <p>提及 {quickResult.summary.mentioned ?? 0} · 未提及 {quickResult.summary.not_mentioned ?? 0} · 提及率 {quickResult.summary.score ?? 0}%</p> : null}
      </div>
      {items && items.length > 0 ? (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-[var(--yayu-muted)]">
              <input
                type="checkbox"
                checked={selected.size > 0 && selected.size === items.length}
                onChange={toggleSelectAll}
                className="accent-[var(--yayu-foreground)]"
              />
              全选
            </label>
            <Button size="sm" disabled={busy || selected.size === 0} onClick={() => void runSelected()} title="批量运行所选监测对象生成的全部探针问题">
              {busy ? '批量监测中…' : `批量监测选中项（${selected.size}）`}
            </Button>
          </div>
          {items.map((i) => (
            <div key={i.monitor_id} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1">
              <div className="flex items-center gap-2.5">
                <input
                  type="checkbox"
                  checked={selected.has(i.monitor_id)}
                  onChange={() => toggleSelect(i.monitor_id)}
                  className="shrink-0 accent-[var(--yayu-foreground)]"
                  aria-label={`勾选 ${i.entity}`}
                />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="truncate text-[12px] text-[var(--yayu-foreground)]">{i.entity}</span>
                    {i.type === 'competitor' && compLabels[i.entity] ? (
                      <span className="shrink-0 rounded bg-[var(--yayu-surface-raised)] px-1.5 py-0.5 text-[9.5px] text-[var(--yayu-muted)]">
                        {compLabels[i.entity]}
                      </span>
                    ) : null}
                  </div>
                  <div className="truncate text-[10px] text-[var(--yayu-faint)]">
                    {formatMonitorProductLine(i.config_json?.product, monitorTypeText(i.type))}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[10px]">
                    <span data-status={i.run_result?.state} className="monitor-run-state">{i.run_result?.label ?? '从未成功'}</span>
                    {i.run_result?.last_run_at ? <span className="text-[var(--yayu-faint)]">{shortDay(i.run_result.last_run_at)} · {i.run_result.answered} 条有效回答</span> : null}
                  </div>
                </div>
                <span className="shrink-0 rounded bg-[var(--yayu-surface-raised)] px-1.5 py-0.5 text-[10px] text-[var(--yayu-muted)]">
                  {i.status === 'active' ? '监测中' : '已暂停'}
                </span>
              </div>
              <div className="mt-1.5 flex items-center gap-1.5 pl-6">
                <Button variant="secondary" size="sm" disabled={runningId === i.monitor_id} onClick={() => void runItem(i)}>
                  <Play className="size-3" /> {runningId === i.monitor_id ? '运行中…' : '运行'}
                </Button>
                <Button variant="secondary" size="sm" onClick={() => void toggleItemStatus(i)}>
                  {i.status === 'active' ? '暂停' : '启用'}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => void showTrend(i)}><BarChart3 className="size-3" />趋势</Button>
                <Button variant="ghost" size="sm" onClick={() => void archiveItem(i)} aria-label="删除监测对象">
                  <Trash2 className="size-3" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-[12px] text-[var(--yayu-muted)]">暂无监测对象，先跑一次自动配置创建。</p>
      )}

      {Array.isArray(tasks?.tasks) && tasks.tasks.length > 0 ? (
        <div className="pt-1">
          <div className="mb-1 text-[12px] font-medium text-[var(--yayu-muted)]">定时任务</div>
          <div className="space-y-1.5">
            {tasks.tasks.map((t) => (
              <div key={t.task_id} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-[12px] text-[var(--yayu-foreground)]">{t.name}</div>
                    <div className="text-[10px] text-[var(--yayu-faint)]">
                      {t.schedule === 'daily' ? '每日' : '每周'} · 上次{' '}
                      {t.last_run_at ? new Date(t.last_run_at).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric' }) : '未跑'}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <span className="text-[10px] text-[var(--yayu-muted)]">{t.status === 'active' ? '开' : '关'}</span>
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void toggleTask(t.task_id, t.status)}
                      aria-label={`${t.name} 开关`}
                      className={`relative h-5 w-9 rounded-full transition-colors ${t.status === 'active' ? 'bg-[var(--yayu-foreground)]' : 'bg-[var(--yayu-surface-raised)]'}`}
                    >
                      <span
                        className={`absolute top-0.5 size-4 rounded-full bg-[var(--yayu-input)] transition-all ${t.status === 'active' ? 'left-[18px]' : 'left-0.5'}`}
                      />
                    </button>
                    <Button variant="ghost" size="sm" disabled={runningId === t.task_id} onClick={() => void runTask(t.task_id)}>
                      <Play className="size-3" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => void showTaskOverview(t.task_id, t.name)} aria-label="查看任务表现"><BarChart3 className="size-3" /></Button>
                    <Button variant="ghost" size="sm" onClick={() => void archiveTask(t.task_id, t.name)} aria-label="归档任务">
                      <Trash2 className="size-3" />
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {detailPanel ? (
        <div className="monitor-detail-panel">
          <header>
            <b>{detailPanel.title}</b>
            <button onClick={() => setDetailPanel(null)}>关闭</button>
          </header>
          <div className="detail-body"><DetailBody panel={detailPanel} /></div>
        </div>
      ) : null}

      {creatingItem ? (
        <div className="space-y-2 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] p-3">
          <div className="text-[12px] font-medium text-[var(--yayu-foreground)]">新建监测对象</div>
          {/* 第一步：类型选择 */}
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(ITEM_TYPE_META).map(([value, meta]) => (
              <button
                key={value}
                type="button"
                onClick={() => {
                  setNewItemType(value)
                  setNewItemPreview(null)
                }}
                className={`rounded-full border px-2.5 py-0.5 text-[11px] transition-colors ${
                  newItemType === value
                    ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                    : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-muted)] hover:border-[var(--yayu-muted)]'
                }`}
              >
                {meta.emoji} {meta.name}
              </button>
            ))}
          </div>
          {/* 第二步：按类型动态字段 */}
          {ITEM_TYPE_META[newItemType]?.fields.map((field) => (
            <input
              key={field.key}
              value={newItemForm[field.key] ?? ''}
              onChange={(e) => setNewItemForm((prev) => ({ ...prev, [field.key]: e.target.value }))}
              placeholder={field.label}
              className="w-full rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1.5 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
            />
          ))}
          {/* 探针预览 */}
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" disabled={previewLoading} onClick={() => void previewItem()}>
              {previewLoading ? '预览中…' : '探针预览'}
            </Button>
            {newItemPreview !== null ? (
              <span className="text-[11px] text-[var(--yayu-muted)]">预计 {newItemPreview} 个探针问题</span>
            ) : null}
          </div>
          <GeoButtonRow>
            <Button size="sm" disabled={busy} onClick={() => void createItem()}>
              {busy ? '创建中…' : '创建'}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setCreatingItem(false)}>
              取消
            </Button>
          </GeoButtonRow>
        </div>
      ) : null}

      {creating ? (
        <div className="space-y-2 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] p-3">
          <div className="text-[12px] font-medium text-[var(--yayu-foreground)]">新建定时任务</div>
          <div className="flex gap-2">
            {(
              [
                ['daily', '每日监测'],
                ['weekly', '每周报告'],
              ] as Array<[Schedule, string]>
            ).map(([value, label]) => (
              <label key={value} className="flex cursor-pointer items-center gap-1.5 text-[12px] text-[var(--yayu-foreground)]">
                <input
                  type="radio"
                  name="geo-task-schedule"
                  checked={schedule === value}
                  onChange={() => setSchedule(value)}
                  className="accent-[var(--yayu-foreground)]"
                />
                {label}
              </label>
            ))}
          </div>
          <GeoButtonRow>
            <Button size="sm" disabled={busy || (items?.length ?? 0) === 0} onClick={() => void createTask()}>
              确定
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setCreating(false)}>
              取消
            </Button>
          </GeoButtonRow>
        </div>
      ) : (
        <GeoButtonRow>
          <Button size="sm" onClick={() => setCreatingItem(true)}>
            <Plus className="size-3.5" /> 新建监测对象
          </Button>
          <Button variant="secondary" size="sm" onClick={() => setCreating(true)}>
            <Plus className="size-3.5" /> 新建定时任务
          </Button>
        </GeoButtonRow>
      )}
    </GeoCardShell>
  )
}

/** 趋势 / 任务详情的正文：一律翻译成指标、趋势柱、明细表，不把接口字段名或 JSON 丢给用户 */
function DetailBody({ panel }: { panel: DetailPanel }) {
  if (panel.error) return <div className="geo-inline-error">{panel.error}</div>
  if (!panel.data) return <div className="geo-empty">没有取到详情。</div>
  if (panel.kind === 'trend') return <TrendDetail data={panel.data as TrendData} />
  return <TaskDetail data={panel.data as TaskOverview} />
}

const TREND_RANGES: Array<[string, string]> = [
  ['3', '最近 3 期'],
  ['6', '最近 6 期'],
  ['90', '最近 90 天'],
  ['all', '全部'],
]

function TrendDetail({ data }: { data: TrendData }) {
  // 周期筛选在本地做：/monitor/items/{id}/trend 没有区间参数，返回的就是全部点，
  // 所以这里只筛「显示哪些」，筛选后把「显示 N / 共 M 期」如实写出来（2026-09-21）。
  const [range, setRange] = useState<string>('all')
  const all = data.points ?? []
  const points = useMemo(() => {
    if (range === 'all') return all
    if (range === '90') {
      const cutoff = Date.now() - 90 * 24 * 60 * 60 * 1000
      const kept = all.filter((point) => Number(new Date(point.ts).getTime()) >= cutoff)
      return kept.length ? kept : all
    }
    return all.slice(-Number(range))
  }, [all, range])
  if (!all.length) return <div className="geo-empty">这个对象还没有跨次记录，跑过一次监测后这里会出现趋势。</div>
  const latest = points[points.length - 1]
  const judgedPoints = points.filter((point) => point.visibility != null)
  const first = points[0]
  const previous = judgedPoints.length > 1 ? judgedPoints[judgedPoints.length - 2] : null
  const delta = previous && latest.visibility != null ? latest.visibility - Number(previous.visibility) : null
  const direction = delta == null ? '暂无可比上一期' : `较上一期 ${delta >= 0 ? '+' : ''}${Math.round(delta * 10) / 10} 个百分点`
  return (
    <>
      <GeoKpis
        items={[
          // 2026-09-21：接口字段叫 visibility，口径就是「回答里提到本企业的比例」= 提及率，
          // 页面上叫「可见度」会让用户以为是另一个指标、和总览的 AI 提及率对不上账。
          { label: '最新提及率', value: latest.visibility == null ? '—' : `${latest.visibility}%`, detail: direction, tone: delta == null || delta >= 0 ? 'good' : 'warn' },
          { label: '被提及', value: `${latest.mention ?? '—'} 条`, detail: '最近一次监测' },
          { label: '正面 / 负面', value: `${latest.positive ?? 0} / ${latest.negative ?? 0}`, detail: '最近一次监测的回答倾向', tone: (latest.negative ?? 0) > (latest.positive ?? 0) ? 'bad' : 'good' },
          { label: '监测期数', value: `${points.length} 期`, detail: `首次 ${shortDay(first.ts)}` },
        ]}
      />
      <div className="geo-subhead">
        <h3>提及率走势</h3>
        <small>{range === 'all' ? `共 ${all.length} 期` : `显示 ${points.length} / 共 ${all.length} 期`}</small>
      </div>
      <div className="trend-range" role="group" aria-label="趋势周期">
        {TREND_RANGES.map(([value, label]) => (
          <button key={value} type="button" className={range === value ? 'active' : ''} onClick={() => setRange(value)}>{label}</button>
        ))}
      </div>
      {judgedPoints.length ? <GeoLine points={judgedPoints.map((point) => ({ label: shortDay(point.ts).slice(5), value: Number(point.visibility) }))} unit="%" /> : <div className="geo-empty">所选周期没有模型成功回答，无法计算提及率趋势。</div>}
      {/* 2026-09-21：原来这里还有一列「引用」，后端 _aggregate_item_trend 的 citation
          是写死的 0（注释写着「item 级待细化」）——一列永远显示 0 的数字，
          用户会读成「一条引用都没有」。没实现就不展示，等它真有了再加回来。 */}
      <GeoTable
        columns={['时间', '提及率', '提及', '正面', '负面']}
        template="96px 74px 60px 60px 60px"
        rows={points.map((point) => [
          <em>{shortDay(point.ts)}</em>,
          <b>{`${point.visibility ?? '—'}%`}</b>,
          <em>{point.mention ?? '—'}</em>,
          <em>{point.positive ?? 0}</em>,
          <em data-tone={(point.negative ?? 0) > 0 ? 'bad' : undefined}>{point.negative ?? 0}</em>,
        ])}
      />
      {latest.snippet ? (
        <>
          <div className="geo-subhead"><h3>最近一次 AI 回答片段</h3><small>{shortDay(latest.ts)}</small></div>
          <GeoQuote>{latest.snippet}</GeoQuote>
        </>
      ) : null}
    </>
  )
}

function TaskDetail({ data }: { data: TaskOverview }) {
  const states = data.item_states ?? []
  const summary = data.last_summary
  return (
    <>
      <GeoKpis
        items={[
          { label: '监测对象', value: `${data.item_count ?? states.length} 个`, detail: statusText(data.task?.status) },
          { label: '最近运行', value: data.last_run_at ? shortDay(data.last_run_at) : '—', detail: data.last_run_at ? '任务最近一次执行' : '这个任务还没跑过' },
          // 2026-09-21 口径修正：summary.coverage_pct 是「回答里提到本企业的问题占比」，
          // rank_avg 是「企业名第一次出现在第几句话」的平均——都不是「推荐度/排名」。
          { label: 'AI 提及率', value: summary?.coverage_pct == null ? '—' : `${summary.coverage_pct}%`, detail: summary ? `提到本企业 ${summary.mentioned_questions ?? 0}/${summary.total_questions ?? 0} 个问题（提及 ≠ 推荐）` : '还没有运行汇总' },
          { label: '首句提及位置', value: summary?.rank_avg == null ? '—' : `第 ${summary.rank_avg} 句`, detail: '企业名首次出现在第几句的平均；未提及的问题不计入' },
        ]}
      />
      <GeoTable
        columns={['对象', '类型', '状态', '可见度', '提及']}
        template="minmax(0,1.5fr) 96px 76px 74px 60px"
        rows={states.map((row) => [
          <b>{row.entity || row.monitor_id}</b>,
          <em>{monitorTypeText(row.type)}</em>,
          <em>{statusText(row.status)}</em>,
          <b>{row.last_visibility == null ? '—' : `${row.last_visibility}%`}</b>,
          <em>{row.last_mentioned ?? '—'}</em>,
        ])}
        empty="这个任务下还没有监测对象。"
      />
    </>
  )
}
