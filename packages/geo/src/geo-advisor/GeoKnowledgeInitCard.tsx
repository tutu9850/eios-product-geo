import { useCallback, useEffect, useState } from 'react'
import { Button } from '@yayu/ui'
import { Database, RefreshCw } from 'lucide-react'
import {
  geoGet,
  geoPost,
  type GeoKbInitApply,
  type GeoKbInitDocument,
  type GeoKbInitScan,
  type GeoProfileCategory,
  type GeoProfileOverview,
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
 *
 * 2026-09-21 Owner 拍板「3要」：把企业资料体检（enterprise-profile）跟这张卡摆到一起 ——
 * 不合并成同一个动作（一个是「你现在缺什么」，一个是「把你有的先搬进来」），而是
 * **初始化做完顺手给一张体检结论**：同一张卡下半部分，只读地显示 8 大类 48 子项
 * 的 足够 / 部分 / 太少 与总覆盖率，告诉人「搬完以后哪儿还缺」。体检走的是现成的
 * `GET /enterprise-profile/overview` 与 `/categories`，读，不写，不新增任何后端面。
 */

type Pick = { companies: Set<string>; products: Set<string>; documents: Set<string> }

// 企业知识库里可能同时出现员工/薪酬/客户等内部资料。初始化只应主动带入
// 面向产品事实的资料；敏感资料必须由用户逐项确认，避免误把人事或财务材料
// 写入 GEO 快照。
const SENSITIVE_DOCUMENT_RE = /(员工|雇员|薪酬|工资|薪资|客户|财务|薪税|合同|法务|人事|绩效|社保|employee|payroll|salary|customer|finance|contract|legal|hr)/i

function isSensitiveDocument(document: GeoKbInitDocument): boolean {
  return SENSITIVE_DOCUMENT_RE.test(`${document.title} ${document.document_id}`)
}

function allPicked(scan: GeoKbInitScan): Pick {
  return {
    companies: new Set(scan.candidates.companies.map((c) => c.name)),
    products: new Set(scan.candidates.products.map((p) => p.name)),
    // 敏感资料默认不选，用户仍可逐项打开并明确确认。
    documents: new Set(scan.candidates.documents.filter((d) => !isSensitiveDocument(d)).map((d) => d.document_id)),
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
  // 体检结论：与初始化同卡（Owner 2026-09-21「3要」）。读，不写。
  const [checkup, setCheckup] = useState<GeoProfileOverview | null>(null)
  const [checkupCats, setCheckupCats] = useState<GeoProfileCategory[] | null>(null)
  const [checkupOpen, setCheckupOpen] = useState(false)

  const loadCheckup = useCallback(async () => {
    try {
      const [ov, cats] = await Promise.all([
        geoGet<GeoProfileOverview>('/enterprise-profile/overview'),
        geoGet<{ categories: GeoProfileCategory[] }>('/enterprise-profile/categories'),
      ])
      setCheckup(ov)
      setCheckupCats(cats.categories ?? [])
    } catch {
      // 体检读不到不该把「扫描知识库」整卡带崩：这一块如实留空，下面会说明。
      setCheckup(null)
      setCheckupCats(null)
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const d = await geoPost<GeoKbInitScan>('/kb-init/scan')
      setScan(d)
      setPicked(allPicked(d))
      await loadCheckup()
    } catch (e) {
      setError(e instanceof Error ? e.message : '扫描知识库失败')
    } finally {
      setLoading(false)
    }
  }, [loadCheckup])

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
      setCheckupOpen(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : '写入 GEO 失败')
    } finally {
      setApplying(false)
    }
  }

  if (loading) return <GeoLoading text="正在扫描企业知识库…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />
  if (!scan) return null

  const allItems = (checkupCats ?? []).flatMap((c) => c.items)
  const tooLittle = allItems.filter((i) => i.level === '太少')
  const checkupAdvice =
    !checkup || checkup.total_items === 0
      ? '体检还没算出结果（后端没返回子项）。'
      : checkup.overall_coverage_pct === null
        ? '客户问题池还是空的，总覆盖率算不出来 —— 先去「问题池 / 监测」生成客户问题，再回来看这张结论。'
        : checkup.too_little_count === checkup.total_items
          ? `${checkup.total_items} 个子项全部「太少」。先补知识库，或去「内容计划」按子项生成要补的内容。`
          : `还差 ${checkup.too_little_count} 个子项${
              tooLittle.length ? `（例如 ${tooLittle.slice(0, 3).map((i) => i.name).join('、')}）` : ''
            }；去「内容计划」可以按子项一键生成要补的内容。`

  const pickedCount = picked.companies.size + picked.products.size + picked.documents.size
  const newCount =
    scan.candidates.companies.filter((c) => !c.in_profile && picked.companies.has(c.name)).length +
    scan.candidates.products.filter((p) => !p.in_profile && picked.products.has(p.name)).length +
    scan.candidates.documents.filter((d) => !d.in_profile && picked.documents.has(d.document_id)).length
  const sensitiveDocuments = scan.candidates.documents.filter(isSensitiveDocument)
  const sensitivePickedCount = sensitiveDocuments.filter((d) => picked.documents.has(d.document_id)).length

  // 文档这一桶：「未发布·快照」= 知识库里还没发布（文档列表看不到），候选来自 GEO 读到过的切块。
  const docBadge = (d: GeoKbInitDocument) =>
    d.listed === false
      ? `未发布·快照${d.chunks_stored ? ` ${d.chunks_stored} 块` : ''}`
      : d.in_profile
        ? '已纳入'
        : '新增'

  // 空选择的结果要单独说：别让它看起来像「记了 0 项」。
  const emptySelectionLine = result?.selection_empty
    ? result.first_time
      ? '工作空间已初始化。这次一项都没勾选：公司 / 产品 / 文档清单还是空的，公司资料随时可以回去勾。'
      : '工作空间已刷新。这次一项都没勾选：清单没有变化。'
    : null

  const resultLine = result
    ? result.first_time
      ? `第一次初始化完成：新增公司 ${result.added.companies.length} / 产品 ${result.added.products.length} / 文档 ${result.added.documents.length}，共 ${result.total.companies + result.total.products + result.total.documents} 项`
      : result.recorded
        ? `增量刷新：新增公司 ${result.added.companies.length} / 产品 ${result.added.products.length} / 文档 ${result.added.documents.length}，共 ${result.total.companies + result.total.products + result.total.documents} 项`
        : `增量刷新：知识库里没有新的（共 ${result.total.companies + result.total.products + result.total.documents} 项没变）`
    : null

  return (
    <GeoCardShell title="企业事实源" className="geo-profile-workbench">
      <div className="flex flex-wrap items-center gap-2">
        {/* Owner 2026-09-22：公司 / 产品 / 相关文档都可以不选 —— 不勾选不再锁按钮。
            知识库里只要有东西（哪怕只有对象、0 个文档），照样把 GEO 工作空间建起来。 */}
        <Button size="sm" onClick={() => void apply()} disabled={applying}>
          <Database className="size-3.5" />
          {applying
            ? '写入中…'
            : pickedCount === 0
              ? scan.initialized
                ? '刷新工作空间（不勾选也可以）'
                : '初始化工作空间（不勾选也可以）'
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

      {pickedCount === 0 && !result ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">
          一项都不勾也可以点：知识库里只要有资料，GEO 工作空间就会建起来（这次不往公司 / 产品 / 文档清单里记）。
        </p>
      ) : null}
      {sensitiveDocuments.length > 0 ? (
        <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-[11px] leading-relaxed text-[var(--yayu-muted)]">
          已识别 {sensitiveDocuments.length} 份可能包含员工、薪酬、客户、财务或合同信息的资料，默认未勾选。只有在确认确实需要用于 GEO 后才建议纳入
          {sensitivePickedCount > 0 ? `（当前已选 ${sensitivePickedCount} 份）` : ''}。
        </p>
      ) : null}
      {emptySelectionLine ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">{emptySelectionLine}</p>
      ) : null}
      {/* 空选择时不要再来一行「共 0 项」——那是同一件事的第二种说法。 */}
      {resultLine && !result?.selection_empty ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">{resultLine}</p>
      ) : null}
      {result?.selection_empty && result.captured ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">
          顺手带回 GEO 自己的库：企业知识对象 {result.captured.objects} 条、正式事实{' '}
          {result.captured.facts} 条、关系 {result.captured.relations} 条
          {result.captured.error ? `（有一项没读到：${result.captured.error}）` : ''}
        </p>
      ) : null}
      {result && (result.chunks_total ?? 0) > 0 ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">
          同步时一并带回 {result.chunks_total} 块文档切块，存进 GEO 自己的库（正本仍在知识库）
          {(result.chunks_truncated?.length ?? 0) > 0
            ? `；其中 ${result.chunks_truncated!.length} 份文档还有没读完的切块，这次只带回了前一部分`
            : ''}
        </p>
      ) : null}
      {result && result.unknown_documents.length > 0 ? (
        <p className="text-[11px] text-[var(--yayu-muted)]">
          这些文档在知识库里查不到，没记（{result.unknown_documents.join('、')}）
        </p>
      ) : null}

      {scan.empty ? (
        <div className="space-y-1">
          <p className="text-[12px] text-[var(--yayu-muted)]">
            {scan.hint ?? '知识库里没有可用的公司/产品/文档。'}
          </p>
          {/* 空态不等于「没得做」：不勾选也能初始化工作空间（Owner 2026-09-22）。 */}
          <p className="text-[11px] text-[var(--yayu-muted)]">
            没有可勾选的候选也没关系：不勾选直接点上面的按钮，工作空间照样建起来。
          </p>
        </div>
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
              <>
                {scan.candidates.documents.map((d) => (
                  <Row
                    key={d.document_id}
                    label={d.title || d.document_id}
                    checked={picked.documents.has(d.document_id)}
                    badge={isSensitiveDocument(d) ? `敏感·${docBadge(d)}` : docBadge(d)}
                    tone={d.listed === false ? 'new' : d.in_profile ? 'mine' : 'new'}
                    onToggle={() => toggle('documents', d.document_id)}
                  />
                ))}
                {scan.snapshot_note ? (
                  <p className="px-0.5 text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">
                    {scan.snapshot_note}
                  </p>
                ) : null}
              </>
            )}
          </div>
        </div>
      )}

      {checkup ? (
        <div className="space-y-1.5 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-surface-raised)] px-2 py-1.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[11.5px] font-semibold text-[var(--yayu-foreground)]">企业资料体检</span>
            <span className="text-[11px] text-[var(--yayu-muted)]">
              企业资料总覆盖率{' '}
              <span className="font-medium text-[var(--yayu-foreground)]">
                {checkup.overall_coverage_pct === null ? '算不出来' : `${checkup.overall_coverage_pct}%`}
              </span>
              （规则估算）
            </span>
            <span className="text-[11px] text-[var(--yayu-muted)]">
              共 {checkup.total_items} 个子项：足够 {checkup.enough_count} / 部分 {checkup.partial_count} / 太少{' '}
              {checkup.too_little_count}
            </span>
            {checkupCats && checkupCats.length > 0 ? (
              <button
                type="button"
                className="text-[11px] text-[var(--yayu-muted)] underline decoration-dotted underline-offset-2"
                onClick={() => setCheckupOpen((v) => !v)}
              >
                {checkupOpen ? '收起 8 大类' : `展开 8 大类（${checkupCats.length}）`}
              </button>
            ) : null}
          </div>
          <p className="text-[11px] leading-snug text-[var(--yayu-muted)]">建议：{checkupAdvice}</p>
          {checkupOpen && checkupCats ? (
            <div className="space-y-1">
              {checkupCats.map((c) => {
                const lv = (k: string) => c.items.filter((i) => i.level === k).length
                const short = c.items.filter((i) => i.level !== '足够').map((i) => i.name)
                return (
                  <div
                    key={c.category}
                    className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1"
                  >
                    <div className="flex flex-wrap items-baseline gap-x-2">
                      <span className="text-[11.5px] text-[var(--yayu-foreground)]">{c.name}</span>
                      <span className="text-[10.5px] text-[var(--yayu-muted)]">
                        足够 {lv('足够')} / 部分 {lv('部分')} / 太少 {lv('太少')}
                      </span>
                    </div>
                    {short.length > 0 ? (
                      <div className="mt-px text-[10.5px] leading-snug text-[var(--yayu-muted)]">
                        要补：{short.slice(0, 6).join('、')}
                        {short.length > 6 ? ` 等 ${short.length} 项` : ''}
                      </div>
                    ) : (
                      <div className="mt-px text-[10.5px] leading-snug text-[var(--yayu-muted)]">这一类都够</div>
                    )}
                  </div>
                )
              })}
            </div>
          ) : null}
          <p className="text-[10px] leading-snug text-[var(--yayu-muted)]">
            三档 = 子项相关问题覆盖率 ≥70% 足够 / ≥30% 部分 / &lt;30% 太少；覆盖率 = 全部客户问题里能被知识支撑的比例
            （COVERED=1、部分=0.5，规则估算，不是模型打分）。体检只读，不改任何数据。
          </p>
        </div>
      ) : null}

      <p className="text-[10.5px] leading-snug text-[var(--yayu-muted)]">
        存进的是 GEO 自己的快照（带来源与时间），正本仍在企业知识库；GEO 只读知识库，不往里写。
        {scan.error ? ` 这次文档读不到：${scan.error}` : ''}
      </p>
    </GeoCardShell>
  )
}
