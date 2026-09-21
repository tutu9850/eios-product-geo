import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowRight, Download, FileText, LoaderCircle, RefreshCw } from 'lucide-react'
import { geoDownloadFile, geoGet, geoPost, type GeoProfileCategory, type GeoProfileOverview } from './geo-api'
import { saveBlobToDisk } from '../lib/save-to-disk'
import { useGeoNav } from './shared'

type Detail = Record<string, any>
const tone = (level?: string) => level === '足够' ? 'good' : level === '部分' ? 'mid' : 'low'

export function GeoProfileWorkspace() {
  const go = useGeoNav()
  const [overview, setOverview] = useState<GeoProfileOverview | null>(null)
  const [categories, setCategories] = useState<GeoProfileCategory[]>([])
  const [selected, setSelected] = useState<string>('')
  const [detail, setDetail] = useState<Detail | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    setBusy(true)
    try {
      const [ov, cats] = await Promise.all([geoGet<GeoProfileOverview>('/enterprise-profile/overview'), geoGet<{ categories: GeoProfileCategory[] }>('/enterprise-profile/categories')])
      setOverview(ov); setCategories(cats.categories ?? [])
      setSelected((current) => current || cats.categories?.[0]?.items?.[0]?.id || '')
    } finally { setBusy(false) }
  }, [])
  useEffect(() => { void load() }, [load])
  useEffect(() => { if (!selected) return; setDetail(null); geoGet<{ item: Detail }>(`/enterprise-profile/items/${selected}`).then((d) => setDetail(d.item)).catch((e) => setNotice(e instanceof Error ? e.message : '详情加载失败')) }, [selected])

  const selectedItem = useMemo(() => categories.flatMap((c) => c.items).find((i) => i.id === selected), [categories, selected])
  async function refresh() { setBusy(true); setNotice('正在重新计算企业资料覆盖…'); try { await geoPost('/enterprise-profile/refresh', {}); await load(); setNotice('资料覆盖已更新') } catch (e) { setNotice(e instanceof Error ? e.message : '刷新失败') } finally { setBusy(false) } }
  async function makePlans() { if (!selected) return; setBusy(true); try { const d = await geoPost<{ added?: number; duplicated?: number; error?: string }>(`/enterprise-profile/items/${selected}/plans`, {}); setNotice(d.error || `已生成 ${d.added ?? 0} 条补充计划${d.duplicated ? `，跳过 ${d.duplicated} 条重复计划` : ''}`); if (!d.error && d.added) go?.('action-plan') } catch (e) { setNotice(e instanceof Error ? e.message : '生成失败') } finally { setBusy(false) } }
  async function exportWord() { setBusy(true); try { const blob = await geoDownloadFile('/enterprise-profile/export'); await saveBlobToDisk(blob, `企业资料总揽-${new Date().toISOString().slice(0,10)}.docx`) } catch (e) { setNotice(e instanceof Error ? e.message : '导出失败') } finally { setBusy(false) } }
  const knowledge = detail?.knowledge
  const questions = [...(detail?.uncovered_questions ?? []), ...(detail?.partial_questions ?? [])]

  return <div className="profile-console">
    <header className="workspace-intro"><div><span>ENTERPRISE SOURCE OF TRUTH</span><h1>企业资料总揽</h1><p>按企业经营结构检查事实、证据与客户问题覆盖，直接把缺失内容转成行动计划。</p></div><div className="workspace-actions"><button className="geo-btn secondary" onClick={() => void exportWord()}><Download />导出 Word</button><button className="geo-btn secondary" onClick={() => void refresh()} disabled={busy}>{busy ? <LoaderCircle className="spin" /> : <RefreshCw />}重新计算</button></div></header>
    {notice && <div className="geo-notice">{notice}</div>}
    <section className="profile-summary"><div><span>整体覆盖率</span><strong>{overview?.overall_coverage_pct ?? '—'}<small>%</small></strong></div><div><b>{overview?.enough_count ?? '—'}</b><span>资料足够</span></div><div><b>{overview?.partial_count ?? '—'}</b><span>部分覆盖</span></div><div><b>{overview?.too_little_count ?? '—'}</b><span>需要补齐</span></div></section>
    <div className="profile-body">
      <aside className="profile-outline">{categories.map((category) => <section key={category.category}><h2>{category.name}<span>{category.items.length}</span></h2>{category.items.map((item) => <button key={item.id} className={selected === item.id ? 'active' : ''} onClick={() => setSelected(item.id)}><i data-tone={tone(item.level)} /> <span>{item.name}</span><em>{item.coverage_pct == null ? '—' : `${item.coverage_pct}%`}</em></button>)}</section>)}</aside>
      <main className="profile-detail">{!detail ? <div className="profile-loading"><LoaderCircle className="spin" />正在读取资料证据…</div> : <>
        <header><div><span data-tone={tone(detail.level)}>{detail.level}</span><h2>{selectedItem?.name ?? detail.name}</h2><p>{detail.reason}</p></div><button className="geo-btn primary" onClick={() => void makePlans()} disabled={busy}>生成补充计划<ArrowRight /></button></header>
        <div className="profile-evidence-summary"><FileText /><div><b>{knowledge?.summary ?? '暂无资料摘要'}</b><span>实体 {knowledge?.counts?.entities ?? 0} · 事实 {knowledge?.counts?.facts ?? 0} · 关系 {knowledge?.counts?.relations ?? 0} · 文档片段 {knowledge?.counts?.doc_chunks ?? 0}</span></div></div>
        {/* 2026-09-21：这一段原来每行末尾写「匹配度 12.4」——那个 score 是知识库检索的
            **序位分**（无界，实测常在 10~14），不是 0~100 的相似度百分比，写「匹配度」会让
            用户以为是匹配百分比。分数没有可比口径，就不展示分数，只留来源。 */}
        <section className="profile-detail-grid"><div><h3>已有资料与来源</h3>{(knowledge?.doc_chunks ?? []).length ? knowledge.doc_chunks.slice(0,6).map((row: Detail, i: number) => <article key={i}><p>{row.text}</p><small>{row.source || '企业知识库'}</small></article>) : <div className="profile-empty">没有找到可支撑这一项的企业资料。</div>}</div><div><h3>待覆盖客户问题</h3>{questions.length ? questions.slice(0,8).map((row: Detail, i: number) => <article key={i}><p>{row.question}</p><small>{i < (detail.uncovered_questions?.length ?? 0) ? '未覆盖' : '部分覆盖'}</small></article>) : <div className="profile-empty">当前没有待补问题。</div>}</div></section>
      </>}</main>
    </div>
  </div>
}
