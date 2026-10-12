import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, Download, FileText, FlaskConical, LoaderCircle, RefreshCw } from 'lucide-react'
import { geoDownloadFile, geoGet, geoPost, type GeoProfileCategory, type GeoProfileOverview } from './geo-api'
import { saveBlobToDisk } from '../lib/save-to-disk'
import { useGeoDemoMode, useGeoNav } from './shared'
import { GEO_DEMO_NOTICE, GEO_DEMO_PROFILE_CATEGORIES, GEO_DEMO_PROFILE_DETAILS, GEO_DEMO_PROFILE_OVERVIEW } from './demo-fixtures'

type Detail = Record<string, any>
const tone = (level?: string) => level === '足够' ? 'good' : level === '部分' ? 'mid' : 'low'

export function GeoProfileWorkspace() {
  const go = useGeoNav()
  const { enabled: demoMode } = useGeoDemoMode()
  const [overview, setOverview] = useState<GeoProfileOverview | null>(null)
  const [categories, setCategories] = useState<GeoProfileCategory[]>([])
  const [selected, setSelected] = useState<string>('')
  const [detail, setDetail] = useState<Detail | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [loadError, setLoadError] = useState('')
  const loadSeq = useRef(0)

  const load = useCallback(async () => {
    const requestId = ++loadSeq.current
    setBusy(true)
    setNotice('')
    setLoadError('')
    try {
      if (demoMode) {
        setOverview(GEO_DEMO_PROFILE_OVERVIEW as GeoProfileOverview)
        const nextCategories = GEO_DEMO_PROFILE_CATEGORIES as GeoProfileCategory[]
        setCategories(nextCategories)
        setSelected((current) => nextCategories.some((category) => category.items.some((item) => item.id === current)) ? current : nextCategories[0]?.items?.[0]?.id || '')
        return
      }
      setOverview(null)
      setCategories([])
      setSelected('')
      setDetail(null)
      const [ov, cats] = await Promise.all([geoGet<GeoProfileOverview>('/enterprise-profile/overview'), geoGet<{ categories: GeoProfileCategory[] }>('/enterprise-profile/categories')])
      if (requestId !== loadSeq.current) return
      setOverview(ov); setCategories(cats.categories ?? [])
      setSelected((current) => cats.categories?.some((category) => category.items.some((item) => item.id === current)) ? current : cats.categories?.[0]?.items?.[0]?.id || '')
    } catch (e) {
      if (requestId === loadSeq.current) setLoadError(e instanceof Error ? e.message : '企业资料读取失败')
    } finally { if (requestId === loadSeq.current) setBusy(false) }
  }, [demoMode])
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    if (!selected) return
    let alive = true
    setDetail(null)
    if (demoMode) {
      setDetail((GEO_DEMO_PROFILE_DETAILS[selected] ?? null) as Detail | null)
      return () => { alive = false }
    }
    geoGet<{ item: Detail }>(`/enterprise-profile/items/${selected}`).then((d) => { if (alive) setDetail(d.item) }).catch((e) => { if (alive) setNotice(e instanceof Error ? e.message : '详情加载失败') })
    return () => { alive = false }
  }, [selected, demoMode])

  const selectedItem = useMemo(() => categories.flatMap((c) => c.items).find((i) => i.id === selected), [categories, selected])
  async function refresh() { if (demoMode) { setNotice(GEO_DEMO_NOTICE); return }; setBusy(true); setNotice('正在重新读取当前可检索的企业资料…'); try { await geoPost('/enterprise-profile/refresh', {}); await load(); setNotice('已按当前可检索的资料重新计算；历史快照不会因原资料删除而消失。') } catch (e) { setNotice(e instanceof Error ? e.message : '刷新失败') } finally { setBusy(false) } }
  async function makePlans() { if (!selected) return; if (demoMode) { setNotice('演示模式不会写入真实行动计划；关闭演示数据后才能操作。'); return }; setBusy(true); try { const d = await geoPost<{ added?: number; duplicated?: number; error?: string }>(`/enterprise-profile/items/${selected}/plans`, {}); setNotice(d.error || `已生成 ${d.added ?? 0} 条补充计划${d.duplicated ? `，跳过 ${d.duplicated} 条重复计划` : ''}`); if (!d.error && d.added) go?.('action-plan') } catch (e) { setNotice(e instanceof Error ? e.message : '生成失败') } finally { setBusy(false) } }
  async function exportWord() { if (demoMode) { setNotice('演示数据不会导出为正式企业资料；关闭演示数据后才能导出真实资料。'); return }; setBusy(true); try { const blob = await geoDownloadFile('/enterprise-profile/export'); await saveBlobToDisk(blob, `企业资料总览-${new Date().toISOString().slice(0,10)}.docx`) } catch (e) { setNotice(e instanceof Error ? e.message : '导出失败') } finally { setBusy(false) } }
  const knowledge = detail?.knowledge
  const questions = [...(detail?.uncovered_questions ?? []), ...(detail?.partial_questions ?? [])]
  // 真实资料尚未返回时，不要先把规则框架当成当前企业覆盖结果；只有接口明确
  // 报告 knowledge_ready=true 才能展示覆盖数字。演示夹具没有该字段，仍按演示流程展示。
  const profileLoading = !demoMode && !overview && !loadError
  const knowledgeReady = demoMode || overview?.data_status?.knowledge_ready === true

  return <div className="profile-console">
    <header className="workspace-intro"><div><span>资料覆盖</span><h1>企业资料总览</h1><p>检查现有企业资料能不能回答客户问题；只统计当前能读到、能追溯来源的资料，历史快照不会冒充当前内容。</p></div><div className="workspace-actions"><button className="geo-btn secondary" onClick={() => void exportWord()} disabled={busy || demoMode} title={demoMode ? '演示数据不会导出为正式企业资料' : undefined}><Download />导出 Word</button><button className="geo-btn secondary" onClick={() => void refresh()} disabled={busy || demoMode} title={demoMode ? '演示数据不会触发真实刷新' : undefined}>{busy ? <LoaderCircle className="spin" /> : <RefreshCw />}重新读取资料</button></div></header>
    {demoMode && <div className="geo-demo-banner"><FlaskConical /><span><b>内测演示数据已开启</b>　{GEO_DEMO_NOTICE}</span></div>}
    {notice && <div className="geo-notice">{notice}</div>}
    {!demoMode && overview ? <div className="profile-data-contract"><b>这是“资料能不能支撑客户回答”的检查，不是自动写好的企业介绍。</b><span>左侧各项对应客户会问的问题；只有当前读到、能追溯来源的企业资料才会进入判断。当前问题 {overview.data_status?.questions_count ?? '—'} 条 · 可核实企业信息 {overview.data_status?.knowledge_facts_count ?? '—'} 条 · 已关联资料 {overview.data_status?.semantic_linked_count ?? '—'} 条 · 已建立关系 {overview.data_status?.relations_count ?? '—'} 条。</span></div> : null}
    {profileLoading ? <div className="profile-loading"><LoaderCircle className="spin" />正在读取当前企业资料…</div> : loadError ? <section className="profile-sync-gate"><div><strong>企业资料暂时读不到</strong><p>{loadError}。先重试一次；在资料读取成功前，系统不会显示覆盖率或补齐建议。</p></div><button className="geo-btn primary" onClick={() => void load()}>重试读取<RefreshCw /></button></section> : !knowledgeReady ? <section className="profile-sync-gate"><div><strong>还没有同步企业资料</strong><p>先把企业资料同步到 GEO 工作区，系统才能判断哪些客户问题有依据。当前不会把账号里其他资料当成这家企业的内容。</p></div><button className="geo-btn primary" onClick={() => go?.('kb-init')}>去同步企业资料<ArrowRight /></button></section> : <>
    <section className="profile-summary"><div><span>整体覆盖率</span><strong>{overview?.overall_coverage_pct == null ? '—' : <>{overview.overall_coverage_pct}<small>%</small></>}</strong></div><div><b>{overview?.enough_count ?? '—'}</b><span>资料足够</span></div><div><b>{overview?.partial_count ?? '—'}</b><span>部分覆盖</span></div><div><b>{overview?.too_little_count ?? '—'}</b><span>需要补齐</span></div></section>
    <div className="profile-body">
      <aside className="profile-outline">{categories.map((category) => <details key={category.category} className="profile-outline-group" open={category.items.some((item) => item.id === selected)}><summary><span>{category.name}</span><b>{category.items.length}</b></summary><div>{category.items.map((item) => <button key={item.id} className={selected === item.id ? 'active' : ''} onClick={() => setSelected(item.id)}><i data-tone={tone(item.level)} /> <span>{item.name}</span><em>{item.coverage_pct == null ? '—' : `${item.coverage_pct}%`}</em></button>)}</div></details>)}</aside>
      <main className="profile-detail">{!detail ? <div className="profile-loading"><LoaderCircle className="spin" />正在读取资料证据…</div> : <>
        <header><div><span data-tone={tone(detail.level)}>{detail.level}</span><h2>{selectedItem?.name ?? detail.name}</h2><p>{detail.reason}</p></div><button className="geo-btn primary" onClick={() => void makePlans()} disabled={busy || demoMode} title={demoMode ? '演示模式不会写入真实行动计划' : undefined}>生成补充计划<ArrowRight /></button></header>
        <div className="profile-evidence-summary"><FileText /><div><b>{knowledge?.summary ?? '暂无资料摘要'}</b><span>当前这一项找到：企业名称 {knowledge?.counts?.entities ?? '—'} 个 · 已确认信息 {knowledge?.counts?.facts ?? '—'} 条 · 关联信息 {knowledge?.counts?.relations ?? '—'} 条 · 文档片段 {knowledge?.counts?.doc_chunks ?? '—'} 段。显示 0 只代表这一项暂时没找到，不代表企业资料全库没有。</span></div></div>
        {/* 2026-09-21：这一段原来每行末尾写「匹配度 12.4」——那个 score 是知识库检索的
            **序位分**（无界，实测常在 10~14），不是 0~100 的相似度百分比，写「匹配度」会让
            用户以为是匹配百分比。分数没有可比口径，就不展示分数，只留来源。 */}
        <section className="profile-detail-grid"><div><details className="profile-list-fold" open={(knowledge?.doc_chunks ?? []).length <= 3}><summary><span>已有资料与来源</span><small>{(knowledge?.doc_chunks ?? []).length} 条</small></summary><div>{(knowledge?.doc_chunks ?? []).length ? knowledge.doc_chunks.slice(0,6).map((row: Detail, i: number) => <article key={i}><p>{row.text}</p><small>{row.source || '企业资料'}</small></article>) : <div className="profile-empty">没有找到可支撑这一项的企业资料。</div>}</div></details></div><div><details className="profile-list-fold" open={questions.length <= 3}><summary><span>待覆盖客户问题</span><small>{questions.length} 条</small></summary><div>{questions.length ? questions.slice(0,8).map((row: Detail, i: number) => <article key={i}><p>{row.question}</p><small>{i < (detail.uncovered_questions?.length ?? 0) ? '未覆盖' : '部分覆盖'}</small></article>) : <div className="profile-empty">当前没有待补问题。</div>}</div></details></div></section>
      </>}</main>
    </div></>}
  </div>
}
