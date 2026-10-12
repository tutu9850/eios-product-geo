import { useEffect, useState } from 'react'
import { Check, Download } from 'lucide-react'
import { Button } from '@yayu/ui'
import {
  geoGet,
  geoPost,
  type GeoCreateResult,
  type GeoDetectResult,
  type GeoDiscoverResult,
  type GeoDistillResult,
  type GeoRunResult,
  type GeoRunStatus,
} from './geo-api'
import { GeoButtonRow, GeoCardShell, GeoError, GeoList, GeoLoading, GeoRow, useGeoNav } from './shared'
import { useMonitorSubjects } from './geo-monitor-subject'

type FlowStep = 'detect' | 'discover' | 'create' | 'run' | 'distill' | 'schedule' | 'report'

function uniqueNames(values: string[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const name = value.trim()
    if (!name || seen.has(name)) continue
    seen.add(name)
    result.push(name)
  }
  return result
}

/**
 * 自动配置流程卡（7 步固定状态机，前端代码驱动，不经大模型）：
 * detect → discover → create → run → distill → schedule → report
 * 按钮点击直接调 GEO 接口，聊天记录干净。
 */
export function AutoConfigFlow({ onClose }: { onClose?: () => void }) {
  const go = useGeoNav()
  const { subjects: activeBrandSubjects, loaded: subjectsLoaded } = useMonitorSubjects()
  const [step, setStep] = useState<FlowStep>('detect')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [detect, setDetect] = useState<GeoDetectResult | null>(null)
  const [discover, setDiscover] = useState<GeoDiscoverResult | null>(null)
  const [create, setCreate] = useState<GeoCreateResult | null>(null)
  const [distill, setDistill] = useState<GeoDistillResult | null>(null)
  const [manualOpen, setManualOpen] = useState(false)
  const [manualText, setManualText] = useState('')
  const [schedule, setSchedule] = useState<'daily' | 'weekly' | 'none' | null>(null)
  const [status, setStatus] = useState<{ items: number; questions: number } | null>(null)
  // 步骤 4 · 监测运行进度（轮询 /onboard/run-status，实时展示进程）
  const [runProgress, setRunProgress] = useState<GeoRunStatus | null>(null)
  const [polling, setPolling] = useState(false)
  // 第 1 步产品/服务可勾选（默认全选，点击取消不想监测的）
  const [selectedProducts, setSelectedProducts] = useState<Set<string>>(new Set())
  const [selectedServices, setSelectedServices] = useState<Set<string>>(new Set())
  // 公司可多选（chips；第一个是主名，其余作为别名一起监测）+ 行业文本输入
  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([])
  const [companyDraft, setCompanyDraft] = useState('')
  const [industryText, setIndustryText] = useState('')
  // 第 1 步产品手填（2026-09-22）：材料里没认出产品名时不再拿文件名充数，
  // 后端如实留空 + 提示；这里必须给人一条手动补的通道，否则「确认继续」点不动。
  const [productDraft, setProductDraft] = useState('')
  // 服务也能手填（与产品同一套：手填的进 chips，也能点掉）
  const [serviceDraft, setServiceDraft] = useState('')
  // 所在地（Owner 2026-09-21）：竞品发现按「{城市}的{行业}都有哪些公司」去问。
  // 以前只能从公司名里抠城市，「笔革家居」抠不出来 → 退化成全国结果（实测返回的是
  // 三维家/酷家乐这类平台，不是成都本地的家装公司），所以这里让用户直接填。
  const [cityText, setCityText] = useState('')
  const [identityOverride, setIdentityOverride] = useState(false)
  // 第 2 步竞品可勾选（按名字保存 + localStorage 持久化，刷新/重进保留）
  const [selectedCompetitorNames, setSelectedCompetitorNames] = useState<Set<string>>(loadSavedCompetitors())

  // 产品 chips = 检测到的 + 手填的（手填的也要能点掉，不然加错了没法撤）
  const productChips = uniqueNames([
    ...(detect?.products ?? []),
    ...[...selectedProducts].filter((p) => !(detect?.products ?? []).includes(p)),
  ])
  // 第一个勾选的公司 = 主名，其余 = 别名（一起当作「我们自己」监测）
  const primaryCompany = selectedCompanies[0] ?? detect?.company?.[0] ?? ''
  const aliasCompanies = selectedCompanies.slice(1)
  const serviceChips = uniqueNames([
    ...(detect?.services ?? []),
    ...[...selectedServices].filter((s) => !(detect?.services ?? []).includes(s)),
  ])
  const companyChips = uniqueNames([
    ...(detect?.company ?? []),
    ...selectedCompanies.filter((name) => !(detect?.company ?? []).includes(name)),
  ])
  const activeBrandNames = uniqueNames(activeBrandSubjects.map((subject) => subject.name))
  const identityConflict = subjectsLoaded && Boolean(primaryCompany) && activeBrandNames.length > 0 && !activeBrandNames.includes(primaryCompany)

  // ── 竞品勾选持久化（刷新页面/重新进入后保留）──
  function loadSavedCompetitors(): Set<string> {
    try {
      const raw = window.localStorage.getItem('geo-flow-competitors-v1')
      if (!raw) return new Set()
      return new Set(JSON.parse(raw) as string[])
    } catch {
      return new Set()
    }
  }

  const saveCompetitors = (names: Set<string>) => {
    try {
      window.localStorage.setItem('geo-flow-competitors-v1', JSON.stringify([...names]))
    } catch {
      // 存储不可用时静默
    }
  }

  const run = async (fn: () => Promise<void>) => {
    setLoading(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败')
    } finally {
      setLoading(false)
    }
  }

  // 第 1 步 · 检测企业实体（挂载即执行；「调整」= 重新检测，不刷新页面）
  const runDetect = () =>
    void run(async () => {
      const d = await geoPost<GeoDetectResult>('/onboard/auto-config', { step: 'detect' })
      setDetect(d)
      const companies = uniqueNames(d.company ?? [])
      const products = uniqueNames(d.products ?? [])
      // 首配默认保持最小监测范围：一个主品牌 + 一个产品。其余候选必须由
      // 用户主动勾选，避免一键生成大量对象或把内部服务误当作对外品牌。
      setSelectedProducts(new Set(products.slice(0, 1)))
      setSelectedServices(new Set())
      setSelectedCompanies(companies.slice(0, 1))
      setIndustryText(d.industry ?? '')
      setStep('detect')
    })

  useEffect(() => {
    void runDetect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggleProduct = (p: string) =>
    setSelectedProducts((prev) => {
      const next = new Set(prev)
      if (next.has(p)) next.delete(p)
      else next.add(p)
      return next
    })

  const toggleService = (s: string) =>
    setSelectedServices((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })

  const toggleCompany = (c: string) =>
    setSelectedCompanies((prev) => (prev.includes(c) ? prev.filter((x) => x !== c) : [...prev, c]))

  const addServiceDraft = () => {
    const name = serviceDraft.trim()
    if (!name) return
    setSelectedServices((prev) => new Set(prev).add(name))
    setServiceDraft('')
  }

  const addCompanyDraft = () => {
    const name = companyDraft.trim()
    if (!name) return
    setSelectedCompanies((prev) => (prev.includes(name) ? prev : [...prev, name]))
    setCompanyDraft('')
  }

  const addProductDraft = () => {
    const name = productDraft.trim()
    if (!name) return
    setSelectedProducts((prev) => new Set(prev).add(name))
    setProductDraft('')
  }

  // 第 2 步 · 竞品发现（「刷新竞品」= 重新调 discover；已勾选按名字保留）
  const runDiscover = () =>
    void run(async () => {
      const d = await geoPost<GeoDiscoverResult>('/onboard/auto-config', {
        step: 'discover',
        products: uniqueNames([...selectedProducts]),
        services: uniqueNames([...selectedServices]),
        company: primaryCompany,
        aliases: aliasCompanies,
        industry: industryText.trim(),
        city: cityText.trim(),
      })
      const names = d.competitors?.map((c) => c.name) ?? []
      setSelectedCompetitorNames((prev) => {
        // 保留旧勾选（含 localStorage 持久化的）+ 新出现的默认勾选
        const next = new Set<string>()
        for (const n of names) {
          if (prev.has(n)) next.add(n)
        }
        for (const n of names) {
          next.add(n)
        }
        saveCompetitors(next)
        return next
      })
      setDiscover(d)
      setStep('discover')
    })

  const toggleCompetitor = (name: string) =>
    setSelectedCompetitorNames((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      saveCompetitors(next)
      return next
    })

  const runCreate = (competitors: Array<{ name: string; company?: string }>) =>
    void run(async () => {
      const c = await geoPost<GeoCreateResult>('/onboard/auto-config', {
        step: 'create',
        company: primaryCompany,
        aliases: aliasCompanies,
        products: uniqueNames([...selectedProducts]),
        services: uniqueNames([...selectedServices]),
        industry: industryText.trim(),
        city: cityText.trim(),
        competitors: competitors.filter((candidate, index, all) =>
          candidate.name.trim() && all.findIndex((item) => item.name.trim() === candidate.name.trim()) === index,
        ).map((candidate) => ({ ...candidate, name: candidate.name.trim() })),
        // 不传 keywords：监测对象只建勾选的产品/服务/竞品，不为未勾选关键词建 keyword 监测
      })
      setCreate(c)
      setStep('create')
    })

  const runMonitor = () =>
    void run(async () => {
      await geoPost<GeoRunResult>('/onboard/auto-config', {
        step: 'run',
        monitor_ids: (create?.created ?? []).map((c) => c.monitor_id),
      })
      setRunProgress(null)
      setPolling(true)
      setStep('run')
    })

  // 步骤 4 · 轮询监测进度（2 秒一次，跑完自动停）
  useEffect(() => {
    if (!polling) return
    const timer = window.setInterval(async () => {
      try {
        const s = await geoGet<GeoRunStatus>('/onboard/run-status')
        setRunProgress(s)
        if (s.finished || !s.running) {
          setPolling(false)
        }
      } catch {
        // 单次轮询失败不中断，等下一次
      }
    }, 2_000)
    return () => window.clearInterval(timer)
  }, [polling])

  const runDistill = () =>
    void run(async () => {
      const d = await geoPost<GeoDistillResult>('/onboard/auto-config', { step: 'distill' })
      setDistill(d)
      setStep('distill')
    })

  const runSchedule = () =>
    void run(async () => {
      if (!schedule) return
      if (schedule !== 'none') {
        await geoPost('/monitor/tasks', {
          name: 'GEO 自动监测',
          schedule,
          item_ids: (create?.created ?? []).map((c) => c.monitor_id),
        })
      }
      const s = await geoGet<{ items: number; questions: number }>('/onboard/status')
      setStatus(s)
      setStep('report')
    })

  const exportReport = () => {
    const lines = [
      '# GEO 自动配置阶段报告',
      '',
      `- 监测对象：${create?.created?.length ?? 0} 个`,
      `- 内容资产：${status?.items ?? '—'} 个`,
      `- 客户问题：${status?.questions ?? '—'} 个`,
      `- 定时任务：${schedule === 'daily' ? '每日监测' : schedule === 'weekly' ? '每周报告' : '未设定'}`,
      '',
    ]
    const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'GEO自动配置报告.md'
    anchor.click()
    URL.revokeObjectURL(url)
  }

  // 后退：按流程顺序回上一步（除第一步 detect 外均可返回）
  const stepBack = () => {
    const order: FlowStep[] = ['detect', 'discover', 'create', 'run', 'distill', 'schedule', 'report']
    const idx = order.indexOf(step)
    if (idx > 0) setStep(order[idx - 1])
  }

  if (loading) return <GeoLoading text="首次设置进行中…" />
  if (error) return <GeoError message={error} onRetry={() => setError(null)} />

  const competitors = (discover?.competitors ?? []).filter(
    (candidate, index, all) => all.findIndex((item) => item.name.trim() === candidate.name.trim()) === index,
  )

  return (
    <GeoCardShell title="第一次使用：从企业资料到模型监测">
      {/* 步骤指示 */}
      <div className="flex flex-wrap items-center gap-1 text-[10px] text-[var(--yayu-faint)]">
        {(
          [
            ['detect', '确认企业资料'],
            ['discover', '查找竞品'],
            ['create', '确认监测范围'],
            ['run', '运行首轮监测'],
            ['distill', '生成问题与缺口'],
            ['schedule', '设置自动监测'],
            ['report', '查看结果'],
          ] as Array<[FlowStep, string]>
        ).map(([id, label], index) => (
          <span key={id} className="flex items-center gap-1">
            {index > 0 ? <span className="text-[var(--yayu-faint)]/50">·</span> : null}
            <span className={id === step ? 'font-medium text-[var(--yayu-foreground)]' : ''}>{label}</span>
          </span>
        ))}
      </div>

      {/* 步骤 1 · 检测企业实体 */}
      {step === 'detect' ? (
        detect?.empty ? (
          <>
            <p className="text-[12px] leading-relaxed text-[var(--yayu-muted)]">
              {detect?.hint
                ? detect.hint
                  : detect?.error
                  ? `企业资料暂时读不到：${detect.error}`
                  : '还没有可用的企业资料，无法自动推断。请先补充产品或案例材料，再重新检测。'}
            </p>
            <GeoButtonRow>
              <Button size="sm" onClick={runDetect}>
                重新检测
              </Button>
              <Button variant="secondary" size="sm" onClick={onClose}>
                结束
              </Button>
            </GeoButtonRow>
          </>
        ) : (
          <>
            {/* 公司：可多选（第一个是主名，其余作为别名一起监测） */}
            <div className="pt-1">
              <div className="mb-1 text-[12px] font-medium text-[var(--yayu-foreground)]">
                先确认企业名称
              </div>
              <details className="auto-config-candidate-fold" open={companyChips.length <= 3}>
                <summary><span>候选名称</span><small>已选 {selectedCompanies.length} 个 · {selectedCompanies.slice(0, 2).join('、') || '还没选'}</small></summary>
                <div className="flex flex-wrap gap-1.5">
                  {companyChips.map((c) => {
                    const active = selectedCompanies.includes(c)
                    return (
                      <button
                        key={c}
                        type="button"
                        onClick={() => toggleCompany(c)}
                        className={`rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors ${
                          active
                            ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                            : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-muted)] hover:border-[var(--yayu-muted)]'
                        }`}
                      >
                        {c}
                      </button>
                    )
                  })}
                </div>
              </details>
              {companyChips.length === 0 ? <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">资料里暂时没有识别到可信的企业名。不要用文件名代替企业名，请手动填写，或先补一份公司介绍。</p> : null}
              {companyChips.length > 0 ? <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">这些是从资料中识别出的候选名称，不代表系统已经确认主体；请先核对再继续。</p> : null}
              <div className="mt-1.5 flex items-center gap-1.5">
                <input
                  value={companyDraft}
                  onChange={(e) => setCompanyDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      addCompanyDraft()
                    }
                  }}
                  placeholder="手动填写企业/品牌名，回车确认"
                  className="min-w-0 flex-1 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
                />
                <Button variant="secondary" size="sm" onClick={addCompanyDraft} disabled={!companyDraft.trim()}>添加</Button>
              </div>
              <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">第一个名称作为主品牌；只有你主动选中的其他名称才会作为别名监测。</p>
              {identityConflict ? (
                <div role="alert" className="mt-2 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-surface-raised)] px-2.5 py-2 text-[11px] leading-relaxed text-[var(--yayu-muted)]">
                  <b className="text-[var(--yayu-foreground)]">资料名称与当前监测主体不一致</b>
                  <p className="mt-0.5">资料检测到“{primaryCompany}”，当前启用的企业监测主体是“{activeBrandNames.join('、')}”。系统不会自动把两个名字合并；先确认主体，避免把回答和企业资料错配。</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <button type="button" className="text-[10.5px] font-medium text-[var(--yayu-foreground)] underline decoration-dotted" onClick={() => go?.('monitor')}>去确认监测主体 →</button>
                    <label className="inline-flex items-center gap-1 text-[10.5px] text-[var(--yayu-muted)]">
                      <input type="checkbox" checked={identityOverride} onChange={(event) => setIdentityOverride(event.target.checked)} className="size-3" />
                      我确认这是另一个品牌主体
                    </label>
                  </div>
                </div>
              ) : null}
            </div>
            {/* 行业：可文本输入（默认填检测结果，可修改） */}
            <div className="pt-1">
              <div className="mb-1 text-[12px] font-medium text-[var(--yayu-foreground)]">行业（可修改）</div>
              <input
                value={industryText}
                onChange={(e) => setIndustryText(e.target.value)}
                placeholder="输入所属行业"
                className="w-full rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1.5 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
              />
            </div>
            {/* 所在地：竞品发现按「成都本地的家装都有哪些公司」这类问法去问；留空则退回从公司名抠 */}
            <div className="pt-1">
              <div className="mb-1 text-[12px] font-medium text-[var(--yayu-foreground)]">所在地（用于发现本地同行）</div>
              <input
                value={cityText}
                onChange={(e) => setCityText(e.target.value)}
                placeholder="如：成都（留空则从公司名里找）"
                className="w-full rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1.5 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
              />
            </div>
            <div className="pt-1">
              <div className="mb-1 text-[12px] font-medium text-[var(--yayu-foreground)]">
                选择要监测的产品
              </div>
              <details className="auto-config-candidate-fold" open={productChips.length <= 3}>
                <summary><span>候选产品</span><small>已选 {selectedProducts.size}/{productChips.length || 0} 个</small></summary>
                <div className="flex flex-wrap gap-1.5">
                  {productChips.map((p) => {
                    const active = selectedProducts.has(p)
                    return (
                      <button
                        key={p}
                        type="button"
                        onClick={() => toggleProduct(p)}
                        className={`rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors ${
                          active
                            ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                            : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-faint)] line-through hover:border-[var(--yayu-muted)]'
                        }`}
                      >
                        {p}
                      </button>
                    )
                  })}
                  {productChips.length === 0 ? <span className="text-[11px] text-[var(--yayu-muted)]">材料里没认出产品名</span> : null}
                </div>
                {detect?.hint ? <p className="mt-1 text-[10.5px] leading-relaxed text-[var(--yayu-muted)]">{detect.hint}</p> : null}
                <div className="mt-1.5 flex items-center gap-1.5">
                  <input
                    value={productDraft}
                    onChange={(e) => setProductDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addProductDraft()
                      }
                    }}
                    placeholder="手动加产品名，回车确认"
                    className="min-w-0 flex-1 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
                  />
                  <Button variant="secondary" size="sm" onClick={addProductDraft} disabled={!productDraft.trim()}>添加</Button>
                </div>
              </details>
            </div>
            {/* 服务：与产品同一套（chips + 手填）。选中会各建一个监测对象，探针按服务问法问。 */}
            <div className="pt-1">
              <div className="mb-1 text-[12px] font-medium text-[var(--yayu-foreground)]">
                服务（可选）
              </div>
              <details className="auto-config-candidate-fold">
                <summary><span>候选服务</span><small>已选 {selectedServices.size}/{serviceChips.length || 0} 个</small></summary>
                <div className="flex flex-wrap gap-1.5">
                  {serviceChips.map((s) => {
                    const active = selectedServices.has(s)
                    return (
                      <button
                        key={s}
                        type="button"
                        onClick={() => toggleService(s)}
                        className={`rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors ${
                          active
                            ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                            : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-faint)] line-through hover:border-[var(--yayu-muted)]'
                        }`}
                      >
                        {s}
                      </button>
                    )
                  })}
                  {serviceChips.length === 0 ? <span className="text-[11px] text-[var(--yayu-muted)]">材料里没认出服务名</span> : null}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5">
                  <input
                    value={serviceDraft}
                    onChange={(e) => setServiceDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        addServiceDraft()
                      }
                    }}
                    placeholder="手动加服务名，回车确认"
                    className="min-w-0 flex-1 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
                  />
                  <Button variant="secondary" size="sm" onClick={addServiceDraft} disabled={!serviceDraft.trim()}>添加</Button>
                </div>
              </details>
            </div>
            {detect && detect.keywords.length > 0 ? (
              <p className="text-[11px] text-[var(--yayu-muted)]">关键词：{detect.keywords.join('、')}</p>
            ) : null}
            <p className="rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-surface-raised)] px-2 py-1.5 text-[11px] leading-relaxed text-[var(--yayu-muted)]">
              当前范围：{selectedCompanies.length > 0 ? 1 : 0} 个主品牌 · {selectedProducts.size} 个产品 · {selectedServices.size} 个服务。
              继续后只会按这个范围发现竞品，后续创建前还会再次显示对象总数。
            </p>
            <GeoButtonRow>
              <Button
                size="sm"
                onClick={runDiscover}
                disabled={identityConflict && !identityOverride || (selectedProducts.size === 0 && selectedServices.size === 0)}
              >
                下一步：查找竞品
              </Button>
              <Button variant="secondary" size="sm" onClick={runDetect}>
                调整
              </Button>
            </GeoButtonRow>
          </>
        )
      ) : null}

      {/* 步骤 2 · 竞品发现 */}
      {step === 'discover' ? (
        competitors.length > 0 ? (
          <>
            <div className="mb-1 text-[12px] font-medium text-[var(--yayu-foreground)]">
              竞品候选（{competitors.filter((c) => selectedCompetitorNames.has(c.name)).length}/{competitors.length}，点击取消不想监测的）
            </div>
            {/* 诚实交代：问了几个模型、问了哪几句、城市哪来的 —— 不替部署吹牛说「已联网搜过」 */}
            {discover && (discover.engines_total ?? 0) > 0 ? (
              <p className="text-[10.5px] leading-relaxed text-[var(--yayu-faint)]">
                本次问了 {discover.engines_total} 个模型，{discover.engines_answered ?? 0} 个作答
                {discover.not_answered && discover.not_answered.length > 0
                  ? `（未作答：${discover.not_answered.join('、')}，通常是这个部署还没给它们配凭据）`
                  : ''}
                ；候选按「被多少个模型提到」排序，取前 10。
              </p>
            ) : null}
            {discover?.questions && discover.questions.length > 0 ? (
              <p className="text-[10.5px] leading-relaxed text-[var(--yayu-faint)]">
                提问：{discover.questions.join(' / ')}
              </p>
            ) : null}
            {discover?.city_source === 'company_name' ? (
              <p className="text-[10.5px] leading-relaxed text-[var(--yayu-faint)]">
                所在地「{discover.city}」是从公司名里读出来的。想按别的城市发现，回上一步填写。
              </p>
            ) : null}
            {discover?.city_source === 'none' ? (
              <p className="text-[10.5px] leading-relaxed text-[var(--yayu-faint)]">
                没有填所在地，这次是按「本地」问的 —— 结果可能不限于你所在的城市。回上一步填写会更准。
              </p>
            ) : null}
            <div className="flex flex-wrap gap-1.5">
              {competitors.map((c) => {
                const active = selectedCompetitorNames.has(c.name)
                return (
                  <button
                    key={c.name}
                    type="button"
                    onClick={() => toggleCompetitor(c.name)}
                    className={`rounded-full border px-2.5 py-0.5 text-[11.5px] transition-colors ${
                      active
                        ? 'border-[var(--yayu-foreground)] bg-[var(--yayu-foreground)] text-[var(--yayu-input)]'
                        : 'border-[var(--yayu-border)] bg-[var(--yayu-input)] text-[var(--yayu-faint)] line-through hover:border-[var(--yayu-muted)]'
                    }`}
                  >
                    <span title={c.mentioned_by?.length ? `提到它的模型：${c.mentioned_by.join('、')}` : undefined}>
                      {c.name}
                      {c.company ? <span className="opacity-70">{`（${c.company}）`}</span> : null}
                      {c.mentioned_by && c.mentioned_by.length > 1 ? (
                        <span className="ml-1 opacity-70">{`×${c.mentioned_by.length}`}</span>
                      ) : null}
                    </span>
                  </button>
                )
              })}
            </div>
            <GeoButtonRow>
              <Button size="sm" disabled={competitors.filter((c) => selectedCompetitorNames.has(c.name)).length === 0} onClick={() => runCreate(competitors.filter((c) => selectedCompetitorNames.has(c.name)))}>
                确认竞品（预计 {selectedProducts.size + selectedServices.size + competitors.filter((c) => selectedCompetitorNames.has(c.name)).length} 个对象）
              </Button>
              <Button variant="secondary" size="sm" onClick={runDiscover}>
                刷新竞品
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setManualOpen(true)}>
                手填
              </Button>
              <Button variant="secondary" size="sm" onClick={stepBack}>
                上一步
              </Button>
            </GeoButtonRow>
          </>
        ) : (
          <>
            <p className="text-[12px] leading-relaxed text-[var(--yayu-muted)]">
              {discover?.hint || '未能自动发现竞品候选。可以手填竞品名称，或跳过。'}
            </p>
            {discover?.questions && discover.questions.length > 0 ? (
              <p className="text-[10.5px] leading-relaxed text-[var(--yayu-faint)]">
                已经问过：{discover.questions.join(' / ')}
                {discover.engines_total ? `（${discover.engines_total} 个模型，${discover.engines_answered ?? 0} 个作答）` : ''}
              </p>
            ) : null}
            <GeoButtonRow>
              <Button size="sm" onClick={() => setManualOpen(true)}>
                手填竞品
              </Button>
              <Button variant="secondary" size="sm" onClick={() => runCreate([])}>
                跳过（无竞品）
              </Button>
              <Button variant="secondary" size="sm" onClick={stepBack}>
                上一步
              </Button>
            </GeoButtonRow>
          </>
        )
      ) : null}

      {/* 手填竞品 */}
      {manualOpen ? (
        <div className="space-y-2">
          <textarea
            value={manualText}
            onChange={(e) => setManualText(e.target.value)}
            placeholder={'每行一个竞品名称，例如：\n某友商公司\n某竞品公司'}
            rows={3}
            className="w-full resize-none rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)] outline-none focus:border-[var(--yayu-muted)]"
          />
          <GeoButtonRow>
            <Button
              size="sm"
              onClick={() => {
                const names = manualText
                  .split('\n')
                  .map((s) => s.trim())
                  .filter(Boolean)
                runCreate(names.map((name) => ({ name })))
                setManualOpen(false)
              }}
            >
              确定
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setManualOpen(false)}>
              取消
            </Button>
          </GeoButtonRow>
        </div>
      ) : null}

      {/* 步骤 3 · 创建监测对象 */}
      {step === 'create' ? (
        <>
          <GeoRow label="已创建监测对象" value={`${create?.created?.length ?? 0} 个`} />
          <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-[11px] leading-relaxed text-[var(--yayu-muted)]">
            请先核对下面清单。只有确认对象名称和数量都正确后再开始监测；重复名称会在提交前自动合并。
          </p>
          {create && create.created.length > 0 ? (
            <div className="space-y-1">
              {create.created.map((c) => (
                <div key={c.monitor_id} className="flex items-center justify-between rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2.5 py-0.5.5 text-[12px]">
                  <span className="truncate text-[var(--yayu-foreground)]">{c.entity ?? c.monitor_id}</span>
                  <span className="shrink-0 rounded bg-[var(--yayu-surface-raised)] px-1.5 py-0.5 text-[10px] text-[var(--yayu-muted)]">{c.type ?? 'brand'}</span>
                </div>
              ))}
            </div>
          ) : null}
          <p className="text-[12px] text-[var(--yayu-muted)]">
            监测范围已确认。开始后，系统会把问题发给国产模型，记录回答里是否出现你的品牌。
          </p>
          <GeoButtonRow>
            <Button size="sm" onClick={runMonitor}>
              开始监测
            </Button>
            <Button variant="secondary" size="sm" onClick={stepBack}>
              上一步
            </Button>
          </GeoButtonRow>
        </>
      ) : null}

      {/* 步骤 4 · 自动监测 + 解析 + 蒸馏（实时进度） */}
      {step === 'run' ? (
        <>
          {runProgress && runProgress.running ? (
            <>
              <div className="flex items-center justify-between text-[12px]">
                <span className="font-medium text-[var(--yayu-foreground)]">
                  {runProgress.phase === 'run' && '抓取模型回答中'}
                  {runProgress.phase === 'parse' && `正在读懂模型回答（${(runProgress.parse?.succeeded ?? 0) + (runProgress.parse?.failed ?? 0)}/${runProgress.parse?.total ?? '…'} 条）`}
                  {runProgress.phase === 'distill' && '整理问题与缺口中'}
                  {runProgress.phase === 'done' && '分析完成'}
                </span>
                <span className="text-[var(--yayu-muted)]">
                  {runProgress.overall_pct ?? Math.round((runProgress.done / Math.max(runProgress.total, 1)) * 100)}%
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-[var(--yayu-surface-raised)]">
                <div
                  className="h-full rounded-full bg-[var(--yayu-muted)]/60 transition-all"
                  style={{ width: `${runProgress.overall_pct ?? Math.min(100, (runProgress.done / Math.max(runProgress.total, 1)) * 100)}%` }}
                />
              </div>
              <p className="text-[11px] text-[var(--yayu-faint)]">
                {runProgress.phase === 'run' && '正在逐个问题抓取模型回答…'}
                {runProgress.phase === 'parse' && '回答抓取完成，正在读懂模型回复（每条一次分析，约几分钟）…'}
                {runProgress.phase === 'distill' && '回答理解完成，正在整理：客户问题 → 资料缺口 → 内容机会…'}
              </p>
            </>
          ) : runProgress && runProgress.finished ? (
            <>
              <div className="flex items-center gap-1.5 text-[12px] text-[var(--yayu-muted)]">
                <Check className="size-3.5" /> 监测完成
              </div>
              {runProgress.summary ? (
                <div className="grid grid-cols-2 gap-x-4 gap-y-1.5">
                  <GeoRow label="有效回答" value={runProgress.summary.answered_questions == null || runProgress.summary.total_questions == null ? '—' : `${runProgress.summary.answered_questions}/${runProgress.summary.total_questions} 问`} />
                  <GeoRow label="被提及" value={runProgress.summary.mentioned_questions == null || runProgress.summary.answered_questions == null ? '—' : `${runProgress.summary.mentioned_questions}/${runProgress.summary.answered_questions} 问`} />
                  <GeoRow label="提及覆盖" value={runProgress.summary.coverage_pct == null ? '—' : `${runProgress.summary.coverage_pct}%`} />
                  <GeoRow label="未提及" value={runProgress.summary.not_mentioned == null ? '—' : `${runProgress.summary.not_mentioned} 问`} />
                </div>
              ) : null}
              {runProgress.summary?.weak_questions?.length ? (
                <div className="rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-surface-raised)] px-2 py-1">
                  <div className="mb-1 text-[11px] font-medium text-[var(--yayu-muted)]">弱项问题（未被提及）</div>
                  <div className="space-y-0.5 text-[11px] text-[var(--yayu-faint)]">
                    {runProgress.summary.weak_questions.slice(0, 4).map((q) => (
                      <div key={q}>· {q}</div>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          ) : (
            <p className="text-[12px] text-[var(--yayu-muted)]">监测已提交，正在启动…</p>
          )}
          <GeoButtonRow>
            <Button size="sm" onClick={runDistill} disabled={!runProgress?.finished && runProgress?.running}>
              下一步：生成问题与缺口
            </Button>
            <Button variant="secondary" size="sm" onClick={stepBack}>
              上一步
            </Button>
          </GeoButtonRow>
        </>
      ) : null}

      {/* 步骤 5 · 蒸馏闭环 */}
      {step === 'distill' ? (
        <>
          {distill?.stats ? (
            <GeoList
              items={[
                { title: `客户问题：${distill.stats.questions ?? 0} 个`, meta: '已生成' },
                { title: `资料缺口：${distill.stats.gaps ?? 0} 个`, meta: '已生成' },
                { title: `内容计划：${distill.stats.plans ?? 0} 条`, meta: '已生成' },
              ]}
            />
          ) : (
              <p className="text-[12px] text-[var(--yayu-muted)]">问题、资料缺口和内容计划已生成。</p>
          )}
          <GeoButtonRow>
            <Button size="sm" onClick={() => setStep('schedule')}>
              下一步：设置自动监测
            </Button>
            <Button variant="secondary" size="sm" onClick={stepBack}>
              上一步
            </Button>
          </GeoButtonRow>
        </>
      ) : null}

      {/* 步骤 6 · 定时任务 */}
      {step === 'schedule' ? (
        <div className="space-y-2">
          <p className="text-[12px] text-[var(--yayu-muted)]">要不要让系统自动运行？</p>
          <div className="space-y-1.5">
            {(
              [
                ['daily', '每天自动监测'],
                ['weekly', '每周监测并出报告'],
                ['none', '不自动运行'],
              ] as Array<['daily' | 'weekly' | 'none', string]>
            ).map(([value, label]) => (
              <label
                key={value}
                className="flex cursor-pointer items-center gap-2 rounded-md border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)]"
              >
                <input
                  type="radio"
                  name="geo-schedule"
                  checked={schedule === value}
                  onChange={() => setSchedule(value)}
                  className="accent-[var(--yayu-foreground)]"
                />
                {label}
              </label>
            ))}
          </div>
          <GeoButtonRow>
            <Button size="sm" disabled={!schedule} onClick={runSchedule}>
              确定
            </Button>
            <Button variant="secondary" size="sm" onClick={stepBack}>
              上一步
            </Button>
          </GeoButtonRow>
        </div>
      ) : null}

      {/* 步骤 7 · 阶段报告 */}
      {step === 'report' ? (
        <>
          <GeoList
            items={[
              { title: `监测对象：${create?.created?.length ?? 0} 个`, meta: '完成' },
              { title: `内容资产：${status?.items ?? '—'} 个`, meta: '完成' },
              { title: `客户问题：${status?.questions ?? '—'} 个`, meta: '完成' },
              {
                title: `定时任务：${schedule === 'daily' ? '每日监测' : schedule === 'weekly' ? '每周报告' : '未设定'}`,
                meta: schedule === 'none' || !schedule ? '未设定' : '完成',
              },
            ]}
          />
          <div className="flex items-center gap-1.5 text-[12px] text-[var(--yayu-muted)]">
            <Check className="size-3.5" />
            {/* 2026-09-21：原来不管上一步选了什么，这里都写「每天监测」——
                选「不设定时」时这句话就是假的（上面那行已经如实写着「未设定」）。 */}
            {schedule === 'daily'
              ? '首次设置完成，日常流程已启动——每天监测、分析后推荐内容。'
              : schedule === 'weekly'
                ? '首次设置完成，每周会跑一轮监测并出报告；日常分析仍可随时手动触发。'
                : '首次设置完成。你选择了不设定时任务——监测不会自动跑，需要时到「国产模型监测」手动运行。'}
          </div>
          <GeoButtonRow>
            {(create?.created?.length ?? 0) === 0 && (status?.items ?? 0) === 0 && (status?.questions ?? 0) === 0 ? (
              // 流程产出为空（无监测对象/资产/问题）→ 只显示「结束」退出
              <Button size="sm" onClick={onClose}>
                结束
              </Button>
            ) : (
              <>
                <Button size="sm" onClick={exportReport}>
                  <Download className="size-3.5" /> 导出报告
                </Button>
                <Button variant="secondary" size="sm" onClick={stepBack}>
                  上一步
                </Button>
              </>
            )}
          </GeoButtonRow>
        </>
      ) : null}
    </GeoCardShell>
  )
}
