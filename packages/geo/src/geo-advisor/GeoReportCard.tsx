import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { Button } from '@yayu/ui'
import { geoGet, type GeoOnboardStatus } from './geo-api'
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
      const { getAuthToken } = await import('../api/session')
      const token = getAuthToken()
      const resp = await fetch('/api/geo/api/v1/report/export', {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => null)
        throw new Error(body?.error?.message ?? `导出失败（HTTP ${resp.status}）`)
      }
      const blob = await resp.blob()
      await saveBlobToDisk(blob, `GEO-AI认知报告-${new Date().toISOString().slice(0, 10)}.pdf`)
    } catch (e) {
      setError(e instanceof Error ? e.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  return (
    <GeoCardShell title="📄 GEO 阶段报告">
      <GeoList
        items={[
          { title: '企业资料', meta: status?.empty === false ? '已就绪' : '未上传' },
          { title: '知识素材', meta: `${status?.items ?? 0} 个` },
          { title: '客户问题池', meta: `${status?.questions ?? 0} 个` },
        ]}
      />
      <GeoButtonRow>
        <Button size="sm" disabled={exporting} onClick={() => void exportReport()}>
          <Download className="size-3.5" /> {exporting ? '生成中…' : '导出 PDF 报告'}
        </Button>
      </GeoButtonRow>
      {error ? <p className="pt-1 text-[11px] text-[var(--yayu-muted)]">{error}</p> : null}
    </GeoCardShell>
  )
}
