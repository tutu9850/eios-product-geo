import { ArrowRight, FlaskConical, Radar } from 'lucide-react'
import { GEO_DEMO_NOTICE } from './demo-fixtures'
import { useGeoNav } from './shared'

/** 演示模式的监测配置讲解。真实对象管理仍由 GeoMonitorObjectsCard 独立负责。 */
export function GeoDemoMonitorSetup() {
  const go = useGeoNav()
  return <section className="geo-demo-monitor-setup geo-panel">
    <div className="geo-demo-banner"><FlaskConical /><span><b>内测演示数据已开启</b>　{GEO_DEMO_NOTICE}</span></div>
    <div className="geo-demo-monitor-head"><Radar /><div><span>演示监测主体</span><h2>笔革家居</h2><p>向国产模型提问，记录它是否认出这家企业、如何描述产品，以及哪些回答缺少依据。</p></div></div>
    <div className="geo-demo-monitor-steps">
      <div><b>1. 监测范围</b><span>品牌：笔革家居 · 产品：沙发、软床、柜类定制 · 地区：成都</span></div>
      <div><b>2. 运行问题</b><span>固定演示问题集覆盖认知、比较、决策和信任；不调用真实模型。</span></div>
      <div><b>3. 核对回答</b><span>本批演示样本为 36 条回答。先看模型原话，再看聚合分析。</span></div>
    </div>
    <div className="geo-demo-monitor-actions"><button type="button" className="geo-btn primary" onClick={() => go?.('monitor-report')}>查看演示模型回答<ArrowRight /></button><button type="button" className="geo-btn secondary" onClick={() => go?.('monitor-analysis')}>查看演示监测分析<ArrowRight /></button></div>
    <p className="geo-note">演示模式只读。关闭顶部“演示数据”后，才能管理和运行真实监测对象。</p>
  </section>
}
