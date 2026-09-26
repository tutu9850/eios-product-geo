import { useEffect, useState } from 'react'
import { ArrowRight, LoaderCircle, Plus, RefreshCw, Search, Trash2 } from 'lucide-react'
import { geoDelete, geoGet, geoPost } from './geo-api'
import { askGeoConfirm, indexStatusText, statusText, useGeoNav } from './shared'

type Row = Record<string, any>
const rows = (v: any, keys = ['items']) => { if (Array.isArray(v)) return v; for (const k of keys) if (Array.isArray(v?.[k])) return v[k]; return [] }
const text = (r: Row, ...keys: string[]) => { for (const k of keys) if (r?.[k] !== undefined && r[k] !== '') return String(r[k]); return '—' }
type Tab = 'watch' | 'signals' | 'links'
/** 关注来源类型与收录状态都是机器值，页面上只显示业务文字（2026-09-21） */
const SOURCE_TYPE_LABEL: Record<string, string> = { website: '官网', news: '媒体', zhihu: '知乎' }

export function GeoMarketWorkspace() {
  const go = useGeoNav()
  const [tab, setTab] = useState<Tab>('signals')
  const [watch, setWatch] = useState<Row[]>([]), [signals, setSignals] = useState<Row[]>([]), [links, setLinks] = useState<Row[]>([])
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(''), [notice, setNotice] = useState('')
  const [showAdd, setShowAdd] = useState(false), [name, setName] = useState(''), [url, setUrl] = useState(''), [type, setType] = useState('website')
  async function load() { setLoading(true); const result = await Promise.allSettled([geoGet('/market/watchlist'),geoGet('/market/signals'),geoGet('/links')]); if(result[0].status==='fulfilled') setWatch(rows(result[0].value)); if(result[1].status==='fulfilled') setSignals(rows(result[1].value)); if(result[2].status==='fulfilled') setLinks(rows(result[2].value)); setLoading(false) }
  useEffect(()=>{void load()},[])
  async function act(key:string, work:()=>Promise<any>, message:string){setBusy(key);setNotice('');try{const d=await work();setNotice(d?.error||message);await load()}catch(e){setNotice(e instanceof Error?e.message:'操作失败')}finally{setBusy('')}}
  async function addWatch(){if(!name.trim())return;await act('add',()=>geoPost('/market/watchlist',{name,url,type}),'已加入关注');setName('');setUrl('');setShowAdd(false)}
  /** 转内容计划成功后直接跳到内容计划页并高亮那条（计划用信号标题做主题，2026-09-21） */
  async function signalToPlan(row: Row){const title=text(row,'title');await act(`plan-${row.id}`,()=>geoPost(`/market/signals/${row.id}/to-plan`,{}),'已转入内容计划');if(title&&title!=='—')go?.('plans',{focus:title})}
  async function removeWatch(row: Row){if(!(await askGeoConfirm(`移除关注「${text(row,'name')}」后，不再采集它的市场信号。`))) return; await act(`delete-${text(row,'id')}`,()=>geoDelete(`/market/watchlist/${row.id}`),'已移除')}
  async function removeLink(row: Row){if(!(await askGeoConfirm(`删除链接「${text(row,'name')}」后，收录检测记录一并移除。`))) return; await act(`delete-${text(row,'id')}`,()=>geoDelete(`/links/${row.id}`),'已删除')}
  async function addLink(){if(!url.trim())return;await act('add-link',()=>geoPost('/links',{name:name.trim(),url:url.trim()}),'链接已添加');setName('');setUrl('');setShowAdd(false)}
  const indexed=links.filter((x)=>x.index_status==='indexed').length
  return <div className="market-console"><header className="workspace-intro"><div><span>市场</span><h1>市场情报</h1><p>关注市场变化，把可信信号转成内容计划，并跟踪发布内容是否被搜索引擎收录。</p></div><button className="geo-btn secondary" onClick={()=>void load()}>{loading?<LoaderCircle className="spin"/>:<RefreshCw/>}刷新</button></header>
    <section className="market-summary"><div><b>{watch.length}</b><span>关注对象</span></div><div><b>{signals.filter(x=>!['ignored','planned'].includes(x.status)).length}</b><span>待处理信号</span></div><div><b>{signals.filter(x=>x.status==='planned').length}</b><span>已转内容计划</span></div><div><b>{indexed}<small>/{links.length}</small></b><span>已收录链接</span></div></section>
    <nav className="market-tabs">{([['watch','关注对象'],['signals','市场信号'],['links','链接收录']] as Array<[Tab,string]>).map(([id,label])=><button key={id} className={tab===id?'active':''} onClick={()=>{setTab(id);setShowAdd(false)}}>{label}<span>{id==='watch'?watch.length:id==='signals'?signals.length:links.length}</span></button>)}</nav>
    {notice&&<div className="geo-notice">{notice}</div>}
    <section className="market-workarea"><header><div><h2>{tab==='watch'?'关注对象':tab==='signals'?'市场信号流':'内容收录台账'}</h2><p>{tab==='watch'?'配置需要持续采集的竞品、媒体或行业来源':tab==='signals'?'提取事实、忽略噪音，或直接转入内容计划':'登记发布链接并进行真实收录检测'}</p></div><div className="workspace-actions">{tab==='watch'&&<button className="geo-btn primary" onClick={()=>setShowAdd(!showAdd)}><Plus/>新增关注</button>}{tab==='watch'&&watch.length>0&&<button className="geo-btn secondary" onClick={()=>void act('collect',()=>geoPost('/market/collect',{watch_ids:null}),'采集完成')}>{busy==='collect'?<LoaderCircle className="spin"/>:<RefreshCw/>}采集全部</button>}{tab==='links'&&<><button className="geo-btn primary" onClick={()=>setShowAdd(!showAdd)}><Plus/>登记链接</button><button className="geo-btn secondary" onClick={()=>void act('check-all',()=>geoPost('/links/check-all',{}),'检测完成')}><Search/>检测未收录</button></>}</div></header>
      {showAdd&&<div className="market-add"><input placeholder={tab==='watch'?'关注名称':'内容名称（可选）'} value={name} onChange={e=>setName(e.target.value)}/><input placeholder={tab==='watch'?'来源网址（可选）':'已发布内容 URL'} value={url} onChange={e=>setUrl(e.target.value)}/>{tab==='watch'&&<select value={type} onChange={e=>setType(e.target.value)}><option value="website">官网</option><option value="news">媒体</option><option value="zhihu">知乎</option></select>}<button className="geo-btn primary" onClick={()=>void(tab==='watch'?addWatch():addLink())}>保存</button></div>}
      {tab==='watch'&&<div className="market-table">{watch.length?watch.map(row=><article key={text(row,'id')}><span className="source-type">{SOURCE_TYPE_LABEL[String(row.type)]??'其他来源'}</span><div><b>{text(row,'name')}</b><small>{text(row,'url','created_at')}</small></div><button onClick={()=>void removeWatch(row)} aria-label="移除关注"><Trash2/></button></article>):<div className="market-empty">先添加竞品官网、行业媒体或内容平台。</div>}</div>}
      {tab==='signals'&&<div className="market-signal-grid">{signals.length?signals.map(row=><article key={text(row,'id')}><header><span data-status={row.status}>{row.status?statusText(row.status):text(row,'source_type')}</span><small>{text(row,'source_name','created_at')}</small></header><h3>{text(row,'title')}</h3><p>{text(row,'summary','text').slice(0,180)}</p>{Array.isArray(row.facts)&&row.facts.length>0&&<ul>{row.facts.slice(0,3).map((f:string,i:number)=><li key={i}>{f}</li>)}</ul>}<footer>{row.status!=='ignored'&&<button onClick={()=>void act(`extract-${row.id}`,()=>geoPost(`/market/signals/${row.id}/extract`,{}),'事实提取完成')}>提取事实</button>}<button onClick={()=>void signalToPlan(row)}>转内容计划<ArrowRight/></button><button onClick={()=>void act(`ignore-${row.id}`,()=>geoPost(`/market/signals/${row.id}/ignore`,{}),'已忽略')}>忽略</button></footer></article>):<div className="market-empty">采集关注对象后，市场信号会出现在这里。</div>}</div>}
      {tab==='links'&&<div className="market-table links">{links.length?links.map(row=><article key={text(row,'id')}><span className="index-state" data-status={row.index_status}>{indexStatusText(row.index_status)}</span><div><b>{text(row,'name')}</b><small>{text(row,'url')} · {text(row,'status_note')}</small></div><button onClick={()=>void act(`check-${row.id}`,()=>geoPost('/links/check',{id:row.id}),'检测完成')} aria-label="检测收录"><Search/></button><button onClick={()=>void removeLink(row)} aria-label="删除链接"><Trash2/></button></article>):<div className="market-empty">登记已发布内容 URL 后，可检测百度收录状态。</div>}</div>}
    </section>
  </div>
}
