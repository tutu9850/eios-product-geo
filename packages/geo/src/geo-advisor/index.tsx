import { AutoConfigFlow } from './AutoConfigFlow'
import { GeoActionPlanCard } from './GeoActionPlanCard'
import { GeoAssetsListCard } from './GeoAssetsListCard'
import { GeoBattleCard } from './GeoBattleCard'
import { GeoCognitionCard } from './GeoCognitionCard'
import { GeoContentGenForm } from './GeoContentGenForm'
import { GeoGapsListCard } from './GeoGapsListCard'
import { GeoKnowledgeInitCard } from './GeoKnowledgeInitCard'
import { GeoMonitorObjectsCard } from './GeoMonitorObjectsCard'
import { GeoMonitorSetup } from './GeoMonitorSetup'
import { GeoMonitorReportCard } from './GeoMonitorReportCard'
import { GeoPlansListCard } from './GeoPlansListCard'
import { GeoQuestionsListCard } from './GeoQuestionsListCard'
import { GeoReportCard } from './GeoReportCard'
import { GeoInsightWorkspace } from './GeoInsightWorkspace'
import { GeoProfileWorkspace } from './GeoProfileWorkspace'
import { GeoMonitorAnalytics } from './GeoMonitorAnalytics'
import { GeoFaqWorkspace } from './GeoFaqWorkspace'
import { GeoCognitionMap } from './GeoCognitionMap'
import { GeoDemoFlowPreview, type DemoPreviewKind } from './GeoDemoFlowPreview'
import { GeoCardErrorBoundary, useGeoDemoMode } from './shared'

export type GeoFlowKind =
  | 'kb-init'
  | 'auto-config'
  | 'monitor'
  | 'monitor-report'
  | 'assets'
  | 'questions'
  | 'gaps'
  | 'cognition'
  | 'content'
  | 'battle'
  | 'report'
  | 'plans'
  | 'action-plan'
  | 'insight-overview'
  | 'profile-overview'
  | 'monitor-analysis'
  | 'faq'
  | 'cognition-map'

/** 触发词 → GEO 功能（前端硬匹配，命中即出固定卡片，不发给 agent） */
export function matchGeoTrigger(text: string): GeoFlowKind | null {
  const t = text.trim()
  if (!t) return null
  // 内测：知识库初始化（Owner 2026-09-21「单独一个按钮，内测用」）
  if (/(知识库初始化|初始化知识库|从知识库导入|初始化我的资料|初始化本公司)/.test(t)) return 'kb-init'
  if (/(自动配置|开始配置|帮我配置好)/.test(t)) return 'auto-config'
  if (/(监测|定时任务)/.test(t)) return 'monitor'
  if (/(内容资产|素材库|素材)/.test(t)) return 'assets'
  if (/(问题池|客户问题|什么问题)/.test(t)) return 'questions'
  if (/(知识缺口|缺口)/.test(t)) return 'gaps'
  if (/(认知评估|认知)/.test(t)) return 'cognition'
  if (/(内容生成|生成内容|写内容|写文章|写一篇)/.test(t)) return 'content'
  if (/(模型对比|对战|辩论|battle)/i.test(t)) return 'battle'
  if (/(阶段报告|^报告|周报|月报)/.test(t)) return 'report'
  if (/(内容计划|计划)/.test(t)) return 'plans'
  if (/(行动计划|行动|30天|三十天)/.test(t)) return 'action-plan'
  return null
}

/** GEO 功能菜单（上拉菜单列项：名字 + 图标，不写说明） */
export const GEO_FLOW_MENU: Array<{ kind: GeoFlowKind; icon: string; label: string }> = [
  // 内测：从知识库初始化本公司资料（独立按钮，Owner 2026-09-21 点名）
  { kind: 'kb-init', icon: '🧪', label: '导入企业资料（内测）' },
  { kind: 'auto-config', icon: '⚙️', label: '首次设置' },
  { kind: 'monitor', icon: '📡', label: '国产模型监测' },
  { kind: 'questions', icon: '🗂', label: '客户会问什么' },
  { kind: 'gaps', icon: '🧩', label: '资料缺口' },
  { kind: 'plans', icon: '📝', label: '内容计划' },
  { kind: 'assets', icon: '📚', label: '内容资产' },
  { kind: 'cognition', icon: '🧠', label: '品牌理解' },
  { kind: 'content', icon: '✍️', label: '内容生成' },
  { kind: 'battle', icon: '⚖️', label: '模型对比' },
  { kind: 'report', icon: '📄', label: '阶段报告' },
  { kind: 'action-plan', icon: '📋', label: '行动计划' },
]

/** GEO 固定功能卡片路由器：按触发类型渲染对应组件 */
export function GeoFlowRouter({ kind, onClose }: { kind: GeoFlowKind; onClose?: (kind: GeoFlowKind) => void }) {
  const { enabled: demoMode } = useGeoDemoMode()
  const demoPreviewKinds: DemoPreviewKind[] = ['kb-init', 'auto-config', 'assets', 'questions', 'gaps', 'plans', 'content', 'battle', 'report', 'faq']
  if (demoMode && demoPreviewKinds.includes(kind as DemoPreviewKind)) return <GeoDemoFlowPreview kind={kind as DemoPreviewKind} />
  switch (kind) {
    case 'kb-init':
      return <GeoKnowledgeInitCard />
    case 'auto-config':
      return <AutoConfigFlow onClose={onClose ? () => onClose('auto-config') : undefined} />
    case 'monitor':
      // 监测工作台只负责管理监测对象和定时任务；模型回答有独立目的地。
      if (demoMode) return <GeoMonitorSetup />
      return (
        <GeoCardErrorBoundary label="监测对象">
          <GeoMonitorObjectsCard />
        </GeoCardErrorBoundary>
      )
    case 'monitor-report':
      return <GeoCardErrorBoundary label="模型回答"><GeoMonitorReportCard /></GeoCardErrorBoundary>
    case 'assets':
      return <GeoAssetsListCard />
    case 'questions':
      return <GeoQuestionsListCard />
    case 'gaps':
      return <GeoGapsListCard />
    case 'cognition':
      return <GeoCognitionCard />
    case 'content':
      return <GeoContentGenForm />
    case 'battle':
      return <GeoBattleCard />
    case 'report':
      return <GeoReportCard />
    case 'action-plan':
      return <GeoActionPlanCard />
    case 'plans':
      return <GeoPlansListCard />
    case 'insight-overview':
      return <GeoInsightWorkspace />
    case 'profile-overview':
      return <GeoProfileWorkspace />
    case 'monitor-analysis':
      return <GeoCardErrorBoundary label="监测分析"><GeoMonitorAnalytics /></GeoCardErrorBoundary>
    case 'faq':
      return <GeoFaqWorkspace />
    case 'cognition-map':
      return <GeoCognitionMap />
  }
}
