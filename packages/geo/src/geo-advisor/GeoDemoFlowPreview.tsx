import { ArrowRight, FlaskConical, ShieldCheck } from 'lucide-react'
import { GeoCardShell, useGeoNav } from './shared'
import { GEO_DEMO_NOTICE } from './demo-fixtures'

export type DemoPreviewKind = 'kb-init' | 'auto-config' | 'assets' | 'questions' | 'gaps' | 'plans' | 'content' | 'battle' | 'report' | 'faq'

const COPY: Record<DemoPreviewKind, { eyebrow: string; title: string; description: string; items: Array<{ title: string; detail: string; tag: string }>; next?: { label: string; kind: string } }> = {
  'kb-init': {
    eyebrow: '资料准备', title: '企业资料已经准备好', description: '演示样例已经放入一套虚构企业资料；正式模式下，这一步会把企业资料导入 GEO 工作区。',
    items: [{ title: '品牌与定位', detail: '有可引用的品牌主张和目标客户描述', tag: '已准备' }, { title: '产品与服务', detail: '有产品目录和定制说明', tag: '已准备' }, { title: '交付与案例', detail: '资料较少，是样例里的主要缺口', tag: '待补齐' }], next: { label: '去看模型回答', kind: 'monitor-report' },
  },
  'auto-config': {
    eyebrow: '首次设置', title: '从企业资料到首轮监测', description: '演示模式只展示完成后的路径，不会创建真实监测对象、任务或问题。关闭演示数据后，可用向导完成真实设置。',
    items: [{ title: '确认企业资料', detail: '确认品牌、产品和所在地', tag: '第 1 步' }, { title: '运行首轮监测', detail: '把客户问题交给国产模型并记录原话', tag: '第 2 步' }, { title: '查看差距并行动', detail: '把缺口变成资料、内容和复测', tag: '第 3 步' }], next: { label: '去看模型回答', kind: 'monitor-report' },
  },
  assets: {
    eyebrow: '内容资产', title: '公开内容资产', description: '这些材料让模型有可以引用的公开依据；它和企业资料分开保存，也不会自动发布。',
    items: [{ title: '成都三居室收纳改造案例', detail: '案例 · 已入库 · 可作为客户案例依据', tag: '案例' }, { title: '交付与售后说明', detail: '服务说明 · 需要补充周期和响应口径', tag: '待补' }, { title: '空间规划指南', detail: '解决方案 · 可用于解释差异化能力', tag: '方案' }], next: { label: '去看资料缺口', kind: 'gaps' },
  },
  questions: {
    eyebrow: '客户问题', title: '客户会问什么', description: '这里回答“客户会问什么”，再把这些问题交给模型验证，而不是直接把问题当成市场结论。',
    items: [{ title: '成都适合年轻家庭的家居品牌有哪些？', detail: '认知 / 比较 · 已监测', tag: '高优先' }, { title: '笔革家居交付和售后怎么样？', detail: '决策 / 信任 · 证据不足', tag: '高优先' }, { title: '小户型如何选择柜类定制？', detail: '选择 · 尚未监测', tag: '待监测' }], next: { label: '去看资料缺口', kind: 'gaps' },
  },
  gaps: {
    eyebrow: '资料差距', title: '资料缺口', description: '缺口不是“模型说错了”，而是当前企业资料还不足以回答某个客户问题。',
    items: [{ title: '交付周期说明', detail: '竞品有明确节点，我方缺少可引用口径', tag: '现在处理 · 信任' }, { title: '真实客户案例结果', detail: '已有案例标题，但缺预算、周期和结果', tag: '现在处理 · 案例' }, { title: '定制差异化证据', detail: '有服务描述，缺可比较的结果证据', tag: '近期处理 · 比较' }], next: { label: '去看增长行动', kind: 'action-plan' },
  },
  plans: {
    eyebrow: '内容计划', title: '内容计划', description: '每条计划都应该对应一个客户问题和一个可补的证据，发布后再回到模型监测复测。',
    items: [{ title: '交付周期与售后说明', detail: '针对：延期交付怎么办？ · 官网 + 知乎', tag: '现在处理' }, { title: '真实客户案例库', detail: '针对：有没有相近户型案例？ · 官网 + 小红书', tag: '现在处理' }, { title: '小户型空间规划指南', detail: '针对：小户型怎么选柜类？ · FAQ', tag: '长期建设' }], next: { label: '去看增长行动', kind: 'action-plan' },
  },
  content: {
    eyebrow: '内容制作', title: '把缺口写成可发布内容', description: '正式模式下，这里会基于企业资料生成草稿并做依据检查；演示模式只展示结果形态，不写入素材库。',
    items: [{ title: '主题：交付周期与售后响应', detail: '目标：回答客户最担心的交付问题', tag: '演示草稿' }, { title: '依据：当前只有服务条款片段', detail: '缺少确定承诺时必须保留“待确认”', tag: '需核验' }], next: { label: '去看阶段报告', kind: 'report' },
  },
  battle: {
    eyebrow: '模型对比', title: '同一个问题，不同模型怎么回答', description: '模型对比用于找出回答差异，不代表模型之间有输赢，也不替企业生成事实。',
    items: [{ title: '问题：笔革家居交付和售后怎么样？', detail: 'DeepSeek：无法确认具体周期 · 豆包：需要补充公开资料', tag: '2 个模型' }, { title: '差异总结', detail: '不同模型都指出交付证据不足，优先补齐公开说明', tag: '演示结论' }], next: { label: '去看监测分析', kind: 'monitor-analysis' },
  },
  report: {
    eyebrow: '阶段结果', title: '企业在模型回答中的表现', description: '报告只总结有模型回答和可追溯原话的结果；没有证据时不会用企业内部资料代替外部判断。',
    items: [{ title: '本期判断', detail: '品牌已经能被看见，但交付证据还没有形成稳定认知', tag: '36 条样例回答' }, { title: '下一步', detail: '补交付周期、售后响应和完整客户案例', tag: '3 个重点' }], next: { label: '去看认知洞察', kind: 'insight-overview' },
  },
  faq: {
    eyebrow: '生成常见问答', title: '把客户问题变成可发布问答', description: '问答会区分企业资料依据和待补内容，依据不足时会明确标出，不会用通用常识冒充企业事实。',
    items: [{ title: '问：笔革家居有哪些优势？', detail: '答：演示资料支持空间规划和组合建议；具体承诺仍需补证据', tag: '部分有依据' }, { title: '问：延期交付怎么办？', detail: '当前资料不足，不能生成确定的时效承诺', tag: '待补依据' }], next: { label: '去看资料缺口', kind: 'gaps' },
  },
}

export function GeoDemoFlowPreview({ kind }: { kind: DemoPreviewKind }) {
  const go = useGeoNav()
  const copy = COPY[kind]
  return <GeoCardShell className="geo-demo-flow-preview">
    <div className="geo-demo-banner"><FlaskConical /><span><b>内测演示数据已开启</b>　{GEO_DEMO_NOTICE}</span></div>
    <header className="geo-demo-preview-head"><div><span>{copy.eyebrow}</span><h2>{copy.title}</h2><p>{copy.description}</p></div><ShieldCheck /></header>
    <div className="geo-demo-preview-list">{copy.items.map((item) => <article key={item.title}><div><b>{item.title}</b><p>{item.detail}</p></div><span>{item.tag}</span></article>)}</div>
    <div className="geo-demo-preview-note">演示页面只读，不会创建监测对象、写入计划、上传素材或导出正式报告。</div>
    {copy.next ? <button className="geo-btn primary geo-demo-preview-next" type="button" onClick={() => go?.(copy.next!.kind)}>{copy.next.label}<ArrowRight /></button> : null}
  </GeoCardShell>
}
