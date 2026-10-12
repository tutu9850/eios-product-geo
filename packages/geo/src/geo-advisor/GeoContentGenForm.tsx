import { useEffect, useRef, useState } from 'react'
import { Check, Copy, Download } from 'lucide-react'
import { Button, cn } from '@yayu/ui'
import { geoGet, geoPost, type GeoPlan } from './geo-api'
import { GeoButtonRow, GeoCardShell, GeoError, GeoLoading, useGeoNavParams } from './shared'
import { MonitorSubjectPicker, useMonitorSubject } from './geo-monitor-subject'

const GOALS = ['让模型更容易推荐', '让更多客户了解产品', '建立行业信任', '回答客户问题', '应对竞品比较', '发布企业最新动态']
const CONTENT_TYPES = ['企业介绍', '行业解决方案', 'FAQ问答', '对比文章', '客户案例', '新闻动态']
const STYLES = ['专业权威', '技术专家', '营销转化', '新闻报道', '白皮书']
const LENGTHS = ['500字', '1500字', '3000字']
/**
 * 展示名 → 平台 id；「通用」不传平台。
 * 审计 B12：后端 ALL_PLATFORMS 共 14 个，前端以前只接了 10 个（缺落地页/产品页/新闻稿/博客）。
 */
const PLATFORMS: Array<{ name: string; id: string | null }> = [
  { name: '通用', id: null },
  { name: '知乎', id: 'zhihu' },
  { name: '小红书', id: 'xiaohongshu' },
  { name: '头条号', id: 'toutiao' },
  { name: '公众号', id: 'weixin' },
  { name: '百家号', id: 'baijiahao' },
  { name: '网易', id: 'netease' },
  { name: '搜狐', id: 'sohu' },
  { name: '微博', id: 'weibo' },
  { name: 'SEO文章', id: 'seo_article' },
  { name: '落地页文案', id: 'seo_landing' },
  { name: '产品介绍页', id: 'seo_product' },
  { name: '新闻稿/软文', id: 'seo_news' },
  { name: '博客文章', id: 'seo_blog' },
  { name: '问答/帮助', id: 'seo_qa' },
]

/**
 * Fact Gate 事实核验模式（后端 `mode`）。
 * 审计 A2：后端三档一直存在，前端从不传 → 恒 creative，用户永远拿不到「哪句话没依据」。
 * 默认仍是 creative（严谨模式是否改默认待 Owner 拍板）。
 */
const MODES: Array<{ label: string; value: 'creative' | 'strict' | 'draft'; hint: string }> = [
  { label: '创作', value: 'creative', hint: '未验证的公司声明会标注「据企业宣传」，不写成已验证事实' },
  { label: '严谨', value: 'strict', hint: '凡未在企业资料 / 内容资产找到依据的声明 → 直接拒绝生成' },
  { label: '草稿', value: 'draft', hint: '未验证声明按草稿构思处理，明确不代表企业已确认事实' },
]

/** 模型易读结构（后端 `structure`）：geo = 可抽取结构模板（五节，便于模型摘要引用） */
const STRUCTURES: Array<{ label: string; value: 'free' | 'geo' }> = [
  { label: '自由长文', value: 'free' },
  { label: '适合模型理解的结构', value: 'geo' },
]

/** 后端 SEO_PLATFORM_CONFIGS 的 6 个平台：选中时展示 SEO 参数（keywords/密度/调性/受众） */
const SEO_PLATFORM_IDS = new Set([
  'seo_article',
  'seo_landing',
  'seo_product',
  'seo_news',
  'seo_blog',
  'seo_qa',
])

interface ContextSource {
  kind: string
  label: string
  items: Array<Record<string, unknown>>
}

interface ClaimCheck {
  status: 'review_required' | 'no_flags'
  flags: Array<{ kind: string; claim: string; reason: string }>
}

interface FactCheckResult {
  score: number
  hit_facts?: string[]
  missing_facts?: string[]
  needs_rewrite?: boolean
  suggestion?: string
}

interface UnverifiedFact {
  claim: string
  level?: string
  score?: number
  evidence?: string
}

/** 审计 A6（Owner 2026-09-21 拍板「喂」）：生成时据以写作的市场现状 */
interface MarketSignals {
  available?: boolean
  ai_answers?: Array<{
    engine: string
    question: string
    mentioned: boolean
    rank_est?: number | null
    sentiment?: string | null
    snippet: string
  }>
  citations?: Array<{ title: string; count: number; questions?: string[] }>
  hallucinations?: Array<{ claim: string; engine?: string; question?: string }>
  competitor_edges?: Array<{ factor: string; competitor?: string; mentions?: number }>
  report_findings?: Array<{ kind: string; title?: string; dimension?: string; competitor?: string; factors?: string[]; gap_type?: string }>
}

interface GenResult {
  ok: boolean
  title: string
  content: string
  company_name?: string
  materials_used?: number
  context_sources?: ContextSource[]
  source_material_ids?: string[]
  knowledge_status?: 'available' | 'ready' | 'not_synced' | 'empty' | 'partial' | 'refused' | 'unavailable' | 'invalid_response' | 'unknown'
  knowledge_error?: { code: string; message: string; category?: string } | null
  warnings?: string[]
  claim_check?: ClaimCheck | null
  sections?: Record<string, string> | null
  fact_check?: FactCheckResult | null
  unverified_facts?: UnverifiedFact[]
  market_signals?: MarketSignals
  mode?: string
  structure?: string
  error?: string
}

interface ScoreResult {
  total: number
  entity_coverage: number
  fact_density: number
  question_coverage: number
  structure_completeness: number
  citation_potential: number
  suggestions: string[]
}

interface QualityResult { total?: number; score?: number; suggestions?: string[]; [key: string]: unknown }

/**
 * 内容生成引导卡（对齐 Builder GeoContent）：
 * 第一步选内容主题（内容计划点选 / 手输）→ 目标 → 类型/风格 → 长度/平台 → 生成 → 结果。
 * 纯前端状态机，提交直接调 GEO 生成接口（不经大模型聊天）。
 */
export function GeoContentGenForm() {
  const { seed: navSeed, nonce: navNonce } = useGeoNavParams()
  const { scopeQuery, subject } = useMonitorSubject()
  const [step, setStep] = useState(1)
  // 第 1 步：内容主题（内容计划点选 + 手输）
  const [plans, setPlans] = useState<GeoPlan[]>([])
  const [plansLoading, setPlansLoading] = useState(true)
  const [topic, setTopic] = useState('')
  const [goal, setGoal] = useState<string | null>(null)
  const [contentType, setContentType] = useState<string | null>(null)
  const [style, setStyle] = useState<string | null>(null)
  const [length, setLength] = useState<string>('1500字')
  const [platform, setPlatform] = useState<string>('通用')
  // 审计 A2：认知编译器结构 / Fact Gate 模式 / 行业 / SEO 参数——后端一直有，前端以前无入口。
  const [structure, setStructure] = useState<'free' | 'geo'>('free')
  const [mode, setMode] = useState<'creative' | 'strict' | 'draft'>('creative')
  const [industry, setIndustry] = useState('')
  const [seoKeywords, setSeoKeywords] = useState('')
  const [seoLongTail, setSeoLongTail] = useState('')
  const [seoDensity, setSeoDensity] = useState('3')
  const [seoTone, setSeoTone] = useState('professional')
  const [seoAudience, setSeoAudience] = useState('')
  const [result, setResult] = useState<GenResult | null>(null)
  const [score, setScore] = useState<ScoreResult | null>(null)
  const [scoring, setScoring] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [quality, setQuality] = useState<QualityResult | null>(null)
  const [qualityLoading, setQualityLoading] = useState(false)
  // 2026-09-22：按用户提示词改这一篇 + 存进企业资料（生成内容）
  const [improveText, setImproveText] = useState('')
  const [improving, setImproving] = useState(false)
  const [improveNote, setImproveNote] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [savedNote, setSavedNote] = useState<string | null>(null)
  // Every body-changing operation invalidates all prior analysis responses.
  const draftRevision = useRef(0)
  const pendingRequests = useRef(new Set<AbortController>())
  const invalidateDraft = () => {
    draftRevision.current += 1
    pendingRequests.current.forEach((request) => request.abort())
    pendingRequests.current.clear()
    setScore(null)
    setQuality(null)
    setScoring(false)
    setQualityLoading(false)
    setLoading(false)
    setImproving(false)
    setSavedNote(null)
    return draftRevision.current
  }
  useEffect(() => () => {
    draftRevision.current += 1
    pendingRequests.current.forEach((request) => request.abort())
  }, [])

  // 从内容计划 / 错误认知跳过来时，把带过来的主题直接填进第 1 步（2026-09-21）
  useEffect(() => {
    if (!navNonce || !navSeed) return
    setTopic(navSeed)
    setStep(1)
  }, [navSeed, navNonce])

  // 拉取内容计划（status=planned 的可生成主题）
  useEffect(() => {
    let cancelled = false
    geoGet<{ items: GeoPlan[] }>(`/distill/plans?status=planned&limit=20${scopeQuery ? `&${scopeQuery}` : ''}`)
      .then((d) => {
        if (!cancelled) setPlans(d.items ?? [])
      })
      .catch(() => {
        // 计划拉取失败不阻塞手输主题
      })
      .finally(() => {
        if (!cancelled) setPlansLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [scopeQuery])

  const generate = async () => {
    if (!topic.trim() || !goal || !contentType || !style || saving) return
    const revision = invalidateDraft()
    const controller = new AbortController()
    pendingRequests.current.add(controller)
    setResult(null)
    setImproveNote(null)
    setLoading(true)
    setError(null)
    setScore(null)
    try {
      const density = Number.parseInt(seoDensity, 10)
      const seo =
        platformId && SEO_PLATFORM_IDS.has(platformId)
          ? {
              target_keywords: seoKeywords.trim() || undefined,
              long_tail_keywords: seoLongTail.trim() || undefined,
              keyword_density: Number.isFinite(density) ? density : 3,
              content_tone: seoTone,
              target_audience: seoAudience.trim() || undefined,
            }
          : null
      const d = await geoPost<GenResult>('/content/generate', {
        goal,
        content_type: contentType,
        style,
        length: length.replace('字', ''),
        platform: platformId,
        question: topic.trim(),
        company_name: subject?.name || null,
        structure,
        mode,
        industry: industry.trim() || null,
        seo,
      }, controller.signal)
      if (revision !== draftRevision.current) return
      if (d.ok === false) {
        // 严谨模式拒绝生成（未验证声明）：把原因留在第四步，不进结果页
        setResult(d)
        setError(d.error || '生成被拒绝（严谨模式）')
        return
      }
      setResult(d)
      setStep(5)
      // 生成后自动评分（可发布度）
      setScoring(true)
      try {
        const s = await geoPost<ScoreResult>('/content/score', {
          title: d.title ?? '',
          content: d.content ?? '',
          goal,
          question: topic.trim(),
          company_name: subject?.name || null,
          platform: platformId,
        }, controller.signal)
        if (revision === draftRevision.current) setScore(s)
      } catch {
        // 评分失败不阻塞结果展示
      } finally {
        if (revision === draftRevision.current) setScoring(false)
      }
    } catch (e) {
      if (revision === draftRevision.current) setError(e instanceof Error ? e.message : '生成失败')
    } finally {
      pendingRequests.current.delete(controller)
      if (revision === draftRevision.current) setLoading(false)
    }
  }

  const copyResult = async () => {
    if (!result) return
    try {
      await navigator.clipboard.writeText(`${result.title}\n\n${result.content}`)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // 剪贴板不可用时静默
    }
  }

  const downloadResult = () => {
    if (!result) return
    const blob = new Blob([`# ${result.title}\n\n${result.content}`], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${result.title.slice(0, 30)}.md`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  // 让模型按用户写的要求改这篇（结果替换当前稿；Enter 不提交，只能点按钮）
  const runImprove = async () => {
    if (!result || !improveText.trim() || improving || saving) return
    const revision = invalidateDraft()
    const controller = new AbortController()
    pendingRequests.current.add(controller)
    setImproving(true)
    setError(null)
    setImproveNote(null)
    setSavedNote(null)
    try {
      const d = await geoPost<{ title?: string; content?: string; context_sources?: ContextSource[]; source_material_ids?: string[]; knowledge_status?: GenResult['knowledge_status']; knowledge_error?: GenResult['knowledge_error']; warnings?: string[]; claim_check?: ClaimCheck | null }>('/content/improve', {
        title: result.title ?? '',
        content: result.content ?? '',
        instruction: improveText.trim(),
        question: topic.trim(),
        company_name: subject?.name || null,
        source_material_ids: result.source_material_ids ?? [],
        context_sources: result.context_sources ?? [],
      }, controller.signal)
      if (revision !== draftRevision.current) return
      const nextTitle = (d.title ?? result.title ?? '').trim()
      const nextContent = (d.content ?? '').trim()
      if (!nextContent) {
        setError('改进没有返回内容，原稿保持不变')
        return
      }
      setResult({
        ...result,
        title: nextTitle,
        content: nextContent,
        // 改稿响应代表新正文实际使用的来源；缺省时清空旧来源，不能沿用旧稿的来源声明。
        context_sources: d.context_sources ?? [],
        source_material_ids: d.source_material_ids ?? [],
        knowledge_status: d.knowledge_status ?? 'unknown',
        knowledge_error: d.knowledge_error ?? null,
        warnings: d.warnings ?? [],
        claim_check: d.claim_check ?? null,
        fact_check: null,
        unverified_facts: [],
        sections: null,
      })
      setScore(null) // 改过之后原来的评分不再对应当前稿子
      setQuality(null)
      setImproveNote(`已按你的要求改过（要求：${improveText.trim().slice(0, 40)}）。改后的稿子需要重新评分。`)
    } catch (e) {
      if (revision === draftRevision.current) setError(e instanceof Error ? e.message : '改进失败')
    } finally {
      pendingRequests.current.delete(controller)
      if (revision === draftRevision.current) setImproving(false)
    }
  }

  // 存进「企业资料 → 内容资产 → 生成内容」（后端 source_type=generated，会切块）
  const saveToAssets = async () => {
    if (!result || saving || improving) return
    const revision = draftRevision.current
    const draft = result
    setSaving(true)
    setError(null)
    setSavedNote(null)
    try {
      const d = await geoPost<{ item?: { title?: string; chunks?: number }; error?: string }>('/content/save', {
        title: draft.title ?? '',
        content: draft.content ?? '',
        question: topic.trim(),
        context_sources: draft.context_sources ?? [],
        source_material_ids: draft.source_material_ids ?? [],
      })
      // A body change while the save was in flight makes its response stale.
      if (revision !== draftRevision.current) return
      if (d.error) throw new Error(d.error)
      const item = d.item
      if (!item) throw new Error('保存没有确认成功，请稍后检查内容资产')
      setSavedNote(
        `已存入企业资料 · 生成内容：${item.title ?? draft.title}${item.chunks ? `（切成 ${item.chunks} 段）` : ''}`,
      )
    } catch (e) {
      if (revision === draftRevision.current) setError(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const runQuality = async () => {
    if (!result || improving || loading || qualityLoading) return
    const revision = draftRevision.current
    const controller = new AbortController()
    pendingRequests.current.add(controller)
    setQualityLoading(true)
    try {
      const checked = await geoPost<QualityResult>('/content/quality', { content: result.content, question: topic, company_name: subject?.name || null }, controller.signal)
      if (revision === draftRevision.current) setQuality(checked)
    }
    catch (e) { if (revision === draftRevision.current) setError(e instanceof Error ? e.message : '内容检查失败') }
    finally {
      pendingRequests.current.delete(controller)
      if (revision === draftRevision.current) setQualityLoading(false)
    }
  }

  const chipClass = (active: boolean) =>
    cn(
      'cursor-pointer rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors',
      active
        ? 'border-accent bg-accent text-on-accent'
        : 'border-border bg-input text-muted hover:border-border-strong hover:text-foreground',
    )

  // 后端 score.total 是 0–1 权重和；此前直接 Math.round(0.85) → 显示「1 分」，与各维度百分比自相矛盾。
  const scoreTotalPct = score ? Math.round(score.total <= 1 ? score.total * 100 : score.total) : 0

  const sourceItemText = (item: Record<string, unknown>) => {
    for (const key of ['content', 'excerpt', 'text', 'chunk', 'fact', 'claim', 'name', 'title', 'question', 'summary']) {
      const value = item[key]
      if (typeof value === 'string' && value.trim()) return value.trim()
    }
    return ''
  }

  const inputClass =
    'w-full rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]'

  const platformId = PLATFORMS.find((p) => p.name === platform)?.id ?? null
  const seoPlatform = platformId != null && SEO_PLATFORM_IDS.has(platformId)
  const activeMode = MODES.find((m) => m.value === mode)

  const options = (list: string[], selected: string | null, onPick: (v: string) => void) => (
    <div className="flex flex-wrap gap-1.5" role="radiogroup">
      {list.map((o) => {
        const active = selected === o
        return (
          <button
            key={o}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onPick(o)}
            className={chipClass(active)}
          >
            {o}
          </button>
        )
      })}
    </div>
  )

  return (
    <GeoCardShell title="内容制作台" className="geo-content-workbench">
      <MonitorSubjectPicker note="内容计划和生成上下文按这里选择的主体筛选；“全部”显示账号汇总。" />
      <div className="flex items-center gap-1 text-[10px] text-[var(--yayu-faint)]">
        {['主题', '目标', '类型/风格', '长度/平台', '结果'].map((label, index) => (
          <span key={label} className="flex items-center gap-1">
            {index > 0 ? <span className="text-muted/50">·</span> : null}
            <span className={step === index + 1 ? 'font-medium text-foreground' : 'text-muted'}>{label}</span>
          </span>
        ))}
      </div>

      {step === 1 ? (
        <div className="space-y-2">
          <div className="text-[12px] font-medium text-[var(--yayu-foreground)]">第一步 · 选择内容主题</div>
          {plansLoading ? (
            <GeoLoading text="内容计划加载中…" />
          ) : plans.length > 0 ? (
            <>
              <div className="text-[11px] text-[var(--yayu-muted)]">从内容计划选（点击选中）：</div>
              <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
                {plans.map((p) => {
                  const active = topic === p.topic
                  return (
                    <button
                      key={p.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() => setTopic(active ? '' : p.topic)}
                      className={chipClass(active)}
                    >
                      {p.topic}
                    </button>
                  )
                })}
              </div>
              <div className="text-[11px] text-[var(--yayu-muted)]">或手动输入主题：</div>
            </>
          ) : (
            <div className="text-[11px] text-[var(--yayu-muted)]">暂无内容计划，手动输入主题：</div>
          )}
          <input
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="例如：这项服务能提升品牌在模型回答中的出现率吗"
            className="w-full rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
          />
          <GeoButtonRow>
            <Button size="sm" disabled={!topic.trim()} onClick={() => setStep(2)}>
              下一步
            </Button>
          </GeoButtonRow>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="space-y-2">
          <div className="text-[12px] font-medium text-[var(--yayu-foreground)]">第二步 · 内容目标</div>
          {options(GOALS, goal, setGoal)}
          <GeoButtonRow>
            <Button size="sm" disabled={!goal} onClick={() => setStep(3)}>
              下一步
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setStep(1)}>
              上一步
            </Button>
          </GeoButtonRow>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="space-y-2">
          <div className="text-[12px] font-medium text-foreground">第三步 · 类型与风格（均为单选）</div>
          <div className="text-[11px] text-muted">内容类型</div>
          {options(CONTENT_TYPES, contentType, setContentType)}
          <div className="pt-1 text-[11px] text-muted">写作风格</div>
          {options(STYLES, style, setStyle)}
          <GeoButtonRow>
            <Button size="sm" disabled={!contentType || !style} onClick={() => setStep(4)}>
              下一步
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setStep(2)}>
              上一步
            </Button>
          </GeoButtonRow>
          {!contentType || !style ? (
            <p className="text-[10.5px] text-[var(--yayu-faint)]">
              需同时选择「类型」和「风格」后，「下一步」才会解锁
            </p>
          ) : null}
        </div>
      ) : null}

      {step === 4 ? (
        <div className="space-y-2">
          <div className="text-[12px] font-medium text-foreground">第四步 · 长度与平台（均为单选）</div>
          <div className="text-[11px] text-muted">篇幅</div>
          {options(LENGTHS, length, setLength)}
          <div className="pt-1 text-[11px] text-muted">发布平台</div>
          {options(PLATFORMS.map((p) => p.name), platform, setPlatform)}
          <div className="pt-1 text-[11px] text-muted">正文结构</div>
          {options(STRUCTURES.map((s) => s.label), STRUCTURES.find((s) => s.value === structure)?.label ?? null, (v) =>
            setStructure(STRUCTURES.find((s) => s.label === v)?.value ?? 'free'),
          )}
          <div className="pt-1 text-[11px] text-muted">资料依据模式</div>
          {options(MODES.map((m) => m.label), activeMode?.label ?? null, (v) =>
            setMode(MODES.find((m) => m.label === v)?.value ?? 'creative'),
          )}
          {activeMode ? <p className="text-[10.5px] text-[var(--yayu-faint)]">{activeMode.hint}</p> : null}
          <div className="pt-1 text-[11px] text-muted">行业（可留空，用于贴合行业语境的表达）</div>
          <input
            value={industry}
            onChange={(e) => setIndustry(e.target.value)}
            placeholder="例如：家装 / 工业质检 / 企业服务"
            className={inputClass}
          />
          {seoPlatform ? (
            <div className="space-y-1.5 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <div className="text-[11px] font-medium text-[var(--yayu-foreground)]">搜索平台参数（当前平台需要额外设置）</div>
              <input
                value={seoKeywords}
                onChange={(e) => setSeoKeywords(e.target.value)}
                placeholder="目标关键词（留空则用主题）"
                className={inputClass}
              />
              <input
                value={seoLongTail}
                onChange={(e) => setSeoLongTail(e.target.value)}
                placeholder="长尾关键词（逗号分隔，可留空）"
                className={inputClass}
              />
              <div className="flex items-center gap-2">
                <span className="shrink-0 text-[10.5px] text-[var(--yayu-muted)]">关键词密度 %</span>
                <input
                  value={seoDensity}
                  onChange={(e) => setSeoDensity(e.target.value)}
                  inputMode="numeric"
                  placeholder="3"
                  className={cn(inputClass, 'w-20')}
                />
                <span className="shrink-0 text-[10.5px] text-[var(--yayu-muted)]">调性</span>
                <select
                  value={seoTone}
                  onChange={(e) => setSeoTone(e.target.value)}
                  className={cn(inputClass, 'w-32')}
                >
                  <option value="professional">专业</option>
                  <option value="casual">通俗</option>
                  <option value="news">新闻</option>
                  <option value="authoritative">权威</option>
                </select>
              </div>
              <input
                value={seoAudience}
                onChange={(e) => setSeoAudience(e.target.value)}
                placeholder="目标受众（可留空）"
                className={inputClass}
              />
            </div>
          ) : null}
          {loading ? <GeoLoading text="内容生成中（约 30 秒）…" /> : null}
          {error ? <GeoError message={error} onRetry={() => setError(null)} /> : null}
          {result && result.ok === false ? (
            <div className="space-y-1 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <div className="text-[11px] font-medium text-[var(--yayu-foreground)]">严谨模式已拒绝生成</div>
              <ul className="space-y-0.5">
                {(result.unverified_facts ?? []).map((u, i) => (
                  <li key={i} className="text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">· {u.claim}</li>
                ))}
              </ul>
              <p className="text-[10.5px] text-[var(--yayu-faint)]">
                如这些声明是真实事实，请先补充到企业资料 / 内容资产，或切换「创作」模式后重新生成。
              </p>
            </div>
          ) : null}
          <GeoButtonRow>
            <Button size="sm" disabled={loading} onClick={() => void generate()}>
              {loading ? '生成中…' : '生成内容'}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setStep(3)}>
              上一步
            </Button>
          </GeoButtonRow>
        </div>
      ) : null}

      {step === 5 && result && result.ok !== false ? (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-[12px] text-[var(--yayu-muted)]">
            <Check className="size-3.5" /> 生成完成
          </div>
          <div className="max-h-56 overflow-y-auto rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-surface-raised)] px-3 py-2">
            <div className="text-[13px] font-medium text-[var(--yayu-foreground)]">{result.title}</div>
            <div className="mt-1 whitespace-pre-wrap text-[12px] leading-relaxed text-[var(--yayu-muted)]">
              {result.content}
            </div>
          </div>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10.5px] text-[var(--yayu-faint)]">
            {result.company_name ? <span>企业：{result.company_name}</span> : null}
            {result.materials_used == null || result.materials_used === 0 ? null : <span>参考资料：{result.materials_used} 条</span>}
            <span>结构：{result.structure === 'geo' ? '适合模型理解的结构' : '自由长文'}</span>
            <span>
              资料依据：
              {MODES.find((m) => m.value === (result.mode ?? 'creative'))?.label ?? result.mode ?? '创作'}
            </span>
          </div>
          {result.context_sources && result.context_sources.length > 0 ? (
            <div className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <div className="text-[11px] font-medium text-[var(--yayu-foreground)]">本篇写作依据（实际选段）</div>
              <div className="mt-1 space-y-1.5">
                {result.context_sources.map((s) => (
                  (s.items ?? []).length ? <div key={s.kind} className="text-[10.5px] text-[var(--yayu-muted)]">
                    <div>{s.label}（{s.items.length} 条）</div>
                    <ul className="mt-0.5 space-y-0.5 text-[var(--yayu-faint)]">
                      {s.items.slice(0, 5).map((item, i) => <li key={i}>· {sourceItemText(item) || '本条来源未提供可显示的原文片段'}</li>)}
                    </ul>
                  </div> : null
                ))}
              </div>
            </div>
          ) : <div className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2 text-[10.5px] text-[var(--yayu-muted)]">本篇来源未记录。请人工核对正文依据。</div>}
          {result.knowledge_status === 'not_synced' ? (
            <p className="text-[10.5px] text-[var(--yayu-muted)]">尚未同步知识库资料，不代表企业没有资料。</p>
          ) : result.knowledge_status === 'refused' ? (
            <p className="text-[10.5px] text-[var(--yayu-muted)]">本次知识库读取被拒绝，未使用旧快照补充依据。{result.knowledge_error?.message}</p>
          ) : result.knowledge_status === 'invalid_response' ? (
            <p className="text-[10.5px] text-[var(--yayu-muted)]">知识库返回格式有问题，不能视为没有资料。</p>
          ) : result.knowledge_status === 'partial' ? (
            <p className="text-[10.5px] text-[var(--yayu-muted)]">本次只读到部分知识库资料，请核对缺失部分。</p>
          ) : result.knowledge_status === 'unavailable' ? (
            <p className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2 text-[10.5px] text-[var(--yayu-muted)]">企业知识库这次未读到，以下草稿仅按可用素材写成，请核对。</p>
          ) : result.knowledge_status === 'empty' ? (
            <p className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2 text-[10.5px] text-[var(--yayu-muted)]">本次未找到相关知识库资料。</p>
          ) : result.knowledge_status === 'unknown' || (result.warnings?.length ?? 0) > 0 ? (
            <p className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2 text-[10.5px] text-[var(--yayu-muted)]">知识库资料读取情况未能确认，请核对本篇来源。</p>
          ) : null}
          {result.claim_check ? (
            <div className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <div className="text-[11px] font-medium text-[var(--yayu-foreground)]">人工核验提醒</div>
              {result.claim_check.status === 'no_flags' ? <p className="mt-0.5 text-[10.5px] text-[var(--yayu-muted)]">自动检查没有标出待核验说法；这不代表正文已经核实，请人工检查。</p> : (
                <ul className="mt-0.5 space-y-0.5">{result.claim_check.flags.map((flag, i) => <li key={i} className="text-[10.5px] text-[var(--yayu-muted)]">· {flag.claim}：{flag.reason}</li>)}</ul>
              )}
            </div>
          ) : null}
          {result.unverified_facts && result.unverified_facts.length > 0 ? (
            <div className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <div className="text-[11px] font-medium text-[var(--yayu-foreground)]">
                未验证声明（{result.unverified_facts.length} 条）
              </div>
              <ul className="mt-0.5 space-y-0.5">
                {result.unverified_facts.map((u, i) => (
                  <li key={i} className="text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">· {u.claim}</li>
                ))}
              </ul>
              <p className="mt-0.5 text-[10.5px] text-[var(--yayu-faint)]">
                这些声明未在企业资料或内容资产中找到依据，正文中不得写成已验证事实。
              </p>
            </div>
          ) : null}
          {result.market_signals?.available ? (
            <details className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <summary className="cursor-pointer text-[11px] font-medium text-[var(--yayu-foreground)]">
                写作时参考的市场信号（
                {[
                  result.market_signals.ai_answers?.length ? `模型当前回答 ${result.market_signals.ai_answers.length}` : null,
                  result.market_signals.hallucinations?.length ? `回答里缺少资料依据 ${result.market_signals.hallucinations.length}` : null,
                  result.market_signals.competitor_edges?.length ? `竞品优势 ${result.market_signals.competitor_edges.length}` : null,
                  result.market_signals.report_findings?.length ? `报告结论 ${result.market_signals.report_findings.length}` : null,
                ]
                  .filter(Boolean)
                  .join(' · ')}
                ，点击展开）
              </summary>
              <div className="mt-1 space-y-1.5">
                {result.market_signals.ai_answers?.length ? (
                  <div>
                    <div className="text-[10.5px] font-medium text-[var(--yayu-foreground)]">模型现在这样回答客户</div>
                    {result.market_signals.ai_answers.slice(0, 4).map((a, i) => (
                      <div key={i} className="text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">
                        · [{a.engine}] {a.mentioned ? '已提及本企业' : '未提及本企业'}：{a.question}
                      </div>
                    ))}
                  </div>
                ) : null}
                {result.market_signals.hallucinations?.length ? (
                  <div>
                    <div className="text-[10.5px] font-medium text-[var(--yayu-foreground)]">回答里缺少资料依据（正文须核对）</div>
                    {result.market_signals.hallucinations.map((h, i) => (
                      <div key={i} className="text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">· {h.claim}</div>
                    ))}
                  </div>
                ) : null}
                {result.market_signals.competitor_edges?.length ? (
                  <div>
                    <div className="text-[10.5px] font-medium text-[var(--yayu-foreground)]">竞品被提到、我方缺席的地方</div>
                    {result.market_signals.competitor_edges.map((c, i) => (
                      <div key={i} className="text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">
                        · {c.factor}
                        {c.competitor ? `（${c.competitor}）` : ''}
                      </div>
                    ))}
                  </div>
                ) : null}
                {result.market_signals.report_findings?.length ? (
                  <div>
                    <div className="text-[10.5px] font-medium text-[var(--yayu-foreground)]">周期报告结论</div>
                    {result.market_signals.report_findings.slice(0, 4).map((f, i) => (
                      <div key={i} className="text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">
                        · {f.title ?? (f.factors ? `竞品 ${f.competitor} 胜出：${f.factors.join('、')}` : `${f.dimension ?? ''} ${f.gap_type ?? ''}`)}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            </details>
          ) : null}
          {result.fact_check ? (
            <div className="space-y-1 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-[var(--yayu-foreground)]">资料依据覆盖</span>
                <span className="text-[11px] font-semibold text-[var(--yayu-foreground)]">
                  {result.fact_check.score == null ? '—' : `${Math.round(result.fact_check.score * 100)}%`}
                </span>
              </div>
              {result.fact_check.needs_rewrite ? (
                <>
                  <div className="text-[10.5px] text-[var(--yayu-muted)]">
                    企业资料里的关键事实还没全部写进正文，建议补充：
                  </div>
                  <ul className="space-y-0.5">
                    {(result.fact_check.missing_facts ?? []).slice(0, 5).map((m, i) => (
                      <li key={i} className="text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">· {m}</li>
                    ))}
                  </ul>
                  {/* 2026-09-21：知识库里一条带数字的事实都没有时，missing_facts 是空的，
                      上面就只剩「建议补充：」后面一片空白。后端其实给了 suggestion，把它如实显示出来。 */}
                  {!(result.fact_check.missing_facts ?? []).length && result.fact_check.suggestion ? (
                    <div className="text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">{result.fact_check.suggestion}</div>
                  ) : null}
                </>
              ) : (
                <div className="text-[10.5px] text-[var(--yayu-muted)]">已覆盖企业资料中的关键事实</div>
              )}
            </div>
          ) : null}
          {result.sections && Object.keys(result.sections).length > 0 ? (
            <details className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <summary className="cursor-pointer text-[11px] font-medium text-[var(--yayu-foreground)]">
                分段结构（{Object.keys(result.sections).length} 节，点击展开）
              </summary>
              <div className="mt-1 space-y-1.5">
                {Object.entries(result.sections).map(([name, body]) => (
                  <div key={name}>
                    <div className="text-[11px] font-medium text-[var(--yayu-foreground)]">{name}</div>
                    <div className="whitespace-pre-wrap text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">
                      {body}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          ) : null}
          {scoring ? <GeoLoading text="评分中…" /> : null}
          {score ? (
            <div className="space-y-1.5 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-[var(--yayu-foreground)]">结构参考分（不代表事实已核实或可以发布）</span>
                <span className="text-[12px] font-semibold text-[var(--yayu-foreground)]">{scoreTotalPct} 分</span>
              </div>
              <p className="text-[10px] text-[var(--yayu-faint)]">此分数只供内容结构参考，不能证明正文事实或资料依据已经核实。</p>
              {(
                [
                  ['企业信息覆盖', score.entity_coverage],
                  ['资料依据覆盖', score.fact_density],
                  ['客户问题覆盖', score.question_coverage],
                  ['内容结构完整', score.structure_completeness],
                  ['被引用可能', score.citation_potential],
                ] as Array<[string, number]>
              ).map(([label, value]) => (
                <div key={label} className="flex items-center gap-2">
                  <span className="w-14 shrink-0 text-[10px] text-[var(--yayu-muted)]">{label}</span>
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--yayu-surface-raised)]">
                    <div className="h-full bg-[var(--yayu-foreground)]" style={{ width: `${Math.min(100, value * 100)}%` }} />
                  </div>
                  <span className="w-8 shrink-0 text-right text-[10px] text-[var(--yayu-faint)]">{Math.round(value * 100)}</span>
                </div>
              ))}
              {score.suggestions && score.suggestions.length > 0 ? (
                <div className="pt-1">
                  <div className="text-[11px] font-medium text-[var(--yayu-muted)]">优化建议</div>
                  <ul className="mt-0.5 space-y-0.5">
                    {score.suggestions.slice(0, 4).map((s, i) => (
                      <li key={i} className="text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">
                        · {s}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
            <div className="text-[11px] font-medium text-[var(--yayu-foreground)]">按你的要求改这篇</div>
            <textarea
              value={improveText}
              onChange={(e) => setImproveText(e.target.value)}
              onKeyDown={(e) => {
                // 明确禁用回车发送：回车只换行，改稿只能点按钮
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  setImproveText((prev) => prev + '\n')
                }
              }}
              rows={2}
              placeholder={'例如：第二段太啰嗦，压到三句；把价格区间补进去'}
              className="mt-1 w-full resize-none rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
            />
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Button size="sm" disabled={improving || saving || !improveText.trim()} onClick={() => void runImprove()}>
                {improving ? '改进中…' : '按此改进'}
              </Button>
              <Button variant="secondary" size="sm" disabled={saving} onClick={() => void saveToAssets()}>
                {saving ? '保存中…' : '保存为内容资产'}
              </Button>
              <span className="text-[10.5px] text-[var(--yayu-faint)]">
                改进不会新增企业事实；保存后会出现在「企业资料 → 内容资产」
              </span>
            </div>
            {improveNote ? <p className="mt-1 text-[10.5px] text-[var(--yayu-muted)]">{improveNote}</p> : null}
            {savedNote ? <p className="mt-1 text-[10.5px] text-[var(--yayu-muted)]">{savedNote}</p> : null}
          </div>
          {quality ? <div className="content-quality"><b>结构参考分 · {quality.total == null && quality.score == null ? '—' : `${Math.round(quality.total ?? quality.score ?? 0)} 分`}</b><p>评分供结构参考，不代表内容可以发布。</p>{quality.suggestions?.slice(0,4).map((s,i)=><p key={i}>· {s}</p>)}</div> : null}
          <GeoButtonRow>
            <Button size="sm" onClick={() => void copyResult()}>
              <Copy className="size-3.5" /> {copied ? '已复制' : '复制'}
            </Button>
            <Button variant="secondary" size="sm" onClick={downloadResult}>
              <Download className="size-3.5" /> 下载
            </Button>
            <Button variant="secondary" size="sm" disabled={qualityLoading || improving || loading} onClick={() => void runQuality()}>
              {qualityLoading ? '内容检查中…' : '检查内容质量'}
            </Button>
            <Button variant="secondary" size="sm" disabled={saving} onClick={() => setStep(1)}>
              再生成一篇
            </Button>
          </GeoButtonRow>
        </div>
      ) : null}
    </GeoCardShell>
  )
}
