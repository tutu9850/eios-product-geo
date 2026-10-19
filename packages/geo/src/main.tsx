import { StrictMode, useEffect, useState, type ComponentType } from 'react'
import { createRoot } from 'react-dom/client'
import { BarChart3, BookOpenCheck, ChartNoAxesCombined, CircleDot, FlaskConical, Radar, Sparkles, Target, Wrench } from 'lucide-react'
import { GeoFlowRouter, type GeoFlowKind } from '@geo-advisor'
import { GeoEnterpriseOverview } from '@geo-advisor/GeoEnterpriseOverview'
import { GeoMarketWorkspace } from '@geo-advisor/GeoMarketWorkspace'
import { GeoAdvancedTools } from '@geo-advisor/GeoAdvancedTools'
import { GeoProductGuide } from '@geo-advisor/GeoProductGuide'
import { configureGeoProductTransport } from '@geo-advisor/geo-api'
import { GeoCardErrorBoundary, GeoConfirmHost, GeoDemoModeContext, GeoNavContext, GeoNavParamsContext, type GeoNavParams } from '@geo-advisor/shared'
import { MonitorSubjectPicker } from '@geo-advisor/geo-monitor-subject'
import { GeoJourneyWorkspace } from '@geo-advisor/GeoJourneyWorkspace'
import './index.css'

const PRODUCT_HOST_CONTRACT = 'eios.product_host/v1'
function notifyHost(type: 'product.ready' | 'product.session.expired') {
  if (window.parent !== window) window.parent.postMessage({ contract: PRODUCT_HOST_CONTRACT, type }, window.location.origin)
}
function useProductHostSession() {
  // GEO 的产品门只在 EIOS Client 的 Product Host 内成立。顶层直开不能
  // 回落到老 BFF：那会把 HTML/旧接口响应误读成 GEO 数据，用户看到的是
  // “请求失败”而不是清晰的入口提示。
  const [connected, setConnected] = useState(false)
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
  { id: 'overview', label: '总览', icon: BarChart3 },
  { id: 'monitor', label: '监测', icon: Radar },
  { id: 'insight', label: '差距', icon: ChartNoAxesCombined },
  { id: 'growth', label: '内容行动', icon: Target },
  { id: 'profile', label: '企业资料', icon: BookOpenCheck },
  { id: 'market', label: '更多', icon: Wrench },
]
const SUBNAV: Partial<Record<Workspace, Array<{ id: GeoFlowKind; label: string }>>> = {
  monitor: [{ id: 'monitor-report', label: '模型回答' }, { id: 'monitor-analysis', label: '统计分析' }, { id: 'monitor', label: '对象与任务' }, { id: 'questions', label: '监测问题' }, { id: 'cognition-map', label: '问题分布' }],
  insight: [{ id: 'insight-overview', label: '有据差距' }, { id: 'gaps', label: '资料缺口' }, { id: 'cognition', label: '理解评估' }],
  profile: [{ id: 'profile-overview', label: '资料与出处' }, { id: 'kb-init', label: '导入资料' }, { id: 'auto-config', label: '首次设置' }],
  growth: [{ id: 'plans', label: '内容计划' }, { id: 'content', label: '撰写稿件' }, { id: 'assets', label: '内容资产' }, { id: 'action-plan', label: '行动排序' }],
  market: [{ id: 'battle', label: '模型对照' }, { id: 'faq', label: '常见问答' }, { id: 'report', label: '阶段报告' }],
}
const DEFAULTS: Partial<Record<Workspace, GeoFlowKind>> = { monitor: 'monitor-report', insight: 'insight-overview', profile: 'profile-overview', growth: 'plans' }

// 默认页只把已经存在的卡片排成一条业务路径；单点页仍由下方页签保留。
// 这里不创建新的业务组件，也不改变任何卡片的数据或接口。
const WORKSPACE_BUNDLES: Partial<Record<Workspace, GeoFlowKind[]>> = {
  monitor: ['monitor'],
  insight: ['insight-overview'],
  profile: ['profile-overview'],
}

const FLOW_WORKSPACE: Record<GeoFlowKind, Workspace> = {
  'kb-init': 'profile', 'auto-config': 'profile', monitor: 'monitor', 'monitor-report': 'monitor', assets: 'growth', questions: 'monitor', gaps: 'insight', cognition: 'insight', content: 'growth', battle: 'market', report: 'market', plans: 'growth', 'action-plan': 'growth', 'insight-overview': 'insight', 'profile-overview': 'profile', 'monitor-analysis': 'monitor', faq: 'market', 'cognition-map': 'monitor',
}

const WORKSPACES = new Set<Workspace>(['overview', 'monitor', 'insight', 'profile', 'growth', 'market'])
const FLOWS = new Set<GeoFlowKind>(Object.keys(FLOW_WORKSPACE) as GeoFlowKind[])
const GEO_ROUTE_STORAGE_KEY = 'eios-geo-route'

function readGeoRoute(): { workspace: Workspace; flow?: GeoFlowKind } {
  const params = new URLSearchParams(window.location.search)
  const requestedWorkspace = params.get('workspace') as Workspace | null
  const requestedFlow = params.get('view') as GeoFlowKind | null
  if (requestedFlow && FLOWS.has(requestedFlow)) {
    const flowWorkspace = FLOW_WORKSPACE[requestedFlow]
    return { workspace: flowWorkspace, flow: requestedFlow }
  }
  if (requestedWorkspace && WORKSPACES.has(requestedWorkspace)) return { workspace: requestedWorkspace }
  try {
    const stored = JSON.parse(window.localStorage.getItem(GEO_ROUTE_STORAGE_KEY) ?? 'null') as { workspace?: unknown; flow?: unknown } | null
    const workspace = stored?.workspace as Workspace | undefined
    const flow = stored?.flow as GeoFlowKind | undefined
    if (flow && FLOWS.has(flow)) return { workspace: FLOW_WORKSPACE[flow], flow }
    if (workspace && WORKSPACES.has(workspace)) return { workspace }
  } catch {
    // 损坏的本地路由只影响恢复，不阻断 GEO 首屏。
  }
  return { workspace: 'overview' }
}

function writeGeoRoute(workspace: Workspace, flow?: GeoFlowKind) {
  const url = new URL(window.location.href)
  url.searchParams.set('workspace', workspace)
  if (flow) url.searchParams.set('view', flow)
  else url.searchParams.delete('view')
  window.history.replaceState({}, '', url)
  window.localStorage.setItem(GEO_ROUTE_STORAGE_KEY, JSON.stringify({ workspace, ...(flow ? { flow } : {}) }))
}

const WORKSPACE_COPY: Record<Exclude<Workspace, 'overview' | 'market' | 'insight' | 'profile'>, { eyebrow: string; title: string; description: string; note: string }> = {
  monitor: { eyebrow: '模型监测', title: '模型如何回答客户的问题', description: '选择要持续观察的品牌，运行一轮真实客户问题，并核对模型原话。', note: '仅监测国产大模型' },
  growth: { eyebrow: '增长闭环', title: '把差距变成一篇有依据的内容', description: '把客户问题、资料缺口和内容计划串成可执行的增长闭环。', note: '从洞察进入行动' },
}


function WorkspaceHeader({ workspace }: { workspace: Exclude<Workspace, 'overview' | 'market' | 'insight' | 'profile'> }) {
  const copy = WORKSPACE_COPY[workspace]
  return <header className="workspace-intro"><div><span>{copy.eyebrow}</span><h1>{copy.title}</h1><p>{copy.description}</p></div><em><CircleDot />{copy.note}</em></header>
}

function GeoProduct() {
  const connected = useProductHostSession()
  const initialRoute = readGeoRoute()
  const [active, setActive] = useState<Workspace>(initialRoute.workspace)
  const [flows, setFlows] = useState(() => ({ ...DEFAULTS, ...(initialRoute.flow ? { [initialRoute.workspace]: initialRoute.flow } : {}) }))
  const [legacyPreview, setLegacyPreview] = useState(false)
  const [advanced, setAdvanced] = useState(false)
  const [guideOpen, setGuideOpen] = useState(false)
  const [demoMode, setDemoMode] = useState(() => window.localStorage.getItem('eios-geo-demo-fixtures') === 'on')
  const [navParams, setNavParams] = useState<GeoNavParams>({ focus: null, seed: null, nonce: 0 })
  const flow = flows[active]
  useEffect(() => { writeGeoRoute(active, flow) }, [active, flow])
  function navigate(next: string) {
    setLegacyPreview(false)
    if (!NAV.some((item) => item.id === next)) return
    const target = next as Workspace
    setActive(target)
    const defaultFlow = DEFAULTS[target]
    if (!defaultFlow) setFlows((current) => ({ ...current, [target]: undefined }))
    if (defaultFlow) setFlows((current) => ({ ...current, [target]: defaultFlow }))
  }
  function go(kind: string, options?: { focus?: string; seed?: string }) {
    setLegacyPreview(false)
    if (!(kind in FLOW_WORKSPACE)) return
    const target = FLOW_WORKSPACE[kind as GeoFlowKind]
    setActive(target)
    setFlows((current) => ({ ...current, [target]: kind as GeoFlowKind }))
    setNavParams((current) => ({ focus: options?.focus ?? null, seed: options?.seed ?? null, nonce: current.nonce + 1 }))
  }
  function navigateDestination(next: string) {
    if (FLOWS.has(next as GeoFlowKind)) go(next)
    else navigate(next)
  }
  function toggleDemoMode() {
    setDemoMode((current) => {
      const next = !current
      window.localStorage.setItem('eios-geo-demo-fixtures', next ? 'on' : 'off')
      return next
    })
  }
  function renderFlow(kind: GeoFlowKind) {
    const labels: Record<GeoFlowKind, string> = {
      'kb-init': '导入企业资料', 'auto-config': '首次设置', monitor: '监测工作台', 'monitor-report': '模型回答', assets: '内容资产', questions: '客户会问什么', gaps: '资料缺口', cognition: '品牌理解', content: '内容生成', battle: '模型对比', report: '阶段报告', plans: '内容计划', 'action-plan': '行动计划', 'insight-overview': '差距诊断', 'profile-overview': '资料总览', 'monitor-analysis': '监测分析', faq: '生成常见问答', 'cognition-map': '客户认知地图',
    }
    return <GeoCardErrorBoundary label={labels[kind]}><GeoFlowRouter kind={kind} /></GeoCardErrorBoundary>
  }
  return <GeoDemoModeContext.Provider value={{ enabled: demoMode, toggle: toggleDemoMode }}><GeoNavContext.Provider value={go}><GeoNavParamsContext.Provider value={navParams}><main className="geo-product-shell">
    <header className="geo-product-nav"><div className="geo-r1-brand"><b>GEO</b><span>企业模型可见性</span></div><nav aria-label="GEO 功能">{NAV.map(({ id, label, icon: Icon }) => <button key={id} type="button" aria-label={label} aria-current={active === id ? 'page' : undefined} onClick={() => navigate(id)}><Icon /><span>{label}</span></button>)}</nav><div className="product-utilities"><button className="guide-trigger" aria-label="打开 GEO 使用说明" onClick={() => setGuideOpen(true)}><Sparkles/><span>怎么使用</span></button><button className={`demo-trigger${demoMode ? ' active' : ''}`} aria-label={`演示数据（仅用于内测样例）：${demoMode ? '已开启' : '已关闭'}`} aria-pressed={demoMode} onClick={toggleDemoMode}><FlaskConical/><span>演示数据 {demoMode ? '开' : '关'}</span></button><button className="advanced-trigger" aria-label="高级工具" onClick={()=>setAdvanced(true)}><Wrench/><span>高级工具</span></button><div className="geo-rail-status"><CircleDot /><span>{connected ? '已连接' : '等待会话'}</span></div></div></header>
    <section className="geo-workspace geo-r1-workspace">
      {!demoMode && active !== 'overview' && active !== 'market' && active !== 'insight' && active !== 'profile' && <WorkspaceHeader workspace={active} />}
      {active === 'market' && <button className="geo-more-market" onClick={()=>setFlows((current)=>({...current,market:undefined}))}>市场线索</button>}
      {demoMode && (active === 'monitor' || active === 'insight' || active === 'growth') && <details className="geo-jw-tools"><summary>辅助功能与原有入口（分析、任务、评估等）</summary><nav className="geo-subnav">{SUBNAV[active]?.map(item=><button key={item.id} onClick={()=>{setLegacyPreview(true);setFlows(current=>({...current,[active]:item.id}))}}>{item.label}</button>)}</nav></details>}
      {SUBNAV[active] && !(demoMode && ['monitor','insight','growth'].includes(active)) && <nav className="geo-subnav" aria-label="页内功能">{SUBNAV[active]?.map((item) => <button key={item.id} type="button" aria-current={flow === item.id ? 'page' : undefined} className={flow === item.id ? 'active' : ''} onClick={() => setFlows((current) => ({ ...current, [active]: item.id }))}>{item.label}</button>)}</nav>}
      {connected && active === 'monitor' && legacyPreview && <button className="geo-btn" onClick={()=>navigate('monitor')}>返回监测主入口 / 新建对象</button>}
      {connected && <div className="geo-scope-bar">{demoMode ? <div><span className="geo-demo-pill">演示样例</span><b>云栖示例家居</b><span>3 轮 · 4 个模型 · 固定样本</span></div> : <MonitorSubjectPicker />}<span>当前范围应用于支持主体筛选的读面</span></div>}
      {connected && <div className="geo-journey-strip" aria-label="GEO 操作主线">{[{id:'monitor',number:'01',title:'看模型回答',detail:'原话与监测结果'}, {id:'insight',number:'02',title:'确认差距',detail:'结论与对应证据'}, {id:'growth',number:'03',title:'完成内容',detail:'计划、稿件与发布登记'}, {id:'monitor',number:'04',title:'新轮次对比',detail:'发布后重新监测'}].map((step,i)=><button key={i} onClick={()=>navigate(step.id)} className={active===step.id && i!==3 ? 'current' : ''}><span>{step.number}</span><div><b>{step.title}</b><small>{step.detail}</small></div><span>→</span></button>)}</div>}
      {connected && demoMode && <p className="geo-preview-notice">界面验收样例 · 数字来自隔离样本，正式资料生成与发布后效果尚未完成真实链验收。</p>}
      {connected ? <>
        {active === 'overview' && <GeoEnterpriseOverview onNavigate={navigateDestination} />}
        {active === 'market' && !flow && <GeoMarketWorkspace />}
        {demoMode && (active === 'monitor' || active === 'insight' || active === 'growth') && !legacyPreview && !['monitor','questions','cognition-map','cognition','action-plan'].includes(flow ?? '') ? <GeoJourneyWorkspace workspace={active} /> : active !== 'overview' && flow ? (
          <div className={WORKSPACE_BUNDLES[active]?.includes(flow) && WORKSPACE_BUNDLES[active]?.[0] === flow ? `geo-legacy-surface geo-flow-bundle geo-flow-bundle-${active}` : 'geo-legacy-surface'}>
            {WORKSPACE_BUNDLES[active]?.includes(flow) && WORKSPACE_BUNDLES[active]?.[0] === flow
              ? WORKSPACE_BUNDLES[active]?.map((kind) => <section className="geo-flow-bundle-item" key={kind}>{renderFlow(kind)}</section>)
              : renderFlow(flow)}
          </div>
        ) : null}
      </> : <div className="geo-session-wait"><Sparkles /><h1>{window.parent === window ? '请从 EIOS Client 打开 GEO' : '正在连接企业工作区'}</h1><p>{window.parent === window ? 'GEO 需要通过 EIOS Client 建立企业工作区会话；请从 Client 的 GEO 入口进入。' : '等待 EIOS Product Host 建立安全会话。'}</p></div>}
    </section>
    {guideOpen && <GeoProductGuide workspace={active} onNavigate={(target) => navigate(target)} onClose={() => setGuideOpen(false)} />}
    {advanced&&<GeoAdvancedTools onClose={()=>setAdvanced(false)}/>} 
    <GeoConfirmHost />
  </main></GeoNavParamsContext.Provider></GeoNavContext.Provider></GeoDemoModeContext.Provider>
}
createRoot(document.getElementById('root')!).render(<StrictMode><GeoProduct /></StrictMode>)
