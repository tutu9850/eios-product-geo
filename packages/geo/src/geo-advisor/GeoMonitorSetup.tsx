import { useEffect, useState } from 'react'
import { emptySetup, SETUP_KEY, SETUP_ENGINES, saveSetupObject, runSetupObject, type SetupState } from './demo-monitor-setup'

function restore(): SetupState {
 try {const s=JSON.parse(localStorage.getItem(SETUP_KEY)||'null');if(Array.isArray(s?.objects))return s}catch{/* sample only */}
 return emptySetup()
}
export function GeoMonitorSetup({createRequest=0}:{createRequest?:number}) {
 const [state,setState]=useState(restore)
 const [open,setOpen]=useState(false)
 const [editId,setEditId]=useState<string|undefined>()
 const [name,setName]=useState('云栖示例家居')
 const [competitors,setCompetitors]=useState('星禾示例家居')
 const [questions,setQuestions]=useState('云栖示例家居有哪些产品与服务？\n云栖示例家居交付和售后怎么样？')
 const [engines,setEngines]=useState(['DeepSeek','Kimi'])
 const [error,setError]=useState('')
 const [notice,setNotice]=useState('')
 const [runId,setRunId]=useState<string|null>(null)
 const [answerId,setAnswerId]=useState<string|null>(null)
 useEffect(()=>{localStorage.setItem(SETUP_KEY,JSON.stringify(state))},[state])
 const object=state.objects.find(o=>o.id===state.selected && o.status!=='archived')
 const run=object?.runs.find(r=>r.id===runId)||object?.runs.at(-1)
 const answer=run?.answers.find(a=>a.id===answerId)
 function newObject(){setEditId(undefined);setName('云栖示例家居');setCompetitors('星禾示例家居');setQuestions('云栖示例家居有哪些产品与服务？\n云栖示例家居交付和售后怎么样？');setEngines(['DeepSeek','Kimi']);setError('');setOpen(true)}
 useEffect(()=>{if(createRequest>0){newObject();window.setTimeout(()=>document.querySelector('.geo-setup-panel')?.scrollIntoView({behavior:'smooth',block:'start'}),0)}},[createRequest])
 function save(){try{setState(saveSetupObject(state,{name,competitors,questions:questions.split('\n'),engines},`sample-object-${crypto.randomUUID()}`,editId));setOpen(false);setNotice(editId?'配置已保存，历史轮次保留。':'监测对象已创建，下一步运行首轮模拟监测。');setAnswerId(null)}catch(e){setError((e as Error).message)}}
 function edit(){if(!object)return;setEditId(object.id);setName(object.name);setCompetitors(object.competitors);setQuestions(object.questions.join('\n'));setEngines(object.engines);setOpen(true);setError('')}
 function runNow(){try{setState(runSetupObject(state,object!.id,new Date().toISOString()));setAnswerId(null);setRunId(null);setNotice('模拟监测完成：已按配置问题 × 所选模型生成回答，可刷新读回。')}catch(e){setError((e as Error).message)}}
 return <section className="geo-setup-panel"><header><div><h2>监测对象</h2><p>建立对象 → 配置问题与模型 → 运行首轮 → 查看回答</p></div><button className="geo-btn" onClick={newObject}>＋ 新建监测对象</button></header>
 {notice&&<p className="geo-jw-notice" role="status">{notice}</p>}{error&&<p role="alert" className="geo-inline-error">{error}</p>}
 {open&&<form className="geo-setup-form" onSubmit={e=>{e.preventDefault();save()}}><h3>{editId?'编辑监测配置':'新建监测对象（演示）'}</h3><label>企业或品牌名称<input required value={name} onChange={e=>setName(e.target.value)}/></label><label>竞品（可选）<input value={competitors} onChange={e=>setCompetitors(e.target.value)}/></label><label>监测问题（每行一个）<textarea required value={questions} onChange={e=>setQuestions(e.target.value)}/></label><fieldset><legend>选择模型（至少一个）</legend>{SETUP_ENGINES.map(engine=><label key={engine}><input type="checkbox" checked={engines.includes(engine)} onChange={e=>setEngines(current=>e.target.checked?[...current,engine]:current.filter(x=>x!==engine))}/>{engine}</label>)}</fieldset><p>问题由你确认；本轮不会调用模型生成问题、联网或创建真实任务。</p><div className="geo-jw-toolbar"><button className="geo-btn" type="submit">{editId?'保存配置':'创建对象并保存配置'}</button><button className="geo-btn secondary" type="button" onClick={()=>setOpen(false)}>取消</button></div></form>}
 {!state.objects.some(o=>o.status!=='archived')&&!open&&<p className="geo-setup-empty">还没有创建演练对象。点击“新建监测对象”，配置问题与模型后运行首轮。</p>}
 {state.objects.some(o=>o.status!=='archived')&&<div className="geo-jw-toolbar"><label>演练对象 <select value={object?.id||''} onChange={e=>{setState({...state,selected:e.target.value});setAnswerId(null);setError('')}}>{!object&&<option value="">选择对象</option>}{state.objects.filter(o=>o.status!=='archived').map(o=><option key={o.id} value={o.id}>{o.name} · {o.status==='paused'?'已暂停':'已启用'}</option>)}</select></label></div>}
 {object&&<><div className="geo-setup-summary"><b>{object.name}</b><span>{object.questions.length} 个问题 × {object.engines.length} 个模型 · {object.runs.length} 轮模拟运行</span><span>竞品：{object.competitors||'未配置'} · 模型：{object.engines.join('、')}</span></div><div className="geo-jw-toolbar"><button className="geo-btn" disabled={object.status!=='active'} onClick={runNow}>{object.runs.length?'再运行一轮模拟监测':'运行首轮模拟监测'}</button><button className="geo-btn secondary" onClick={edit}>编辑问题与模型</button><button className="geo-btn secondary" onClick={()=>setState({...state,objects:state.objects.map(o=>o.id===object.id?{...o,status:o.status==='active'?'paused':'active'}:o)})}>{object.status==='active'?'暂停对象':'启用对象'}</button><button className="geo-btn secondary" onClick={()=>{if(window.confirm('归档这个演练对象？历史模拟回答会保留。'))setState({...state,selected:null,objects:state.objects.map(o=>o.id===object.id?{...o,status:'archived'}:o)})}}>归档对象</button></div>{run&&<><label className="geo-setup-round">查看运行轮次 <select value={run.id} onChange={e=>{setRunId(e.target.value);setAnswerId(null)}}>{object.runs.map((r,i)=><option key={r.id} value={r.id}>第 {i+1} 轮 · {new Date(r.at).toLocaleString()}</option>)}</select></label><div className="geo-jw-split"><div className="geo-jw-list"><h3>首轮 / 最近轮次回答 · {run.answers.length} 条</h3>{run.answers.map(a=><button key={a.id} onClick={()=>setAnswerId(a.id)} className={answerId===a.id?'selected':''}><span>{a.engine}</span><b>{a.question}</b><p>{a.text.slice(0,85)}</p></button>)}</div><aside className="geo-jw-detail"><h3>{answer?'模拟原话':'选择回答查看原话'}</h3>{answer?<><p>{answer.text}</p><small>{answer.id}</small></>:<p>仅包含本对象配置的问题和模型，不混用下方历史样例。</p>}<p>运行时间：{new Date(run.at).toLocaleString()} · {run.id}</p><details><summary>历史模拟轮次（{object.runs.length}）</summary>{object.runs.map(r=><p key={r.id}>{r.id} · {r.answers.length} 条 · {new Date(r.at).toLocaleString()}</p>)}</details></aside></div></>}</>}
 <details><summary>归档对象（{state.objects.filter(o=>o.status==='archived').length}）</summary>{state.objects.filter(o=>o.status==='archived').map(o=><details key={o.id}><summary>{o.name} · {o.runs.length} 轮历史</summary>{o.runs.flatMap(r=>r.answers).map(a=><p key={a.id}>{a.engine} · {a.question}<br/>{a.text}<small>{a.id}</small></p>)}</details>)}</details>
 <p className="geo-setup-boundary">上方是创建与首轮运行演练；下方为云栖示例家居既有历史样本的差距与内容演练，两份样例不混算。</p>
 </section>
}
