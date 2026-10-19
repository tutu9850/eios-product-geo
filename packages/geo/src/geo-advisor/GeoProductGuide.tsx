import { ArrowRight, BarChart3, BookOpenCheck, ChartNoAxesCombined, CircleHelp, FileText, Radar, Target, X } from 'lucide-react'

type GuideWorkspace = 'overview' | 'monitor' | 'insight' | 'profile' | 'growth' | 'market'

const STEPS: Array<{ workspace: GuideWorkspace; icon: typeof BookOpenCheck; title: string; detail: string; result: string }> = [
  { workspace: 'profile', icon: BookOpenCheck, title: '准备企业资料', detail: '告诉 GEO 你是谁、卖什么、有什么真实交付能力。', result: '得到可引用的企业事实' },
  { workspace: 'monitor', icon: Radar, title: '运行模型监测', detail: '把客户会问的问题交给国产大模型，保存模型原话。', result: '知道品牌有没有被看见' },
  { workspace: 'insight', icon: ChartNoAxesCombined, title: '看懂认知差距', detail: '区分“被提到”“被正确理解”和“被明确推荐”。', result: '找到需要补证据的地方' },
  { workspace: 'growth', icon: Target, title: '完成内容行动', detail: '把问题和缺口变成资料、内容，登记发布后运行新轮次。', result: '形成可重复的改进闭环' },
]

const OBJECTS = [
  { title: '企业资料', detail: '你提供的事实和材料，是 GEO 判断的依据。' },
  { title: '监测主体', detail: '被识别和登记的企业或品牌；登记不代表已经在持续监测。' },
  { title: '监测配置', detail: '针对主体的启停、问题和频率设置；它决定什么时候运行监测问题。' },
  { title: '一次监测', detail: '一次批量运行，产生一批模型回答；不会自动变成品牌结论。' },
  { title: '即时检测', detail: '用户临时问一个问题，只看本次结果，不改变持续监测配置。' },
  { title: '模型回答', detail: '模型在某个客户问题下说过的原话；原话不等于企业事实。' },
  { title: '证据', detail: '能追溯到回答原文或资料来源的依据；没有证据就保持未判定。' },
  { title: '市场信号', detail: '竞品或行业的外部线索，确认后才能转成内容计划，不直接改变品牌指标。' },
]

const WORKSPACE_LABEL: Record<GuideWorkspace, string> = {
  overview: '总览', profile: '企业资料', monitor: '监测', insight: '差距', growth: '内容行动', market: '更多',
}

export function GeoProductGuide({ workspace, onNavigate, onClose }: { workspace: GuideWorkspace; onNavigate: (workspace: GuideWorkspace) => void; onClose: () => void }) {
  return (
    <div className="geo-product-guide-backdrop" role="presentation" onMouseDown={(event) => { if (event.currentTarget === event.target) onClose() }}>
      <section className="geo-product-guide" role="dialog" aria-modal="true" aria-labelledby="geo-product-guide-title">
        <header className="geo-product-guide-head">
          <div>
            <span><CircleHelp />先理解这一套系统</span>
            <h2 id="geo-product-guide-title">GEO 是什么？</h2>
            <p>GEO 帮你检查：客户向国产大模型提问时，模型有没有看见你的品牌、能不能说对，以及下一步该补什么。系统先保存回答，再用可追溯证据形成判断。</p>
          </div>
          <button type="button" className="geo-product-guide-close" aria-label="关闭 GEO 使用说明" onClick={onClose}><X /></button>
        </header>

        <div className="geo-product-guide-current"><BarChart3 /><span>你当前在「{WORKSPACE_LABEL[workspace]}」；下面四步是完整工作路径。</span></div>

        <div className="geo-product-guide-steps">
          {STEPS.map(({ workspace: stepWorkspace, icon: Icon, title, detail, result }, index) => (
            <button key={stepWorkspace} type="button" className={workspace === stepWorkspace ? 'active' : ''} onClick={() => { onNavigate(stepWorkspace); onClose() }}>
              <div className="geo-product-guide-step-top"><span>{index + 1}</span><Icon /></div>
              <b>{title}</b>
              <p>{detail}</p>
              <small><ArrowRight />{result}</small>
            </button>
          ))}
        </div>

        <div className="geo-product-guide-objects">
          <header><FileText /><div><b>页面里这些词分别代表什么？</b><span>它们是不同资源域：先分清对象，再看结论。</span></div></header>
          <div className="geo-product-guide-object-grid">{OBJECTS.map((item) => <div key={item.title}><b>{item.title}</b><p>{item.detail}</p></div>)}</div>
        </div>
      </section>
    </div>
  )
}
