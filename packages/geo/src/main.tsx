import { StrictMode, useEffect, useState, type ComponentType } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, BarChart3, BookOpenCheck, ChartNoAxesCombined, CircleDot, Radar, Sparkles, Target, Wrench } from 'lucide-react'
import { GeoFlowRouter, type GeoFlowKind } from '@geo-advisor'
import { GeoEnterpriseOverview } from '@geo-advisor/GeoEnterpriseOverview'
import { GeoMarketWorkspace } from '@geo-advisor/GeoMarketWorkspace'
import { GeoAdvancedTools } from '@geo-advisor/GeoAdvancedTools'
import { configureGeoProductTransport } from '@geo-advisor/geo-api'
import { GeoConfirmHost, GeoNavContext, GeoNavParamsContext, type GeoNavParams } from '@geo-advisor/shared'
import './index.css'

const PRODUCT_HOST_CONTRACT = 'eios.product_host/v1'
function notifyHost(type: 'product.ready' | 'product.session.expired') {
  if (window.parent !== window) window.parent.postMessage({ contract: PRODUCT_HOST_CONTRACT, type }, window.location.origin)
}
function useProductHostSession() {
  const [connected, setConnected] = useState(window.parent === window)
  useEffect(() => {
    function receive(event: MessageEvent) {
      if (event.origin !== window.location.origin || event.source !== window.parent) return
      const message = event.data as { contract?: unknown; type?: unknown; sessionToken?: unknown } | null
      if (!message || message.contract !== PRODUCT_HOST_CONTRACT) return
      if (message.type === 'host.session.expired') {
        configureGeoProductTransport({ apiBase: '/api/product/geo', sessionToken: null }); setConnected(false); return
      }
      if (message.type !== 'host.hello' && message.type !== 'host.session') return
      const sessionToken = typeof message.sessionToken === 'string' ? message.sessionToken : null
      configureGeoProductTransport({ apiBase: '/api/product/geo', sessionToken, onSessionExpired: () => notifyHost('product.session.expired') })
      setConnected(Boolean(sessionToken))
    }
    window.addEventListener('message', receive); notifyHost('product.ready')
    return () => window.removeEventListener('message', receive)
  }, [])
  return connected
}

type Workspace = 'overview' | 'monitor' | 'insight' | 'profile' | 'growth' | 'market'
type NavItem = { id: Workspace; label: string; icon: ComponentType<{ className?: string }> }
const NAV: NavItem[] = [
  { id: 'overview', label: '经营总览', icon: BarChart3 }, { id: 'monitor', label: 'AI 监测', icon: Radar },
  { id: 'insight', label: '认知洞察', icon: ChartNoAxesCombined }, { id: 'growth', label: '增长行动', icon: Target },
  { id: 'profile', label: '企业资料', icon: BookOpenCheck },
  { id: 'market', label: '市场情报', icon: Activity },
]
const SUBNAV: Partial<Record<Workspace, Array<{ id: GeoFlowKind; label: string }>>> = {
  monitor: [{ id: 'monitor', label: '监测工作台' }, { id: 'monitor-analysis', label: '专业分析' }, { id: 'battle', label: 'AI 对战' }],
  insight: [{ id: 'insight-overview', label: '差距诊断' }, { id: 'cognition', label: '认知健康' }, { id: 'cognition-map', label: '客户认知地图' }, { id: 'report', label: '阶段报告' }],
  profile: [{ id: 'profile-overview', label: '资料总揽' }, { id: 'kb-init', label: '知识库同步' }, { id: 'assets', label: '内容资产' }, { id: 'auto-config', label: '自动配置' }],
  growth: [{ id: 'questions', label: '客户问题池' }, { id: 'gaps', label: '知识缺口' }, { id: 'plans', label: '内容计划' }, { id: 'content', label: '内容生成' }, { id: 'faq', label: 'FAQ 生产' }, { id: 'action-plan', label: '行动计划' }],
}
const DEFAULTS: Partial<Record<Workspace, GeoFlowKind>> = { monitor: 'monitor', insight: 'insight-overview', profile: 'profile-overview', growth: 'plans' }

/** 功能 → 它所在的页签（跨页跳转用，保证跳过去时页签也对） */
const FLOW_WORKSPACE: Record<GeoFlowKind, Workspace> = {
  'kb-init': 'profile', 'auto-config': 'profile', monitor: 'monitor', assets: 'profile', questions: 'growth',
  gaps: 'growth', cognition: 'insight', content: 'growth', battle: 'monitor', report: 'insight',
  plans: 'growth', 'action-plan': 'growth', 'insight-overview': 'insight', 'profile-overview': 'profile',
  'monitor-analysis': 'monitor', faq: 'growth', 'cognition-map': 'insight',
}

const WORKSPACE_COPY: Record<Exclude<Workspace, 'overview' | 'market' | 'insight' | 'profile'>, { eyebrow: string; title: string; description: string; note: string }> = {
  monitor: { eyebrow: 'MODEL OBSERVATORY', title: '国产大模型监测', description: '管理监测对象、运行探针，并在同一工作区判断品牌是否被看见、如何被描述。', note: '仅监测国产大模型' },
  growth: { eyebrow: 'GROWTH OPERATIONS', title: '增长行动中心', description: '把客户问题、知识缺口和内容计划串成可执行的增长闭环。', note: '从洞察进入行动' },
}

function WorkspaceHeader({ workspace }: { workspace: Exclude<Workspace, 'overview' | 'market' | 'insight' | 'profile'> }) {
  const copy = WORKSPACE_COPY[workspace]
  return <header className="workspace-intro">
    <div><span>{copy.eyebrow}</span><h1>{copy.title}</h1><p>{copy.description}</p></div>
    <em><CircleDot />{copy.note}</em>
  </header>
}

function GeoProduct() {
  const connected = useProductHostSession()
  const [active, setActive] = useState<Workspace>('overview')
  const [flows, setFlows] = useState(DEFAULTS)
  const [advanced, setAdvanced] = useState(false)
  const [navParams, setNavParams] = useState<GeoNavParams>({ focus: null, seed: null, nonce: 0 })
  const flow = flows[active]
  function navigate(next: string) { if (NAV.some((item) => item.id === next)) setActive(next as Workspace) }
  // 卡片发起的跨页跳转：切页签 + 切该页签的页内功能 + 带上 focus / seed
  function go(kind: string, options?: { focus?: string; seed?: string }) {
    if (!(kind in FLOW_WORKSPACE)) return
    const target = FLOW_WORKSPACE[kind as GeoFlowKind]
    setActive(target)
    setFlows((current) => ({ ...current, [target]: kind as GeoFlowKind }))
    setNavParams((current) => ({ focus: options?.focus ?? null, seed: options?.seed ?? null, nonce: current.nonce + 1 }))
  }
  return <GeoNavContext.Provider value={go}><GeoNavParamsContext.Provider value={navParams}><main className="geo-product-shell">
    <header className="geo-product-nav"><nav aria-label="GEO 功能">{NAV.map(({ id, label, icon: Icon }) => <button key={id} type="button" aria-current={active === id ? 'page' : undefined} onClick={() => setActive(id)}><Icon /><span>{label}</span></button>)}</nav><div className="product-utilities"><button className="advanced-trigger" onClick={()=>setAdvanced(true)}><Wrench/><span>高级工具</span></button><div className="geo-rail-status"><CircleDot /><span>{connected ? '已连接' : '等待会话'}</span></div></div></header>
    <section className="geo-workspace">
      {active !== 'overview' && active !== 'market' && active !== 'insight' && active !== 'profile' && <WorkspaceHeader workspace={active} />}
      {SUBNAV[active] && <nav className="geo-subnav" aria-label="页内功能">{SUBNAV[active]?.map((item) => <button key={item.id} className={flow === item.id ? 'active' : ''} onClick={() => setFlows((current) => ({ ...current, [active]: item.id }))}>{item.label}</button>)}</nav>}
      {connected || window.parent === window ? <>{active === 'overview' && <GeoEnterpriseOverview onNavigate={navigate} />}{active === 'market' && <GeoMarketWorkspace />}{active !== 'overview' && active !== 'market' && flow && <div className="geo-legacy-surface"><GeoFlowRouter kind={flow} /></div>}</> : <div className="geo-session-wait"><Sparkles /><h1>正在连接企业工作区</h1><p>等待 EIOS Product Host 建立安全会话。</p></div>}
    </section>
    {advanced&&<GeoAdvancedTools onClose={()=>setAdvanced(false)}/>} 
    <GeoConfirmHost />
  </main></GeoNavParamsContext.Provider></GeoNavContext.Provider>
}
createRoot(document.getElementById('root')!).render(<StrictMode><GeoProduct /></StrictMode>)
