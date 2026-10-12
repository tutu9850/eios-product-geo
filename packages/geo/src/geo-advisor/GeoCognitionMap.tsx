import { GeoMonitorAnalytics } from './GeoMonitorAnalytics'

/**
 * 客户认知地图曾经是一个独立的双栏分数页，导致“当前批次覆盖”和“历史认知评估”
 * 被误读成同一套指标。它现在只是监测分析的解释上下文入口，统一走同一条证据到行动
 * 的页面，避免同一批数据在两个页面各说一套。
 */
export function GeoCognitionMap() {
  return <GeoMonitorAnalytics />
}
