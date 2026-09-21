import { useCallback, useEffect, useState } from 'react'
import { Button } from '@yayu/ui'
import { Database, RefreshCw } from 'lucide-react'
import {
  geoPost,
  type GeoKbInitApply,
  type GeoKbInitScan,
} from './geo-api'
import { GeoCardShell, GeoError, GeoLoading } from './shared'

/**
 * 知识库初始化（内测）—— 单独一个按钮：先搜知识库，筛出里面的公司 / 产品 / 相关文档，
 * 由人点选，再把选中的落进 GEO 自己的库。
 *
 * Owner 2026-09-21 的拍板就是这一句：「先搜知识库，筛选里面的公司和产品和相关文档，
 * 就是自动配置，让用户点击选择，单独一个按钮，内测用，后面就第一次 增量刷新，快照」。
 *
 * 所以这张卡有三件事必须说清楚，不能含糊：
 * 1. 候选是**读**出来的（GEO 只读知识库，不写）；
 * 2. 落库落的是 **GEO 自己的快照** —— 正本仍在知识库，界面要这么写；
 * 3. 第一次是全量，后面再点只补新的（增量刷新）；「和上次一样」是正常结果，不是错误。
 */

type Pick = { companies: Set<string>; products: Set<string>; documents: Set<string> }

function allPicked(scan: GeoKbInitScan): Pick {
  return {
    companies: new Set(scan.candidates.companies.map((c) => c.name)),
    products: new Set(scan.candidates.products.map((p) => p.name)),
    documents: new Set(scan.candidates.documents.map((d) => d.document_id)),
  }
}

function Row({
  label,
  checked,
  badge,
  tone,
  onToggle,
}: {
  label: string
  checked: boolean
  badge?: string
  tone?: 'new' | 'mine'
  onToggle: () => void
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1">
      <input
        type="checkbox"
        className="size-3.5 shrink-0 accent-[var(--yayu-primary,#3b82f6)]"
        checked={checked}
        onChange={onToggle}
      />
      <span className="min-w-0 flex-1 truncate text-[12px] text-[var(--yayu-foreground)]">{label}</span>
      {badge ? (
        <span
          className={
            tone === 'new'
              ? 'shrink-0 rounded bg-[var(--yayu-surface-raised)] px-1 py-px text-[9.5px] text-[var(--yayu-muted)]'
              : 'shrink-0 rounded bg-[var(--yayu-surface-raised)] px-1 py-px text-[9.5px] text-[var(--yayu-muted)] opacity-70'
          }
        >
          {badge}
        </span>
      ) : null}
    </label>
  )
}

export function GeoKnowledgeInitCard() {
  const [scan, setScan] = useState<GeoKbInitScan | null>(null)
  const [picked, setPicked] = useState<Pick>({ companies: new Set(), products: new Set(), documents: new Set() })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [applying, setApplying] = useState(false)
  const [result, setResult] = useState<GeoKbInitApply | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await geoPost<GeoKbInitScan>('/kb-init/scan')
      setScan(d)
      setPicked(allPicked(d))
    } catch (e) {
      setError(e instanceof Error ? e.message : '扫描知识库失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const toggle = (bucket: keyof Pick, key: string) => {
    setPicked((prev) => {
      const next = new Set(prev[bucket])
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return { ...prev, [bucket]: next }
    })
  }

  const apply = async () => {
    setApplying(true)
    setResult(null)
    try {
      const d = await geoPost<GeoKbInitApply>('/kb-init/apply', {
        companies: [...picked.companies],
        products: [...picked.products],
        documents: [...picked.documents],
      })
      setResult(d)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : '写入 GEO 失败')
    } finally {
      setApplying(false)
    }
  }

  if (loading) return <GeoLoading text="正在扫描企业知识库…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />
  if (!scan) return null

  const pickedCount = picked.companies.size + picked.products.size + picked.documents.size
  const newCount =
    scan.candidates.companies.filter((c) => !c.in_profile && picked.companies.has(c.name)).length +
    scan.candidates.products.filter((p) => !p.in_profile && picked.products.has(p.name)).length +
    scan.candidates.documents.filter((d) => !d.in_profile && picked.documents.has(d.document_id)).length

  const resultLine = result
    ? result.first_time
      ? `第一次初始化完成：新增公司 ${result.added.companies.length} / 产品 ${result.added.products.length} / 文档 ${result.added.documents.length}，共 ${result.total.companies + result.total.products + result.total.documents} 项`
      : result.recorded
        ? `增量刷新：新增公司 ${result.added.companies.length} / 产品 ${result.added.products.length} / 文档 ${result.added.documents.length}，共 ${result.total.companies + result.total.products + result.total.documents} 项`
        : `增量刷新：知识库里没有新的（共 ${result.total.companies + result.total.products + result.total.documents} 项没变）`
    : null

  return (
    <GeoCardShell title="🧪 知识库初始化（内测）">
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => void apply()} disabled={applying || pickedCount === 0}>
          <Database className="size-3.5" />
          {applying
            ? '写入中…'
            : scan.initialized
              ? `增量刷新进我的库（${pickedCount} 项）`
              : `初始化进我的库（${pickedCount} 项）`}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => void load()} disabled={loading || applying}>
          <RefreshCw className="size-3.5" /> 重新扫描知识库
        </Button>
        <span className="text-[11px] text-[var(--yayu-muted)]">
          {scan.initialized
            ? `已初始化过（上次 ${scan.last_applied_at ? scan.last_applied_at.slice(0, 19).replace('T', ' ') : '未知'}）`
            : '还没初始化过'}
          {newCount > 0 ? ` · 本次有新候选 ${newCount} 项` : ' · 没有新候选'}
        </span>
      </div>

      {resultLine ? <p className="text-[11px] text-[var(--yayu-muted)]">{resultLine}</p> : null}
      {result && result.unknown_documents.length > 0 ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">
          这些文档在知识库里查不到，没记（{result.unknown_documents.join('、')}）
        </p>
      ) : null}

      {scan.empty ? (
        <p className="text-[12px] text-[var(--yayu-muted)]">
          {scan.hint ?? '知识库里没有可用的公司/产品/文档。'}
        </p>
      ) : (
        <div className="space-y-2">
          <div className="space-y-1">
            <div className="text-[11px] text-[var(--yayu-muted)]">公司</div>
            {scan.candidates.companies.length === 0 ? (
              <p className="text-[11px] text-[var(--yayu-muted)]">知识库里没筛出公司名</p>
            ) : (
              scan.candidates.companies.map((c) => (
                <Row
                  key={c.name}
                  label={c.name}
                  checked={picked.companies.has(c.name)}
                  badge={c.in_profile ? '已纳入' : '新增'}
                  tone={c.in_profile ? 'mine' : 'new'}
                  onToggle={() => toggle('companies', c.name)}
                />
              ))
            )}
          </div>

          <div className="space-y-1">
            <div className="text-[11px] text-[var(--yayu-muted)]">产品</div>
            {scan.candidates.products.length === 0 ? (
              <p className="text-[11px] text-[var(--yayu-muted)]">知识库里没筛出产品名</p>
            ) : (
              scan.candidates.products.map((p) => (
                <Row
                  key={p.name}
                  label={p.name}
                  checked={picked.products.has(p.name)}
                  badge={p.in_profile ? '已纳入' : '新增'}
                  tone={p.in_profile ? 'mine' : 'new'}
                  onToggle={() => toggle('products', p.name)}
                />
              ))
            )}
          </div>

          <div className="space-y-1">
            <div className="text-[11px] text-[var(--yayu-muted)]">相关文档</div>
            {scan.candidates.documents.length === 0 ? (
              <p className="text-[11px] text-[var(--yayu-muted)]">知识库里没有文档</p>
            ) : (
              scan.candidates.documents.map((d) => (
                <Row
                  key={d.document_id}
                  label={d.title || d.document_id}
                  checked={picked.documents.has(d.document_id)}
                  badge={d.in_profile ? '已纳入' : '新增'}
                  tone={d.in_profile ? 'mine' : 'new'}
                  onToggle={() => toggle('documents', d.document_id)}
                />
              ))
            )}
          </div>
        </div>
      )}

      <p className="text-[10.5px] leading-snug text-[var(--yayu-muted)]">
        存进的是 GEO 自己的快照（带来源与时间），正本仍在企业知识库；GEO 只读知识库，不往里写。
        {scan.error ? ` 这次文档读不到：${scan.error}` : ''}
      </p>
    </GeoCardShell>
  )
}
