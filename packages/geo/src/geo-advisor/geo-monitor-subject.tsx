import { useCallback, useEffect, useState } from 'react'
import { geoGet } from './geo-api'
import { useGeoDemoMode } from './shared'
import { DEMO_COMPANY } from './demo-monitor-samples'

/**
 * 监测主体（哪家企业品牌）在 GEO 内是**同一份**选择：
 * 总览 / 专业分析 / 认知健康 / 认知地图 共用，存本地，选一次后面都跟着。
 * `all` = 全选（汇总全部启用中的品牌对象）。
 */
export const ALL_SUBJECTS = 'all'

const STORAGE_KEY = 'geo.monitorSubject'
const EVENT = 'geo-monitor-subject'

export interface MonitorSubject {
  monitor_id: string
  name: string
}

interface MonitorItemRow {
  monitor_id: string
  type: string
  entity: string
  status: string
  config_json?: { company?: string } | null
}

function readStored(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setMonitorSubject(value: string) {
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // 无 storage（隐私模式）也要能用：只在这一个页面会话里生效
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: { value } }))
}

export function useMonitorSubjects() {
  const { enabled: demoMode } = useGeoDemoMode()
  const [subjects, setSubjects] = useState<MonitorSubject[]>([])
  const [loaded, setLoaded] = useState(false)
  const [loadedMode, setLoadedMode] = useState<boolean | null>(null)
  useEffect(() => {
    let alive = true
    if (demoMode) {
      setSubjects([{ monitor_id: 'demo-brand', name: DEMO_COMPANY }])
      setLoadedMode(true)
      setLoaded(true)
      return () => { alive = false }
    }
    setLoaded(false)
    geoGet<{ items: MonitorItemRow[] }>('/monitor/items')
      .then((result) => {
        if (!alive) return
        setSubjects(
          (result.items ?? [])
            .filter((item) => item.type === 'brand' && item.status === 'active')
            .map((item) => ({
              monitor_id: item.monitor_id,
              name: item.config_json?.company || item.entity || '未命名品牌',
            })),
        )
      })
      .catch(() => {
        if (alive) setSubjects([])
      })
      .finally(() => {
        if (alive) { setLoadedMode(false); setLoaded(true) }
      })
    return () => {
      alive = false
    }
  }, [demoMode])
  return { subjects, loaded: loaded && loadedMode === demoMode }
}

export function useMonitorSubject() {
  const { enabled: demoMode } = useGeoDemoMode()
  const { subjects, loaded } = useMonitorSubjects()
  const [value, setValue] = useState(readStored)

  useEffect(() => {
    const sync = (event: Event) => setValue((event as CustomEvent<{ value?: string }>).detail?.value ?? readStored())
    window.addEventListener(EVENT, sync)
    window.addEventListener('storage', sync)
    return () => {
      window.removeEventListener(EVENT, sync)
      window.removeEventListener('storage', sync)
    }
  }, [])

  useEffect(() => {
    if (!loaded || demoMode) return
    const known = value === ALL_SUBJECTS || subjects.some((item) => item.monitor_id === value)
    if (value && known) return
    // 第一次进来 / 存的主体已经不存在了：只有一个就自动选它，否则先汇总，别让页面停在空态
    setMonitorSubject(subjects.length === 1 ? subjects[0].monitor_id : ALL_SUBJECTS)
  }, [loaded, subjects, value, demoMode])

  const select = useCallback((next: string) => setMonitorSubject(next), [])
  const query = value ? `monitor_id=${encodeURIComponent(value)}` : ''
  const scopeQuery = value && value !== ALL_SUBJECTS ? `monitor_id=${encodeURIComponent(value)}` : ''
  const subject = subjects.find((item) => item.monitor_id === value) ?? null
  return { value, select, query, scopeQuery, subject, subjects, loaded }
}

/** 监测主体选择器：全 GEO 共用一处，选完各页都用这个主体。 */
export function MonitorSubjectPicker({ note }: { note?: string }) {
  const { value, select, subjects, loaded } = useMonitorSubject()
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-3 py-2">
      <label htmlFor="geo-monitor-subject" className="text-[12px] font-medium text-[var(--yayu-foreground)]">监测主体</label>
      <select
        id="geo-monitor-subject"
        className="min-w-48 rounded border border-[var(--yayu-border)] bg-[var(--yayu-input)] px-2 py-1 text-[12px] text-[var(--yayu-foreground)]"
        value={value}
        disabled={!loaded}
        onChange={(event) => select(event.target.value)}
      >
        <option value={ALL_SUBJECTS}>全部（全选汇总）</option>
        {subjects.map((item) => <option key={item.monitor_id} value={item.monitor_id}>{item.name}</option>)}
      </select>
      <span className="text-[11px] text-[var(--yayu-muted)]">
        {!loaded
          ? '正在读取监测对象…'
          : subjects.length === 0
            ? '还没有启用中的企业品牌监测对象，请先到监测工作台创建。'
            : note ?? `共 ${subjects.length} 个企业品牌对象；在这里选择后，其他页面都会使用同一个主体`}
      </span>
    </div>
  )
}
