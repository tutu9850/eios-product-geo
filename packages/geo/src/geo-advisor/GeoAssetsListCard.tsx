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

/** 内容资产卡：搜索 + 详情展开 + 删除（交互对齐 Builder GeoKb） */
export function GeoAssetsListCard() {
  const [items, setItems] = useState<GeoMaterial[] | null>(null)
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [detailId, setDetailId] = useState<string | null>(null)
  const [detailText, setDetailText] = useState<string | null>(null)
  const [detailChunks, setDetailChunks] = useState<number | null>(null)
  // S4 发布打点：素材 → 已发布 URL（监测引用对上 citation）
  const [urlDraft, setUrlDraft] = useState<Record<string, string>>({})
  const [savingUrl, setSavingUrl] = useState<string | null>(null)
  // 新建 / 上传：Owner 2026-09-21「2要」—— 这一页能看能删，就得能往里放东西。
  const [creating, setCreating] = useState(false)
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [adding, setAdding] = useState(false)
  const fileInput = useRef<HTMLInputElement | null>(null)

  const load = useCallback(async (q: string = '') => {
    setLoading(true)
    setError(null)
    try {
      const d = q
        ? await geoGet<{ items: GeoMaterial[] }>(`/knowledge/materials/search?q=${encodeURIComponent(q)}&top_k=8`)
        : await geoGet<{ items: GeoMaterial[] }>('/knowledge/materials')
      setItems(d.items)
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

  const remove = async (id: string) => {
    if (!(await askGeoConfirm('删除后这份素材会从内容资产里移除，引用统计不再计入。'))) return
    setError(null)
    try {
      await geoDelete(`/knowledge/materials/${id}`)
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

  const uploadFile = async (file: File) => {
    setError(null)
    setAdding(true)
    try {
      const d = await geoUpload<{ error?: string }>('/knowledge/materials/upload', file)
      const soft = softError(d)
      if (soft) {
        setError(soft)
        return
      }
      await load(query)
    } catch (e) {
      setError(e instanceof Error ? e.message : '上传失败')
    } finally {
      setAdding(false)
    }
  }

  if (loading) return <GeoLoading text="内容资产加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  return (
    <GeoCardShell title={`资产目录 · ${items?.length ?? 0} 个素材`} className="geo-assets-workbench">
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

      {/* 新建 / 上传：直接存进 GEO 自己的素材库（不走企业知识库的治理链） */}
      <div className="flex flex-wrap items-center gap-1.5">
        <Button variant="secondary" size="sm" onClick={() => setCreating((v) => !v)}>
          <Plus className="size-3.5" /> 新建素材
        </Button>
        <Button variant="secondary" size="sm" disabled={adding} onClick={() => fileInput.current?.click()}>
          <Upload className="size-3.5" /> {adding ? '处理中…' : '上传文件'}
        </Button>
        <span className="text-[10.5px] leading-snug text-[var(--yayu-muted)]">
          文件支持 txt / md / csv / pdf / docx / xlsx / 图片（20MB 内），解析不出文本会如实报错。
        </span>
        <input
          ref={fileInput}
          type="file"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            e.target.value = ''
            if (file) void uploadFile(file)
          }}
        />
      </div>

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
        <p className="text-[12px] text-[var(--yayu-muted)]">暂无素材，先上传知识材料。</p>
      ) : (
        <div className="space-y-1.5">
          {items.map((m) => {
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
                      {m.chunks ? (
                        <span className="ml-1.5 text-[10.5px] text-[var(--yayu-muted)]">{m.chunks} 段</span>
                      ) : null}
                    </span>
                    {!active ? (
                      <span className="mt-0.5 block truncate text-[11px] text-[var(--yayu-muted)]">
                        {m.content?.slice(0, 60) ?? ''}
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
                      onClick={() => void remove(id)}
                      aria-label="删除素材"
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
