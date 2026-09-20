import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoDownload, geoGet, type GeoOnboardStatus } from './geo-api'
import { GeoButtonRow, GeoCardShell, GeoError, GeoList, GeoLoading } from './shared'
import { saveBlobToDisk } from '../lib/save-to-disk'

/** 阶段报告卡：自动配置/监测整体状态汇总 + 导出 */
export function GeoReportCard() {
  const [status, setStatus] = useState<GeoOnboardStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const s = await geoGet<GeoOnboardStatus>('/onboard/status')
      setStatus(s)
    } catch (e) {
      setError(e instanceof Error ? e.message : '报告加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  if (loading) return <GeoLoading text="阶段报告加载中…" />
  if (error) return <GeoError message={error} onRetry={() => void load()} />

  const exportReport = async () => {
    setExporting(true)
    setError(null)
    try {
      // 真实 PDF 路由是 v1 的 /intelligence/reports/latest/pdf（2026-08-15 新增）；
      // 走 geoDownload 才既用得上产品门基址，又不会被「200 + JSON 暂无报告」骗成一个假 .pdf。
      const blob = await geoDownload('/intelligence/reports/latest/pdf')
      await saveBlobToDisk(blob, `GEO-AI认知报告-${new Date().toISOString().slice(0, 10)}.pdf`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  // 三种「素材」不是一回事，分开如实报（2026-09-20 修标签错位）：
  // 企业资料来自企业知识库（GEO 只读，读到的留在自己的快照表里），
  // GEO 素材库是 GEO 自己的内容资产，监测对象是 GEO 在监测谁。
  const knowledge = status?.knowledge
  const knowledgeLine = !knowledge
    ? '未检测'
    : knowledge.read_ever
      ? `已读取 · 知识对象 ${knowledge.objects_seen} / 文档 ${knowledge.documents_seen}`
      : '尚未读取知识库'

  return (
    <GeoCardShell title="📄 GEO 阶段报告">
      <GeoList
        items={[
          { title: '企业资料', meta: knowledgeLine },
          { title: 'GEO 素材库', meta: `${status?.materials ?? 0} 个` },
          { title: '监测对象', meta: `${status?.items ?? 0} 个` },
          { title: '客户问题池', meta: `${status?.questions ?? 0} 个` },
        ]}
      />
      {knowledge ? (
        <p className="pt-1 text-[11px] text-[var(--yayu-muted)]">
          {knowledge.read_ever
            ? `企业知识来自知识库（正本在知识库，GEO 存的是快照${knowledge.last_read_at ? `，最后读取 ${knowledge.last_read_at.slice(0, 10)}` : ''}）；GEO 不写知识库。`
            : 'GEO 还没从企业知识库读到过内容；GEO 只读知识库，不写。'}
        </p>
      ) : null}
      <GeoButtonRow>
        <Button size="sm" disabled={exporting} onClick={() => void exportReport()}>
          <Download className="size-3.5" /> {exporting ? '生成中…' : '导出 PDF 报告'}
        </Button>
      </GeoButtonRow>
      {error ? <p className="pt-1 text-[11px] text-[var(--yayu-muted)]">{error}</p> : null}
    </GeoCardShell>
  )
}
