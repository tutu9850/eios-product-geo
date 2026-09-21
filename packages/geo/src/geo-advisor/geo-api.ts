/**
 * GEO 功能前端卡片化的统一 API 封装。
 * 全部请求走 yayu BFF 的 /api/geo/api/v1（本地 controller：数据存 BFF 个人空间，计算转发 :3002）。
 * 返回结构统一为 { ok, data, error }，这里剥壳后直接返回 data。
 */

import { getAuthToken } from '../api/session'

let geoApiBase = '/api/geo/api/v1'
let productSessionToken: string | null = null
let onProductSessionExpired: (() => void) | null = null

/**
 * 独立 GEO Product 的 Host 注入面。
 *
 * yayu 旧会话页不调用它，继续走原 BFF 与自身登录 token；独立 Product 页面在收到
 * `eios.product_host/v1` 的 host.session 后调用它，改走 EIOS 的单一产品门。
 */
export function configureGeoProductTransport(options: {
  apiBase: string
  sessionToken: string | null
  onSessionExpired?: () => void
}) {
  geoApiBase = options.apiBase.replace(/\/+$/, '')
  productSessionToken = options.sessionToken
  onProductSessionExpired = options.onSessionExpired ?? null
}

function geoHeaders(): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = productSessionToken ?? getAuthToken()
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

const NEST_GENERIC = /^(Bad Request|Internal Server Error|Unauthorized|Forbidden|Not Found)$/i

/** 从 BFF / Nest / :3002 错误体抽出可读文案（避免把 HTTP 状态短语当原因） */
export function geoErrorMessage(
  status: number,
  j: { error?: unknown; detail?: unknown; message?: unknown; statusCode?: unknown } | null,
): string {
  const nestMsg = j?.message
  if (nestMsg && typeof nestMsg === 'object' && typeof (nestMsg as { error?: unknown }).error === 'string') {
    return (nestMsg as { error: string }).error
  }
  if (typeof nestMsg === 'string' && nestMsg && !NEST_GENERIC.test(nestMsg)) {
    return nestMsg
  }
  const err = j?.error
  if (err && typeof err === 'object' && typeof (err as { message?: unknown }).message === 'string') {
    return (err as { message: string }).message
  }
  if (typeof err === 'string' && err && !NEST_GENERIC.test(err)) {
    return err
  }
  if (typeof j?.detail === 'string' && j.detail) return j.detail
  return `GEO 请求失败（${status}）`
}

function geoFail(status: number, j: { error?: unknown; detail?: unknown; message?: unknown; statusCode?: unknown } | null): never {
  if (status === 401) onProductSessionExpired?.()
  throw new Error(geoErrorMessage(status, j))
}

export async function geoGet<T>(path: string): Promise<T> {
  const r = await fetch(`${geoApiBase}${path}`, { headers: geoHeaders() })
  const j = await r.json().catch(() => null)
  if (!r.ok || !j?.ok) geoFail(r.status, j)
  return j.data as T
}

export async function geoPost<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${geoApiBase}${path}`, {
    method: 'POST',
    headers: geoHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const j = await r.json().catch(() => null)
  if (!r.ok || !j?.ok) geoFail(r.status, j)
  return j.data as T
}

export async function geoDelete<T>(path: string): Promise<T> {
  const r = await fetch(`${geoApiBase}${path}`, { method: 'DELETE', headers: geoHeaders() })
  const j = await r.json().catch(() => null)
  if (!r.ok || !j?.ok) geoFail(r.status, j)
  return j.data as T
}

export async function geoPatch<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${geoApiBase}${path}`, {
    method: 'PATCH',
    headers: geoHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const j = await r.json().catch(() => null)
  if (!r.ok || !j?.ok) geoFail(r.status, j)
  return j.data as T
}

/**
 * 下载二进制产物（周期报告 PDF）：走同一个 geoApiBase、同一张会话票。
 *
 * 为什么要看 content-type 而不是只看状态码：老 v1 的 PDF 路由在「暂无报告」时
 * 是 **HTTP 200 + JSON** `{ok:false,error}`。只信状态码就会把那段 JSON 当成分存成
 * `.pdf`，用户拿到一个打不开的文件还以为是报告。不是 `application/pdf` 就不是产物，
 * 如实把原因说出来。
 */
export async function geoDownload(path: string): Promise<Blob> {
  const r = await fetch(`${geoApiBase}${path}`, { headers: geoHeaders() })
  const contentType = r.headers.get('content-type') ?? ''
  if (r.ok && contentType.toLowerCase().includes('application/pdf')) {
    return r.blob()
  }
  const j = await r.json().catch(() => null)
  if (r.status === 401) onProductSessionExpired?.()
  if (j?.error || j?.message || j?.detail) geoFail(r.status, j)
  throw new Error(
    `GEO 没有返回可下载的文件（HTTP ${r.status}，content-type=${contentType || '无'}）`,
  )
}

/** PUT（素材更新/发布打点等，S4） */
export async function geoPut<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${geoApiBase}${path}`, {
    method: 'PUT',
    headers: geoHeaders(),
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const j = await r.json().catch(() => null)
  if (!r.ok || !j?.ok) geoFail(r.status, j)
  return j.data as T
}

// ── 类型（字段名来自 :3002 OpenAPI 实测返回） ──────────────────────────────

export interface GeoStatsOverview {
  knowledge: { materials: number; text_blocks: number; bytes: number }
  links: { total: number; indexed: number; failed: number; pending: number; unknown: number }
  monitor: { runs: number; mentioned: number; avg_score: number }
  // total = 这个部署登记了几个模型；answered = 最近一次监测里几个引擎答上来了。
  // 后者不再由产品猜「谁配了 key」——凭据在企业部署手里，猜不出来也不该猜。
  engines: { total: number; answered: number }
}

export interface GeoDistillOverview {
  funnel: Array<{ stage: string; question_count: number; coverage_pct: number }>
  ai_judgment: { stage: string; coverage_pct: number; reason: string; samples: string[] }
}

export interface GeoMonitorOverview {
  recommend: { value: number; delta: number }
  rank: { value: number; delta: number }
  citations_count: number
  cite_rate: number | null
  published_count: number
  cited_count: number
  latest_batch_at: string | null
  platforms: Record<string, Array<{ ts: string; recommend_pct: number; mentioned: number; configured: number }>>
}

export interface GeoQuestion {
  id: string
  question: string
  keyword: string
  intent: string
  customer_stage: string
  priority: number
  related_entities: string[]
  source: string
  evidence_level: string
  confidence: number
  validated: boolean
  monitor_count: number
  created_at: string
  status?: string
}

export interface GeoGap {
  question: string
  entity: string
  missing_information: string
  source: string
  retrieval_score: number
  matched_refs: Array<{ score: number; name: string }>
}

export interface GeoPlan {
  id: string
  topic: string
  reason: string
  target_question: string
  recommended_content_type: string
  priority: number
  gap_id: string
  source_object: string
  source_type: string
  source: string
  // 内容计划 V1（2026-08-19）：48 认知子项压力算法新增字段
  state?: string          // 待生产 / 待补知识 / 已发布
  status?: string         // planned / knowledge_required / published
  subitem?: string
  subitem_name?: string
  category?: string
  subitem_pressure?: number
  covered_questions?: number
}

export interface GeoMonitorItem {
  monitor_id: string
  type: string
  config_json: { company?: string; aliases?: string[]; product?: string | string[]; industry?: string; tier?: string }
  entity: string
  query_count: number
  status: string
  created_time: string
  updated_time: string
}

export interface GeoTasks {
  tasks: Array<{
    task_id: string
    name: string
    schedule: string
    status: string
    item_ids: string[]
    created_time: string
    updated_time: string
    id: string
    item_count: number
    last_run_at: string | null
  }>
  total: number
}

export interface GeoCognitionProfile {
  dims: Array<{ key: string; label: string; words: string[]; mention_rate: number; gap_level: string }>
}

export interface GeoMaterial {
  title: string
  content: string
  material_id?: string
  id?: string
  source?: string
  created_at?: string
  published_url?: string // S4 打点：已发布 URL
}

export interface GeoKnowledgeReadiness {
  source: string
  authoritative: boolean
  read_ever: boolean
  snapshot_count: number
  objects_seen: number
  documents_seen: number
  kinds: Record<string, number>
  last_read_at: string | null
  note: string
}

export interface GeoOnboardStatus {
  empty: boolean
  items: number
  questions: number
  /** GEO 自己的素材库（geo_kb）条目数；不是监测对象数 */
  materials?: number
  /** 企业知识库读到的快照概况（GEO 只读知识库，读到的留在自己库里） */
  knowledge?: GeoKnowledgeReadiness
}

export interface GeoDetectResult {
  company: string[]
  aliases: string[]
  products: string[]
  services: string[]
  industry: string
  keywords: string[]
  empty: boolean
  /** 读知识库失败时非空：「读不到」不等于「知识库是空的」 */
  error?: string | null
  /** llm = 模型归类；heuristic = 名称规则兜底（模型未配置时） */
  classification_source?: string | null
  hint?: string | null
}

export interface GeoDiscoverResult {
  competitors: Array<{ name: string; company?: string; reason?: string }>
  empty?: boolean
}

export interface GeoCreateResult {
  created: Array<{ monitor_id: string; entity?: string; type?: string }>
}

export interface GeoRunResult {
  status: string
  progress?: Array<{ monitor_id: string; status: string }>
}

/** GET /onboard/run-status：监测/蒸馏运行进度 */
export interface GeoRunStatus {
  running: boolean
  phase: string
  done: number
  total: number
  error: string | null
  started_at: string | null
  finished: boolean
  overall_pct?: number
  parse?: { succeeded: number; failed: number; running: number; total: number; queue_size: number } | null
  summary: {
    total_questions: number
    answered_questions: number
    mentioned_questions: number
    coverage_pct: number
    score: number
    mentioned: number
    not_mentioned: number
    weak_questions: string[]
  } | null
  distill: unknown
  intelligence: { evidence: number; succeeded: number; failed: number; pending: number; mentions: number } | null
}

export interface GeoDistillResult {
  status: string
  steps?: Array<{ step: string; status: string; detail?: string }>
  stats?: { questions: number; gaps: number; plans: number }
}
