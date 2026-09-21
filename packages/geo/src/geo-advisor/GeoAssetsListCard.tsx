import { useCallback, useEffect, useRef, useState } from 'react'
import { Plus, Search, Trash2, Upload, X } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoDelete, geoGet, geoPost, geoPut, geoUpload, type GeoMaterial } from './geo-api'
import { GeoCardShell, GeoError, GeoLoading, askGeoConfirm } from './shared'

/**
 * 老 v1 的软失败：HTTP 200、`ok:true`，原因写在 `data.error` 里（envelope.py 的 `ok()`）。
 * 只看 HTTP 成功会把「文件太大」「提不出文本」当成上传成功，所以这里必须读它。
 */
function softError(data: { error?: unknown } | null): string | null {
  const message = data?.error
  return typeof message === 'string' && message ? message : null
}

/** 内容资产全库统计（文件管理器顶部那行） */
type AssetStats = { files?: number; chunks?: number; chars?: number; uploaded_files?: number }

/** 素材来源标签（文件管理器里给用户看的，不暴露接口字段名） */
const SOURCE_LABELS: Record<string, string> = {
  file: '上传文件',
  text: '手写素材',
  generated: '生成内容',
  faq: 'FAQ',
  url: '链接收录',
}
const SOURCE_FILTERS = [
  { id: 'all', label: '全部' },
  { id: 'file', label: '上传文件' },
  { id: 'text', label: '手写素材' },
  { id: 'generated', label: '生成内容' },
  { id: 'faq', label: 'FAQ' },
]

function sourceLabel(value?: string) {
  return SOURCE_LABELS[value ?? ''] ?? '素材'
}

function shortTime(value?: string) {
  if (!value) return ''
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatChars(n?: number) {
  const v = Number(n ?? 0)
  if (!v) return '0 字'
  if (v >= 10000) return `${(v / 10000).toFixed(1)} 万字`
  return `${v} 字`
}

/**
 * 内容资产 · 文件管理系统（Owner 2026-09-22）
 *
 * 「就一个文件管理系统，能看到上传什么了，可以删除，删除的时候就连着处理的切块一起删除，
 *  这里是 GEO 的数据，不是知识库半毛钱关系没有。」
 *
 * 所以这一页只读/只删 **GEO 自己的素材库**（`store.kb`，含每份素材切好的段）：
 * - 列表能看出：来源类型、原文件名、字数、切了几段、什么时候进库的；
 * - 删除 = 正文 + 它切好的段一起删（后端同一个库里一行记录，删了就都没了），删完如实报删了几段；
 * - 不写企业知识库、不向量化（向量只是 GEO 库里的检索索引，删素材时一并清掉）。
 *
 * 诚实说明：上传的原始文件本身**不入库**，这里存的是解析出来的正文与切块 ——
 * 所以删除只能删这份文本与切块，原始文件请自行留存。
 */
export function GeoAssetsListCard() {
  const [items, setItems] = useState<GeoMaterial[] | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [detailText, setDetailText] = useState<string | null>(null)
  const [detailChunks, setDetailChunks] = useState<number | null>(null)
  // 文件管理器：按来源筛选 + 全库统计 + 删除后的如实回执
  const [filter, setFilter] = useState('all')
  const [stats, setStats] = useState<AssetStats | null>(null)
  const [note, setNote] = useState<string | null>(null)
  // S4 发布打点：素材 → 已发布 URL（监测引用对上 citation）
  const [urlDraft, setUrlDraft] = useState<Record<string, string>>({})
  const [savingUrl, setSavingUrl] = useState<string | null>(null)
  // 新建 / 上传：Owner 2026-09-21「2要」—— 这一页能看能删，就得能往里放东西。
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [adding, setAdding] = useState(false)
  // 批量上传的进度（一次选多个文件时，「现在传到第几个」要让人看得见）
  const [progress, setProgress] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)

  const load = useCallback(async (q: string = '') => {
    setLoading(true)
    setError(null)
    try {
      const d = q
        ? await geoGet<{ items: GeoMaterial[]; stats?: AssetStats }>(
            `/knowledge/materials/search?q=${encodeURIComponent(q)}&top_k=8`,
          )
        : await geoGet<{ items: GeoMaterial[]; stats?: AssetStats }>('/knowledge/materials')
      setItems(d.items)
      // 检索结果没有全库统计（那是搜索命中，不是文件列表），保留上一次的统计别清空
      if (!q && d.stats) setStats(d.stats)
    } catch (e) {
      setError(e instanceof Error ? e.message : '内容资产加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const search = (e: React.FormEvent) => {
    e.preventDefault()
    void load(query.trim())
  }

  const resetSearch = () => {
    setQuery('')
    void load('')
  }

  const toggleDetail = async (id: string) => {
    if (detailId === id) {
      setDetailId(null)
      setDetailText(null)
      setDetailChunks(null)
      return
    }
    setDetailId(id)
    setDetailText(null)
    setDetailChunks(null)
    try {
      // 接口返回的是 { item, effects }：以前这里读 d.content，永远是 undefined →
      // 详情永远显示「（无内容）」（2026-09-21 修）。
      const d = await geoGet<{ item: GeoMaterial }>(`/knowledge/materials/${id}`)
      setDetailText(d.item?.content ?? '（无内容）')
      setDetailChunks(d.item?.chunks ?? null)
    } catch (e) {
      setDetailText(`详情加载失败：${e instanceof Error ? e.message : '未知错误'}`)
    }
  }

  const remove = async (title: string, id: string, chunks?: number) => {
    const chunkText = chunks ? `，连同它切好的 ${chunks} 段也一起删掉` : ''
    if (
      !(await askGeoConfirm(
        `删除后「${title}」会从 GEO 的内容资产里移除${chunkText}（正文与切块都在 GEO 自己的库里，删了不可恢复）。`,
      ))
    )
      return
    setError(null)
    setNote(null)
    try {
      const d = await geoDelete<{ chunks_removed?: number }>(`/knowledge/materials/${id}`)
      setNote(`已删除「${title}」，一并清掉 ${d?.chunks_removed ?? chunks ?? 0} 段切块。`)
      if (detailId === id) {
        setDetailId(null)
        setDetailText(null)
        setDetailChunks(null)
      }
      await load(query)
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  const saveUrl = async (id: string) => {
    const url = (urlDraft[id] ?? '').trim()
    if (!url) return
    setSavingUrl(id)
    try {
      await geoPut(`/knowledge/materials/${id}`, { published_url: url })
      await load(query)
    } catch (e) {
      setError(e instanceof Error ? e.message : '打点失败')
    } finally {
      setSavingUrl(null)
    }
  }

  const createMaterial = async () => {
    const t = title.trim()
    if (!t || adding) return
    setAdding(true)
    setError(null)
    try {
      const d = await geoPost<{ error?: string }>('/knowledge/materials', {
        title: t,
        content,
        source_type: 'text',
      })
      const soft = softError(d)
      if (soft) {
        setError(soft)
        return
      }
      setTitle('')
      setContent('')
      setCreating(false)
      await load(query)
    } catch (e) {
      setError(e instanceof Error ? e.message : '新建素材失败')
    } finally {
      setAdding(false)
    }
  }

  /**
   * 批量上传（Owner 2026-09-22「内容资产这里可以批量上传」）。
   *
   * 一次选多个文件，**逐个**上传（解析是同进程的重活，并发只会互相拖慢，也会让失败
   * 更难归因），过程中显示「正在上传 2/5：xxx」。收口必须如实分开三件事：
   * 全成功 / 部分失败（哪几个、为什么）/ 全失败 —— 不许把「有几份没进来」混成一句「已完成」。
   */
  const uploadFiles = async (files: File[]) => {
    if (!files.length) return
    setError(null)
    setNote(null)
    setAdding(true)
    const done: string[] = []
    const failed: string[] = []
    try {
      for (let i = 0; i < files.length; i += 1) {
        const f = files[i]
        setProgress(`正在上传 ${i + 1}/${files.length}：${f.name}`)
        try {
          const d = await geoUpload<{ error?: string }>('/knowledge/materials/upload', f)
          const soft = softError(d)
          if (soft) failed.push(`${f.name}：${soft}`)
          else done.push(f.name)
        } catch (e) {
          failed.push(`${f.name}：${e instanceof Error ? e.message : '上传失败'}`)
        }
      }
    } finally {
      setProgress(null)
      setAdding(false)
    }
    await load(query)
    if (!failed.length) {
      setNote(`已上传 ${done.length} 份：${done.join('、')}`)
    } else if (done.length) {
      setNote(`已上传 ${done.length} 份：${done.join('、')}；${failed.length} 份没进来 —— ${failed.join('；')}`)
    } else {
      setError(`这 ${failed.length} 份都没进来 —— ${failed.join('；')}`)
    }
  }

  const visibleItems = (items ?? []).filter((m) => filter === 'all' || (m.source_type ?? '') === filter)

  if (loading) return <GeoLoading text="内容资产加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  return (
    <GeoCardShell title="内容资产 · 文件管理" className="geo-assets-workbench">
      {/* 全库统计：这是 GEO 自己的库，跟企业知识库没关系 */}
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-[11px] text-[var(--yayu-muted)]">
        <span className="text-[12px] text-[var(--yayu-foreground)]">
          {stats?.files ?? items?.length ?? 0} 份素材
        </span>
        <span>其中上传文件 {stats?.uploaded_files ?? 0} 份</span>
        <span>共 {stats?.chunks ?? 0} 段切块</span>
        <span>{formatChars(stats?.chars)}</span>
        <span className="text-[10.5px]">存在 GEO 自己的库里；原始文件不入库，只存解析出的正文与切块</span>
      </div>

      {note ? <p className="text-[11px] text-[var(--yayu-muted)]">{note}</p> : null}

      {/* 搜索 */}
      <form onSubmit={search} className="flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-[var(--yayu-faint)]" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索素材（回车）"
            className="w-full rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] py-1.5 pl-8 pr-8 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
          />
          {query ? (
            <button
              type="button"
              onClick={resetSearch}
              aria-label="清除搜索"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--yayu-faint)]"
            >
              <X className="size-3.5" />
            </button>
          ) : null}
        </div>
      </form>

      {/* 按来源筛选（文件 / 手写 / 生成 / FAQ） */}
      <div className="flex flex-wrap items-center gap-1.5">
        {SOURCE_FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFilter(f.id)}
            aria-pressed={filter === f.id}
            className={`rounded-md border px-2 py-0.5 text-[11px] ${
              filter === f.id
                ? 'border-[var(--yayu-muted)] text-[var(--yayu-foreground)]'
                : 'border-[var(--yayu-border)] text-[var(--yayu-muted)]'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* 新建 / 上传：直接存进 GEO 自己的素材库（不走企业知识库的治理链） */}
      <div className="flex flex-wrap items-center gap-1.5">
        <Button variant="secondary" size="sm" onClick={() => setCreating((v) => !v)}>
          <Plus className="size-3.5" /> 新建素材
        </Button>
        <Button variant="secondary" size="sm" disabled={adding} onClick={() => fileInput.current?.click()}>
          <Upload className="size-3.5" /> {adding ? '处理中…' : '上传文件'}
        </Button>
        <span className="text-[10.5px] leading-snug text-[var(--yayu-muted)]">
          可一次选多个文件（20MB 内），逐个上传、逐个报结果；解析不出文本的那份会如实说。
        </span>
        <input
          ref={fileInput}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            const files = Array.from(e.target.files ?? [])
            e.target.value = ''
            if (files.length) void uploadFiles(files)
          }}
        />
      </div>

      {progress ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">
          {progress}
          {adding ? '（这份传完自动传下一个）' : ''}
        </p>
      ) : null}

      {creating ? (
        <div className="space-y-1.5 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1.5">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="素材标题（必填）"
            className="w-full rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={4}
            placeholder="素材正文（可留空，后面再补）"
            className="w-full resize-y rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[11.5px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
          />
          <div className="flex items-center gap-1.5">
            <Button variant="primary" size="sm" disabled={adding || !title.trim()} onClick={() => void createMaterial()}>
              {adding ? '保存中…' : '保存'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setCreating(false)}>
              取消
            </Button>
          </div>
        </div>
      ) : null}

      {!items || items.length === 0 ? (
        <p className="text-[12px] text-[var(--yayu-muted)]">
          还没有内容资产。上传公司资料/文章，或先「新建素材」写一份 —— 生成内容只吃这里的材料。
        </p>
      ) : visibleItems.length === 0 ? (
        <p className="text-[12px] text-[var(--yayu-muted)]">这个来源下没有素材，换个筛选看看。</p>
      ) : (
        <div className="space-y-1.5">
          {visibleItems.map((m) => {
            const id = m.material_id ?? m.id ?? m.title
            const active = detailId === id
            return (
              <div key={id} className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1">
                <div className="flex items-start justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => void toggleDetail(id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <span className="block text-[12px] leading-snug text-[var(--yayu-foreground)]">
                      {m.title}
                      {typeof m.chunk_ordinal === 'number' ? (
                        <span className="ml-1.5 text-[10.5px] text-[var(--yayu-muted)]">
                          命中第 {m.chunk_ordinal + 1} 段
                        </span>
                      ) : null}
                    </span>
                    <span className="mt-0.5 block text-[10.5px] text-[var(--yayu-muted)]">
                      {sourceLabel(m.source_type)}
                      {m.file_name ? ` · ${m.file_name}` : ''}
                      {` · ${formatChars(m.chars ?? m.content?.length)}`}
                      {` · ${m.chunks ?? 0} 段切块`}
                      {shortTime(m.created_at) ? ` · ${shortTime(m.created_at)}` : ''}
                    </span>
                    {!active ? (
                      <span className="mt-0.5 block truncate text-[11px] text-[var(--yayu-muted)]">
                        {/* 检索命中时显示命中的那一段，而不是整篇开头 60 字 */}
                        {m.snippet ?? m.content?.slice(0, 60) ?? ''}
                      </span>
                    ) : null}
                  </button>
                  <div className="flex shrink-0 items-center gap-1">
                    <Button variant="ghost" size="sm" onClick={() => void toggleDetail(id)}>
                      {active ? '收起' : '详情'}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => void remove(m.title, id, m.chunks)}
                      aria-label="删除素材及其切块"
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                </div>
                {active ? (
                  <>
                    <div className="mt-2 text-[10.5px] text-[var(--yayu-muted)]">
                      {(detailChunks ?? m.chunks)
                        ? `已切块 ${detailChunks ?? m.chunks} 段（切块与正文存在 GEO 自己的库；未向量化、不写企业知识库）`
                        : '还没切块（正文为空或上传早于切块）'}
                    </div>
                    <div className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-[var(--yayu-surface-raised)] p-2 text-[11px] leading-relaxed text-[var(--yayu-muted)]">
                      {detailText ?? '加载中…'}
                    </div>
                  </>
                ) : null}
                {active ? (
                  <div className="mt-1.5 flex items-center gap-1.5">
                    <input
                      value={urlDraft[id] ?? ''}
                      onChange={(e) => setUrlDraft((d) => ({ ...d, [id]: e.target.value }))}
                      placeholder={m.published_url ? `已发布：${m.published_url}` : '发布 URL（打点后监测可对上引用）'}
                      className="min-w-0 flex-1 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[11px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
                    />
                    <Button variant="secondary" size="sm" disabled={savingUrl === id} onClick={() => void saveUrl(id)}>
                      {savingUrl === id ? '打点中…' : m.published_url ? '更新' : '打点'}
                    </Button>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      )}
    </GeoCardShell>
  )
}
