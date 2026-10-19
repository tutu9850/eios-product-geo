import { useEffect, useReducer, useState } from 'react'
import { DEMO_OBSERVATIONS, DEMO_MATERIALS, DEMO_QUESTIONS } from './demo-monitor-samples'
import { emptyJourney, journeyReducer, JOURNEY_KEY, SAMPLE_GAPS, sampleComparison, type JourneyState } from './demo-journey'
import { GeoMonitorSetup } from './GeoMonitorSetup'
import { useGeoNav } from './shared'

function restore(): JourneyState {
  try { const value = JSON.parse(localStorage.getItem(JOURNEY_KEY) || 'null'); if (Array.isArray(value?.plans) && Array.isArray(value?.extra)) return value } catch { /* isolated sample storage */ }
  return emptyJourney()
}
export function GeoJourneyWorkspace({ workspace }: { workspace: 'monitor' | 'insight' | 'growth' }) {
  const [state, dispatch] = useReducer(journeyReducer, undefined, restore)
  const [round, setRound] = useState('2')
  const [question, setQuestion] = useState('all')
  const [selectedAnswer, setSelectedAnswer] = useState<string | null>(null)
  const [gapId, setGapId] = useState('delivery')
  const [url, setUrl] = useState('https://example.invalid/demo/delivery')
  const [setupRequest, setSetupRequest] = useState(0)
  const [notice, setNotice] = useState('')
  const go = useGeoNav()
  useEffect(() => { localStorage.setItem(JOURNEY_KEY, JSON.stringify(state)) }, [state])
  const plan = state.plans.find(p => p.id === state.selected)
  const gap = SAMPLE_GAPS.find(g => g.id === gapId)!
  const rows = [...DEMO_OBSERVATIONS, ...state.extra].filter(r => String(r.round) === round && (question === 'all' || r.query_id === question))
  const answered = rows.filter(r => r.answer)
  const answer = [...DEMO_OBSERVATIONS, ...state.extra].find(r => r.id === selectedAnswer)
  const comparison = plan ? sampleComparison(state, plan) : null
  function createPlan() { dispatch({ type: 'plan', gap: gapId }); setNotice('已创建演示计划，可编辑并保存。'); go?.('plans') }
  function runRound() { dispatch({ type: 'round', at: new Date(Date.now() + 1000).toISOString() }); setRound('3'); setNotice('已生成发布后模拟轮次；不代表真实模型表现。') }
  return <section className="geo-journey-workspace">
    <header className="geo-jw-head"><div><span>云栖示例家居 · 本地演练</span><h1>{workspace === 'monitor' ? '从模型原话开始' : workspace === 'insight' ? '每一个差距，都能追到依据' : '从计划到稿件，再到新轮次'}</h1><p>{workspace === 'monitor' ? '筛选轮次和问题，打开回答，再把对应差距带入行动。' : workspace === 'insight' ? '区分缺少资料和模型说法待核实，选择一项开始处理。' : '编辑、保存与发布登记只保存在本浏览器的演示空间。'}</p></div>{workspace === 'monitor' && <button className="geo-btn" onClick={()=>setSetupRequest(n=>n+1)}>新建监测对象</button>}<button className="geo-btn secondary" onClick={() => { if (window.confirm('重置本地演练？这会清除演示计划、稿件与模拟轮次。')) { dispatch({ type: 'reset' }); setNotice('演练已重置') } }}>重置演练</button></header>
    {notice && <p className="geo-jw-notice" role="status">{notice}</p>}
    {workspace === 'monitor' && <>
      <GeoMonitorSetup createRequest={setupRequest} />
      <h2 className="geo-history-title">历史样例：回答、差距与内容闭环</h2>
      <div className="geo-jw-toolbar"><label>监测轮次 <select value={round} onChange={e => {setRound(e.target.value);setSelectedAnswer(null)}}><option value="0">第 1 轮</option><option value="1">第 2 轮</option><option value="2">第 3 轮 · 发布前基线</option>{state.extra.length > 0 && <option value="3">第 4 轮 · 发布后模拟</option>}</select></label><label>客户问题 <select value={question} onChange={e => {setQuestion(e.target.value);setSelectedAnswer(null)}}><option value="all">全部问题</option>{DEMO_QUESTIONS.map((q,i) => <option key={q} value={`demo-query-${i+1}`}>{q}</option>)}</select></label>{state.plans.some(p=>p.publishedAt) && <button className="geo-btn" onClick={runRound} disabled={!plan?.publishedAt || !!comparison}>运行发布后模拟轮次</button>}</div>
      <div className="geo-jw-counts"><article><span>有效回答</span><b>{answered.length}</b></article><article><span>失败槽位</span><b>{rows.length-answered.length}</b></article><article><span>确认提及</span><b>{rows.filter(r=>r.mentioned===true).length}</b></article><article><span>身份未确认</span><b>{rows.filter(r=>r.answer && r.mentioned===false && r.recognition==='not_recognised').length}</b></article></div>
      <div className="geo-jw-split"><div className="geo-jw-list">{rows.map(r=><button key={r.id} className={selectedAnswer===r.id?'selected':''} onClick={()=>setSelectedAnswer(r.id)}><span>{r.engine} · {r.error?'失败':r.mentioned?'已提及':'未确认 / 未提及'}</span><b>{r.question}</b><p>{r.answer.slice(0,110)||r.error}</p></button>)}</div><aside className="geo-jw-detail"><h2>模型回答与出处</h2>{answer ? <><span>{answer.id} · {answer.engine}</span><p className="geo-jw-original">{answer.answer||answer.error}</p><h3>引用的样例资料</h3>{answer.citation_ids.length ? answer.citation_ids.map(id=><p key={id}>{DEMO_MATERIALS.find(m=>m.id===id)?.text}<small>{id}</small></p>):<p>这条回答没有可追溯的样例引用。</p>}<button className="geo-btn" onClick={()=> { setGapId(answer.factor==='客户案例'?'case':'delivery'); go?.('insight-overview') }}>查看对应差距 →</button></>:<p>选择一条回答查看完整原话、稳定编号和样例出处。</p>}</aside></div>
    </>}
    {workspace === 'insight' && <div className="geo-jw-split"><div className="geo-jw-list">{SAMPLE_GAPS.map(g=><button key={g.id} className={gapId===g.id?'selected':''} onClick={()=>setGapId(g.id)}><span>待补依据 · {DEMO_OBSERVATIONS.filter(r=>r.round===2 && r.query_id===`demo-query-${g.question+1}` && r.answer).length} 条有效回答</span><b>{g.title}</b><p>{g.detail}</p></button>)}</div><aside className="geo-jw-detail"><h2>{gap.title}</h2><p>{gap.detail}</p><h3>对应客户问题</h3><p>{DEMO_QUESTIONS[gap.question]}</p><h3>模型原话</h3>{DEMO_OBSERVATIONS.filter(r=>r.round===2 && r.query_id===`demo-query-${gap.question+1}` && r.answer).slice(0,2).map(r=><blockquote key={r.id}>{r.answer}<small>{r.engine} · {r.id}</small></blockquote>)}<h3>当前样例依据</h3><p>{DEMO_MATERIALS[gap.material].text}<small>{DEMO_MATERIALS[gap.material].id}</small></p><button className="geo-btn" onClick={createPlan}>创建内容计划 →</button></aside></div>}
    {workspace === 'growth' && <div className="geo-jw-split"><div className="geo-jw-list"><h2>内容计划 / 已保存稿件</h2>{state.plans.length ? state.plans.map(p=><button key={p.id} className={p.id===state.selected?'selected':''} onClick={()=>dispatch({type:'select',id:p.id})}><span>{p.publishedAt?'发布已登记':p.saved?'稿件已保存':'待撰写'}</span><b>{p.title}</b><p>{p.id}</p></button>):<div><p>先从一个有依据的差距创建计划。</p><button className="geo-btn" onClick={()=>go?.('insight-overview')}>选择差距 →</button></div>}</div><aside className="geo-jw-detail">{plan ? <><span>{plan.publishedAt?'04 等待新轮次 / 对比':plan.saved?'03 保存 / 发布登记':'02 撰写稿件'}</span><h2>{plan.title}</h2><p>来源差距：{SAMPLE_GAPS.find(g=>g.id===plan.gap)?.detail}</p><details><summary>取材依据与原话编号</summary><p>{DEMO_MATERIALS[SAMPLE_GAPS.find(g=>g.id===plan.gap)!.material].text}</p><small>{DEMO_MATERIALS[SAMPLE_GAPS.find(g=>g.id===plan.gap)!.material].id}</small>{DEMO_OBSERVATIONS.filter(r=>r.round===2 && r.query_id===`demo-query-${SAMPLE_GAPS.find(g=>g.id===plan.gap)!.question+1}` && r.answer).map(r=><small key={r.id}>{r.id} · {r.engine}</small>)}</details><label className="geo-jw-editor">稿件正文<textarea value={plan.draft} readOnly={!!plan.publishedAt} onChange={e=>dispatch({type:'edit',text:e.target.value})} placeholder="点击生成演示草稿，或直接编辑正文。" /></label><div className="geo-jw-toolbar">{!plan.publishedAt && <><button className="geo-btn secondary" onClick={()=>dispatch({type:'generate'})}>填入演示草稿</button><button className="geo-btn" disabled={!plan.draft.trim() || plan.saved===plan.draft} onClick={()=> {dispatch({type:'save'});setNotice('稿件已保存；刷新或重开仍可读回。')}}>保存稿件</button></>}{plan.saved && <button className="geo-btn secondary" onClick={()=>{dispatch({type:'reopen'});setNotice('已从保存版本重开稿件')}}>重开保存版本</button>}</div>{plan.saved && !plan.publishedAt && <div className="geo-jw-publish"><h3>人工发布登记（演示）</h3><p>这里只登记样例链接，不会向任何平台发布。</p><label>发布链接<input value={url} onChange={e=>setUrl(e.target.value)} /></label><button className="geo-btn" disabled={plan.saved!==plan.draft || !/^https?:\/\//.test(url)} onClick={()=>{dispatch({type:'publish',url,at:new Date().toISOString()});setNotice('发布已登记；请运行发布后的新模拟轮次。')}}>登记样例发布</button>{plan.saved!==plan.draft && <p>正文有未保存修改，请先保存。</p>}</div>}{plan.publishedAt && <div className="geo-jw-publish"><h3>发布后新轮次对比</h3><p>已登记：{plan.url} · {new Date(plan.publishedAt).toLocaleString()}</p>{comparison ? <><b>提及率：{comparison.before.toFixed(1)}% → {comparison.after.toFixed(1)}%（{comparison.delta.toFixed(1)} 个百分点）</b><p>发布前 {comparison.beforeCount} / 发布后 {comparison.afterCount} 条有效回答，同问题、同模型；失败不计分母。模拟结果不证明内容带来真实变化。</p></>:<><p>尚无发布后新轮次，当前不可比较。</p><button className="geo-btn" onClick={runRound}>运行发布后模拟轮次</button></>}</div>}</>:<p>选择一个计划，继续撰写和保存。</p>}</aside></div>}
  </section>
}
