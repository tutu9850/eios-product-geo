export const SETUP_KEY = 'geo.ui-review.monitor-setup.v1'
export const SETUP_ENGINES = ['DeepSeek', 'Kimi', '豆包', '通义']
export type SetupAnswer = { id: string; question: string; engine: string; text: string; error: string | null }
export type SetupObject = { id: string; name: string; competitors: string; questions: string[]; engines: string[]; status: 'active' | 'paused' | 'archived'; runs: { id: string; at: string; answers: SetupAnswer[] }[] }
export type SetupState = { objects: SetupObject[]; selected: string | null }
export const emptySetup = (): SetupState => ({ objects: [], selected: null })
export function saveSetupObject(state: SetupState, input: { name: string; competitors: string; questions: string[]; engines: string[] }, id: string, editId?: string): SetupState {
 const name=input.name.trim(), questions=[...new Set(input.questions.map(q=>q.trim()).filter(Boolean))], engines=[...new Set(input.engines.filter(e=>SETUP_ENGINES.includes(e)))]
 if (!name || !questions.length || !engines.length || state.objects.some(o=>o.id!==editId && o.status!=='archived' && o.name===name)) throw new Error('请填写不重复的对象名称，至少一个问题和一个模型。')
 if(editId && !state.objects.some(o=>o.id===editId && o.status!=='archived')) throw new Error('对象已归档或不存在。')
 const object:SetupObject={id:editId||id,...input,name,questions,engines,status:'active',runs:[]}
 return {objects:editId?state.objects.map(o=>o.id===editId?{...object,status:o.status,runs:o.runs}:o):[...state.objects,object],selected:object.id}
}
export function runSetupObject(state: SetupState, id: string, at: string): SetupState {
 const object=state.objects.find(o=>o.id===id)
 if(!object || object.status!=='active') throw new Error('请先启用监测对象。')
 if(!Number.isFinite(Date.parse(at))) throw new Error('运行时间无效。')
 const runId=`${id}-round-${object.runs.length+1}`
 const answers=object.questions.flatMap((question,q)=>object.engines.map((engine,e)=>({id:`${runId}-q${q+1}-e${e+1}`,question,engine,text:`【模拟回答】关于“${question}”：${object.name}的具体产品、交付和服务承诺需要核对企业资料。本演练只验证配置与回答读回，不进行真实品牌识别或事实判断。`,error:null})))
 return {...state,objects:state.objects.map(o=>o.id===id?{...o,runs:[...o.runs,{id:runId,at,answers}]}:o)}
}
