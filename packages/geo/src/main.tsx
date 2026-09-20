import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Radar } from 'lucide-react'
import { GEO_FLOW_MENU, GeoFlowRouter, type GeoFlowKind } from '@geo-advisor'
import { configureGeoProductTransport } from '@geo-advisor/geo-api'
import './index.css'

const PRODUCT_HOST_CONTRACT = 'eios.product_host/v1'

function notifyHost(type: 'product.ready' | 'product.session.expired') {
  if (window.parent === window) return
  window.parent.postMessage({ contract: PRODUCT_HOST_CONTRACT, type }, window.location.origin)
}

function useProductHostSession() {
  const [connected, setConnected] = useState(window.parent === window)

  useEffect(() => {
    function receive(event: MessageEvent) {
      if (event.origin !== window.location.origin || event.source !== window.parent) return
      const message = event.data as { contract?: unknown; type?: unknown; sessionToken?: unknown } | null
      if (!message || message.contract !== PRODUCT_HOST_CONTRACT) return
      if (message.type === 'host.session.expired') {
        configureGeoProductTransport({ apiBase: '/api/product/geo', sessionToken: null })
        setConnected(false)
        return
      }
      if (message.type !== 'host.hello' && message.type !== 'host.session') return
      const sessionToken = typeof message.sessionToken === 'string' ? message.sessionToken : null
      configureGeoProductTransport({
        apiBase: '/api/product/geo',
        sessionToken,
        onSessionExpired: () => notifyHost('product.session.expired'),
      })
      setConnected(Boolean(sessionToken))
    }
    window.addEventListener('message', receive)
    notifyHost('product.ready')
    return () => window.removeEventListener('message', receive)
  }, [])

  return connected
}

function GeoProduct() {
  const connected = useProductHostSession()
  const [active, setActive] = useState<GeoFlowKind>('monitor')
  const selected = GEO_FLOW_MENU.find((item) => item.kind === active)

  return (
    <main className="mx-auto min-h-screen w-full max-w-[1440px] space-y-5 p-5 md:p-7">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex size-10 items-center justify-center rounded-xl bg-accent text-white">
            <Radar className="size-5" aria-hidden="true" />
          </span>
          <div>
            <h1 className="text-xl font-semibold">GEO</h1>
            <p className="text-sm text-muted">企业外部智能感知</p>
          </div>
        </div>
        <span className="rounded-full border px-3 py-1 text-xs text-muted">
          {connected ? '已连接 EIOS 会话' : '等待 EIOS 会话'}
        </span>
      </header>

      <nav className="flex flex-wrap gap-2" aria-label="GEO 功能">
        {GEO_FLOW_MENU.map((item) => (
          <button
            key={item.kind}
            type="button"
            aria-current={active === item.kind ? 'page' : undefined}
            onClick={() => setActive(item.kind)}
            className={
              active === item.kind
                ? 'rounded-lg bg-accent px-3 py-2 text-sm text-white'
                : 'rounded-lg border bg-surface px-3 py-2 text-sm text-muted hover:bg-surface-raised hover:text-foreground'
            }
          >
            <span aria-hidden="true">{item.icon}</span> {item.label}
          </button>
        ))}
      </nav>

      <section aria-label={selected?.label ?? 'GEO 功能'} className="rounded-2xl border bg-surface p-4 md:p-5">
        {connected || window.parent === window ? (
          <GeoFlowRouter kind={active} />
        ) : (
          <div className="py-12 text-center text-sm text-muted">正在等待 EIOS Product Host 建立会话…</div>
        )}
      </section>
    </main>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <GeoProduct />
  </StrictMode>,
)
