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

/** 下载由 GEO 生成的非 PDF 文件（例如企业资料 Word）。 */
export async function geoDownloadFile(path: string): Promise<Blob> {
  const r = await fetch(`${geoApiBase}${path}`, { headers: geoHeaders() })
  const contentType = r.headers.get('content-type') ?? ''
  if (r.ok && !contentType.toLowerCase().includes('application/json')) return r.blob()
  const j = await r.json().catch(() => null)
  if (r.status === 401) onProductSessionExpired?.()
  if (j?.error || j?.message || j?.detail) geoFail(r.status, j)
  throw new Error(`GEO 没有返回可下载的文件（HTTP ${r.status}）`)
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

/**
 * 文件上传（multipart）。只送 file 本身：`Content-Type` 必须由浏览器带着
 * boundary 自己生成，手写一个 `application/json` 会让后端解析不出任何字段。
 *
 * 老 v1 的上传 handler 在「文件太大 / 类型不支持 / 提不出文本」时回的是
 * **HTTP 200 + `ok:true` 里带 `data.error`**（见 app/core/envelope.py 的 `ok()`），
 * 所以调用方必须读 `data.error`，不能只看 HTTP 成功。
 */
export async function geoUpload<T>(path: string, file: File, field = 'file'): Promise<T> {
  const form = new FormData()
  form.append(field, file)
  const headers = geoHeaders()
  delete headers['Content-Type']
  const r = await fetch(`${geoApiBase}${path}`, { method: 'POST', headers, body: form })
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
  // 发布登记（Owner 2026-09-21）：发布链接与时间
  published_url?: string
  published_at?: string
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

/** POST /kb-init/scan：从企业知识库扫出来的候选（内测「知识库初始化」） */
export interface GeoKbInitCandidate {
  name: string
  in_profile: boolean
}

export interface GeoKbInitDocument {
  document_id: string
  title: string
  version?: number | string | null
  in_profile: boolean
}

export interface GeoKbInitScan {
  contract: string
  initialized: boolean
  revision: string | null
  last_applied_at: string | null
  existing: {
    companies: string[]
    products: string[]
    documents: Array<{ document_id: string; title: string; version?: number | string | null }>
  }
  candidates: {
    companies: GeoKbInitCandidate[]
    products: GeoKbInitCandidate[]
    documents: GeoKbInitDocument[]
  }
  classification_source?: string | null
  industry?: string | null
  empty: boolean
  error?: string | null
  hint?: string | null
}

/** POST /kb-init/apply：这份选择落进 GEO 自己的库（快照）之后的结果 */
export interface GeoKbInitApply {
  contract: string
  first_time: boolean
  added: {
    companies: string[]
    products: string[]
    documents: Array<{ document_id: string; title: string; version?: number | string | null }>
  }
  kept: { companies: number; products: number; documents: number }
  total: { companies: number; products: number; documents: number }
  unknown_documents: string[]
  recorded: boolean
  revision: string | null
  read_count?: number | null
  note: string
}

/**
 * GET /enterprise-profile/overview：企业资料体检总览（规则估算，非 LLM）。
 * total_items = 48 子项 + 合并进来的自定义子项；overall_coverage_pct 为 null 表示问题池还空着，
 * 「算不出来」不等于 0。
 */
export interface GeoProfileOverview {
  overall_coverage_pct: number | null
  total_items: number
  enough_count: number
  partial_count: number
  too_little_count: number
  note: string
}

/** 单子项档位：足够 / 部分 / 太少；related_state=none 表示问题池还没覆盖到它 */
export interface GeoProfileItemBrief {
  id: string
  name: string
  level: string
  related_state: string
  coverage_pct: number | null
  related_count: number
}

/** GET /enterprise-profile/categories：8 大类大纲（左树数据） */
export interface GeoProfileCategory {
  category: string
  name: string
  items: GeoProfileItemBrief[]
}

export interface GeoDiscoverResult {
  competitors: Array<{
    name: string
    company?: string
    reason?: string
    /** 哪些模型提到了它（Owner 2026-09-21：问「这几个 AI」，谁答了要如实说） */
    mentioned_by?: string[]
    /** 它在哪几组问题里出现：行业 / 产品 / 服务 */
    asked?: string[]
  }>
  empty?: boolean
  hint?: string | null
  /** 城市从哪来：user=用户填的所在地；company_name=从公司名抠的；none=没有（问「本地」） */
  city?: string
  city_source?: 'user' | 'company_name' | 'none'
  /** 这次实际问了哪几句 */
  questions?: string[]
  engines_total?: number
  engines_answered?: number
  engines_used?: string[]
  not_answered?: string[]
}

/**
 * POST /battle：同一个问题拿去问部署里每一个已登记引擎，可多轮辩论，最后由裁判模型
 * 点评。引擎是谁、有几个，由企业部署决定（GEO 不写死 6 个、也不持凭据）；这个部署
 * 一个都没登记时后端明确回 `no_engines_configured`，不假装打过。
 */
export interface GeoBattleResult {
  question: string
  rounds: Array<{
    round: number
    results: Array<{ engine_id: string; engine_name: string; answer: string }>
  }>
  judge: string | null
  // judge=true 但裁判模型没配上：如实说跳过了，不把「没点评」写成「点评了没意见」。
  judge_skipped: boolean
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
