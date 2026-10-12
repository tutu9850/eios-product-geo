import { useEffect, useState } from 'react'
import { ArrowRight, LoaderCircle, Plus, RefreshCw, Search, Trash2 } from 'lucide-react'
import { geoDelete, geoGet, geoPost } from './geo-api'
import { askGeoConfirm, indexStatusText, statusText, useGeoDemoMode, useGeoNav } from './shared'
import { GEO_DEMO_MARKET, GEO_DEMO_NOTICE } from './demo-fixtures'

type Row = Record<string, any>
const rows = (v: any, keys = ['items']) => { if (Array.isArray(v)) return v; for (const k of keys) if (Array.isArray(v?.[k])) return v[k]; return [] }
const text = (r: Row, ...keys: string[]) => { for (const k of keys) if (r?.[k] !== undefined && r[k] !== '') return String(r[k]); return '—' }
type Tab = 'watch' | 'signals' | 'links'
/** 关注来源类型与收录状态都是机器值，页面上只显示业务文字（2026-09-21） */
const SOURCE_TYPE_LABEL: Record<string, string> = { website: '官网', news: '媒体', zhihu: '知乎' }

export function GeoMarketWorkspace() {
  const go = useGeoNav()
  const { enabled: demoMode } = useGeoDemoMode()
  const [tab, setTab] = useState<Tab>('signals')
  const [watch, setWatch] = useState<Row[]>([]), [signals, setSignals] = useState<Row[]>([]), [links, setLinks] = useState<Row[]>([])
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(''), [notice, setNotice] = useState('')
  const [showAdd, setShowAdd] = useState(false), [name, setName] = useState(''), [url, setUrl] = useState(''), [type, setType] = useState('website')
  async function load() {
    setLoading(true)
    if (demoMode) {
      setWatch([...GEO_DEMO_MARKET.watch] as Row[])
      setSignals([...GEO_DEMO_MARKET.signals] as Row[])
      setLinks([...GEO_DEMO_MARKET.links] as Row[])
      setLoading(false)
      return
    }
    const result = await Promise.allSettled([geoGet('/market/watchlist'),geoGet('/market/signals'),geoGet('/links')]); if(result[0].status==='fulfilled') setWatch(rows(result[0].value)); if(result[1].status==='fulfilled') setSignals(rows(result[1].value)); if(result[2].status==='fulfilled') setLinks(rows(result[2].value)); setLoading(false)
  }
  useEffect(()=>{void load()},[demoMode])
  async function act(key:string, work:()=>Promise<any>, message:string){setBusy(key);setNotice('');try{const d=await work();setNotice(d?.error||message);await load()}catch(e){setNotice(e instanceof Error?e.message:'操作失败')}finally{setBusy('')}}
  async function addWatch(){if(!name.trim())return;await act('add',()=>geoPost('/market/watchlist',{name,url,type}),'已加入关注');setName('');setUrl('');setShowAdd(false)}
  /** 转内容计划成功后直接跳到内容计划页并高亮那条（计划用信号标题做主题，2026-09-21） */
  async function signalToPlan(row: Row){const title=text(row,'title');await act(`plan-${row.id}`,()=>geoPost(`/market/signals/${row.id}/to-plan`,{}),'已转入内容计划');if(title&&title!=='—')go?.('plans',{focus:title})}
  async function removeWatch(row: Row){if(!(await askGeoConfirm(`移除关注「${text(row,'name')}」后，不再采集它的市场信号。`))) return; await act(`delete-${text(row,'id')}`,()=>geoDelete(`/market/watchlist/${row.id}`),'已移除')}
  async function removeLink(row: Row){if(!(await askGeoConfirm(`删除链接「${text(row,'name')}」后，收录检测记录一并移除。`))) return; await act(`delete-${text(row,'id')}`,()=>geoDelete(`/links/${row.id}`),'已删除')}
  async function addLink(){if(!url.trim())return;await act('add-link',()=>geoPost('/links',{name:name.trim(),url:url.trim()}),'链接已添加');setName('');setUrl('');setShowAdd(false)}
  const indexed=links.filter((x)=>x.index_status==='indexed').length
  return <div className="market-console"><header className="workspace-intro"><div><span>市场</span><h1>市场情报</h1><p>追踪竞品和行业变化，把外部公开信息先变成可核实的线索，再决定是否进入内容计划。</p></div><button className="geo-btn secondary" onClick={()=>void load()} disabled={demoMode}>{loading?<LoaderCircle className="spin"/>:<RefreshCw/>}{demoMode?'演示样例':'刷新'}</button></header>
    {demoMode&&<div className="geo-demo-banner"><span><b>内测演示数据已开启</b>　{GEO_DEMO_NOTICE}；本页只读展示关注来源、市场信号和收录状态。</span></div>}
    <div className="geo-scope-note"><b>这页解决什么问题：</b>发现外部市场变化 → 人工确认事实 → 需要时转成内容计划。这里的信号不会直接改变品牌曝光率、推荐率或认知洞察。</div>
    <section className="market-summary"><div><b>{watch.length}</b><span>关注来源</span></div><div><b>{signals.filter(x=>!['ignored','planned'].includes(x.status)).length}</b><span>待确认信号</span></div><div><b>{signals.filter(x=>x.status==='planned').length}</b><span>已转内容计划</span></div><div><b>{indexed}<small>/{links.length}</small></b><span>已收录链接</span></div></section>
    <nav className="market-tabs">{([['watch','关注来源'],['signals','市场信号'],['links','链接收录']] as Array<[Tab,string]>).map(([id,label])=><button key={id} className={tab===id?'active':''} onClick={()=>{setTab(id);setShowAdd(false)}}>{label}<span>{id==='watch'?watch.length:id==='signals'?signals.length:links.length}</span></button>)}</nav>
    {notice&&<div className="geo-notice">{notice}</div>}
    <section className="market-workarea"><header><div><h2>{tab==='watch'?'关注来源':tab==='signals'?'近期市场变化':'内容收录台账'}</h2><p>{tab==='watch'?'配置需要持续采集的竞品官网、行业媒体或内容平台':tab==='signals'?'先确认事实，再决定是否转入内容计划':'登记发布链接并进行真实收录检测'}</p></div><div className="workspace-actions">{!demoMode&&tab==='watch'&&<button className="geo-btn primary" onClick={()=>setShowAdd(!showAdd)}><Plus/>新增关注</button>}{!demoMode&&tab==='watch'&&watch.length>0&&<button className="geo-btn secondary" onClick={()=>void act('collect',()=>geoPost('/market/collect',{watch_ids:null}),'采集完成')}>{busy==='collect'?<LoaderCircle className="spin"/>:<RefreshCw/>}采集全部</button>}{!demoMode&&tab==='links'&&<><button className="geo-btn primary" onClick={()=>setShowAdd(!showAdd)}><Plus/>登记链接</button><button className="geo-btn secondary" onClick={()=>void act('check-all',()=>geoPost('/links/check-all',{}),'检测完成')}><Search/>检测未收录</button></>}</div></header>
      {showAdd&&!demoMode&&<div className="market-add"><input placeholder={tab==='watch'?'来源名称':'内容名称（可选）'} value={name} onChange={e=>setName(e.target.value)}/><input placeholder={tab==='watch'?'来源网址（可选）':'已发布内容 URL'} value={url} onChange={e=>setUrl(e.target.value)}/>{tab==='watch'&&<select value={type} onChange={e=>setType(e.target.value)}><option value="website">官网</option><option value="news">媒体</option><option value="zhihu">知乎</option></select>}<button className="geo-btn primary" onClick={()=>void(tab==='watch'?addWatch():addLink())}>保存</button></div>}
      {tab==='watch'&&<details className="geo-long-list market-long-list" data-empty={watch.length===0} open={watch.length <= 6}><summary><span>关注来源</span><small>{watch.length} 个{watch.length > 6 ? '，默认收起长列表' : ''}</small></summary><div className="geo-long-list-body"><div className="market-table">{watch.length?watch.map(row=><article key={text(row,'id')}><span className="source-type">{SOURCE_TYPE_LABEL[String(row.type)]??'其他来源'}</span><div><b>{text(row,'name')}</b><small>{text(row,'url','created_at')}</small></div>{!demoMode&&<button onClick={()=>void removeWatch(row)} aria-label="移除关注"><Trash2/></button>}</article>):<div className="market-empty"><b>还没有关注来源</b><span>先添加一个竞品官网、行业媒体或内容平台，系统才有东西可追踪。</span><button className="geo-btn primary" onClick={()=>setShowAdd(true)}><Plus/>添加第一个关注来源</button></div>}</div></div></details>}
      {tab==='signals'&&<details className="geo-long-list market-long-list" data-empty={signals.length===0} open={signals.length <= 6}><summary><span>近期市场变化</span><small>{signals.length} 条{signals.length > 6 ? '，默认收起长列表' : ''}</small></summary><div className="geo-long-list-body"><div className="market-signal-grid">{signals.length?signals.map(row=><article key={text(row,'id')}><header><span data-status={row.status}>{row.status?statusText(row.status):text(row,'source_type')}</span><small>{text(row,'source_name','created_at')}</small></header><h3>{text(row,'title')}</h3><p>{text(row,'summary','text').slice(0,180)}</p>{Array.isArray(row.facts)&&row.facts.length>0&&<ul>{row.facts.slice(0,3).map((f:string,i:number)=><li key={i}>{f}</li>)}</ul>}{!demoMode&&<footer>{row.status!=='ignored'&&<button onClick={()=>void act(`extract-${row.id}`,()=>geoPost(`/market/signals/${row.id}/extract`,{}),'事实提取完成')}>提取事实</button>}<button onClick={()=>void signalToPlan(row)}>转内容计划<ArrowRight/></button><button onClick={()=>void act(`ignore-${row.id}`,()=>geoPost(`/market/signals/${row.id}/ignore`,{}),'已忽略')}>忽略</button></footer>}</article>):<div className="market-empty"><b>还没有外部市场信号</b><span>先添加关注来源，再点击“采集全部”；采集结果只是线索，确认事实后才会进入内容计划。</span><button className="geo-btn primary" onClick={()=>{setTab('watch');setShowAdd(true)}}><Plus/>先添加关注来源</button></div>}</div></div></details>}
      {tab==='links'&&<details className="geo-long-list market-long-list" data-empty={links.length===0} open={links.length <= 6}><summary><span>内容收录台账</span><small>{links.length} 条{links.length > 6 ? '，默认收起长列表' : ''}</small></summary><div className="geo-long-list-body"><div className="market-table links">{links.length?links.map(row=><article key={text(row,'id')}><span className="index-state" data-status={row.index_status}>{indexStatusText(row.index_status)}</span><div><b>{text(row,'name')}</b><small>{text(row,'url')} · {text(row,'status_note')}</small></div>{!demoMode&&<><button onClick={()=>void act(`check-${row.id}`,()=>geoPost('/links/check',{id:row.id}),'检测完成')} aria-label="检测收录"><Search/></button><button onClick={()=>void removeLink(row)} aria-label="删除链接"><Trash2/></button></>}</article>):<div className="market-empty"><b>还没有发布链接</b><span>把已经发布的文章或页面 URL 登记进来，系统才能检查搜索引擎是否收录。</span><button className="geo-btn primary" onClick={()=>setShowAdd(true)}><Plus/>登记第一条链接</button></div>}</div></div></details>}
    </section>
  </div>
}
