# GEO 功能全清单（给前端 UI 设计用）

2026-09-21 第一轮 · 基线 `eios-product-geo` @ `cf443ac` + 「初始化顺手给体检结论」
2026-09-21 第二轮 · 前端改造（消灭临时展示 + 交互收口）：**UI 列按打包 UI 的真实调用重扫了一遍**，
不采信上一轮的标记。

## 0. 一句话

GEO 后端现在有 **139 条能力**（method + path）：**136 条已过产品门放行**、**103 条已有界面
入口**（第二轮从 49 涨到 103），剩下 **36 条只有后端能力、菜单里没有门进去**。这份清单把它们
按**用户要干的事**重排一遍，给 UI 设计当输入。

**UI 列怎么算的（第二轮）**：机械扫描 `packages/geo/src/**` 里所有
`geoGet / geoPost / geoPut / geoPatch / geoDelete / geoUpload / geoDownload(File)` 调用的路径字面量；
模板参数（例：`` `/monitor/items/${id}/trend` ``）先归一成形状再比对，**不算「未使用」**；
两族动态路径（`/intelligence/{9 个}`、`/monitor/{6 个分析页}`）按代码里真实的路径数组逐条展开。

几条事实先钉住，免得设计时踩空：

- **不是所有能力都该有界面。** 有些是给别的产品调的（顾问交接面 3 条，现在**没放行**），
  有些是内部恢复动作（`/intelligence/recover`、`/monitor/pool`），有些已经并进了别的卡
  （`/content/score` 就在内容生成卡里）。
- **性质分布**：读 72 / 写 38 / 跑 21 / 算 8。「跑」的 21 条会调模型（Model Capability
  :8094）或打 AI 引擎，**企业部署承担模型成本**；「算」的 8 条只是本机算一遍，不落库、不调模型。
- **产品门三档 scope**（签名用）：`read` 77 / `run` 20 / `manage` 39。「长任务」在 `run` 档，
  代理超时 180 秒；UI 上「点了要转圈」和「点了就存下来」长得不一样，就是这个原因。
- **第一轮的增量**：`GET /enterprise-profile/overview` 与 `/categories` 从「无入口」变成有入口
  （当时 47 → 49）。
- **第二轮新增的界面入口（54 条）**：市场情报整面（watchlist / signals / links / 采集 / 转计划）、
  洞察汇报层与诊断层（humanize / sov / trend-delta / matrix / factor-gaps / gap-analysis / evidence /
  keywords / perception / strategies）、监测六个分析页 + 导出 + 驾驶舱 + 对象趋势 + 任务聚合、
  企业资料总揽（categories / items / items-plans / export / refresh）、认知覆盖矩阵与客户认知地图、
  内容闭环（publish / recheck / quality / faq / loop）、高级工具（engines / ping / profile / company /
  harvest / vectorize）、总览（stats/overview、distill/overview）。
- **第二轮唯一一处「界面入口减少」**：没有。上一轮标 ✅ 的 49 条，这一轮仍然全部 ✅。

## 1. 怎么读「性质」列

| 值 | 意思 |
|---|---|
| 读 | 不改任何东西（全部 GET） |
| 算 | POST，但只是本机算一遍：不落库、不调模型（8 条，逐条人工确认） |
| 写 | 会往 GEO 自己的库里加/改/删记录 |
| 跑 | 会调模型或打 AI 引擎：要转圈、要额度、可能超时（21 条） |

「UI」列 ✅ = 打包 UI 今天真的在调这条；— = 只有后端能力。


### 2.1 ① 开局：把企业搬进来（11 条 · 读6/写2/跑1/算2）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/onboard/auto-config` | — | 跑 | ✅ |
| GET | `/onboard/run-status` | 后台监测+蒸馏进度（前端轮询；finished 后带 distill 结果 + inte… | 读 | ✅ |
| GET | `/onboard/status` | 空态检测 + 三种「素材」各有多少（2026-09-20 修正标签错位）。 | 读 | ✅ |
| POST | `/kb-init/apply` | 把用户点选的那份资料落进 GEO 自己的库（快照台账）。 | 写 | ✅ |
| POST | `/kb-init/scan` | 扫一遍知识库，给出可点选的候选（公司 / 产品 / 相关文档）。 | 算 | ✅ |
| GET | `/enterprise-profile/categories` | 8 大类 + 子项 + 档位/关联状态（左大纲树数据）。 | 读 | ✅ |
| GET | `/enterprise-profile/export` | 导出 Word（python-docx，九章结构）。 | 读 | ✅ |
| GET | `/enterprise-profile/items/{item_id}` | 单子项详情：已有资料 + 已覆盖/未覆盖问题 + 知识来源。 | 读 | ✅ |
| POST | `/enterprise-profile/items/{item_id}/plans` | 太少/部分子项 → 一键生成内容计划（对接蒸馏页 plans）。 | 写 | ✅ |
| GET | `/enterprise-profile/overview` | 总体健康度：企业资料覆盖率 + 足够/部分/太少 计数。 | 读 | ✅ |
| POST | `/enterprise-profile/refresh` | 刷新：清缓存重算（种子补齐 + 返回最新总览）。 | 算 | ✅ |
### 2.2 ② 监测：AI 怎么答你（31 条 · 读18/写7/跑5/算1）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/monitor/answers` | 0.2+：监测报告数据源——把 history 拍平成逐探针 × 逐引擎的回答列表 | 读 | ✅ |
| POST | `/monitor/batch` | 批量监测：支持两入口（0.2 统一内部流程，不留两套执行逻辑） | 跑 | — |
| POST | `/monitor/check` | — | 跑 | — |
| GET | `/monitor/citations` | 被 AI 引用的内容 Top N（S2：聚合 history batch 条目的 cit… | 读 | ✅ |
| GET | `/monitor/competitor` | 全智解析·竞品分析（0.4 升级）：从监测回答聚合竞争认知 | 读 | ✅ |
| GET | `/monitor/effects` | 单内容效果卡（S0）：素材详情弹窗「效果」区块数据源 | 读 | — |
| GET | `/monitor/export` | 导出监测报告（markdown）：批量监测汇总 + 薄弱问题榜 + 内容建议 | 读 | ✅ |
| GET | `/monitor/fact-check` | P1-5：事实分析页（基于知识库识别 AI 回复失真：命中/异常/排行/明细） | 读 | ✅ |
| POST | `/monitor/generate-questions` | AI 生成客户问题（问题池来源）：围绕企业/行业生成真实搜索问法 | 跑 | — |
| GET | `/monitor/history` | — | 读 | — |
| GET | `/monitor/industry` | 全智解析·行业分析：从行业/关键词监测对象回答聚合行业格局 | 读 | ✅ |
| GET | `/monitor/items` | 0.2：监测对象列表（默认只 active/paused，archived 单独看） | 读 | ✅ |
| POST | `/monitor/items` | 0.2：新建监测对象（type 四枚举校验；status 默认 active） | 写 | ✅ |
| POST | `/monitor/items/preview` | 0.2+：监测对象探针预览——不落库，返回系统将生成的探针问题 + 成本估算 | 算 | ✅ |
| DELETE | `/monitor/items/{mid}` | 0.2：软删除（status → archived，历史趋势保留，不硬删） | 写 | ✅ |
| PATCH | `/monitor/items/{mid}` | 0.2：更新监测对象（部分更新：只改传入字段，不整包覆盖）——审计 P0 修复 | 写 | ✅ |
| POST | `/monitor/items/{mid}/run` | 0.2+：手动触发单监测对象运行（建完对象即可单独监测，不必先建任务） | 跑 | ✅ |
| GET | `/monitor/items/{mid}/trend` | 0.2：监测对象跨次趋势（同一 item 反复监测 → 逐次对比） | 读 | ✅ |
| GET | `/monitor/overview` | P0：数据总览驾驶舱四指标 + 分平台趋势 | 读 | ✅ |
| GET | `/monitor/pool` | — | 读 | — |
| POST | `/monitor/pool` | — | 写 | — |
| GET | `/monitor/public-opinion` | P1：舆情分析页（健康分 + 四指标 + 趋势 + 平台分布 + 高风险 top3 + … | 读 | ✅ |
| GET | `/monitor/rank-sentiment` | P0：平均排名（估算）+ 评价分布 + 趋势（驾驶舱/评价分析共用） | 读 | — |
| GET | `/monitor/sentiment` | P1：评价分析页（占比 + 趋势 + 用户意图维度 + 负面高频词） | 读 | ✅ |
| GET | `/monitor/sources` | 全智解析·信源分析：各 AI 引擎（信源）的表现排行 | 读 | ✅ |
| GET | `/monitor/tasks` | 0.3：监测任务列表（含每任务的 item 数与最近运行时间） | 读 | ✅ |
| POST | `/monitor/tasks` | 0.3：新建监测任务（名字 + 频率 + 绑定的监测对象） | 写 | ✅ |
| DELETE | `/monitor/tasks/{tid}` | 0.3：软删除任务（status → archived；item 解绑但保留） | 写 | ✅ |
| PATCH | `/monitor/tasks/{tid}` | 0.3：更新任务（改名/改频率/改绑定/启停） | 写 | ✅ |
| GET | `/monitor/tasks/{tid}/overview` | 0.3：任务级聚合——任务下每 item 的最新状态 + 任务整体指标 | 读 | ✅ |
| POST | `/monitor/tasks/{tid}/run` | 0.3：手动触发任务运行（engines 可指定，默认全部已配置引擎） | 跑 | ✅ |
### 2.3 ③ 认知与洞察：差距在哪（27 条 · 读23/写2/跑2/算0）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/intelligence/analyses` | 条级解析结果（兼容 answer_id 别名）。 | 读 | — |
| POST | `/intelligence/analyze` | 手动触发解析：指定 evidence_ids，或从监测历史回填（monitor_id/s… | 写 | — |
| GET | `/intelligence/compare` | 认知总表（方案 V2）：维度 × 主体 × 认知层级 × 认知状态 + 证据引用。min… | 读 | — |
| GET | `/intelligence/evidence` | 证据链：某因子的全部原话 + 传播强度 + 关联因子。 | 读 | ✅ |
| GET | `/intelligence/factor-gaps` | 因子级左右对比：竞品有·我方无（left，要补）vs 我方有·竞品无（right，优势）… | 读 | ✅ |
| GET | `/intelligence/gap-analysis` | 知识缺口两种分离：Knowledge Gap（补知识库/放弃）vs Evidence G… | 读 | ✅ |
| GET | `/intelligence/harvest/runs/{run_id}` | 补搜 run 状态（采集态，与解析成功与否无关）。 | 读 | — |
| POST | `/intelligence/harvest/search` | Phase A：外网补搜（WebSearch Harvest）。采集成功不依赖 LLM。 | 跑 | ✅ |
| GET | `/intelligence/humanize` | 商业化翻译层：一句话结论 + 三数字 + 左右列 + 行动清单（人话版）。 | 读 | ✅ |
| GET | `/intelligence/keywords` | 必备关键词：高频维度按提及数排序。 | 读 | ✅ |
| GET | `/intelligence/matrix` | 差距矩阵（S1 聚合，无 LLM）：维度榜 + 三色 + 观察区。gap_type 留 … | 读 | ✅ |
| GET | `/intelligence/overview` | 品牌提及概览：我方 vs 竞品提及率%。mode=comparison 只统计推荐/对比… | 读 | — |
| GET | `/intelligence/perception` | 认知标签分布（S1 聚合，无 LLM）。 | 读 | ✅ |
| POST | `/intelligence/recover` | 启动恢复：无 succeeded extraction 的 evidence 重新入队（… | 写 | — |
| GET | `/intelligence/reports/latest` | 最新周期报告。company 空则取全局最新；指定公司名则精确匹配 company_na… | 读 | ✅ |
| GET | `/intelligence/reports/latest/pdf` | 最新周期报告 PDF 下载（2026-08-15 新增）。无报告 → 404。 | 读 | ✅ |
| POST | `/intelligence/reports/run` | 触发 Reasoning 生成报告（限流 5 分钟一次）。 | 跑 | ✅ |
| GET | `/intelligence/sov` | SOV 声量份额（汇报第一指标）：品牌 vs 竞品在 AI 推荐中的 % 份额 + 趋势… | 读 | ✅ |
| GET | `/intelligence/stats` | 分析引擎状态（S0 用）：各表计数。 | 读 | — |
| GET | `/intelligence/strategies` | 内容策略（GEO Action Score）：需求×差距×可改变性×证据强度×竞争重要性… | 读 | ✅ |
| GET | `/intelligence/trend-delta` | 推荐率趋势变化：相邻周期（7 天）品牌推荐 gained/lost/rising/fal… | 读 | ✅ |
| GET | `/cognition/competitors` | — | 读 | ✅ |
| GET | `/cognition/coverage` | — | 读 | ✅ |
| GET | `/cognition/health` | — | 读 | ✅ |
| GET | `/cognition/portrait` | — | 读 | ✅ |
| GET | `/cognition/reasons` | — | 读 | ✅ |
| GET | `/cognition/sources` | — | 读 | ✅ |
### 2.4 ④ 蒸馏与内容生产（30 条 · 读9/写10/跑10/算1）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/distill/analyze` | Content Analyzer：内容覆盖分析（问题池 vs 内容） | 写 | — |
| GET | `/distill/cognition-map` | 蒸馏中心·客户认知地图：问题池按决策阶段聚合 + 企业覆盖 | 读 | ✅ |
| GET | `/distill/cognition-profile` | 企业 AI 认知覆盖矩阵：AI 回答里企业在 5 个维度的被提及率 | 读 | ✅ |
| POST | `/distill/cognition/evaluate` | AI 认知评估 V2 · 批处理评估：monitor_history 回答 → LLM … | 跑 | ✅ |
| GET | `/distill/cognition/profile` | AI 认知评估 V2 · 聚合结果：读 cognition_evaluations → … | 读 | ✅ |
| POST | `/distill/content-plan` | 内容计划算法（V1 规则版）：问题池 × AI 监测 → 48 子项压力 → 内容计划 … | 写 | ✅ |
| POST | `/distill/content-publish` | 发布日志（效果反哺闭环第一步）：计划 → 已发布。 | 写 | ✅ |
| POST | `/distill/content-recheck` | 复测对比（效果反哺第二步，手动触发）：已发布计划 → 重算覆盖问题监测分数 → 对比发布… | 写 | ✅ |
| POST | `/distill/faq` | FAQ 提炼：主题/关键词 → 客户常问的问答对（带 Knowledge Groundi… | 跑 | ✅ |
| POST | `/distill/faq/upgraded` | FAQ 升级版：单问题 → 知识检查 → 基于企业知识回答（无依据标注通用） | 跑 | — |
| GET | `/distill/gaps` | — | 读 | ✅ |
| POST | `/distill/gaps` | 知识缺口检测：问题池 → 逐个 Kernel 匹配 → 无知识的问题生成缺口 | 跑 | ✅ |
| POST | `/distill/loop/run` | 自动闭环（2026-08-15）：planned 计划 → 自动生产内容 → 存资产 →… | 跑 | ✅ |
| POST | `/distill/opportunities` | 内容机会（V2）：知识资产 → 可直接生产 + 知识缺口 → 建议补充 | 写 | — |
| GET | `/distill/overview` | 蒸馏总览：认知漏斗 + 验证状态 + TOP 缺口 + 机会数 | 读 | ✅ |
| GET | `/distill/plans` | 内容计划列表（S0 起支持三维排序：priority/weak/effect；分数可解释… | 读 | ✅ |
| POST | `/distill/plans` | 内容规划：知识缺口 → 运营内容计划（topic/reason/推荐类型/优先级） | 跑 | — |
| POST | `/distill/plans/customer-gap` | P6 薄接收口：客服知识缺口 → 现有内容计划；不生产、不发布、不写 Kernel。 | 写 | — |
| POST | `/distill/plans/from-gaps` | 薄弱问题一键生成内容计划（纯规则不调 LLM，省 token） | 写 | ✅ |
| POST | `/distill/plans/manual` | 手动/AI 写入单条内容计划（去重：同 target_question 或同 topic… | 写 | ✅ |
| DELETE | `/distill/plans/{plan_id}` | 删除内容计划（用户拍板：计划只加不减不行，每条可删） | 写 | ✅ |
| GET | `/distill/questions` | — | 读 | ✅ |
| POST | `/distill/questions` | Question Intelligence：种子词 → 客户问题池（意图/阶段/优先级/… | 跑 | ✅ |
| DELETE | `/distill/questions/{qid}` | — | 写 | ✅ |
| GET | `/distill/questions/{qid}/platforms` | P0：单个问题的 6 平台监测明细（对齐竞品"用户意图图"平台列） | 读 | ✅ |
| GET | `/content/company` | 自动识别当前企业（Kernel 读取） | 读 | ✅ |
| POST | `/content/generate` | 生成 GEO 内容草稿（自动读企业资料；不自动发布） | 跑 | ✅ |
| POST | `/content/parse` | AI 自动配置：把自然语言需求解析成 GEO 配置（目标/类型/风格/长度/平台/问题） | 跑 | — |
| POST | `/content/quality` | GEO 质量检测：内容 → 5 项评分（0-100）+ 改进建议 | 跑 | ✅ |
| POST | `/content/score` | GEO 评分：实体覆盖/事实密度/问题覆盖/结构完整 + 引用潜力（启发式）。 | 算 | ✅ |
### 2.5 ⑤ 市场情报与链接收录（16 条 · 读3/写9/跑1/算3）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/market/collect` | — | 写 | ✅ |
| GET | `/market/signals` | — | 读 | ✅ |
| POST | `/market/signals/{signal_id}/confirm` | 人工确认信号 —— **不写知识库**（Owner 2026-09-20）。 | 写 | — |
| POST | `/market/signals/{signal_id}/extract` | LLM 提取可核验事实（竞品发布/融资/合作/数据）；宣传口径不提取为事实 | 跑 | ✅ |
| POST | `/market/signals/{signal_id}/ignore` | — | 写 | ✅ |
| POST | `/market/signals/{signal_id}/to-plan` | 信号 → 内容计划（source=market_signal，reason 带市场信号来… | 写 | ✅ |
| GET | `/market/watchlist` | — | 读 | ✅ |
| POST | `/market/watchlist` | — | 写 | ✅ |
| DELETE | `/market/watchlist/{watch_id}` | — | 写 | ✅ |
| GET | `/links` | — | 读 | ✅ |
| POST | `/links` | — | 写 | ✅ |
| POST | `/links/check` | 检测单个链接收录状态（真实查询百度，备用引擎兜底） | 算 | ✅ |
| POST | `/links/check-all` | 批量检测：所有非 indexed 的链接 | 算 | ✅ |
| DELETE | `/links/{link_id}` | — | 写 | ✅ |
| POST | `/collect/crawl` | 爬取 URL → raw 落盘 storage/raw（P1） | 写 | — |
| POST | `/keywords/expand` | 拓词（P2） | 算 | — |
### 2.6 ⑥ 素材与知识（12 条 · 读5/写7/跑0/算0）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/knowledge/materials` | — | 读 | ✅ |
| POST | `/knowledge/materials` | — | 写 | ✅ |
| GET | `/knowledge/materials/search` | 素材混合检索（S1b）：n-gram 关键词为主 + 向量语义补充；向量不可用自动降级纯… | 读 | ✅ |
| POST | `/knowledge/materials/upload` | 文件直接入库素材（2026-08-18）：提取文本 → 建素材（可检索/可被报告引用）。 | 写 | ✅ |
| POST | `/knowledge/materials/vectorize` | 素材向量化（幂等，S1b）：Qdrant 在 → geo_materials colle… | 写 | ✅ |
| DELETE | `/knowledge/materials/{material_id}` | — | 写 | ✅ |
| GET | `/knowledge/materials/{material_id}` | 素材详情 + 效果聚合（S0 效果卡：列表数据无 effects，须单独拉） | 读 | ✅ |
| PUT | `/knowledge/materials/{material_id}` | 更新素材（部分更新：只改传了的字段；发布打点填 published_url） | 写 | ✅ |
| POST | `/knowledge/media/upload` | 上传图片/文件：存 storage/media/，返回可访问 URL 与路径。大小上限 … | 写 | — |
| GET | `/knowledge/media/{filename}` | 读取媒体文件（前端 <img src> 用）。路径校验：必须落在 media_dir 内… | 读 | — |
| GET | `/knowledge/profile` | 企业画像组装（认知编译器第 1 层）：Kernel 事实+关系 → 画像卡片。 | 读 | ✅ |
| POST | `/knowledge/reset` | 重置 GEO 数据（出厂状态）：清空全部业务表 + 媒体文件 + Qdrant 素材向量… | 写 | — |
### 2.7 ⑦ 对战、诊断与引擎（7 条 · 读3/写1/跑2/算1）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/battle` | — | 跑 | ✅ |
| POST | `/diagnose` | — | 算 | — |
| POST | `/analyze/diagnose` | 官网诊断（异步，P2） | 写 | — |
| GET | `/analyze/reports/{report_id}` | 诊断报告（P2） | 读 | — |
| GET | `/meta/engines` | — | 读 | ✅ |
| POST | `/meta/engines/{engine_id}/ping` | 单引擎连通性实测（P0） | 跑 | — |
| GET | `/stats/overview` | — | 读 | ✅ |
### 2.8 ⑧ 顾问交接面（未放行）（5 条 · 读5/写0/跑0/算0）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/geo/consumer/knowledge` | 在 GEO 自己的库里找东西：GEO 正本产物 + 知识快照文本。 | 读 | — |
| GET | `/geo/consumer/snapshots` | GEO 从企业知识库读到过的东西（快照，不是正本）。 | 读 | — |
| GET | `/geo/consumer/summary` | GEO 手里有什么：正本产物计数 + 读过的知识快照概况。 | 读 | — |
| GET | `/eios/export/knowledge-index` | seed.knowledge.json 兼容索引导出（非全文，P3） | 读 | — |
| GET | `/health` | — | 读 | — |
## 3. 每个面「能干什么」（人话版，给设计用）

下面按用户任务讲，不按文件讲。**✅有入口** = 今天已经能点到；**🕳无入口** = 后端已经能用、
菜单里没有。

### ① 开局：把企业搬进来（11 条）

用户视角：打开 GEO 第一件事，是让系统知道「你是谁、你卖什么、现在 AI 怎么答你」。

- **✅ 自动配置（7 步状态机）** `POST /onboard/auto-config`（`跑`）+ `GET /onboard/status` + `GET /onboard/run-status`
  1. `detect` 认出公司/别名/产品/服务/行业/关键词（模型归类；模型没配上就按名称规则兜底，并如实标注）
  2. `discover` 找竞品　3. `create` 建监测对象　4. `run` 批量监测（**长任务**，前端轮询）
  5. `distill` 顺手出问题池 / 缺口 / 内容机会
- **✅ 知识库初始化（内测）** `POST /kb-init/scan`（`算`，只读知识库）+ `POST /kb-init/apply`（`写`）
  - scan 筛出**公司 / 产品 / 相关文档**候选，逐条标「已纳入 / 新增」，默认全选
  - apply 把勾选的落进 GEO **自己的快照台账**（第一次全量、之后增量；GEO 只读知识库、不写）
- **体检 —— 「你现在缺什么」的权威答案**
  - `GET /enterprise-profile/overview` **✅**（接进初始化卡）：总覆盖率 + 50 子项 足够/部分/太少
  - `GET /enterprise-profile/categories` **✅**（同上）：8 大类大纲 —— **就是左树数据**
  - `GET /enterprise-profile/items/{item_id}` **✅** 单子项详情：已有资料 + 已覆盖/未覆盖问题 + 知识来源
  - `POST /enterprise-profile/items/{item_id}/plans` **✅** 太少/部分子项 → 一键生成内容计划（生成后直接跳到「增长行动」）
  - `GET /enterprise-profile/export` **✅** 导出 Word（九章结构）　`POST /enterprise-profile/refresh` **✅** 清缓存重算（`算`）
  - **给设计**：`categories` + `items/{id}` + `items/{id}/plans` 这一页（左树 + 右详情 + 一键补内容）
    就是本轮的「企业资料 · 资料总揽」，已经做出来了。
- **✅ 企业画像** `GET /knowledge/profile`：Kernel 事实+关系 → 画像卡片（入口在右上「高级工具」抽屉）
- **✅ 识别当前企业** `GET /content/company`：读 Kernel 认出「现在是谁」+ 素材数（高级工具里自动带出）

### ② 监测：AI 怎么答你（31 条）

用户视角：盯着批「监测对象」，隔一段时间问 AI 一遍，看它有没有提到我、排第几、说了什么。

- **✅ 监测对象** `GET/POST /monitor/items`、`PATCH/DELETE /monitor/items/{mid}`、`POST /monitor/items/{mid}/run`（`跑`）
- **✅ 探针预览** `POST /monitor/items/preview`（`算`）：不落库，先说清「会问哪几句 + 大概花多少」
- **✅ 监测任务** `GET/POST /monitor/tasks`、`PATCH/DELETE /monitor/tasks/{tid}`、`POST /monitor/tasks/{tid}/run`（`跑`）
- **✅ 任务级聚合** `/monitor/tasks/{tid}/overview`　**✅ 对象跨次趋势** `/monitor/items/{mid}/trend`（趋势页含周期筛选）
- **🕳 单问句即时监测** `POST /monitor/check`（`跑`）　**🕳 批量监测** `POST /monitor/batch`（`跑`）
- **✅ 报告数据源** `GET /monitor/answers`（拍平成「逐探针 × 逐引擎」）　**🕳 历史** `/monitor/history`
- **✅ 导出** `GET /monitor/export`（markdown，专业分析页右上「导出」）
- **✅ 驾驶舱** `GET /monitor/overview`（四指标 + 分平台趋势）← **就是「经营总览」首页那张卡**
- **🕳 平均排名+评价分布** `/monitor/rank-sentiment`　**✅ 评价分析** `/monitor/sentiment`
- **✅ 舆情分析** `/monitor/public-opinion`　**✅ 事实分析** `/monitor/fact-check`（都在「AI 监测 · 专业分析」六个页签里）
- **✅ 竞品/行业/信源** `/monitor/competitor`、`/monitor/industry`、`/monitor/sources`（同上六页签）
- **✅ 引用来源 Top N** `/monitor/citations`　**🕳 单内容效果卡** `/monitor/effects`
- **🕳 旧问题池** `GET/POST /monitor/pool`　**🕳 AI 生成客户问题** `POST /monitor/generate-questions`（`跑`）

> 设计提示：`overview` / `public-opinion` / `sentiment` / `fact-check` / `competitor` / `industry`
> / `sources` 是并列「分析页」，返回结构同族（指标 + 趋势 + 分布 + top 列表），共用一套版式。
> **第二轮已经做了后六个（「AI 监测 · 专业分析」六个页签）+ 驾驶舱 `overview`。**

### ③ 认知与洞察：差距在哪（27 条）

用户视角：把监测到的回答结构化，回答「我在 AI 心里是什么形象、跟竞品差在哪、差在哪几个词上」。

- **✅ SOV 声量份额** `/intelligence/sov` —— 汇报第一指标
- **🕳 品牌提及概览** `/intelligence/overview`（我方 vs 竞品提及率%）　**✅ 趋势变化** `/intelligence/trend-delta`
- **🕳 认知总表** `/intelligence/compare`（维度 × 主体 × 认知层级 × 状态 + 证据引用）
- **✅ 差距矩阵** `/intelligence/matrix`（维度榜 + 三色 + 观察区）　**✅ 因子左右对比** `/intelligence/factor-gaps`
- **✅ 证据链** `/intelligence/evidence`（点维度 → 右侧证据抽屉：原话 + 传播强度 + 关联因子）
- **✅ 人话版** `/intelligence/humanize`（一句话结论 + 三数字 + 左右列 + 行动清单）← **给老板看的**
- **✅ 关键词 / 标签分布 / 内容策略** `/intelligence/keywords`、`/intelligence/perception`、`/intelligence/strategies`
- **✅ 缺口两种分离** `/intelligence/gap-analysis`（补知识 vs 补证据）
- **✅ 周期报告** `GET /intelligence/reports/latest` **✅** + `POST /intelligence/reports/run` **✅**（`跑`，限流 5 分钟）+ 报告 PDF **✅**（正文按章节渲染，不再是 JSON）
- **✅ 外网补搜** `POST /intelligence/harvest/search`（`跑`，高级工具里）　**🕳 补搜进度** `GET /harvest/runs/{run_id}`
- **🕳 引擎侧** `POST /intelligence/analyze`（入队）、`POST /recover`、`GET /analyses`、`GET /stats`
- **✅ 认知卡 4 合 1** `/cognition/health`、`/portrait`、`/coverage`、`/reasons`（另有 `/competitors`、`/sources`）
- **✅ AI 认知评估 V2** `POST /distill/cognition/evaluate`（`跑`）+ `GET /distill/cognition/profile`
- **✅ 认知覆盖矩阵** `/distill/cognition-profile`　**✅ 客户认知地图** `/distill/cognition-map`
- **✅ 蒸馏总览** `/distill/overview`（认知漏斗 + 验证状态 + TOP 缺口 + 机会数）← 「经营总览」在用

> 设计提示：这一面本来最缺界面（第一轮 27 条只有 9 条有入口）；**第二轮把三层里最该有的
> 汇报层 + 诊断层 + 素材层都做出来了**（「认知洞察」页），剩下的 🕳 集中在内部恢复动作与
> 引擎侧入队接口。三层划分：
> **汇报层**（humanize / sov / overview / trend-delta）→ **诊断层**（compare / matrix / factor-gaps
> / gap-analysis / evidence）→ **素材层**（keywords / perception / cognition-map）。

### ④ 蒸馏与内容生产（30 条）

用户视角：知道缺什么之后，排计划、写内容、发出去、再测一遍。

- **✅ 客户问题池** `GET /distill/questions`（`读`）、`POST /distill/questions`（🕳 `跑`）、`DELETE /{qid}`
- **✅ 单问题 6 平台明细** `/distill/questions/{qid}/platforms`
- **✅ 知识缺口** `GET /distill/gaps`（`读`）、`POST /distill/gaps`（`跑`）
- **✅ 内容计划** `GET /distill/plans`（三维排序 priority/weak/effect）、`DELETE /distill/plans/{plan_id}`
- **✅ 薄弱问题一键出计划** `POST /distill/plans/from-gaps`（纯规则，不调 LLM 省 token）
- **🕳 内容规划（LLM 版）** `POST /distill/plans`　**✅ 48 子项压力算法** `POST /distill/content-plan`
- **✅ 手动写计划** `POST /distill/plans/manual`　**🕳 客服缺口薄接收口** `POST /distill/plans/customer-gap`
- **🕳 内容机会 V2** `POST /distill/opportunities`　**🕳 内容覆盖分析** `POST /distill/analyze`
- **✅ FAQ** `POST /distill/faq`（`跑`，「增长行动 · FAQ 生产」）　**🕳 FAQ 升级版** `POST /distill/faq/upgraded`（`跑`，带知识依据）
- **✅ 内容生成** `POST /content/generate`（`跑`，自动读企业资料；**不自动发布**）
- **✅ 内容评分** `POST /content/score`（`算`，启发式）　**✅ 内容质检** `POST /content/quality`（`跑`，内容生成里的「AI 质检」）
- **🕳 需求解析** `POST /content/parse`（`跑`，自然语言 → GEO 配置）
- **✅ 发布日志** `POST /distill/content-publish`　**✅ 复测对比** `POST /distill/content-recheck`
- **✅ 自动闭环** `POST /distill/loop/run`（`跑`：planned → 自动生产 → 存；发布仍人工；入口在高级工具）

> 设计提示：现有 `问题池`/`知识缺口`/`内容计划`/`内容生成` 四张卡是这条链的骨架；
> 缺的是**闭环可视化**（发布 → 复测 → 效果回写）和 **FAQ** 这一块。

### ⑤ 市场情报与链接收录（16 条）

用户视角：盯竞品动态 + 看自己发的东西有没有被百度收录。

- **✅ 关注列表** `GET/POST /market/watchlist`、`DELETE /market/watchlist/{watch_id}`
- **✅ 采集** `POST /market/collect`　**🕳 爬单个 URL** `POST /collect/crawl`
- **✅ 信号流** `GET /market/signals`
- **✅ 信号动作**：`extract`（`跑`，抽可核验事实）/ `to-plan`（转内容计划，转完自动跳到内容计划页并高亮）/
  `ignore`；**🕳 `confirm`** 没做入口（它的语义是「确认这条信号」，当前 UI 只提供提取/转计划/忽略）
- **✅ 链接** `GET/POST /links`、`DELETE /links/{link_id}`、`POST /links/check`、`/check-all`（`算`，真查百度）
- **🕳 拓词** `POST /keywords/expand`（`算`）

**第二轮已经把「市场情报」整页做出来了**（关注对象 / 市场信号 / 链接收录 三个页签）。

### ⑥ 素材与知识（12 条）

- **✅ 素材库** `GET/POST /knowledge/materials`、`GET/PUT/DELETE /knowledge/materials/{id}`
- **✅ 混合检索** `GET /knowledge/materials/search`（n-gram 关键词 + 向量语义补充）
- **✅ 文件上传入库** `POST /knowledge/materials/upload`（txt/md/csv/pdf/docx/xlsx/图片，20MB 内）
- **✅ 向量化** `POST /knowledge/materials/vectorize`（幂等；**只在高级工具里**，不做成普通用户主功能）　**🕳 媒体上传/读取** `/knowledge/media/*`
- **✅ 企业画像** `GET /knowledge/profile`
- **🕳 一键重置** `POST /knowledge/reset` —— **全表唯一「一次抹掉全部业务表」的动作**，
  必须 `confirm=true`；**没有界面入口**；放行与否仍待 Owner 一句话

### ⑦ 对战、诊断与引擎（7 条）

- **✅ AI 对战** `POST /battle`（`跑`）：同一个问题问部署里每个已登记引擎，可多轮 + 裁判点评
- **🕳 官网诊断** `POST /analyze/diagnose`（异步）、`GET /analyze/reports/{report_id}`、`POST /diagnose`（同步版，`算`）
- **✅ 引擎清单 / 实测** `GET /meta/engines`、`POST /meta/engines/{engine_id}/ping`（`跑`，高级工具）
- **✅ 总览** `GET /stats/overview`（知识/链接/监测/引擎/Kernel 计数，「经营总览」在用）

### ⑧ 顾问交接面（5 条，**未放行**）

`GET /geo/consumer/summary` / `snapshots` / `knowledge` + `GET /eios/export/knowledge-index` + `GET /health`。
这是给顾问来查 GEO 库用的（GEO 只读知识库、读到的存自己库，顾问再连过来查）。
Owner 2026-09-21 说过「顾问先不考虑查 geo 数据」，所以**没放行，也不该出现在 GEO 自己的界面里**。

## 4. 现有菜单 → 覆盖了什么（第二轮后）

第一轮这里是「12 项平铺菜单」；**第二轮重排成 6 个页签 + 页内子页签 + 右上高级工具**。
子页签名沿用旧菜单名，所以老的触发词/卡片仍然找得到。

| 页签 | 页内子页签 | 面 | 覆盖的能力 |
|---|---|---|---|
| **经营总览** | —（默认页） | ②③④⑤ | monitor/overview + stats/overview + distill/overview，四指标 + 国产模型表现 + 问题覆盖漏斗 |
| **AI 监测** | 监测工作台 | ② | 监测对象 + 定时任务 + 监测报告（answers / sentiment / citations / sources 四页签）、对象跨次趋势、任务聚合 |
|  | 专业分析 | ② | public-opinion / sentiment / fact-check / competitor / industry / sources 六页签 + 导出 |
|  | AI 对战 | ⑦ | battle |
| **认知洞察** | 差距诊断 | ③ | humanize / sov / trend-delta / matrix / factor-gaps / gap-analysis / evidence（证据抽屉）/ keywords / perception / strategies |
|  | 认知健康 | ③ | cognition health / portrait / coverage / reasons + 评估 V2 |
|  | 客户认知地图 | ③ | distill/cognition-map + cognition-profile |
|  | 阶段报告 | ③ | 报告正文（按章节渲染）+ 生成 + 导出 PDF + onboard status |
| **增长行动** | 客户问题池 | ③④ | questions 列表/删除 + 6 平台明细 + 认知覆盖 |
|  | 知识缺口 | ④ | gaps 列表 + 检测 |
|  | 内容计划 | ④ | plans 列表/排序/删除 + from-gaps + 手动新建 + 48 子项算法 + 登记发布 + 复测 |
|  | 内容生成 | ④ | generate + score + quality（AI 质检） |
|  | FAQ 生产 | ④ | distill/faq |
|  | 行动计划 | ③④ | gaps + plans 混合视图 |
| **企业资料** | 资料总揽 | ① | enterprise-profile overview / categories / items / items-plans / export / refresh + Word 导出 |
|  | 知识库同步 | ① | kb-init scan/apply + 体检 overview/categories |
|  | 内容资产 | ⑥ | 素材 CRUD + 上传 + 搜索 + 详情 |
|  | 自动配置 | ① | onboard auto-config / status / run-status（7 步） |
| **市场情报** | —（三页签） | ⑤ | 关注对象 / 市场信号 / 链接收录（含采集、转计划、收录检测） |
| **高级工具**（右上抽屉） | — | ①④⑥⑦ | meta/engines + ping、harvest/search、loop/run、knowledge/profile、content/company、materials/vectorize |

## 5. 第一轮的 UI 建议 → 第二轮做到哪了（逐条对账）

1. **总览首页** ✅ 做了（「经营总览」）。
2. **汇报页「给老板看的」** ✅ 做了（「认知洞察 · 差距诊断」顶部：一句话判断 + 三数字 + 行动清单）。
3. **差距诊断页** ✅ 做了（维度榜 → 点进去看证据链的抽屉交互）。**🕳 只差 `/intelligence/compare`**
   （认知总表）没接。
4. **资料体检页** ✅ 做了（「企业资料 · 资料总揽」，左树 + 右详情 + 一键补）。
5. **市场情报页** ✅ 做了（一次做完整面，没零敲碎打）。
6. **内容闭环** ✅ 做了「发布 → 复测」（`content-publish` + `content-recheck`）；
   **🕳 `/monitor/effects` 单内容效果卡还没接**（素材详情里没有「效果」区块）。
7. **分析页统一版式** ✅ 做了（六个页签共用「指标 + 趋势 + 分布 + top 列表」）。

**仍然不建议进界面的**（列出来免得被当成漏掉的）：`/intelligence/recover`、`/intelligence/analyze`
（内部恢复/入队）、`/monitor/pool`（旧问题池，已被 `/distill/questions` 取代）、
`/knowledge/reset`（破坏性）、`/geo/consumer/*`（不是给 GEO 用户看的）。
第二轮的 UI **一条都没有把它们露出来**，并且有自动检查：见 §6。

## 6. 第二轮没做的（诚实登记）

- **36 条仍无界面入口**（第一轮 87 → 第二轮 36）。明细见 §2 各表里 UI 列为 `—` 的行。
- 顾问交接面 5 条**仍未放行**，两轮都没动；UI 里也没有任何入口。
- **明确不该进界面的**（第二轮做了机械自查：打包 UI 的 API 调用里**没有**它们）：
  `/intelligence/recover`、`/intelligence/analyze`、`/monitor/pool`、`/knowledge/reset`、`/geo/consumer/*`。
- **官网诊断仍是 P0 占位**：`POST /analyze/diagnose`、`GET /analyze/reports/{id}`、`POST /diagnose`
  三条后端还没产生真实诊断报告，所以「高级工具」里这一块**只有说明文字、没有运行按钮**，
  没有伪装成已实现。
- `POST /knowledge/materials/vectorize` 只在高级工具里，**没有**做成普通用户主功能。
- `POST /knowledge/reset` 是否保留放行，**仍待 Owner 一句话**。

## 附录 A：139 条全表

机械扫描 `apps/api/app/api/v1/*.py` 的 router 装饰器生成（含入参模型字段名与返回顶层 key，
存在 `/tmp` 的扫描产物里，**不落仓**）。「性质」= 方法 + 是否调模型，并对 14 条做了人工修正
（6 条 POST 其实是「跑」、2 条 GET 被误判成「跑」后改回「读」、8 条 POST 其实是「算」）。

### `analyze.py`（2 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/analyze/diagnose` | 官网诊断（异步，P2） | 写 | — |
| GET | `/analyze/reports/{report_id}` | 诊断报告（P2） | 读 | — |

### `battle.py`（1 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/battle` | — | 跑 | ✅ |

### `cognition.py`（6 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/cognition/competitors` | — | 读 | ✅ |
| GET | `/cognition/coverage` | — | 读 | ✅ |
| GET | `/cognition/health` | — | 读 | ✅ |
| GET | `/cognition/portrait` | — | 读 | ✅ |
| GET | `/cognition/reasons` | — | 读 | ✅ |
| GET | `/cognition/sources` | — | 读 | ✅ |

### `collect.py`（1 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/collect/crawl` | 爬取 URL → raw 落盘 storage/raw（P1） | 写 | — |

### `content.py`（5 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/content/company` | 自动识别当前企业（Kernel 读取） | 读 | ✅ |
| POST | `/content/generate` | 生成 GEO 内容草稿（自动读企业资料；不自动发布） | 跑 | ✅ |
| POST | `/content/parse` | AI 自动配置：把自然语言需求解析成 GEO 配置（目标/类型/风格/长度/平台/问题） | 跑 | — |
| POST | `/content/quality` | GEO 质量检测：内容 → 5 项评分（0-100）+ 改进建议 | 跑 | ✅ |
| POST | `/content/score` | GEO 评分：实体覆盖/事实密度/问题覆盖/结构完整 + 引用潜力（启发式）。 | 算 | ✅ |

### `diagnose.py`（1 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/diagnose` | — | 算 | — |

### `distill.py`（25 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/distill/analyze` | Content Analyzer：内容覆盖分析（问题池 vs 内容） | 写 | — |
| GET | `/distill/cognition-map` | 蒸馏中心·客户认知地图：问题池按决策阶段聚合 + 企业覆盖 | 读 | ✅ |
| GET | `/distill/cognition-profile` | 企业 AI 认知覆盖矩阵：AI 回答里企业在 5 个维度的被提及率 | 读 | ✅ |
| POST | `/distill/cognition/evaluate` | AI 认知评估 V2 · 批处理评估：monitor_history 回答 → LLM … | 跑 | ✅ |
| GET | `/distill/cognition/profile` | AI 认知评估 V2 · 聚合结果：读 cognition_evaluations → … | 读 | ✅ |
| POST | `/distill/content-plan` | 内容计划算法（V1 规则版）：问题池 × AI 监测 → 48 子项压力 → 内容计划 … | 写 | ✅ |
| POST | `/distill/content-publish` | 发布日志（效果反哺闭环第一步）：计划 → 已发布。 | 写 | ✅ |
| POST | `/distill/content-recheck` | 复测对比（效果反哺第二步，手动触发）：已发布计划 → 重算覆盖问题监测分数 → 对比发布… | 写 | ✅ |
| POST | `/distill/faq` | FAQ 提炼：主题/关键词 → 客户常问的问答对（带 Knowledge Groundi… | 跑 | ✅ |
| POST | `/distill/faq/upgraded` | FAQ 升级版：单问题 → 知识检查 → 基于企业知识回答（无依据标注通用） | 跑 | — |
| GET | `/distill/gaps` | — | 读 | ✅ |
| POST | `/distill/gaps` | 知识缺口检测：问题池 → 逐个 Kernel 匹配 → 无知识的问题生成缺口 | 跑 | ✅ |
| POST | `/distill/loop/run` | 自动闭环（2026-08-15）：planned 计划 → 自动生产内容 → 存资产 →… | 跑 | ✅ |
| POST | `/distill/opportunities` | 内容机会（V2）：知识资产 → 可直接生产 + 知识缺口 → 建议补充 | 写 | — |
| GET | `/distill/overview` | 蒸馏总览：认知漏斗 + 验证状态 + TOP 缺口 + 机会数 | 读 | ✅ |
| GET | `/distill/plans` | 内容计划列表（S0 起支持三维排序：priority/weak/effect；分数可解释… | 读 | ✅ |
| POST | `/distill/plans` | 内容规划：知识缺口 → 运营内容计划（topic/reason/推荐类型/优先级） | 跑 | — |
| POST | `/distill/plans/customer-gap` | P6 薄接收口：客服知识缺口 → 现有内容计划；不生产、不发布、不写 Kernel。 | 写 | — |
| POST | `/distill/plans/from-gaps` | 薄弱问题一键生成内容计划（纯规则不调 LLM，省 token） | 写 | ✅ |
| POST | `/distill/plans/manual` | 手动/AI 写入单条内容计划（去重：同 target_question 或同 topic… | 写 | ✅ |
| DELETE | `/distill/plans/{plan_id}` | 删除内容计划（用户拍板：计划只加不减不行，每条可删） | 写 | ✅ |
| GET | `/distill/questions` | — | 读 | ✅ |
| POST | `/distill/questions` | Question Intelligence：种子词 → 客户问题池（意图/阶段/优先级/… | 跑 | ✅ |
| DELETE | `/distill/questions/{qid}` | — | 写 | ✅ |
| GET | `/distill/questions/{qid}/platforms` | P0：单个问题的 6 平台监测明细（对齐竞品"用户意图图"平台列） | 读 | ✅ |

### `enterprise_profile.py`（6 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/enterprise-profile/categories` | 8 大类 + 子项 + 档位/关联状态（左大纲树数据）。 | 读 | ✅ |
| GET | `/enterprise-profile/export` | 导出 Word（python-docx，九章结构）。 | 读 | ✅ |
| GET | `/enterprise-profile/items/{item_id}` | 单子项详情：已有资料 + 已覆盖/未覆盖问题 + 知识来源。 | 读 | ✅ |
| POST | `/enterprise-profile/items/{item_id}/plans` | 太少/部分子项 → 一键生成内容计划（对接蒸馏页 plans）。 | 写 | ✅ |
| GET | `/enterprise-profile/overview` | 总体健康度：企业资料覆盖率 + 足够/部分/太少 计数。 | 读 | ✅ |
| POST | `/enterprise-profile/refresh` | 刷新：清缓存重算（种子补齐 + 返回最新总览）。 | 算 | ✅ |

### `export.py`（1 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/eios/export/knowledge-index` | seed.knowledge.json 兼容索引导出（非全文，P3） | 读 | — |

### `geo_consumer.py`（3 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/geo/consumer/knowledge` | 在 GEO 自己的库里找东西：GEO 正本产物 + 知识快照文本。 | 读 | — |
| GET | `/geo/consumer/snapshots` | GEO 从企业知识库读到过的东西（快照，不是正本）。 | 读 | — |
| GET | `/geo/consumer/summary` | GEO 手里有什么：正本产物计数 + 读过的知识快照概况。 | 读 | — |

### `health.py`（1 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/health` | — | 读 | — |

### `intelligence.py`（21 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/intelligence/analyses` | 条级解析结果（兼容 answer_id 别名）。 | 读 | — |
| POST | `/intelligence/analyze` | 手动触发解析：指定 evidence_ids，或从监测历史回填（monitor_id/s… | 写 | — |
| GET | `/intelligence/compare` | 认知总表（方案 V2）：维度 × 主体 × 认知层级 × 认知状态 + 证据引用。min… | 读 | — |
| GET | `/intelligence/evidence` | 证据链：某因子的全部原话 + 传播强度 + 关联因子。 | 读 | ✅ |
| GET | `/intelligence/factor-gaps` | 因子级左右对比：竞品有·我方无（left，要补）vs 我方有·竞品无（right，优势）… | 读 | ✅ |
| GET | `/intelligence/gap-analysis` | 知识缺口两种分离：Knowledge Gap（补知识库/放弃）vs Evidence G… | 读 | ✅ |
| GET | `/intelligence/harvest/runs/{run_id}` | 补搜 run 状态（采集态，与解析成功与否无关）。 | 读 | — |
| POST | `/intelligence/harvest/search` | Phase A：外网补搜（WebSearch Harvest）。采集成功不依赖 LLM。 | 跑 | ✅ |
| GET | `/intelligence/humanize` | 商业化翻译层：一句话结论 + 三数字 + 左右列 + 行动清单（人话版）。 | 读 | ✅ |
| GET | `/intelligence/keywords` | 必备关键词：高频维度按提及数排序。 | 读 | ✅ |
| GET | `/intelligence/matrix` | 差距矩阵（S1 聚合，无 LLM）：维度榜 + 三色 + 观察区。gap_type 留 … | 读 | ✅ |
| GET | `/intelligence/overview` | 品牌提及概览：我方 vs 竞品提及率%。mode=comparison 只统计推荐/对比… | 读 | — |
| GET | `/intelligence/perception` | 认知标签分布（S1 聚合，无 LLM）。 | 读 | ✅ |
| POST | `/intelligence/recover` | 启动恢复：无 succeeded extraction 的 evidence 重新入队（… | 写 | — |
| GET | `/intelligence/reports/latest` | 最新周期报告。company 空则取全局最新；指定公司名则精确匹配 company_na… | 读 | ✅ |
| GET | `/intelligence/reports/latest/pdf` | 最新周期报告 PDF 下载（2026-08-15 新增）。无报告 → 404。 | 读 | ✅ |
| POST | `/intelligence/reports/run` | 触发 Reasoning 生成报告（限流 5 分钟一次）。 | 跑 | ✅ |
| GET | `/intelligence/sov` | SOV 声量份额（汇报第一指标）：品牌 vs 竞品在 AI 推荐中的 % 份额 + 趋势… | 读 | ✅ |
| GET | `/intelligence/stats` | 分析引擎状态（S0 用）：各表计数。 | 读 | — |
| GET | `/intelligence/strategies` | 内容策略（GEO Action Score）：需求×差距×可改变性×证据强度×竞争重要性… | 读 | ✅ |
| GET | `/intelligence/trend-delta` | 推荐率趋势变化：相邻周期（7 天）品牌推荐 gained/lost/rising/fal… | 读 | ✅ |

### `kb_init.py`（2 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/kb-init/apply` | 把用户点选的那份资料落进 GEO 自己的库（快照台账）。 | 写 | ✅ |
| POST | `/kb-init/scan` | 扫一遍知识库，给出可点选的候选（公司 / 产品 / 相关文档）。 | 算 | ✅ |

### `keywords.py`（1 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/keywords/expand` | 拓词（P2） | 算 | — |

### `knowledge.py`（12 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/knowledge/materials` | — | 读 | ✅ |
| POST | `/knowledge/materials` | — | 写 | ✅ |
| GET | `/knowledge/materials/search` | 素材混合检索（S1b）：n-gram 关键词为主 + 向量语义补充；向量不可用自动降级纯… | 读 | ✅ |
| POST | `/knowledge/materials/upload` | 文件直接入库素材（2026-08-18）：提取文本 → 建素材（可检索/可被报告引用）。 | 写 | ✅ |
| POST | `/knowledge/materials/vectorize` | 素材向量化（幂等，S1b）：Qdrant 在 → geo_materials colle… | 写 | ✅ |
| DELETE | `/knowledge/materials/{material_id}` | — | 写 | ✅ |
| GET | `/knowledge/materials/{material_id}` | 素材详情 + 效果聚合（S0 效果卡：列表数据无 effects，须单独拉） | 读 | ✅ |
| PUT | `/knowledge/materials/{material_id}` | 更新素材（部分更新：只改传了的字段；发布打点填 published_url） | 写 | ✅ |
| POST | `/knowledge/media/upload` | 上传图片/文件：存 storage/media/，返回可访问 URL 与路径。大小上限 … | 写 | — |
| GET | `/knowledge/media/{filename}` | 读取媒体文件（前端 <img src> 用）。路径校验：必须落在 media_dir 内… | 读 | — |
| GET | `/knowledge/profile` | 企业画像组装（认知编译器第 1 层）：Kernel 事实+关系 → 画像卡片。 | 读 | ✅ |
| POST | `/knowledge/reset` | 重置 GEO 数据（出厂状态）：清空全部业务表 + 媒体文件 + Qdrant 素材向量… | 写 | — |

### `links.py`（5 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/links` | — | 读 | ✅ |
| POST | `/links` | — | 写 | ✅ |
| POST | `/links/check` | 检测单个链接收录状态（真实查询百度，备用引擎兜底） | 算 | ✅ |
| POST | `/links/check-all` | 批量检测：所有非 indexed 的链接 | 算 | ✅ |
| DELETE | `/links/{link_id}` | — | 写 | ✅ |

### `market.py`（9 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/market/collect` | — | 写 | ✅ |
| GET | `/market/signals` | — | 读 | ✅ |
| POST | `/market/signals/{signal_id}/confirm` | 人工确认信号 —— **不写知识库**（Owner 2026-09-20）。 | 写 | — |
| POST | `/market/signals/{signal_id}/extract` | LLM 提取可核验事实（竞品发布/融资/合作/数据）；宣传口径不提取为事实 | 跑 | ✅ |
| POST | `/market/signals/{signal_id}/ignore` | — | 写 | ✅ |
| POST | `/market/signals/{signal_id}/to-plan` | 信号 → 内容计划（source=market_signal，reason 带市场信号来… | 写 | ✅ |
| GET | `/market/watchlist` | — | 读 | ✅ |
| POST | `/market/watchlist` | — | 写 | ✅ |
| DELETE | `/market/watchlist/{watch_id}` | — | 写 | ✅ |

### `meta.py`（2 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/meta/engines` | — | 读 | ✅ |
| POST | `/meta/engines/{engine_id}/ping` | 单引擎连通性实测（P0） | 跑 | — |

### `monitor.py`（31 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/monitor/answers` | 0.2+：监测报告数据源——把 history 拍平成逐探针 × 逐引擎的回答列表 | 读 | ✅ |
| POST | `/monitor/batch` | 批量监测：支持两入口（0.2 统一内部流程，不留两套执行逻辑） | 跑 | — |
| POST | `/monitor/check` | — | 跑 | — |
| GET | `/monitor/citations` | 被 AI 引用的内容 Top N（S2：聚合 history batch 条目的 cit… | 读 | ✅ |
| GET | `/monitor/competitor` | 全智解析·竞品分析（0.4 升级）：从监测回答聚合竞争认知 | 读 | ✅ |
| GET | `/monitor/effects` | 单内容效果卡（S0）：素材详情弹窗「效果」区块数据源 | 读 | — |
| GET | `/monitor/export` | 导出监测报告（markdown）：批量监测汇总 + 薄弱问题榜 + 内容建议 | 读 | ✅ |
| GET | `/monitor/fact-check` | P1-5：事实分析页（基于知识库识别 AI 回复失真：命中/异常/排行/明细） | 读 | ✅ |
| POST | `/monitor/generate-questions` | AI 生成客户问题（问题池来源）：围绕企业/行业生成真实搜索问法 | 跑 | — |
| GET | `/monitor/history` | — | 读 | — |
| GET | `/monitor/industry` | 全智解析·行业分析：从行业/关键词监测对象回答聚合行业格局 | 读 | ✅ |
| GET | `/monitor/items` | 0.2：监测对象列表（默认只 active/paused，archived 单独看） | 读 | ✅ |
| POST | `/monitor/items` | 0.2：新建监测对象（type 四枚举校验；status 默认 active） | 写 | ✅ |
| POST | `/monitor/items/preview` | 0.2+：监测对象探针预览——不落库，返回系统将生成的探针问题 + 成本估算 | 算 | ✅ |
| DELETE | `/monitor/items/{mid}` | 0.2：软删除（status → archived，历史趋势保留，不硬删） | 写 | ✅ |
| PATCH | `/monitor/items/{mid}` | 0.2：更新监测对象（部分更新：只改传入字段，不整包覆盖）——审计 P0 修复 | 写 | ✅ |
| POST | `/monitor/items/{mid}/run` | 0.2+：手动触发单监测对象运行（建完对象即可单独监测，不必先建任务） | 跑 | ✅ |
| GET | `/monitor/items/{mid}/trend` | 0.2：监测对象跨次趋势（同一 item 反复监测 → 逐次对比） | 读 | ✅ |
| GET | `/monitor/overview` | P0：数据总览驾驶舱四指标 + 分平台趋势 | 读 | ✅ |
| GET | `/monitor/pool` | — | 读 | — |
| POST | `/monitor/pool` | — | 写 | — |
| GET | `/monitor/public-opinion` | P1：舆情分析页（健康分 + 四指标 + 趋势 + 平台分布 + 高风险 top3 + … | 读 | ✅ |
| GET | `/monitor/rank-sentiment` | P0：平均排名（估算）+ 评价分布 + 趋势（驾驶舱/评价分析共用） | 读 | — |
| GET | `/monitor/sentiment` | P1：评价分析页（占比 + 趋势 + 用户意图维度 + 负面高频词） | 读 | ✅ |
| GET | `/monitor/sources` | 全智解析·信源分析：各 AI 引擎（信源）的表现排行 | 读 | ✅ |
| GET | `/monitor/tasks` | 0.3：监测任务列表（含每任务的 item 数与最近运行时间） | 读 | ✅ |
| POST | `/monitor/tasks` | 0.3：新建监测任务（名字 + 频率 + 绑定的监测对象） | 写 | ✅ |
| DELETE | `/monitor/tasks/{tid}` | 0.3：软删除任务（status → archived；item 解绑但保留） | 写 | ✅ |
| PATCH | `/monitor/tasks/{tid}` | 0.3：更新任务（改名/改频率/改绑定/启停） | 写 | ✅ |
| GET | `/monitor/tasks/{tid}/overview` | 0.3：任务级聚合——任务下每 item 的最新状态 + 任务整体指标 | 读 | ✅ |
| POST | `/monitor/tasks/{tid}/run` | 0.3：手动触发任务运行（engines 可指定，默认全部已配置引擎） | 跑 | ✅ |

### `onboard.py`（3 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| POST | `/onboard/auto-config` | — | 跑 | ✅ |
| GET | `/onboard/run-status` | 后台监测+蒸馏进度（前端轮询；finished 后带 distill 结果 + inte… | 读 | ✅ |
| GET | `/onboard/status` | 空态检测 + 三种「素材」各有多少（2026-09-20 修正标签错位）。 | 读 | ✅ |

### `stats.py`（1 条）

| 方法 | 路径 | 一句话 | 性质 | UI |
|---|---|---|---|---|
| GET | `/stats/overview` | — | 读 | ✅ |
