import { useEffect, useState } from 'react'
import { Check, Copy, Download } from 'lucide-react'
import { Button, cn } from '@yayu/ui'
import { geoGet, geoPost, type GeoPlan } from './geo-api'
import { GeoButtonRow, GeoCardShell, GeoError, GeoLoading, useGeoNavParams } from './shared'

const GOALS = ['提升AI推荐概率', '推广产品', '建立行业权威', '回答客户问题', '对抗竞品', '发布企业动态']
const CONTENT_TYPES = ['企业介绍', '行业解决方案', 'FAQ问答', '对比文章', '客户案例', '新闻动态']
const STYLES = ['专业权威', '技术专家', '营销转化', '新闻报道', '白皮书']
const LENGTHS = ['500字', '1500字', '3000字']
/** 展示名 → :3002 platform id；「通用」不传平台 */
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
  { name: '问答/帮助', id: 'seo_qa' },
]

interface GenResult {
  ok: boolean
  title: string
  content: string
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
  const [result, setResult] = useState<GenResult | null>(null)
  const [score, setScore] = useState<ScoreResult | null>(null)
  const [scoring, setScoring] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [quality, setQuality] = useState<QualityResult | null>(null)
  const [qualityLoading, setQualityLoading] = useState(false)

  // 从内容计划 / 错误认知跳过来时，把带过来的主题直接填进第 1 步（2026-09-21）
  useEffect(() => {
    if (!navNonce || !navSeed) return
    setTopic(navSeed)
    setStep(1)
  }, [navSeed, navNonce])

  // 拉取内容计划（status=planned 的可生成主题）
  useEffect(() => {
    let cancelled = false
    geoGet<{ items: GeoPlan[] }>('/distill/plans?status=planned&limit=20')
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
  }, [])

  const generate = async () => {
    if (!topic.trim() || !goal || !contentType || !style) return
    setLoading(true)
    setError(null)
    setScore(null)
    try {
      const platformId = PLATFORMS.find((p) => p.name === platform)?.id ?? null
      const d = await geoPost<GenResult>('/content/generate', {
        goal,
        content_type: contentType,
        style,
        length: length.replace('字', ''),
        platform: platformId,
        question: topic.trim(),
      })
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
          platform: platformId,
        })
        setScore(s)
      } catch {
        // 评分失败不阻塞结果展示
      } finally {
        setScoring(false)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '生成失败')
    } finally {
      setLoading(false)
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

  const runQuality = async () => {
    if (!result) return
    setQualityLoading(true)
    try { setQuality(await geoPost<QualityResult>('/content/quality', { content: result.content, question: topic })) }
    catch (e) { setError(e instanceof Error ? e.message : 'AI 质检失败') }
    finally { setQualityLoading(false) }
  }

  const chipClass = (active: boolean) =>
    cn(
      'cursor-pointer rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors',
      active
        ? 'border-accent bg-accent text-on-accent'
        : 'border-border bg-input text-muted hover:border-border-strong hover:text-foreground',
    )

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
            placeholder="例如：亚宇臻隆 GEO 服务能提升 AI 搜索可见度吗"
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
          {loading ? <GeoLoading text="内容生成中（约 30 秒）…" /> : null}
          {error ? <GeoError message={error} onRetry={() => setError(null)} /> : null}
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

      {step === 5 && result ? (
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
          {scoring ? <GeoLoading text="评分中…" /> : null}
          {score ? (
            <div className="space-y-1.5 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-2">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-medium text-[var(--yayu-foreground)]">可发布度</span>
                <span className="text-[12px] font-semibold text-[var(--yayu-foreground)]">{Math.round(score.total)} 分</span>
              </div>
              {(
                [
                  ['实体覆盖', score.entity_coverage],
                  ['事实密度', score.fact_density],
                  ['问题覆盖', score.question_coverage],
                  ['结构完整', score.structure_completeness],
                  ['引用潜力', score.citation_potential],
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
          {quality ? <div className="content-quality"><b>AI 质量检测 · {Math.round(quality.total ?? quality.score ?? 0)} 分</b>{quality.suggestions?.slice(0,4).map((s,i)=><p key={i}>· {s}</p>)}</div> : null}
          <GeoButtonRow>
            <Button size="sm" onClick={() => void copyResult()}>
              <Copy className="size-3.5" /> {copied ? '已复制' : '复制'}
            </Button>
            <Button variant="secondary" size="sm" onClick={downloadResult}>
              <Download className="size-3.5" /> 下载
            </Button>
            <Button variant="secondary" size="sm" disabled={qualityLoading} onClick={() => void runQuality()}>
              {qualityLoading ? 'AI 质检中…' : 'AI 质量检测'}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setStep(1)}>
              再生成一篇
            </Button>
          </GeoButtonRow>
        </div>
      ) : null}
    </GeoCardShell>
  )
}
