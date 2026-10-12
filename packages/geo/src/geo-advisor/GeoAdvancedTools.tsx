import { useEffect, useState } from 'react'
import { CheckCircle2, LoaderCircle, Search, Server, Sparkles, Trash2, X } from 'lucide-react'
import { geoGet, geoPost } from './geo-api'
import { GeoBars, GeoKpis, GeoTable, askGeoConfirm, shortDay } from './shared'

type Row=Record<string,any>
/**
 * 画像来源是后端内部标识（company_profile.py 的 sources），页面上不给用户看英文代号。
 * 2026-09-21：这张卡原来直接打印后端的原始来源标识（下划线字段名），用户看不懂。
 */
const PROFILE_SOURCE_LABEL: Record<string, string> = {
  knowledge_search: '企业资料检索',
  knowledge_relations: '企业资料关系',
  geo_questions: 'GEO 客户问题',
  geo_kb: '公开内容资产',
  enterprise_facts: '已确认企业信息',
}
const profileSourceText = (value: string) => PROFILE_SOURCE_LABEL[value] ?? `其他来源（${value}）`
const DIAG_LABEL: Record<string,string> = { schema:'结构化数据', meta:'标题与描述', structure:'内容结构', depth:'内容深度', brand:'品牌识别', faq:'FAQ 问答', accessibility:'页面可访问' }

export function GeoAdvancedTools({onClose}:{onClose:()=>void}){
  const [engines,setEngines]=useState<Row[]>([]),[profile,setProfile]=useState<Row|null>(null),[busy,setBusy]=useState(''),[notice,setNotice]=useState('')
  const [progress,setProgress]=useState<Row|null>(null)
  const [company,setCompany]=useState(''),[keywords,setKeywords]=useState(''),[platform,setPlatform]=useState('sogou'),[limit,setLimit]=useState(3)
  const [website,setWebsite]=useState(''),[diagnosis,setDiagnosis]=useState<Row|null>(null)
  async function load(){
    // 统计路径已在宿主 Product API 的冻结路由表中；不请求无法穿过宿主门的内部 progress 路径。
    const [e,c,p]=await Promise.allSettled([geoGet<{engines:Row[]}>('/meta/engines'),geoGet<{company_name?:string}>('/content/company'),geoGet<Row>('/intelligence/stats')])
    if(e.status==='fulfilled')setEngines(e.value.engines??[])
    if(p.status==='fulfilled')setProgress({parse:{succeeded:p.value.succeeded??0,failed:p.value.failed??0,running:0,queue_size:0,deferred:0},harvest:{written:p.value.research_harvest??0,status:'snapshot'}})
    if(c.status==='fulfilled'&&c.value.company_name){setCompany((v)=>v||c.value.company_name||'');try{setProfile(await geoGet<Row>(`/knowledge/profile?company_name=${encodeURIComponent(c.value.company_name)}`))}catch{setProfile(null)}}
  }
  useEffect(()=>{void load()},[])
  useEffect(()=>{if(!['pending','running'].includes(String(progress?.harvest?.status??'')))return;const timer=window.setInterval(()=>void load(),2000);return()=>window.clearInterval(timer)},[progress?.harvest?.status])
  async function act(key:string,fn:()=>Promise<any>,done:string){setBusy(key);setNotice('');try{const d=await fn();setNotice(d?.error||d?.skipped||done);await load()}catch(e){setNotice(e instanceof Error?e.message:'操作失败')}finally{setBusy('')}}
  /** 出厂重置：两次确认后带 confirm=true 调用（后端不带 confirm 会直接拒绝） */
  async function resetGeoData(){
    if(!(await askGeoConfirm('这是最高危操作：将清空本 GEO 的全部业务数据（客户问题 / 资料缺口 / 内容计划 / 监测历史 / 内容资产 / 关注与采集 / 链接 / 可搜索内容），恢复出厂状态，且不可撤销。企业资料库与其他产品不受影响。','继续')))return
    if(!(await askGeoConfirm('最后确认：现在就清空 GEO 数据？清空后无法找回。','确认清空')))return
    await act('reset',()=>geoPost('/knowledge/reset?confirm=true',{}),'GEO 数据已重置为出厂状态')
  }
  async function diagnoseWebsite(){if(!website.trim())return;setBusy('diagnose');setNotice('');try{const d=await geoPost<Row>('/diagnose',{url:website.trim()});setDiagnosis(d);if(!d.fetchable)setNotice(String(d.error??'官网无法访问'))}catch(e){setNotice(e instanceof Error?e.message:'官网诊断失败')}finally{setBusy('')}}
  return <aside className="advanced-drawer"><header><div><span>工具</span><h2>高级工具</h2><p>低频、可能消耗模型额度或需要技术判断的能力集中在这里。</p></div><button onClick={onClose} aria-label="关闭高级工具"><X/></button></header>{notice&&<div className="geo-notice">{notice}</div>}
    <section><header><Server/><div><h3>国产模型连接</h3><p>检查当前登记的国产模型是否能正常回答。</p></div></header><div className="engine-list">{engines.map((e,i)=><article key={e.id??e.engine_id??i}><div><b>{String(e.name??e.engine_name??e.id??'模型')}</b><small>{String(e.provider??e.status??'已登记')}</small></div><button disabled={busy===String(e.id??e.engine_id)} onClick={()=>void act(String(e.id??e.engine_id),()=>geoPost(`/meta/engines/${e.id??e.engine_id}/ping`,{}),'连接检查完成')}>{busy===String(e.id??e.engine_id)?<LoaderCircle className="spin"/>:<CheckCircle2/>}检查</button></article>)}</div></section>
    <section><header><Search/><div><h3>回答理解与公开资料补充</h3><p>先查看监测回答是否已被系统读懂；证据不足时再补充公开来源，并和企业正式资料分开保存。</p></div></header><div className="intelligence-progress"><span><b>{Number(progress?.parse?.succeeded??0)}</b>已完成理解</span><span><b>{Number(progress?.parse?.running??0)+Number(progress?.parse?.queue_size??0)+Number(progress?.parse?.deferred??0)}</b>等待处理</span><span><b>{Number(progress?.parse?.failed??0)}</b>处理失败</span><span><b>{Number(progress?.harvest?.written??0)}</b>公开资料</span></div>{progress?.harvest&&progress.harvest.status!=='snapshot'?<p className="geo-note">最近补充：{String(progress.harvest.status==='done'?'已完成':progress.harvest.status==='failed'?'失败':progress.harvest.status==='running'?'采集中':'排队中')} · {Array.isArray(progress.harvest.keywords)?progress.harvest.keywords.join('、'):''}{progress.harvest.error?` · ${String(progress.harvest.error)}`:''}</p>:null}<div className="advanced-form"><input value={company} onChange={e=>setCompany(e.target.value)} placeholder="企业名称"/><input value={keywords} onChange={e=>setKeywords(e.target.value)} placeholder="关键词，逗号分隔"/><select value={platform} onChange={e=>setPlatform(e.target.value)}><option value="sogou">搜狗</option><option value="baidu">百度</option><option value="weibo">微博</option></select><button className="geo-btn primary" disabled={busy==='harvest'||!company.trim()||!keywords.trim()} onClick={()=>void act('harvest',()=>geoPost('/intelligence/harvest/search',{company:company.trim(),keywords:keywords.split(/[，,]/).map(x=>x.trim()).filter(Boolean),platform,max_per_keyword:10}),'补充任务已创建，正在采集')}>{busy==='harvest'?<LoaderCircle className="spin"/>:<Search/>}开始补充资料</button></div></section>
    <section><header><Sparkles/><div><h3>按计划生成内容</h3><p>从待生产计划生成内容草稿并存入素材库；不会自动发布到外部平台。</p></div></header><div className="loop-control"><label>本次最多处理 <select value={limit} onChange={e=>setLimit(Number(e.target.value))}><option value={1}>1 条</option><option value={3}>3 条</option><option value={5}>5 条</option></select></label><button className="geo-btn primary" disabled={busy==='loop'} onClick={()=>void act('loop',()=>geoPost(`/distill/loop/run?limit=${limit}`,{}),'内容草稿已生成')}>{busy==='loop'?<LoaderCircle className="spin"/>:<Sparkles/>}生成内容草稿</button></div></section>
    <section><header><CheckCircle2/><div><h3>企业资料索引</h3><p>更新素材搜索索引，并查看现有资料能否支撑客户问题。</p></div></header><div className="profile-preview"><details className="advanced-detail-fold"><summary>查看企业资料支撑详情</summary><ProfileBody profile={profile}/></details><button className="geo-btn secondary" disabled={busy==='vector'} onClick={()=>void act('vector',()=>geoPost('/knowledge/materials/vectorize',{}),'资料索引已更新')}>更新资料索引</button></div></section>
    {/* Owner 2026-09-21：重置接口已在产品门放行，前端补入口（原先只有接口没有按钮）。
        出厂重置是最高危操作，点两次才算数——第一次说明范围，第二次是真正确认，然后才带 confirm=true 调用。 */}
    <section className="disabled-tool"><header><Trash2/><div><h3>重置 GEO 数据</h3><p>恢复出厂状态：清空客户问题、资料缺口、内容计划、监测历史、内容资产、关注/采集/链接与可搜索内容。<b>不可撤销</b>；不动企业自己的资料库与其他产品。</p></div></header><div className="loop-control"><button className="geo-btn secondary" disabled={busy==='reset'} onClick={()=>void resetGeoData()}>{busy==='reset'?<LoaderCircle className="spin"/>:<Trash2/>}重置 GEO 数据</button></div></section>
    <section><header><Search/><div><h3>官网页面检查</h3><p>检查官网是否容易被模型识别企业、产品与问答结构；这是页面内容诊断，不代表搜索排名。</p></div></header><div className="advanced-form"><input value={website} onChange={e=>setWebsite(e.target.value)} placeholder="官网 URL，例如 https://example.com"/><button className="geo-btn primary" disabled={busy==='diagnose'||!website.trim()} onClick={()=>void diagnoseWebsite()}>{busy==='diagnose'?<LoaderCircle className="spin"/>:<Search/>}开始检查</button></div>{diagnosis?<div className="website-diagnosis"><div><strong>{diagnosis.fetchable?`${Number(diagnosis.score??0)} 分`:'无法访问'}</strong><span>{String(diagnosis.url??website)}</span></div>{Array.isArray(diagnosis.checks)&&diagnosis.checks.length?<GeoTable columns={['检查项','得分','检查说明']} template="92px 64px minmax(0,1fr)" rows={diagnosis.checks.map((row:Row)=>[<b>{DIAG_LABEL[String(row.key)]??String(row.key)}</b>,<em>{String(row.score)}/{String(row.max)}</em>,<em>{String(row.note)}</em>])}/>:null}{Array.isArray(diagnosis.suggestions)&&diagnosis.suggestions.length?<div><b>优先建议</b><ul>{diagnosis.suggestions.map((s:string,i:number)=><li key={i}>{s}</li>)}</ul></div>:null}</div>:null}</section>
  </aside>
}

/* ── 企业画像正文（2026-09-21）────────────────────────────────────────────
   原来是 `<pre>{JSON.stringify(profile)}</pre>`，直接把接口字段名摊给用户看。
   结构取自 apps/api/app/services/company_profile.py：知识库事实/对象 + 关系 + 本地问题池/资产。
   归纳不出来的字段就写「暂无记录」——这一条是后端自己的原则，前端保持一致。 */
const PROFILE_GROUPS: Array<{ key: string; label: string }> = [
  { key: 'industry', label: '行业' },
  { key: 'products', label: '产品与方案' },
  { key: 'customers', label: '客户' },
  { key: 'advantages', label: '优势与资质' },
  { key: 'competitors', label: '竞争对标' },
  { key: 'timeline', label: '大事记' },
  { key: 'people', label: '关键人物' },
]

/** 知识对象 → 一行人话。优先用后端给的 display：命中里的 value 是「这条对象
    出现在哪段原文里」（一张表可能几百字），直接打印就是把原文倒给用户。 */
function factLine(row: Record<string, unknown>): string {
  const display = String(row.display ?? '').trim()
  if (display) return display
  const name = String(row.canonical_name ?? '').trim()
  const value = oneLine(row.value)
  if (name && value) return `${name}：${value}`
  if (name) return name
  const text = oneLine(row.text)
  return text || '（这条知识对象没有可读内容）'
}

/** 压成单行并限长（与后端 _one_line 同一口径） */
function oneLine(raw: unknown, limit = 120): string {
  return String(raw ?? '').replace(/\s+/g, ' ').trim().slice(0, limit)
}

function ProfileBody({ profile }: { profile: Row | null }) {
  if (!profile) return <div className="geo-empty">暂无企业画像数据，先在企业资料里生成一次画像。</div>
  if (typeof profile.error === 'string' && profile.error) return <div className="geo-inline-error">{profile.error}</div>

  const facts = (profile.facts ?? []) as Array<Record<string, unknown>>
  const enterpriseFacts = (profile.knowledge_facts ?? []) as Array<Record<string, unknown>>
  const factGroups = (profile.fact_groups ?? {}) as Record<string, number>
  const linkedFacts = enterpriseFacts.filter((f) => String(f.semantic_object_id ?? '').trim()).length
  const keyFacts = (profile.key_facts ?? []) as Array<Record<string, unknown>>
  const keyFactsBasis = String(profile.key_facts_basis ?? '')
  const relations = (profile.relations ?? []) as Array<Record<string, unknown>>
  const questions = (profile.questions ?? []) as Array<Record<string, unknown>>
  const assets = (profile.assets ?? []) as Array<Record<string, unknown>>
  const classified = (profile.classified ?? {}) as Record<string, Array<Record<string, unknown>>>
  const sources = (profile.sources ?? []) as string[]
  const dataStatus = (profile.data_status ?? {}) as Record<string, unknown>

  return (
    <div className="geo-profile-readout">
      <p className="geo-note profile-data-contract"><strong>这里是企业资料的支撑状态，不是模型编出来的企业介绍。</strong>它只回答“哪些客户问题有资料可支撑”；没有正式分类的资料不会被硬塞进某个类别。</p>
      <GeoKpis
        items={[
          { label: '已确认企业信息', value: `${enterpriseFacts.length} 条`, detail: '企业资料里已发布的信息，原样读取' },
          { label: '按企业名找到的资料', value: `${facts.length} 条`, detail: '按企业名检索到的相关资料（最多展示 20 条）' },
          { label: '资料中的关系', value: `${relations.length} 条`, detail: '人与产品、客户等对象之间的连接' },
          { label: '内容资产', value: `${assets.length} 个`, detail: '本企业已入库的素材' },
        ]}
      />
      <p className="geo-note">
        {profile.knowledge_ok === false
          ? `企业资料这次读不到：${String(profile.knowledge_error ?? '未知原因')}（这是读取失败，不代表企业没有数据）`
          : '企业资料读取正常'}
        {profile.built_at ? ` · 画像构建于 ${shortDay(String(profile.built_at))}` : ''}
        {sources.length ? ` · 来源 ${sources.map(profileSourceText).join('、')}` : ''}
      </p>
      <p className="geo-note profile-data-status">
        数据状态：客户问题 {String(dataStatus.questions_count ?? questions.length)} 条 · 已确认信息 {String(dataStatus.knowledge_facts_count ?? enterpriseFacts.length)} 条 · 已完成分类 {String(dataStatus.semantic_linked_count ?? linkedFacts)} 条 · 资料关系 {String(dataStatus.relations_count ?? relations.length)} 条 · 内容素材 {String(dataStatus.assets_count ?? assets.length)} 个
      </p>

      {profile.facts_error ? (
        <p className="geo-note">已确认信息这次读不到：{String(profile.facts_error)}（这是读取失败，不代表企业没有资料）</p>
      ) : null}

      {enterpriseFacts.length ? (
        <>
          <div className="geo-subhead">
            <h3>已确认企业信息</h3>
            <small>
              企业资料里已发布的事实，原样展示，不由 GEO 改写；共 {enterpriseFacts.length} 条
              {Object.keys(factGroups).length ? ` · ${Object.entries(factGroups).map(([k, v]) => `${k === 'enterprise_fact' ? '还没分类' : k} ${v}`).join(' / ')}` : ''}
            </small>
          </div>
          <ul className="geo-lines">
            {enterpriseFacts.slice(0, 12).map((row, index) => (
              <li key={index}>
                {String(row.display ?? row.canonical_name ?? '')}
                <span className="geo-muted">{String(row.fact_group_label ?? '')}</span>
              </li>
            ))}
          </ul>
          {enterpriseFacts.length > 12 ? <p className="geo-note">仅展示前 12 条，共 {enterpriseFacts.length} 条。</p> : null}
        </>
      ) : null}

      {enterpriseFacts.length ? (
        <p className="geo-note">
          已确认信息里完成正式分类的只有 <strong>{linkedFacts}</strong> 条，
          因此下面的分类摘要暂时可能显示「暂无记录」——资料没有被丢掉，它们都在上面；
          GEO 不根据关键词替你猜测资料属于哪一类。
        </p>
      ) : null}

      {keyFacts.length ? (
        <>
          <div className="geo-subhead">
            <h3>关键事实</h3>
            <small>
              {keyFactsBasis === 'number_or_time'
                ? '带数字/时间，生成内容时优先引用（已随已确认企业信息整体注入）'
                : '当前信息里没有带数字/时间的，这里按证据强度列出前几条（同样随已确认企业信息注入）'}
            </small>
          </div>
          <ul className="geo-lines">{keyFacts.slice(0, 6).map((row, index) => <li key={index}>{factLine(row)}</li>)}</ul>
        </>
      ) : null}

      <div className="geo-subhead"><h3>资料分类摘要</h3><small>只依据已确认分类归类；没有分类依据就显示暂无记录</small></div>
      <GeoTable
        columns={['类别', '内容']}
        template="96px minmax(0,2fr)"
        rows={PROFILE_GROUPS.map((group) => {
          const rows = classified[group.key] ?? []
          return [
            <b>{group.label}</b>,
            rows.length ? <em>{rows.map(factLine).join('；')}</em> : <em className="geo-muted">暂无记录</em>,
          ]
        })}
      />

      {relations.length ? (
        <>
          <div className="geo-subhead"><h3>对象关系</h3><small>企业资料里的对象关系</small></div>
          <ul className="geo-lines">
            {relations.slice(0, 12).map((row, index) => (
              <li key={index}>
                <b>{String(row.source_name ?? '某对象')}</b>
                {` ${String(row.relation_type ?? '关联')} `}
                <b>{String(row.target_name ?? '某对象')}</b>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      {questions.length ? (
        <>
          <div className="geo-subhead"><h3>客户在问什么</h3><small>与本企业有关的客户问题</small></div>
          <ul className="geo-lines">{questions.slice(0, 8).map((row, index) => <li key={index}>{String(row.question ?? '')}</li>)}</ul>
        </>
      ) : null}

      {assets.length ? (
        <>
          <div className="geo-subhead"><h3>已入库内容资产</h3><small>{assets.length} 个</small></div>
          <GeoBars
            items={assets.slice(0, 8).map((row, index) => ({ label: String(row.title ?? `素材 ${index + 1}`), value: 1, text: '已入库' }))}
          />
        </>
      ) : null}

      {!facts.length && !enterpriseFacts.length && !relations.length && !questions.length && !assets.length ? (
        <div className="geo-empty">企业资料里还没有这家企业的可读事实，先去「企业资料」导入一次资料。</div>
      ) : null}
    </div>
  )
}
