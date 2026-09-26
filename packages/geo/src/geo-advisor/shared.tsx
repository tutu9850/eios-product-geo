import { Component, createContext, useContext, useEffect, useState, type ErrorInfo, type ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { Button, cn } from '@yayu/ui'
import { GeoApiError, type GeoErrorCode } from './geo-api'

/** GEO 卡片外壳（自适应聊天界面宽度，内容舒适排版） */
export function GeoCardShell({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  const cleanTitle = title?.replace(/^[\p{Extended_Pictographic}\uFE0F\s]+/u, '')
  return (
    <div
      className={cn(
        'geo-card-shell w-full space-y-2 text-[12.5px]',
        className,
      )}
    >
      {cleanTitle ? <div className="geo-card-title">{cleanTitle}</div> : null}
      {children}
    </div>
  )
}

export function GeoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-[11px] text-[var(--yayu-muted)]">{label}</span>
      <span className="truncate text-right text-[12px] font-medium text-[var(--yayu-foreground)]">{value}</span>
    </div>
  )
}

export function GeoList({ items }: { items: Array<{ title: string; desc?: string; meta?: string }> }) {
  return (
    <div className="geo-data-list space-y-1">
      {items.map((item, index) => (
        <div key={index} className="geo-data-row flex items-start justify-between gap-2.5">
          <div className="min-w-0">
            <div className="text-[12px] leading-snug text-[var(--yayu-foreground)]">{item.title}</div>
            {item.desc ? <div className="mt-px text-[10px] leading-snug text-[var(--yayu-muted)]">{item.desc}</div> : null}
          </div>
          {item.meta ? (
            <span className="shrink-0 rounded bg-[var(--yayu-surface-raised)] px-1 py-px text-[9.5px] text-[var(--yayu-muted)]">{item.meta}</span>
          ) : null}
        </div>
      ))}
    </div>
  )
}

export function GeoLoading({ text = '加载中…' }: { text?: string }) {
  return (
    <div className="flex items-center gap-2 py-3 text-[12px] text-[var(--yayu-muted)]">
      <Loader2 className="size-3.5 animate-spin" /> {text}
    </div>
  )
}

const ERROR_LABEL: Record<GeoErrorCode, string> = {
  empty: '暂无数据',
  'not-configured': '需要配置',
  forbidden: '无权访问',
  'not-found': '资源不存在',
  upstream: '服务暂时不可用',
  contract: '数据格式异常',
}

function errorDetails(error: unknown, fallback?: string): { message: string; code?: GeoErrorCode } {
  if (error instanceof GeoApiError) return { message: error.message, code: error.code }
  if (error instanceof Error) return { message: error.message || fallback || '暂时无法完成操作' }
  if (typeof error === 'string' && error) return { message: error }
  return { message: fallback || '暂时无法完成操作' }
}

export function GeoError({
  message,
  error,
  onRetry,
  onConfigure,
  configureLabel = '去配置',
}: {
  message?: string
  error?: unknown
  onRetry?: () => void
  onConfigure?: () => void
  configureLabel?: string
}) {
  const details = errorDetails(error, message)
  const label = details.code ? ERROR_LABEL[details.code] : null
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-3 py-2 text-[12px] text-[var(--yayu-muted)]" role="alert">
      <span className="min-w-0 flex-1 leading-relaxed">⚠️ {label ? <b className="mr-1 text-[var(--yayu-foreground)]">{label}</b> : null}{details.message}</span>
      <span className="flex shrink-0 items-center gap-2">
        {details.code === 'not-configured' && onConfigure ? <Button variant="secondary" size="sm" onClick={onConfigure}>{configureLabel}</Button> : null}
        {onRetry ? <Button variant="secondary" size="sm" onClick={onRetry}>重试</Button> : null}
      </span>
    </div>
  )
}

export function GeoButtonRow({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2 pt-1">{children}</div>
}

/** 单卡崩溃不拖垮整页（监测两卡并排时尤其需要） */
export class GeoCardErrorBoundary extends Component<{ children: ReactNode; label: string }, { message: string | null }> {
  state = { message: null as string | null }

  static getDerivedStateFromError(error: Error) {
    return { message: error.message || '卡片渲染失败' }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[geo-advisor] ${this.props.label} crashed`, error, info.componentStack)
  }

  render() {
    if (this.state.message) {
      return <GeoError message={`${this.props.label}打不开：${this.state.message}`} />
    }
    return this.props.children
  }
}

/* ── 业务数据组件（2026-09-21：不再把接口字段名或 JSON 丢给用户）──────────
   Owner 交接单第 2 条：趋势、对比、指标、证据都要变成正式业务组件。
   这一组是共用底座，只负责「怎么显示」，不认识任何接口字段。 */

export type GeoKpi = { label: string; value: string; detail?: string; tone?: 'good' | 'warn' | 'bad' }

/** 指标行：一个结论一行，值大、说明小 */
export function GeoKpis({ items }: { items: GeoKpi[] }) {
  return (
    <div className="geo-kpis">
      {items.map((item) => (
        <article className="geo-kpi" key={item.label} data-tone={item.tone ?? 'good'}>
          <span>{item.label}</span>
          <b>{item.value}</b>
          {item.detail ? <small>{item.detail}</small> : null}
        </article>
      ))}
    </div>
  )
}

/** 排行条：对比表的主力，value 同时给数字和比例 */
export function GeoBars({
  items,
  empty = '暂无数据',
  max,
}: {
  items: Array<{ label: string; value: number; text?: string }>
  empty?: string
  max?: number
}) {
  if (!items.length) return <div className="geo-empty">{empty}</div>
  const top = max ?? Math.max(...items.map((item) => item.value), 1)
  return (
    <div className="geo-bars">
      {items.map((item) => (
        <div className="geo-bar" key={item.label}>
          <span title={item.label}>{item.label}</span>
          <i>
            <em style={{ width: `${Math.max(2, Math.min(100, (item.value / top) * 100))}%` }} />
          </i>
          <b>{item.text ?? item.value}</b>
        </div>
      ))}
    </div>
  )
}

/** 比例条：正/中/负这类「一分三」的分布 */
export function GeoRatio({ segments }: { segments: Array<{ label: string; value: number; color: string }> }) {
  const total = segments.reduce((sum, item) => sum + item.value, 0) || 1
  return (
    <div>
      <div className="geo-ratio">
        {segments.map((item) => (
          <i key={item.label} style={{ width: `${(item.value / total) * 100}%`, background: item.color }} />
        ))}
      </div>
      <div className="geo-ratio-legend">
        {segments.map((item) => (
          <span key={item.label}>
            <i style={{ background: item.color }} />
            {item.label} {item.value}
            {total > 1 ? `（${Math.round((item.value / total) * 100)}%）` : ''}
          </span>
        ))}
      </div>
    </div>
  )
}

/** 趋势柱：按时间顺序的紧凑柱图（不做花哨图表，趋势看方向就够） */
export function GeoTrend({ values, unit = '' }: { values: number[]; unit?: string }) {
  if (values.length < 2) return <div className="geo-empty">只有一个数据点，攒够两期才能看趋势。</div>
  const top = Math.max(...values, 1)
  return (
    <div className="geo-trend">
      {values.map((value, index) => (
        <i key={index} title={`${value}${unit}`} style={{ height: `${Math.max(6, (value / top) * 100)}%` }} />
      ))}
    </div>
  )
}

/** 数据表：columns 决定列宽（grid-template-columns），rows 是已经翻译好的业务文字 */
export function GeoTable({
  columns,
  template,
  rows,
  empty = '暂无数据',
}: {
  columns: string[]
  template: string
  rows: ReactNode[][]
  empty?: string
}) {
  if (!rows.length) return <div className="geo-empty">{empty}</div>
  return (
    <div className="geo-table">
      <header style={{ gridTemplateColumns: template }}>
        {columns.map((column, index) => (
          <span key={index}>{column}</span>
        ))}
      </header>
      {rows.map((row, index) => (
        <article key={index} style={{ gridTemplateColumns: template }}>
          {row.map((cell, cellIndex) => (
            <span key={cellIndex}>{cell}</span>
          ))}
        </article>
      ))}
    </div>
  )
}

/** 原话引用：证据层统一用这个，别把 quote 塞进 <p> 里 */
export function GeoQuote({ children }: { children: ReactNode }) {
  return <p className="geo-quote">{children}</p>
}

/** 模型回答轻量排版：识别标题、列表和粗体，不把 Markdown 控制符原样丢给用户。 */
export function stripAnswerMarkdown(value: string): string {
  return value
    .replace(/^\s{0,3}#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+[.)]\s+/gm, '')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .trim()
}

function AnswerInline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`)/g).filter(Boolean)
  return <>{parts.map((part, index) => {
    if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) return <strong key={index}>{part.slice(2, -2)}</strong>
    if (part.startsWith('`') && part.endsWith('`')) return <code key={index}>{part.slice(1, -1)}</code>
    return <span key={index}>{part}</span>
  })}</>
}

export function GeoFormattedAnswer({ text }: { text: string }) {
  const lines = text.replace(/\r\n?/g, '\n').split('\n')
  const nodes: ReactNode[] = []
  let list: Array<{ ordered: boolean; text: string }> = []
  const flush = () => {
    if (!list.length) return
    const ordered = list[0].ordered
    const Tag = ordered ? 'ol' : 'ul'
    nodes.push(<Tag key={`list-${nodes.length}`}>{list.map((item, index) => <li key={index}><AnswerInline text={item.text} /></li>)}</Tag>)
    list = []
  }
  for (const raw of lines) {
    const line = raw.trim()
    if (!line) { flush(); continue }
    const heading = line.match(/^#{1,6}\s+(.+)$/)
    const bullet = line.match(/^[-*+]\s+(.+)$/)
    const ordered = line.match(/^\d+[.)]\s+(.+)$/)
    if (bullet || ordered) { list.push({ ordered: !!ordered, text: (bullet?.[1] ?? ordered?.[1] ?? '').trim() }); continue }
    flush()
    if (heading) nodes.push(<h4 key={`heading-${nodes.length}`}><AnswerInline text={heading[1]} /></h4>)
    else nodes.push(<p key={`paragraph-${nodes.length}`}><AnswerInline text={line} /></p>)
  }
  flush()
  return <div className="geo-formatted-answer">{nodes}</div>
}

/* ── 业务文案映射（2026-09-21）────────────────────────────────────────────
   后端返回的是 positive / brand / active 这类机器值，页面上不给用户看英文。
   索引不到就显示「未判定」，不猜。 */
export const SENTIMENT_LABEL: Record<string, string> = { positive: '正面', negative: '负面', neutral: '中性' }
export const MONITOR_TYPE_LABEL: Record<string, string> = {
  brand: '企业品牌',
  product: '产品服务',
  keyword: '行业关键词',
  competitor: '竞品对比',
  question: '客户问题',
}
export const STATUS_LABEL: Record<string, string> = {
  active: '运行中',
  paused: '已暂停',
  archived: '已归档',
  planned: '计划中',
  ignored: '已忽略',
  pending: '待处理',
  running: '进行中',
  done: '已完成',
  failed: '失败',
  blocked: '受阻',
  // 市场信号（apps/api/app/api/v1/market.py 的真实取值）
  new: '新信号',
  confirmed: '已确认',
  extracted: '已提取事实',
  draft: '草稿',
}
/** 链接收录检测（apps/api/app/api/v1/links.py 的真实取值）：单独一套，别和通用状态混用 */
export const INDEX_STATUS_LABEL: Record<string, string> = {
  indexed: '已收录',
  failed: '未收录',
  pending: '待检测',
  unknown: '检测受限',
}
export const sentimentText = (value: string | undefined | null) => SENTIMENT_LABEL[value ?? ''] ?? '未判定'
export const monitorTypeText = (value: string | undefined | null) => MONITOR_TYPE_LABEL[value ?? ''] ?? '其他对象'
export const statusText = (value: string | undefined | null) => STATUS_LABEL[value ?? ''] ?? '未知状态'
export const indexStatusText = (value: string | undefined | null) => INDEX_STATUS_LABEL[value ?? ''] ?? '待检测'
/** 只取日期：接口给的是 ISO 时间戳 */
export const shortDay = (value: string | undefined | null) => (value ? String(value).slice(0, 10) : '—')

/* ── 统一二次确认（2026-09-21）────────────────────────────────────────────
   交接单要求「所有删除操作统一二次确认」。这里用一个模块级的小服务，
   调用方只写一行 `if (!(await askGeoConfirm('…'))) return`，
   界面由 main.tsx 里挂一次的 <GeoConfirmHost /> 负责渲染，样式跟 EIOS 一致，
   不用每个卡片自己造一套弹窗。 */
type ConfirmRequest = { message: string; confirmText: string; resolve: (ok: boolean) => void }
let confirmRequest: ConfirmRequest | null = null
const confirmListeners = new Set<() => void>()
const emitConfirm = () => confirmListeners.forEach((listener) => listener())

export function askGeoConfirm(message: string, confirmText = '确认删除'): Promise<boolean> {
  return new Promise((resolve) => {
    confirmRequest = { message, confirmText, resolve }
    emitConfirm()
  })
}

function settleConfirm(ok: boolean) {
  const request = confirmRequest
  confirmRequest = null
  emitConfirm()
  request?.resolve(ok)
}

/** 全局挂一次；渲染当前待确认的动作 */
export function GeoConfirmHost() {
  const [request, setRequest] = useState<ConfirmRequest | null>(confirmRequest)
  useEffect(() => {
    const listener = () => setRequest(confirmRequest)
    confirmListeners.add(listener)
    listener()
    return () => {
      confirmListeners.delete(listener)
    }
  }, [])
  if (!request) return null
  return (
    <div className="geo-confirm-backdrop" role="dialog" aria-modal="true" aria-label="操作确认">
      <div className="geo-confirm">
        <h3>再确认一次</h3>
        <p>{request.message}</p>
        <div className="geo-confirm-actions">
          <Button variant="secondary" size="sm" onClick={() => settleConfirm(false)}>取消</Button>
          <Button size="sm" onClick={() => settleConfirm(true)}>{request.confirmText}</Button>
        </div>
      </div>
    </div>
  )
}

/* ── 跨页跳转（2026-09-21）───────────────────────────────────────────────
   交接单第 3 条：内容计划 → 内容生成、市场信号 → 内容计划、企业资料 → 增长行动、
   错误认知 → 纠正内容计划。卡片不能直接改 main.tsx 的页签状态，所以由 main.tsx
   注入一个 go()：kind 是 GeoFlowRouter 的功能名，focus 用于「跳过去并高亮」，
   seed 用于「跳过去并预填」（例如把一条错误认知带进内容生成的主题）。
   nonce 每次都变，保证同一个 seed 连点两次也能触发目标卡片重新取值。 */
export type GeoNavOptions = { focus?: string; seed?: string }
export type GeoNavParams = { focus: string | null; seed: string | null; nonce: number }
export type GeoGo = (kind: string, options?: GeoNavOptions) => void

export const GeoNavContext = createContext<GeoGo | null>(null)
export const GeoNavParamsContext = createContext<GeoNavParams>({ focus: null, seed: null, nonce: 0 })
export const useGeoNav = () => useContext(GeoNavContext)
export const useGeoNavParams = () => useContext(GeoNavParamsContext)

/** 折线趋势图：只有两三个点也看得清方向；不引图表库，直接出 SVG */
export function GeoLine({
  points,
  unit = '',
  empty = '只有一个数据点，攒够两期才能看趋势。',
}: {
  points: Array<{ label: string; value: number }>
  unit?: string
  empty?: string
}) {
  if (points.length < 2) return <div className="geo-empty">{empty}</div>
  const values = points.map((point) => point.value)
  const max = Math.max(...values)
  const min = Math.min(...values)
  const span = max - min || Math.max(1, Math.abs(max))
  const width = 640
  const height = 150
  const padLeft = 34
  const padRight = 10
  const padTop = 14
  const padBottom = 24
  const stepX = (width - padLeft - padRight) / Math.max(1, points.length - 1)
  const x = (index: number) => padLeft + index * stepX
  const y = (value: number) => padTop + (1 - (value - min) / span) * (height - padTop - padBottom)
  const line = points.map((point, index) => `${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(' ')
  const every = Math.max(1, Math.ceil(points.length / 6))
  return (
    <div className="geo-line">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="趋势折线图">
        <line x1={padLeft} y1={height - padBottom} x2={width - padRight} y2={height - padBottom} className="axis" />
        <line x1={padLeft} y1={y(max)} x2={width - padRight} y2={y(max)} className="grid" />
        <line x1={padLeft} y1={y(min)} x2={width - padRight} y2={y(min)} className="grid" />
        <polyline points={line} className="plot" />
        {points.map((point, index) =>
          index % every === 0 || index === points.length - 1 ? (
            <circle key={index} cx={x(index)} cy={y(point.value)} r="3" className="dot">
              <title>{`${point.label}：${point.value}${unit}`}</title>
            </circle>
          ) : null,
        )}
        <text x={padLeft - 5} y={y(max) + 3} className="tick" textAnchor="end">{`${max}${unit}`}</text>
        <text x={padLeft - 5} y={y(min) + 3} className="tick" textAnchor="end">{`${min}${unit}`}</text>
        {points.map((point, index) =>
          index % every === 0 || index === points.length - 1 ? (
            <text key={`x-${index}`} x={x(index)} y={height - 8} className="tick" textAnchor="middle">{point.label}</text>
          ) : null,
        )}
      </svg>
    </div>
  )
}
