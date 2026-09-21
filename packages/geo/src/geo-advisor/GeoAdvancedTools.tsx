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
  knowledge_search: '企业知识库检索',
  knowledge_relations: '企业知识库关系',
  geo_questions: 'GEO 客户问题池',
  geo_kb: 'GEO 内容资产',
  enterprise_facts: '知识库正式事实（active fact）',
}
const profileSourceText = (value: string) => PROFILE_SOURCE_LABEL[value] ?? `其他来源（${value}）`

export function GeoAdvancedTools({onClose}:{onClose:()=>void}){
  const [engines,setEngines]=useState<Row[]>([]),[profile,setProfile]=useState<Row|null>(null),[busy,setBusy]=useState(''),[notice,setNotice]=useState('')
  const [company,setCompany]=useState(''),[keywords,setKeywords]=useState(''),[platform,setPlatform]=useState('sogou'),[limit,setLimit]=useState(3)
  async function load(){
    const [e,c]=await Promise.allSettled([geoGet<{engines:Row[]}>('/meta/engines'),geoGet<{company_name?:string}>('/content/company')])
    if(e.status==='fulfilled')setEngines(e.value.engines??[])
    if(c.status==='fulfilled'&&c.value.company_name){setCompany((v)=>v||c.value.company_name||'');try{setProfile(await geoGet<Row>(`/knowledge/profile?company_name=${encodeURIComponent(c.value.company_name)}`))}catch{setProfile(null)}}
  }
  useEffect(()=>{void load()},[])
  async function act(key:string,fn:()=>Promise<any>,done:string){setBusy(key);setNotice('');try{const d=await fn();setNotice(d?.error||d?.skipped||done);await load()}catch(e){setNotice(e instanceof Error?e.message:'操作失败')}finally{setBusy('')}}
  /** 出厂重置：两次确认后带 confirm=true 调用（后端不带 confirm 会直接拒绝） */
  async function resetGeoData(){
    if(!(await askGeoConfirm('这是最高危操作：将清空本 GEO 的全部业务数据（问题池 / 知识缺口 / 内容计划 / 监测历史 / 内容资产 / 关注与采集 / 链接 / 素材向量），恢复出厂状态，且不可撤销。企业知识库与其他产品不受影响。','继续')))return
    if(!(await askGeoConfirm('最后确认：现在就清空 GEO 数据？清空后无法找回。','确认清空')))return
    await act('reset',()=>geoPost('/knowledge/reset?confirm=true',{}),'GEO 数据已重置为出厂状态')
  }
  return <aside className="advanced-drawer"><header><div><span>ADVANCED OPERATIONS</span><h2>高级工具</h2><p>低频、可能消耗模型额度或需要技术判断的能力集中在这里。</p></div><button onClick={onClose} aria-label="关闭高级工具"><X/></button></header>{notice&&<div className="geo-notice">{notice}</div>}
    <section><header><Server/><div><h3>模型引擎</h3><p>显示企业部署登记的国产模型；连通性以实测为准。</p></div></header><div className="engine-list">{engines.map((e,i)=><article key={e.id??e.engine_id??i}><div><b>{String(e.name??e.engine_name??e.id??'模型')}</b><small>{String(e.provider??e.status??'已登记')}</small></div><button disabled={busy===String(e.id??e.engine_id)} onClick={()=>void act(String(e.id??e.engine_id),()=>geoPost(`/meta/engines/${e.id??e.engine_id}/ping`,{}),'连通性检测完成')}>{busy===String(e.id??e.engine_id)?<LoaderCircle className="spin"/>:<CheckCircle2/>}实测</button></article>)}</div></section>
    <section><header><Search/><div><h3>外网证据补搜</h3><p>证据不足时使用，采集内容与企业正式资料保持分离。</p></div></header><div className="advanced-form"><input value={company} onChange={e=>setCompany(e.target.value)} placeholder="企业名称"/><input value={keywords} onChange={e=>setKeywords(e.target.value)} placeholder="关键词，逗号分隔"/><select value={platform} onChange={e=>setPlatform(e.target.value)}><option value="sogou">搜狗</option><option value="baidu">百度</option><option value="weibo">微博</option></select><button className="geo-btn primary" disabled={busy==='harvest'||!company.trim()||!keywords.trim()} onClick={()=>void act('harvest',()=>geoPost('/intelligence/harvest/search',{company:company.trim(),keywords:keywords.split(/[，,]/).map(x=>x.trim()).filter(Boolean),platform,max_per_keyword:10}),'补搜任务已完成采集')}>{busy==='harvest'?<LoaderCircle className="spin"/>:<Search/>}开始补搜</button></div></section>
    <section><header><Sparkles/><div><h3>自动内容闭环</h3><p>从待生产计划自动生成内容并存入素材库；不会自动发布到外部平台。</p></div></header><div className="loop-control"><label>本次最多处理 <select value={limit} onChange={e=>setLimit(Number(e.target.value))}><option value={1}>1 条</option><option value={3}>3 条</option><option value={5}>5 条</option></select></label><button className="geo-btn primary" disabled={busy==='loop'} onClick={()=>void act('loop',()=>geoPost(`/distill/loop/run?limit=${limit}`,{}),'自动生产完成')}>{busy==='loop'?<LoaderCircle className="spin"/>:<Sparkles/>}运行自动生产</button></div></section>
    <section><header><CheckCircle2/><div><h3>素材索引与企业画像</h3><p>索引由系统维护；这里提供人工补跑和画像状态检查。</p></div></header><div className="profile-preview"><ProfileBody profile={profile}/><button className="geo-btn secondary" disabled={busy==='vector'} onClick={()=>void act('vector',()=>geoPost('/knowledge/materials/vectorize',{}),'素材索引已更新')}>更新素材索引</button></div></section>
    {/* Owner 2026-09-21：重置接口已在产品门放行，前端补入口（原先只有接口没有按钮）。
        出厂重置是最高危操作，点两次才算数——第一次说明范围，第二次是真正确认，然后才带 confirm=true 调用。 */}
    <section className="disabled-tool"><header><Trash2/><div><h3>重置 GEO 数据</h3><p>恢复出厂状态：清空问题池、知识缺口、内容计划、监测历史、内容资产、关注/采集/链接与素材向量。<b>不可撤销</b>；不动企业自己的知识库与其他产品。</p></div></header><div className="loop-control"><button className="geo-btn secondary" disabled={busy==='reset'} onClick={()=>void resetGeoData()}>{busy==='reset'?<LoaderCircle className="spin"/>:<Trash2/>}重置 GEO 数据</button></div></section>
    <section className="disabled-tool"><header><Search/><div><h3>官网诊断</h3><p>后端当前仍是 P0 占位接口，尚未产生真实诊断报告，因此不开放运行按钮。</p></div></header></section>
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

  return (
    <div className="geo-profile-readout">
      <GeoKpis
        items={[
          { label: '正式企业事实', value: `${enterpriseFacts.length} 条`, detail: '知识库里已发布的事实（原样消费）' },
          { label: '企业名检索命中', value: `${facts.length} 条`, detail: '按企业名检索到的知识对象（相关性前 20 条）' },
          { label: '对象关系', value: `${relations.length} 条`, detail: '人、产品、客户之间的连接' },
          { label: '内容资产', value: `${assets.length} 个`, detail: '本企业已入库的素材' },
        ]}
      />
      <p className="geo-note">
        {profile.knowledge_ok === false
          ? `知识库这次读不到：${String(profile.knowledge_error ?? '未知原因')}（这是读取失败，不代表企业没有数据）`
          : '知识库读取正常'}
        {profile.built_at ? ` · 画像构建于 ${shortDay(String(profile.built_at))}` : ''}
        {sources.length ? ` · 来源 ${sources.map(profileSourceText).join('、')}` : ''}
      </p>

      {profile.facts_error ? (
        <p className="geo-note">正式事实这次读不到：{String(profile.facts_error)}（这是读取失败，不代表企业没有事实）</p>
      ) : null}

      {enterpriseFacts.length ? (
        <>
          <div className="geo-subhead">
            <h3>正式企业事实</h3>
            <small>
              知识库里已发布的事实（facts），原样展示，不由 GEO 改写；共 {enterpriseFacts.length} 条
              {Object.keys(factGroups).length ? ` · ${Object.entries(factGroups).map(([k, v]) => `${k === 'enterprise_fact' ? '未关联 Semantic' : k} ${v}`).join(' / ')}` : ''}
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
          正式事实里带权威 Semantic 关联的只有 <strong>{linkedFacts}</strong> 条，
          因此下面的七类归纳暂时只会显示「暂无记录」——事实没有被丢掉，它们都在上面；
          是「谁属于哪一类」还没有权威依据，GEO 不按关键词替你猜。
        </p>
      ) : null}

      {keyFacts.length ? (
        <>
          <div className="geo-subhead">
            <h3>关键事实</h3>
            <small>
              {keyFactsBasis === 'number_or_time'
                ? '带数字/时间，生成内容时优先引用（已随正式企业事实整体注入）'
                : '当前事实里没有带数字/时间的，这里按证据强度列出前几条（同样随正式企业事实注入）'}
            </small>
          </div>
          <ul className="geo-lines">{keyFacts.slice(0, 6).map((row, index) => <li key={index}>{factLine(row)}</li>)}</ul>
        </>
      ) : null}

      <div className="geo-subhead"><h3>画像归纳</h3><small>只依据知识库对象的权威 Semantic 关联归类；没有关联就写暂无记录</small></div>
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
          <div className="geo-subhead"><h3>对象关系</h3><small>知识库里的实体连接</small></div>
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
          <div className="geo-subhead"><h3>客户在问什么</h3><small>问题池里与本企业有关的提问</small></div>
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
        <div className="geo-empty">知识库里还没有这家企业的可读事实，先去「企业资料」执行一次知识库初始化。</div>
      ) : null}
    </div>
  )
}
